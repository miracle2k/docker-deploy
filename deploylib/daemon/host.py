import os
from os import path
import shlex
from subprocess import check_output as run
import random
import shelve
import netifaces
import uuid
import docker


def normalize_port_mapping(s):
    """Given a port mapping, return a 2-tuple (ip, port).

    The return value will be given to docker-py, which has it's own range
    of supported format variations; for a missing port, we would return
    ``(ip, '')``.
    """
    if isinstance(s, (tuple, list)):
        return tuple(s)
    if isinstance(s, int):
        return '', s
    if ':' in s:
        parts = s.split(':', 1)
        return tuple(parts)
    return s, ''


class Service(dict):
    """Normalize a service definition into a canonical state such that
    we'll be able to tell whether it changed.
    """

    def __init__(self, name, data=None):
        dict.__init__(self, {})

        data = data.copy() if data else {}

        # Image can be given instead of an explicit name. The last
        # part of the image will be used as the name only.
        if not 'image' in data:
            self['image'] = name
            self.name = name.split('/')[-1]
        else:
            self.name = name
            self['image'] = data['image']

        self.globals = {}

        self['cmd'] = data.pop('cmd', '')
        if isinstance(self['cmd'], basestring):
            # docker-py accepts string as well and does the same split.
            # To allow our internal code to rely on one format, we normalize
            # to a list earlier.
            self['cmd'] = shlex.split(self['cmd'])
        self['entrypoint'] = data.pop('entrypoint', '')
        self['env'] = data.pop('env', {})
        self['volumes'] = data.pop('volumes', {})
        self['privileged'] = data.pop('privileged', False)
        self['host_ports'] = {
            k: normalize_port_mapping(v)
            for k, v in data.pop('host_ports', {}).items()}

        ports = data.pop('ports', None)
        if not ports:
            # If no ports are given, always provide a default port
            ports = {'': 'assign'}
        if isinstance(ports, (list, tuple)):
            # If a list of port names is given, consider them to be 'assign'
            ports = {k: 'assign' for k in ports}
        self['ports'] = ports

        # Hide all other, non-default keys in a separate dict
        self['kwargs'] = data.pop('kwargs', {})
        self['kwargs'].update(data)

    def copy(self):
        new_service = self.__class__(self.name, dict.copy(self))
        new_service.globals = self.globals
        return new_service


