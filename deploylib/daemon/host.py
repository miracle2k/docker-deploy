import copy
import os
from os import path
import shlex
from subprocess import check_output as run, CalledProcessError
import random
import netifaces
import uuid
import docker
import ZODB
import ZODB.FileStorage
from deploylib.daemon.backend import DockerOnlyBackend
from deploylib.daemon.db import DeployDB, Deployment
from deploylib.plugins.setup_require import RequiresPlugin


class DeployError(Exception):
    """Unrecoverable error that causes the deploy process to abort.

    As deploys are not atomic, this can leave the deploy in an
    in-between state.
    """


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


class DeepCopyDict(dict):

    def copy(self):
        # deepcopy(self) would call this function, so we need to do the
        # initial deepcopy-level manually.
        datacopy = {}
        for k, v in self.items():
            datacopy[k] = copy.deepcopy(v)
        return self.__class__(datacopy)


def canonical_definition(name, definition):
    """Normalize a service definition into a canonical state such that
    we'll be able to tell whether it changed.
    """
    canonical = {}
    definition = definition.copy()

    # Image can be given instead of an explicit name. The last
    # part of the image will be used as the name only.
    if not 'image' in definition:
        canonical['image'] = name
        name = name.split('/')[-1]
    else:
        name = name
        canonical['image'] = definition.pop('image')

    canonical['cmd'] = definition.pop('cmd', '')
    if isinstance(canonical['cmd'], basestring):
        # docker-py accepts string as well and does the same split.
        # To allow our internal code to rely on one format, we normalize
        # to a list earlier.
        canonical['cmd'] = shlex.split(canonical['cmd'])
    canonical['entrypoint'] = definition.pop('entrypoint', '')
    canonical['env'] = definition.pop('env', {})
    canonical['volumes'] = definition.pop('volumes', {})
    canonical['privileged'] = definition.pop('privileged', False)
    canonical['host_ports'] = {
        k: normalize_port_mapping(v)
        for k, v in definition.pop('host_ports', {}).items()}

    ports = definition.pop('ports', None)
    if not ports:
        # If no ports are given, always provide a default port
        ports = {'': 'assign'}
    if isinstance(ports, (list, tuple)):
        # If a list of port names is given, consider them to be 'assign'
        ports = {k: 'assign' for k in ports}
    canonical['ports'] = ports

    # Hide all other, non-default keys in a separate dict
    canonical['kwargs'] = definition.pop('kwargs', {})
    canonical['kwargs'].update(definition)

    return name, DeepCopyDict(canonical)


class LocalMachineImplementation(object):
    """The DockerHost class is currently split in two, with the features
    that depend on the local filesystem in one class and the features that
    use the Docker API via TCP in another.
    """

    def __init__(self, db_dir, volumes_dir):
        self.volume_base = path.abspath(volumes_dir)

        self._zodb_storage = ZODB.FileStorage.FileStorage(db_dir)
        self._zodb_obj = ZODB.DB(self._zodb_storage)
        self._zodb_connection = self._zodb_obj.open()
        if not getattr(self._zodb_connection.root, 'deploy', None):
            self._zodb_connection.root.deploy = DeployDB()
        self.db = self._zodb_connection.root.deploy

        if not path.exists(volumes_dir):
            os.mkdir(volumes_dir)

    def close(self):
        self._zodb_connection.close()
        self._zodb_obj.close()
        self._zodb_storage.close()

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
        try:
            return run('DISCOVERD={}:1111 sdutil services -1 {}'.format(
                self.get_host_ip(), servicename), shell=True).strip()
        except CalledProcessError as e:
            raise DeployError(e)

    def cache(self, *names):
        """Return a cache path. Same path for same name.
        """
        tmpdir =  path.join(self.volume_base, '_cache', *names)
        if not os.path.exists(tmpdir):
            os.makedirs(tmpdir)
        return tmpdir

    def create_deployment(self, deploy_id, fail=True):
        """Create a new instance.
        """
        if deploy_id in self.db.deployments:
            if fail:
                raise ValueError('Instance %s already exists.' % deploy_id)
            return False
        self.db.deployments[deploy_id] = Deployment(deploy_id)
        return self.db.deployments[deploy_id]

    def set_globals(self, deploy_id, globals):
        """Set the global data of the deployment.

        Return True if the data was changed.
        """
        deployment = self.db.deployments[deploy_id]
        globals_changed = deployment.globals != globals
        deployment.globals = globals
        if globals_changed:
            self.run_plugins('on_globals_changed', deployment)
        return globals_changed

    def set_service(self, deploy_id, name, definition):
        """Add or replace service ``name`` with the new definition."""
        raise NotImplementedError()


