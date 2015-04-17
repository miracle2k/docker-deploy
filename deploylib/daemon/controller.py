import copy
import os
from os import path
import shlex
from subprocess import check_output as run, CalledProcessError
import random
import binascii
import BTrees.OOBTree
import click
import gevent
import netifaces
import ZODB
import ZODB.FileStorage
import transaction
from deploylib.daemon.api import create_app
from deploylib.plugins import load_plugins, Plugin
from deploylib.plugins.upstart import UpstartBackend
from deploylib.daemon.db import Deployment, DeployDBNew
from .context import ctx, set_context, Context


# For old ZODB databases, support module alias
import sys
sys.modules['deploylib.daemon.host'] = sys.modules[__name__]


class DeployError(Exception):
    """Unrecoverable error that causes the deploy process to abort.

    As deploys are not atomic, this can leave the deploy in an
    in-between state.
    """


class ServiceDiscoveryError(DeployError):
    pass


def normalize_port_mapping(s):
    """Given a port mapping, return a 2-tuple (ip, port).

    The return value will be given to docker-py, which has it's own range
    of supported format variations; for a missing port, we would return
    ``(ip, '')``.


    TODO: We may no longer need this.
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

    canonical['cmd'] = definition.pop('cmd', [])
    if isinstance(canonical['cmd'], basestring):
        # docker-py accepts string as well and does the same split.
        # To allow our internal code to rely on one format, we normalize
        # to a list earlier, so copy the docker behaviour itself here.
        canonical['cmd'] = ['/bin/sh', '-c', canonical['cmd']]
    canonical['entrypoint'] = definition.pop('entrypoint', '')
    if isinstance(canonical['entrypoint'], basestring):
        canonical['entrypoint'] = shlex.split(canonical['entrypoint'])
    canonical['env'] = definition.pop('env', {})
    canonical['volumes'] = definition.pop('volumes', {})
    canonical['privileged'] = definition.pop('privileged', False)
    canonical['wan_map'] = {
        normalize_port_mapping(k) : v
        for k, v in definition.pop('wan_map', {}).items()}

    port = definition.pop('port', None)
    ports = definition.pop('ports', None)
    assert not (port and ports), 'Specify either ports or port'
    if port:
        # Shortcut to specify the default port
        ports = {'': port}
    elif not ports:
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


class ControllerInterface(object):
    """This implements the main controller functionality around a
    database connection. Because we are a multi-threaded/multi-greenleted
    application, and ZODB does not support multiple threads sharing the
    same connection (nor generally do other databases), each thread
    operating on the server will get their own ``ControllerInterface``.
    """

    def __init__(self, controller):
        self.controller = controller
        self.backend = controller.backend

        self.run_plugins = controller.run_plugins
        self.get_plugin = controller.get_plugin
        self.discover = controller.discover
        self.register = controller.register
        self.get_host_ip = controller.get_host_ip

        self._db_obj, self.db = controller.get_connection()

    def close(self):
        self._db_obj.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            transaction.abort()
        else:
            transaction.commit()
        self.close()

    def create_deployment(self, deploy_id, fail=True):
        """Create a new instance.
        """
        if deploy_id in self.db.deployments:
            if fail:
                raise ValueError('Instance %s already exists.' % deploy_id)
            return False
        self.db.deployments[deploy_id] = dep = Deployment(deploy_id)
        self.run_plugins('on_create_deployment', dep)
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

    def set_service(self, deploy_id, name, definition, force=False, **kwargs):
        """Add a service to the deployment, or replace the existing
        service with a changed definition.

        Return the database record of the service.
        """

        ctx.job('%s - installing' % name)

        deployment = self.db.deployments[deploy_id]
        name, definition = canonical_definition(name, definition)

        # If the service is not changed, we can skip it
        exists = name in deployment.services
        if exists and not force:
            latest = deployment.services[name].latest
            if latest and latest.definition == definition:
                ctx.log("service has not changed, skipping")
                return

        # Make sure a slot for this service exists.
        service = deployment.set_service(name)
        version = service.derive(definition)

        self.setup_version(service, version, **kwargs)
        return service

    def setup_version(self, service, version, **kwargs):
        """Internal method to go through the service setup process, to
        be used by plugins. Needs to be passed the db objects, and the
        canonical service definition.
        """

        # See if a plugin will handle this.
        handled_by_plugin = self.run_plugins('setup', service, version)

        # If no plugin handles this, deploy as a regular docker image.
        if not handled_by_plugin:
            self.create_container(service, version, **kwargs)
        else:
            if service.held:
                ctx.log('service was held: %s' % service.hold_message)

        self.run_plugins('post_setup', service, version)

    def provide_data(self, deploy_id, service_name, files, info):
        """Some services rely on external data that cannot be included in
        the service definition itself (like the code for an application).

        Via this API such data can be added.
        """
        service = self.db.deployments[deploy_id].services[service_name]
        self.run_plugins('on_data_provided', service, files, info)

    def set_resource(self, deploy_id, name, data):
        """Declare the given resource to be available.
        """
        deployment = self.db.deployments[deploy_id]
        is_new = deployment.set_resource(name, data)
        self.run_plugins('on_resource_changed', deployment, name, data)

    def generate_runcfg(self, service, version):
        """Given a service version, generate a final controller-independent
        runcfg structure as used by the backends.
        """
        deployment = service.deployment

        # Start by letting plugins rewrite the definition
        definition = version.definition.copy()
        self.run_plugins(
            'rewrite_service', service, version, definition)

        def get_free_port():
            return random.randint(10000, 65000)

        local_repl = {}
        extra_env = {}
        host_lan_ip = self.get_host_ip()
        local_repl['HOST'] = host_lan_ip
        local_repl['DEPLOY_ID'] = deployment.id
        self.run_plugins(
            'provide_vars', service, version, definition, local_repl)

        def replvars(s):
            if not isinstance(s, basestring):
                return s
            return s.format(**local_repl)

        # First, we'll need to take the service and create a container
        # start config, which means resolving various parts of the service
        # definition to a final value.
        runcfg = {
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
                self.controller.volume_base, deployment.id, service.name, volume_name)
            runcfg['volumes'][host_path] = volume_path

        # Construct the 'ports' argument. Given some named ports, we want
        # to determine which of them need to be mapped to the host and how.
        defined_ports = definition['ports']
        port_assignments = {}
        for port_name, container_port in defined_ports.items():
            # All ports are mapped to the host LAN in this default networking
            # mode that has not yet been moved to plugins.
            host_port = (host_lan_ip, get_free_port())

            # If we need to select a port to give the container, just use
            # the same one as on the host, because why not.
            if container_port == 'assign':
                container_port = host_port[1]

            port_assignments[port_name] = {
                'host': host_port, 'container': container_port}
            runcfg['ports'].setdefault(container_port, [])
            runcfg['ports'][container_port].append(host_port)

            # These ports can be used in the service definition, for
            # example as part of the command line or env definition.
            var_name = 'PORT' if port_name == "" else 'PORT_%s' % port_name.upper()
            local_repl[var_name] = container_port
            extra_env[var_name] = container_port
            var_name = 'SD' if port_name == "" else 'SD_%s' % port_name.upper()
            extra_env[var_name] = ':'.join(map(str, host_port))
            extra_env['%s_PORT'%var_name] = host_port[1]
            extra_env['%s_HOST'%var_name] = host_port[0]
            extra_env['%s_NAME'%var_name] = '{did}:{sname}'.format(
                did=deployment.id, sname=service.name)
            if port_name != "":
                extra_env['%s_NAME'%var_name] += ':%s' % port_name

        # This allows extra mappings to be used for
        for binding, port_name in definition.get('wan_map', {}).items():
            cp = port_assignments[port_name]['container']
            runcfg['ports'].setdefault(cp, [])
            runcfg['ports'][cp].append(binding)

        # The environment variables
        runcfg['env'] = ((version.globals.get('Env') or {}).get(service.name, {}) or {}).copy()
        runcfg['env']['DEPLOY_ID'] = deployment.id
        runcfg['env']['DISCOVERD'] = '%s:1111' % host_lan_ip
        runcfg['env']['ETCD'] = 'http://%s:4001' % host_lan_ip
        runcfg['env'].update(extra_env)
        runcfg['env'].update(definition['env'])
        runcfg['env'] = {replvars(k): replvars(v)
                           for k, v in runcfg['env'].items()}
        self.run_plugins('provide_environment', deployment, definition, runcfg['env'])

        # Replace local variables in configuration
        runcfg['cmd'] = [i.format(**local_repl) for i in runcfg['cmd']]
        runcfg['entrypoint'] = [i.format(**local_repl) for i in runcfg['entrypoint']]
        runcfg['env'] = {k: v.format(**local_repl) if isinstance(v, str) else v
                           for k, v in runcfg['env'].items()}

        return runcfg, definition, port_assignments

    def create_container(self, service, version):
        """Create the docker container that the service(-version) defines.
        """

        runcfg, definition, port_assignments = \
            self.generate_runcfg(service, version)

        # Construct a name; for now, for informative purposes only; later
        # this might be what we use for matching.
        runcfg['name'] = "{deploy}-{service}-{version}-{instance}".format(
            deploy=service.deployment.id, service=service.name,
            version=len(service.versions)+1,
            instance=service.latest.instance_count if service.latest else 1)

        # We are almost ready, let plugins do some final modifications
        # before we are starting the container.
        self.run_plugins(
            'before_start', service, definition, runcfg, port_assignments)

        # Create the new container
        instance_id = self.backend.prepare(runcfg, service)

        # For now, all services may only run once. If there is already
        # a container for this service, make sure it is shut down.
        for inst in service.instances:
            ctx.log("Killing existing container %s" % inst.container_id[1])
            self.backend.terminate(inst.container_id)
            service.instances.remove(inst)

        # Run the container
        instance_id = self.backend.start(runcfg, service, instance_id)

        service.append_version(version)
        service.append_instance(instance_id)
        ctx.log("New instance id is %s" % instance_id[0])

    #####

    def cache(self, *names):
        """Return a cache path. Same path for same name.
        """
        tmpdir =  path.join(self.controller.volume_base, '_cache', *names)
        if not os.path.exists(tmpdir):
            os.makedirs(tmpdir)
        return tmpdir


class Controller(object):
    """This is the main class of the controller daemon.
    """

    def __init__(self, db_dir, volumes_dir, docker_url=None, plugins=None):
        if not path.exists(volumes_dir):
            os.mkdir(volumes_dir)

        self.volume_base = path.abspath(volumes_dir)

        self._zodb_storage = ZODB.FileStorage.FileStorage(db_dir)
        self._zodb_obj = ZODB.DB(self._zodb_storage)

        if plugins is None:
            self.plugins = load_plugins(Plugin)
        else:
            self.plugins = [p() for p in plugins]

        self.backend = UpstartBackend(docker_url)

    def close(self):
        self._zodb_obj.close()
        self._zodb_storage.close()

    def get_connection(self):
        self._zodb_connection = self._zodb_obj.open()
        if not getattr(self._zodb_connection.root, 'deploy', None):
            self._zodb_connection.root.deploy = DeployDBNew()
        self.migrate(self._zodb_connection.root)
        return self._zodb_connection, self._zodb_connection.root.deploy

    CURRENT_DB_VERSION = 2
    def migrate(self, root):
        """Migrate database schema versions. There must be a cleaner
        way of doing this."""
        if not getattr(root, 'versions', None):
            root.versions = BTrees.OOBTree.BTree()
        no_prev_version = not 'deploydb' in root.versions
        root.versions.setdefault('deploydb', self.CURRENT_DB_VERSION)

        if no_prev_version or root.deploy.__class__.__name__ == 'DeployDB':
            # Change db root object.
            old = root.deploy
            root.deploy = DeployDBNew()
            root.deploy.__dict__ = old.__dict__.copy()
            transaction.commit()
            print "Upgraded Schema"

    def interface(self):
        """
        ZODB absolutely does not like you creating multiple connections
        in the same thread:

        StorageTransactionError: Duplicate tpc_begin calls for same transaction
        """
        return ControllerInterface(self)

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

    def get_plugin(self, klass, require=True):
        for plugin in self.plugins:
            if isinstance(plugin, klass):
                return plugin
        if not require:
            return None
        raise IndexError(klass)

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
            raise ServiceDiscoveryError(e)

    def register(self, servicename, address):
        """This is used by the controller to register itself.
        """
        def regger():
            try:
                cip = os.environ.get('CONTROLLER_IP')
                if cip:
                    opts = '-h %s' % cip
                else:
                    opts = ''
                run('DISCOVERD={0}:1111 sdutil register {opts}  {2}:{1}'.format(
                    self.get_host_ip(), address, servicename, opts=opts), shell=True)
            except CalledProcessError as e:
                raise ServiceDiscoveryError(e)
        return gevent.spawn(regger)

    def run(self, host, port):
        # Register ourselves with service discovery
        greenlet = self.register('docker-deploy', int(port))

        try:
            # Start API
            print('Serving API from :%s' % port)
            app = create_app(self)
            from gevent.wsgi import WSGIServer
            server = WSGIServer((host, int(port)), app)
            server.serve_forever()

        finally:
            greenlet.kill()


def run_controller(host, port):
    controller = Controller(
        docker_url=os.environ.get('DOCKER_HOST', None),
        volumes_dir=os.environ.get('DEPLOY_DATA', '/srv/vdata'),
        db_dir=os.environ.get('DEPLOY_STATE', '/srv/vstate'))

    # Initialize the controller on first run
    with controller.interface() as api:
        set_context(Context(api))
        if not api.db.auth_key:
            api.db.auth_key = binascii.hexlify(os.urandom(256//8)).decode('ascii')
            print('Generated auth key: %s' % api.db.auth_key)

        if not 'system' in api.db.deployments:
            api.create_deployment('system', fail=False)
            api.run_plugins('on_system_init')
            print "Initialized system."
            print "Auth key is: %s" % api.db.auth_key
            return

    controller.run(host, port)


@click.option('--bind')
@click.command()
def cli(bind):
    use_reloader = os.environ.get('RELOADER') == '1'

    # Either the tests have already patched, or we do it now
    import gevent.monkey
    if not gevent.monkey.saved:
        import sys
        # if 'threading' in sys.modules:
        #         raise Exception('threading module loaded before patching!')
        gevent.monkey.patch_all(subprocess=True)

    bind_opt = (bind or '0.0.0.0:5555').split(':', 1)
    if len(bind_opt) == 1:
        host = bind_opt[0]
        port = 5555
    else:
        host, port = bind_opt

    use_reloader = os.environ.get('RELOADER') == '1'
    if use_reloader:
        import werkzeug.serving
        werkzeug.serving.run_with_reloader(lambda: run_controller(host, port))
    else:
        run_controller(host, port)



if __name__ == '__main__':
    cli()