class LocalMachineBackend(object):
    """db_dir stores runtime data like the deployments that have been setup.

    volumes_dir contains the data volumes used by containers.
    """

    def __init__(self, db_dir, volumes_dir):
        self.volume_base = path.abspath(volumes_dir)
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
        return run('DISCOVERD={}:1111 sdutil services -1 {}'.format(
            self.get_host_ip(), servicename), shell=True).strip()

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

    def create_deployment(self, deploy_id, fail=True):
        """Create a new instance.
        """
        self.state.setdefault('deployments', {})
        if deploy_id in self.state['deployments']:
            if fail:
                raise ValueError('Instance %s already exists.' % deploy_id)
            return False
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
        from deploylib.plugins.app import AppPlugin
        from deploylib.plugins.domains import DomainPlugin
        from deploylib.plugins.sdutil import SdutilPlugin
        from deploylib.plugins.flynn_postgres import FlynnPostgresPlugin
        from deploylib.plugins.wait import WaitPlugin
        self.plugins = [
            WaitPlugin(self),
            AppPlugin(self),
            FlynnPostgresPlugin(self),
            DomainPlugin(self),
            SdutilPlugin(self)]

        self.client = docker.Client(
            base_url=docker_url, version='1.6', timeout=10)

    def run_plugins(self, method_name, *args, **kwargs):
        for plugin in self.plugins:
            method = getattr(plugin, method_name, None)
            if not method:
                continue
            result = method(*args, **kwargs)
            if result:
                return result
        else:
            return False

    def deployment_setup_service(self, deploy_id, service, force=False, **kwargs):
        """Add a service to the deployment.
        """

        # Save the service definition somewhere
        deployment = self.state.get('deployments', {}).get(deploy_id)
        service.globals = deployment.get('globals', {})
        deployment.setdefault(service.name, {})
        if not force:
            old_definition = deployment[service.name].get('definition')
            if old_definition == service:
                print "%s has not changed, skipping" % service.name
                return
        deployment[service.name]['definition'] = service
        self.state.sync()

        if not self.run_plugins('setup', deploy_id, service):
            # If not plugin handles this, deploy as a regular docker image.
            self.deploy_docker_image(deploy_id, service, **kwargs)

        self.run_plugins('post_service_deploy', deploy_id, service)
        self.state.sync()

    def deploy_docker_image(self, deploy_id, service, namer=None):
        """Deploy a regular docker image.
        """

        deployment = self.state.get('deployments', {}).get(deploy_id)

        def get_free_port():
            return random.randint(10000, 65000)

        local_repl = {}
        host_lan_ip = self.get_host_ip()
        local_repl['HOST'] = host_lan_ip
        local_repl['DEPLOY_ID'] = deploy_id
        self.run_plugins('provide_local_vars', service, local_repl)

        def replvars(s):
            if not isinstance(s, basestring):
                return s
            return s.format(**local_repl)

        # First, we'll need to take the service and create a container
        # start config, which means resolving various parts of the service
        # definition to a final value.
        startcfg = {
            'image': service['image'],
            'cmd': service['cmd'],
            'entrypoint': service['entrypoint'],
            'privileged': service['privileged'],
            'volumes': {},
            'ports': {},
            'env': {}
        }

        # Construct the 'volumes' argument.
        for volume_name, volume_path in service.get('volumes').items():
            host_path = path.join(
                self.volume_base, deploy_id or '__sys__', service.name, volume_name)
            startcfg['volumes'][host_path] = volume_path

        # Construct the 'ports' argument. Given some named ports, we want
        # to determine which of them need to be mapped to the host and how.
        defined_ports = service['ports']
        defined_mappings = service['host_ports']
        port_assignments = {}
        for port_name, container_port in defined_ports.items():
            # Ports may be defined but won't be mapped, assume this by default.
            host_port = None

            # Maybe this named port should be mapped to a specific host port
            host_port = defined_mappings.get(port_name, None)

            # See if we should provide a port to the container.
            if container_port == 'assign':
                # If no host port was assigned, get a random one.
                if not host_port:
                    host_port = ('', get_free_port())

                # Always use the same port within the container as on the
                # host. Makes it easier for the container to register the
                # right port for service discovery.
                container_port = host_port[1]

            port_assignments[port_name] = {
                'host': host_port, 'container': container_port}

            if host_port:
                if not host_port[0]:
                    # docker by default would bind to 0.0.0.0, exposing
                    # the service to the world; we bind to the lan only
                    # by default. user can give 0.0.0.0 if he wants to.
                    host_port = (host_lan_ip, host_port[1])

                startcfg['ports'][container_port] = host_port

                # These ports can be used in the service definition, for
                # example as part of the command line or env definition.
                var_name = 'PORT'if port_name == "" else 'PORT_%s' % port_name.upper()
                local_repl[var_name] = container_port

        # The environment variables
        startcfg['env'] = ((service.globals.get('Env') or {}).get(service.name, {}) or {}).copy()
        startcfg['env'].update(local_repl.copy())
        startcfg['env']['DISCOVERD'] = '%s:1111' % host_lan_ip
        startcfg['env']['ETCD'] = 'http://%s:4001' % host_lan_ip
        startcfg['env'].update(service['env'])
        startcfg['env'] = {replvars(k): replvars(v)
                           for k, v in startcfg['env'].items()}

        # Construct a name, for informative purposes only
        startcfg['name'] = namer(service) if namer else "{}-{}-{}".format(
            deploy_id, service.name, uuid.uuid4().hex[:5])

        # We are almost ready, let plugins do some final modifications
        # before we are starting the container.
        self.run_plugins('before_start', deploy_id, service, startcfg,
                         port_assignments)

        # Replace local variables in configuration
        startcfg['cmd'] = [i.format(**local_repl) for i in startcfg['cmd']]
        startcfg['entrypoint'] = startcfg['entrypoint'].format(**local_repl)
        startcfg['env'] = {k: v.format(**local_repl) if isinstance(v, str) else v
                           for k, v in startcfg['env'].items()}

        # If the name provided by the namer already exists, delete it
        if namer:
            try:
                self.client.inspect_container(startcfg['name'])
            except docker.APIError:
                pass
            else:
                print "Removing existing container %s" % startcfg['name']
                self.client.kill(startcfg['name'])
                self.client.remove_container(startcfg['name'])

        print "Pulling image %s" % service['image']
        print self.client.pull(service['image'])

        print "Creating container %s" % startcfg['name']
        result = self.client.create_container(
            image=startcfg['image'],
            name=startcfg['name'],
            entrypoint=startcfg['entrypoint'],
            command=startcfg['cmd'],
            environment=startcfg['env'],
            # Seems need to be pre-declared (or or in the image itself)
            # or the binds won't work during start.
            ports=startcfg['ports'].keys(),
            volumes=startcfg['volumes'].values(),
        )
        container_id = result['Id']

        # For now, all services may only run once. If there is already
        # a container for this service, make sure it is shut down.
        existing_id = deployment.get(service.name, {}).get('container_id', None)
        if existing_id:
            print "Killing existing container %s" % existing_id
            try:
                self.client.stop(existing_id, 10)
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
        for host_path in startcfg['volumes'].keys():
            if not path.exists(host_path):
                os.makedirs(host_path)

        # Run the container
        print "Starting container %s" % container_id
        self.client.start(
            startcfg['name'],
            binds=startcfg['volumes'],
            port_bindings=startcfg['ports'],
            privileged=startcfg['privileged'])