class DockerHost(LocalMachineImplementation):
    """This is our high-level internal API.

    It is what the outward-facing HTTP API uses to do its job. You can
    tell it to deploy a service.
    """

    def __init__(self, docker_url=None, plugins=None, **kwargs):
        LocalMachineImplementation.__init__(self, **kwargs)

        self.plugins = plugins or []

        # TODO: Load these from somewhere and pass them in
        from deploylib.plugins.app import AppPlugin
        from deploylib.plugins.domains import DomainPlugin
        from deploylib.plugins.sdutil import SdutilPlugin
        from deploylib.plugins.flynn_postgres import FlynnPostgresPlugin
        from deploylib.plugins.wait import WaitPlugin
        self.plugins = [
            WaitPlugin(self),
            RequiresPlugin(self),
            AppPlugin(self),
            FlynnPostgresPlugin(self),
            DomainPlugin(self),
            SdutilPlugin(self)]

        self.backend = DockerOnlyBackend(docker_url)

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

    def set_service(self, deploy_id, name, definition, force=False, **kwargs):
        """Add a service to the deployment, or replace the existing
        service with a changed definition.

        Return the database record of the service.
        """

        deployment = self.db.deployments[deploy_id]
        name, definition = canonical_definition(name, definition)

        # If the service is not changed, we can skip it
        exists = name in deployment.services
        if exists and not force:
            latest = deployment.services[name].latest
            if latest and latest.definition == definition:
                print "%s has not changed, skipping" % name
                return

        # Make sure a slot for this service exists.
        service = deployment.set_service(name)

        self.setup_service(deployment, service, definition)
        return service

    def setup_service(self, deployment, service, definition, **kwargs):
        """Internal method to go through the service setup process, to
        be used by plugins. Needs to be passed the db objects, and the
        canonical service definition.
        """

        # See if a plugin will handle this.
        handled_by_plugin = self.run_plugins('setup', service, definition.copy())

        # If no plugin handles this, deploy as a regular docker image.
        if not handled_by_plugin:
            self.create_container(service, definition, **kwargs)
            service.append_version(definition)

        self.run_plugins('post_setup', deployment, service)

    def provide_data(self, deploy_id, service_name, files, info):
        """Some services rely on external data that cannot be included in
        the service definition itself (like the code for an application).

        Via this API such data can be added.
        """
        service = self.db.deployments[deploy_id].services[service_name]
        self.run_plugins('on_data_provided', service, files, info)

    def create_container(self, service, definition, namer=None):
        """Create the docker container that the service defines.
        """

        deployment = service.deployment

        def get_free_port():
            return random.randint(10000, 65000)

        local_repl = {}
        host_lan_ip = self.get_host_ip()
        local_repl['HOST'] = host_lan_ip
        local_repl['DEPLOY_ID'] = deployment.id

        def replvars(s):
            if not isinstance(s, basestring):
                return s
            return s.format(**local_repl)

        # First, we'll need to take the service and create a container
        # start config, which means resolving various parts of the service
        # definition to a final value.
        startcfg = {
            'image': definition['image'],
            'cmd': definition['cmd'],
            'entrypoint': definition['entrypoint'],
            'privileged': definition['privileged'],
            'volumes': {},
            'ports': {},
            'env': {}
        }

        # Construct the 'volumes' argument.
        for volume_name, volume_path in definition.get('volumes').items():
            host_path = path.join(
                self.volume_base, deployment.id or '__sys__', service.name, volume_name)
            startcfg['volumes'][host_path] = volume_path

        # Construct the 'ports' argument. Given some named ports, we want
        # to determine which of them need to be mapped to the host and how.
        defined_ports = definition['ports']
        defined_mappings = definition['host_ports']
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
        startcfg['env'] = ((deployment.globals.get('Env') or {}).get(service.name, {}) or {}).copy()
        startcfg['env'].update(local_repl.copy())
        startcfg['env']['DISCOVERD'] = '%s:1111' % host_lan_ip
        startcfg['env']['ETCD'] = 'http://%s:4001' % host_lan_ip
        startcfg['env'].update(definition['env'])
        startcfg['env'] = {replvars(k): replvars(v)
                           for k, v in startcfg['env'].items()}
        self.run_plugins('provide_environment', deployment, definition, startcfg['env'])

        # Construct a name; for now, for informative purposes only; later
        # this might be what we use for matching.
        if namer:
            startcfg['name'] = namer(definition)
        else:
            "{deploy}-{service}-{version}-{instance}".format(
                deploy=deployment.id, service=service.name,
                version=len(service.versions),
                instance=service.latest.instance_count if service.latest else 1)

        # We are almost ready, let plugins do some final modifications
        # before we are starting the container.
        self.run_plugins(
            'before_start', service, definition, startcfg, port_assignments)

        # Replace local variables in configuration
        startcfg['cmd'] = [i.format(**local_repl) for i in startcfg['cmd']]
        startcfg['entrypoint'] = startcfg['entrypoint'].format(**local_repl)
        startcfg['env'] = {k: v.format(**local_repl) if isinstance(v, str) else v
                           for k, v in startcfg['env'].items()}

        # Create the new container
        instance_id = self.backend.prepare(startcfg)
        service.append_instance(instance_id)
        print "New container id is %s" % instance_id

        # For now, all services may only run once. If there is already
        # a container for this service, make sure it is shut down.
        for inst in service.instances:
            print "Killing existing container %s" % inst.container_id
            self.backend.terminate(inst)
            service.instances.remove(inst)

        # Run the container
        self.backend.start(startcfg, instance_id)
