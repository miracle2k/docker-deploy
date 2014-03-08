import os
import netifaces
import docker


class LocalMachineBackend(object):

    def __init__(self):
        self.volume_base = os.environ.get('DEPLOY_DATA', '/srv/vdata')
        self.state_base = os.environ.get('DEPLOY_STATE', '/srv/vstate')

    def get_interface_id(self, interface):
        """Get IP from local interface."""
        return netifaces.ifaddresses('docker0')[netifaces.AF_INET][0]['addr']

    def cache(self, *names):
        """Return a cache path. Same path for same name.
        """
        path = '/srv/vcache/{}'.format('/'.join(names))
        self.e(run, 'mkdir -p "{}"'.format(path))
        return path

    def list_state_dir(self):
        return os.listdir(self.state_base)

    def _get_file(self, filename):
        buffer = io.BytesIO()
        try:
            self.e(get, filename, buffer)
        except:
            return None
        return buffer.getvalue()

    def get_ports(self):
        portfile = path(self.state_base, '_ports_')
        data = self._get_file(portfile)
        return json.loads(data) if data else {}

    def set_ports(self, ports):
        portfile = path(self.state_base, '_ports_')
        state = io.BytesIO(json.dumps(ports))
        self.e(put, state, portfile)

    def get_info(self, deploy_id, service_name):
        """Search the host state database for this service."""
        statefile = path(self.state_base, deploy_id, service_name.replace('/', ':'))
        return self._get_file(statefile)

    def set_info(self, deploy_id, service_name, container_id):
        """Set server state for service.
        """
        statefile = path(self.state_base, deploy_id, service_name.replace('/', ':'))
        self.e(run, 'mkdir -p "{}"'.format(dirname(statefile)))
        state = io.BytesIO(container_id)
        self.e(put, state, statefile)


class DockerHost(LocalMachineBackend):
    """Runs service files on a docker host via the API.

    Uses the following on the host:

    /srv/vdata/
        Exposed volumes here

    /srv/deploydb/
        Which containers/services are managed by us.
    """

    def __init__(self, docker_url=None, plugins=None):
        LocalMachineBackend.__init__(self)

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

    def deploy_servicefile(self, deploy_id, servicefile, **kwargs):
        for service in servicefile.services:
            self.deploy_service(deploy_id, service, **kwargs)

        self.run_plugins('post_deploy', servicefile)

    def deploy_service(self, deploy_id, service, **kwargs):
        if not self.run_plugins('deploy', deploy_id, service):
            return self.deploy_docker_image(deploy_id, service, **kwargs)

    def deploy_docker_image(self, deploy_id, service, namer=None):
        """Deploy a regular docker image.
        """

        portvars = self.get_ports().get(deploy_id, {})
        cmd_vars = portvars.copy()

        host_ip = self.get_interface_ip('docker0')
        cmd_vars['HOST'] = host_ip

        # Determine the volumes on the host
        cmd_volumes = {}
        for volume in service.volumes:
            # TODO: We should make sure two volumes cannot resolve to
            # the same path on the host: add a hash, or keep a registry
            assert volume[0] == '/'
            volume_id = volume[1:].replace('/', '_')
            host_path = path(
                self.volume_base, deploy_id, service.name, volume_id)
            cmd_volumes[host_path] = volume

        # Determine the final ports to use on the host
        cmd_ports = {}
        for port, expose in service.ports.items():
            if isinstance(port, basestring):
                # Assign a random port
                varname = 'PORT_{}'.format(port.upper())
                port = random.randint(10000, 50000)
                cmd_vars[varname] = port
                portvars['%s.%s' % (service.name, varname)] = port
                assert isinstance(expose, basestring)  # name: number syntax not allowed
            if expose == 'wan' or expose == 'host':
                internal = port
            else:
                internal = expose
            if expose == 'host':
                port = "%s:%s" % (host_ip, port)
            # expose is the internal port
            cmd_ports[port] = internal

        # The environment variables
        cmd_env = (service.from_file.env.get(service.name, {}) or {}).copy()
        cmd_env['DISCOVERD'] = '%s:1111' % host_ip
        cmd_env['ETCD'] = 'http://%s:4001' % host_ip
        cmd_env.update(service.env)

        self.client.create_container(
            image=service.image,
            name=container_name,
            command=service.cmd,
            environment=cmd_env,
            entrypoint=service.entrypoint)

        # For now, all services may only run once. See if the container
        # has been run before, if yes, kill it first.
        existing_id = self.get_info(deploy_id, service.name)
        if existing_id:
            self.client.kill(existing_id)

        # Construct a name, for informative purposes only
        container_name = namer(service) if namer else "{}-{}".format(deploy_id, uuid.uuid4().hex[:5])

        # Make sure the volumes exist
        for host_path in cmd_volumes.keys():
            self.e(run, 'mkdir -p "{}"'.format(host_path))

        # Run the container
        c.start(container_name, binds=volumes, port_bindings=ports, privileged=True)

        # Store used ports
        self.set_ports(portvars)

        # splitlines to ignore e.g. deprecation warnings printed before
        container_id = new_id.splitlines()[-1]
        self.set_info(deploy_id, service.name, container_id)

    def get_instances(self):
        """Return all service instances."""
        return self.list_state_dir()
