from os import path
import uuid
from fabric.api import execute, run, get, put
import io
import yaml


class Service(dict):

    def __init__(self, name, data):
        data.setdefault('volumes', [])
        data.setdefault('env', {})
        data.setdefault('ports', {})

        dict.__init__(self, data)
        self['name'] = name
        if not 'image' in self:
            self['image'] = name

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError:
            raise AttributeError(item)


class ServiceFile(object):
    """A file listing multiple services."""

    @classmethod
    def load(cls, filename):
        with open(filename, 'r') as f:
            structure = yaml.load(f)

        servicefile = cls()
        for name, service in structure.items():
            if name == '?':
                # Special id gives the name
                servicefile.name = name
                continue
            service = Service(name, service)
            servicefile.services.append(service)

        return servicefile

    def __init__(self, name=None, services=None):
        self.name = name
        self.services = services or []


class Host(object):
    """Represents the host management service.

    Might run server-side in the future (or by flynn-host). For now,
    uses fabric to run commands.

    Uses the following on the host:

    /srv/vdata/
        Exposed volumes here

    /srv/deploydb/
        Which containers/services are managed by us.
    """

    def __init__(self, hoststr):
        self.host = hoststr
        self.volume_base = '/srv/vdata'
        self.state_base = '/srv/vstate'

    def docker(self, cmdline, *args, **kwargs):
        return self.e(run, 'docker %s' % cmdline.format(*args, **kwargs))

    def e(self, *a, **kw):
        kw.setdefault('hosts', [self.host])
        result = execute(*a, **kw)
        # Contains one string for each host
        return result.values()[0]

    def get_info(self, deploy_id, service_name):
        """Search the host state database for this service."""
        statefile = path.join(self.state_base, deploy_id, service_name.replace('/', ':'))
        state = io.BytesIO()
        try:
            self.e(get, statefile, state)
        except:
            return None
        return state.getvalue()

    def set_info(self, deploy_id, service_name, container_id):
        """Set server state for service.
        """
        statefile = path.join(self.state_base, deploy_id, service_name.replace('/', ':'))
        self.e(run, 'mkdir -p "{}"'.format(path.dirname(statefile)))
        state = io.BytesIO(container_id)
        self.e(put, state, statefile)

    def deploy_servicefile(self, deploy_id, servicefile):
        for service in servicefile.services:
            self.deploy_service(deploy_id, service)

    def deploy_service(self, deploy_id, service):
        # Make sure the docker image is available
        self.docker('pull {}', service.image)

        # Determine the volumes on the host
        cmd_volumes = {}
        for volume in service.volumes:
            # TODO: We should make sure two volumes cannot resolve to
            # the same path on the host: add a hash, or keep a registry
            assert volume[0] == '/'
            volume_id = volume[1:].replace('/', '_')
            host_path = path.join(
                self.volume_base, deploy_id, service.name, volume_id)
            cmd_volumes[host_path] = volume

        # Determine the final ports to use on the host
        cmd_ports = {}
        for port, expose in service.ports.items():
            if expose == 'wan':
                expose = port
            cmd_ports[expose] = port

        # For now, all services may only run once. See if the container
        # has been run before, if yes, kill it first.
        existing_id = self.get_info(deploy_id, service.name)
        if existing_id:
            try:
                self.docker('kill {name} && docker rm {name}', name=existing_id)
            except:
                pass

        # Construct a name, for informative purposes only
        name = "{}-{}".format(deploy_id, uuid.uuid4().hex[:5])

        # Make sure the volumes exist
        for host_path in cmd_volumes.keys():
            self.e(run, 'mkdir -p "{}"'.format(host_path))

        # Run the container
        optstring = self.fmt_docker_options(
            service.image, name, cmd_volumes, service.env, cmd_ports,
            service.cmd)
        print(optstring)
        new_id = self.docker('run -d {}', optstring)

        # splitlines to ignore e.g. deprecation warnings printed before
        container_id = new_id.splitlines()[-1]
        self.set_info(deploy_id, service.name, container_id)

    def get_container_ip(self, name):
        return self.docker('''inspect {} | grep IPAddress | cut -d '"' -f 4'''.format(name))

    def fmt_docker_options(self, image, name, volumes, env, ports, cmd):
        return '{name} {volumes} {ports} {env} {image} {cmd}'.format(
            image=image,
            name='--name "{}"'.format(name) if name else '',
            volumes=' '.join(['-v "%s:%s"' % (h, g) for h, g in volumes.items()]),
            env=' '.join(['-e %s="%s"' % (k, v) for k, v in env.items()]),
            ports=' '.join(['-p %s:%s' % (k, v) for k, v in ports.items()]),
            cmd=cmd
        )
