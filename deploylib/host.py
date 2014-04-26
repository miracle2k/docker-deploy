import os
from os import path
import random
import shelve
import netifaces
import uuid
import docker


class LocalMachineBackend(object):
    """db_dir stores runtime data like the deployments that have been setup.

    volumes_dir contains the data volumes used by containers.
    """

    def __init__(self, db_dir, volumes_dir):
        self.volume_base = volumes_dir
        self.state = shelve.open(db_dir, writeback=True)

        if not path.exists(volumes_dir):
            os.mkdir(volumes_dir)

    def get_interface_ip(self, interface):
        """Get IP from local interface."""
        try:
            return netifaces.ifaddresses('docker0')[netifaces.AF_INET][0]['addr']
        except ValueError:
            return ''

    def cache(self, *names):
        """Return a cache path. Same path for same name.
        """
        path = '/srv/vcache/{}'.format('/'.join(names))
        self.e(run, 'mkdir -p "{}"'.format(path))
        return path

    def get_deployments(self):
        """Return all service instances.
        """
        return self.state.get('deployments', {})

    def create_deployment(self, deploy_id):
        """Create a new instance.
        """
        self.state.setdefault('deployments', {})
        if deploy_id in self.state['deployments']:
            raise ValueError('Instance %s already exists.' % deploy_id)
        self.state['deployments'][deploy_id] = {}
        self.state.sync()

    def deployment_setup_service(self, deploy_id, service):
        raise NotImplementedError()


class DockerHost(LocalMachineBackend):
    """Runs service files on a docker host via the API.

    We could also:
        - Create initd files
        - Create CoreOS fleet files
        - Send to flynn-host
    """

    def __init__(self, docker_url=None, plugins=None, **kwargs):
        LocalMachineBackend.__init__(self, **kwargs)

        self.plugins = plugins or []

        # TODO: Load these from somewhere and pass them in
        from .plugins.app import AppPlugin
        from .plugins.domains import DomainPlugin
        self.plugins = [AppPlugin(self), DomainPlugin(self)]

        self.client = docker.Client(
            base_url=docker_url, version='1.6', timeout=10)

    def run_plugins(self, method_name, *args, **kwargs):
        for plugin in self.plugins:
            method = getattr(plugin, method_name, None)
            if not method:
                continue
            if method(*args, **kwargs):
                return True
        else:
            return False

    def deployment_setup_service(self, deploy_id, service, **kwargs):
        """Add a service to the deployment.
        """
        if not self.run_plugins('deploy', deploy_id, service):
            # If not plugin handles this, deploy as a regular docker image.
            return self.deploy_docker_image(deploy_id, service, **kwargs)

    def deploy_docker_image(self, deploy_id, service, namer=None):
        """Deploy a regular docker image.
        """

        service_name = service['name']

        deployment = self.state.get('deployments', {}).get(deploy_id)
        if deployment is None:
            raise ValueError()

        def get_free_port():
            return random.randint(10000, 65000)

        local_repl = {}
        host_ip = self.get_interface_ip('docker0')
        local_repl['HOST'] = host_ip

        # Construct the 'volumes' argument.
        api_volumes = {}
        for volume_name, volume_path in service.get('volumes').items():
            host_path = path.join(
                self.volume_base, deploy_id, service_name, volume_name)
            api_volumes[host_path] = volume_path

        # Construct the 'ports' argument. Given some named ports, we want
        # to determine which of them need to be mapped to the host and how.
        #
        # First, normalize different ways of providing the named ports
        defined_ports = service.get('ports', None)
        if not defined_ports:
            # If no ports are given, always provide a default port
            defined_ports = {'': 'assign'}
        if isinstance(defined_ports, (list, tuple)):
            # If a list of port names is given, consider them to be 'assign'
            defined_ports = {k: 'assign' for k in defined_ports}

        # Then, rewrite for the docker API call.
        api_ports = {}
        defined_mappings = service.get('host_ports', {})
        for port_name, container_port in defined_ports.items():
            # Ports may be defined but won't be mapped, assume this by default.
            host_port = None

            # Maybe this named port should be mapped to a specific host port
            host_port = defined_mappings.get(port_name, None)

            # See if we should provide a port to the container.
            if container_port == 'assign':
                # If no host port was assigned, get a random one.
                if not host_port:
                    host_port = get_free_port()

                # Always use the same port within the container as on the
                # host. Makes it easier for the container to register the
                # right port for service discovery.
                container_port = host_port

            if host_port:
                api_ports[host_port] = container_port

                # These ports can be used in the service definition, for
                # example as part of the command line or env definition.
                var_name = 'PORT'if port_name == "" else 'PORT_%s' % port_name.upper()
                local_repl[var_name] = container_port

        # The environment variables
        #api_env = (service.from_file.env.get(service_name, {}) or {}).copy()
        api_env = {}
        api_env['DISCOVERD'] = '%s:1111' % host_ip
        api_env['ETCD'] = 'http://%s:4001' % host_ip
        api_env.update(service['env'])

        # Construct a name, for informative purposes only
        container_name = namer(service) if namer else "{}-{}".format(
            deploy_id, uuid.uuid4().hex[:5])

        print "Pulling image %s" % service['image']
        print self.client.pull(service['image'])

        print "Creating container %s" % container_name
        result = self.client.create_container(
            image=service['image'],
            name=container_name,
            command=service['cmd'].format(**local_repl),
            environment=api_env,
            volumes=api_volumes,
            entrypoint=service['entrypoint'])
        container_id = result['Id']

        # For now, all services may only run once. If there is already
        # a container for this service, make sure it is shut down.
        existing_id = deployment.get(service_name, {}).get('container_id', None)
        if existing_id:
            print "Killing existing container %s" % existing_id
            try:
                self.client.kill(existing_id)
            except:
                pass

        # Then, store the new container id.
        deployment.setdefault(service_name, {})
        deployment[service_name]['container_id'] = container_id
        self.state.sync()

        print "New container id is %s" % container_id

        #########################################################

        # We are finally ready to run the container.

        # Make sure the volumes exist
        for host_path in api_volumes.keys():
            if not path.exists(host_path):
                os.makedirs(host_path)

        # Run the container
        print "Starting container %s" % container_id
        self.client.start(
            container_name,
            binds=api_volumes,
            port_bindings=api_ports,
            privileged=service.get('privileged', False))
