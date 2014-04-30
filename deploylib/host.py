import os
from os import path
from subprocess import check_output as run
import random
import shelve
import netifaces
import uuid
import docker


class Service(dict):
    """Normalize a service definition into a canonical state such that
    we'll be able to tell whether it changed.
    """

    def __init__(self, name, data):
        dict.__init__(self, {})

        # Image can be given instead of an explicit name. The last
        # part of the image will be used as the name only.
        self.name = name
        if not 'image' in self:
            self['image'] = name
            self.name = name.split('/')[-1]

        self['cmd'] = data.pop('cmd', '')
        self['entrypoint'] = data.pop('entrypoint', '')
        self['env'] = data.pop('env', {})
        self['volumes'] = data.pop('volumes', {})
        self['host_ports'] = data.pop('host_ports', {})

        ports = data.pop('ports', None)
        if not ports:
            # If no ports are given, always provide a default port
            ports = {'': 'assign'}
        if isinstance(ports, (list, tuple)):
            # If a list of port names is given, consider them to be 'assign'
            ports = {k: 'assign' for k in ports}
        self['ports'] = ports

        # Hide all other, non-default keys in a separate dict
        self['kwargs'] = data


class LocalMachineBackend(object):
    """db_dir stores runtime data like the deployments that have been setup.

    volumes_dir contains the data volumes used by containers.
    """

    def __init__(self, db_dir, volumes_dir):
        self.volume_base = volumes_dir
        self.state = shelve.open(db_dir, writeback=True)

        if not path.exists(volumes_dir):
            os.mkdir(volumes_dir)

    def get_host_ip(self):
        """Get IP from local interface."""
        lan_ip = os.environ.get('HOST_IP')
        if lan_ip:
            return lan_ip

        try:
            return netifaces.ifaddresses('docker0')[netifaces.AF_INET][0]['addr']
        except ValueError:
            raise RuntimeError('Cannot determine host ip, set HOST_IP environment variable')

    def discover(self, servicename):
        # sdutil does not support specifying a discoverd host yet, which is
        # fine with us for now since all is running on the same host.
        return '172.17.42.1:49272'
        return run('DISCOVERD=:1111 sdutil services -1 {}'.format(servicename), shell=True)

    def cache(self, *names):
        """Return a cache path. Same path for same name.
        """
        tmpdir =  path.join(self.volume_base, '_cache', *names)
        if not os.path.exists(tmpdir):
            os.makedirs(tmpdir)
        return tmpdir

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

        # Save the service definition somewhere
        deployment = self.state.get('deployments', {}).get(deploy_id)
        deployment.setdefault(service.name, {})
        old_definition = deployment[service.name].get('definition')
        if old_definition == service:
            print "%s has not changed, skipping" % service.name
            return
        deployment[service.name]['definition'] = service
        self.state.sync()

        if not self.run_plugins('setup', deploy_id, service):
            # If not plugin handles this, deploy as a regular docker image.
            return self.deploy_docker_image(deploy_id, service, **kwargs)

    def deploy_docker_image(self, deploy_id, service, namer=None):
        """Deploy a regular docker image.
        """

        deployment = self.state.get('deployments', {}).get(deploy_id)

        def get_free_port():
            return random.randint(10000, 65000)

        local_repl = {}
        host_ip = self.get_host_ip()
        local_repl['HOST'] = host_ip

        # Construct the 'volumes' argument.
        api_volumes = {}
        for volume_name, volume_path in service.get('volumes').items():
            host_path = path.join(
                self.volume_base, deploy_id, service.name, volume_name)
            api_volumes[host_path] = volume_path

        # Construct the 'ports' argument. Given some named ports, we want
        # to determine which of them need to be mapped to the host and how.
        api_ports = {}
        defined_ports = service['ports']
        defined_mappings = service['host_ports']
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
        #api_env = (service.from_file.env.get(service.name, {}) or {}).copy()
        api_env = local_repl.copy()
        api_env['DISCOVERD'] = '%s:1111' % host_ip
        api_env['ETCD'] = 'http://%s:4001' % host_ip
        api_env.update(service['env'])

        # Construct a name, for informative purposes only
        container_name = namer(service) if namer else "{}-{}-{}".format(
            deploy_id, service.name, uuid.uuid4().hex[:5])

        print "Pulling image %s" % service['image']
        print self.client.pull(service['image'])

        print "Creating container %s" % container_name
        result = self.client.create_container(
            image=service['image'],
            name=container_name,
            ports=api_ports.values(), # Be sure to expose if image doesn't already
            command=service['cmd'].format(**local_repl),
            environment=api_env,
            volumes=api_volumes,
            entrypoint=service['entrypoint'].format(**local_repl))
        container_id = result['Id']

        # For now, all services may only run once. If there is already
        # a container for this service, make sure it is shut down.
        existing_id = deployment.get(service.name, {}).get('container_id', None)
        if existing_id:
            print "Killing existing container %s" % existing_id
            try:
                self.client.kill(existing_id)
            except:
                pass

        # Then, store the new container id.
        deployment.setdefault(service.name, {})
        deployment[service.name]['container_id'] = container_id
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
