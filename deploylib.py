import contextlib
import os
from os.path import join as path, dirname, abspath
import tempfile
import uuid
from fabric.api import execute, run, get, put, local
import io
import yaml


@contextlib.contextmanager
def directory(path):
    old = os.getcwd()
    os.chdir(path)
    yield
    os.chdir(old)


class Service(dict):

    def __init__(self, name, data):
        # Shortcut specifies only the command
        if isinstance(data, basestring):
            data = {'cmd': data}

        data.setdefault('volumes', [])
        data.setdefault('cmd', '')
        data.setdefault('entrypoint', '')
        data.setdefault('env', {})
        data.setdefault('ports', {})

        dict.__init__(self, data)

        # Image can be given instead of an explicit name. The last
        # part of the image will be used as the name only
        self['name'] = name
        if not 'image' in self:
            self['image'] = name
            self['name'] = name.split('/')[-1]

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

    def cache(self, *names):
        """Return a cache path. Same path for same name.
        """
        path = '/srv/vcache/{}'.format('/'.join(names))
        self.e(run, 'mkdir -p "{}"'.format(path))
        return path

    def get_instances(self):
        """Return all service instances."""
        instances = self.e(run, 'ls -1 {}'.format(self.state_base))
        return instances.splitlines()

    def get_info(self, deploy_id, service_name):
        """Search the host state database for this service."""
        statefile = path(self.state_base, deploy_id, service_name.replace('/', ':'))
        state = io.BytesIO()
        try:
            self.e(get, statefile, state)
        except:
            return None
        return state.getvalue()

    def set_info(self, deploy_id, service_name, container_id):
        """Set server state for service.
        """
        statefile = path(self.state_base, deploy_id, service_name.replace('/', ':'))
        self.e(run, 'mkdir -p "{}"'.format(dirname(statefile)))
        state = io.BytesIO(container_id)
        self.e(put, state, statefile)

    def discover(self, servicename):
        # sdutil does not support specifying a discoverd host yet, which is
        # fine with us for now since all is running on the same host.
        return self.e(run, 'DISCOVERD={} sdutil services -1 {}'.format(
            '{}:1111'.format(self.get_container_ip('discoverd')),
            servicename))

    def deploy_servicefile(self, deploy_id, servicefile, **kwargs):
        for service in servicefile.services:
            self.deploy_service(deploy_id, service, **kwargs)

    def deploy_service(self, deploy_id, service, **kwargs):
        if 'git' in service:
            return AppPlugin(self).deploy(deploy_id, service)
        else:
            return self.deploy_docker_image(deploy_id, service, **kwargs)

    def deploy_docker_image(self, deploy_id, service, namer=None):
        """Deploy a regular docker image.
        """

        # Make sure the docker image is available
        self.docker('pull {}', service.image)

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
            if expose == 'wan':
                expose = port
            cmd_ports[expose] = port

        # The environment variables
        cmd_env = {}
        cmd_env['DISCOVERD'] = 'discoverd.docker:1111'
        cmd_env['ETCD'] = 'etcd.docker'
        cmd_env.update(service.env)

        # For now, all services may only run once. See if the container
        # has been run before, if yes, kill it first.
        existing_id = self.get_info(deploy_id, service.name)
        if existing_id:
            try:
                self.docker('kill {name} && docker rm {name}', name=existing_id)
            except:
                pass

        # Construct a name, for informative purposes only
        name = namer(service) if namer else "{}-{}".format(deploy_id, uuid.uuid4().hex[:5])

        # Make sure the volumes exist
        for host_path in cmd_volumes.keys():
            self.e(run, 'mkdir -p "{}"'.format(host_path))

        # Run the container
        optstring = self.fmt_docker_options(
            service.image, name, cmd_volumes, cmd_env, cmd_ports,
            service.cmd, service.entrypoint)
        print(optstring)
        new_id = self.docker('run -d {}', optstring)

        # splitlines to ignore e.g. deprecation warnings printed before
        container_id = new_id.splitlines()[-1]
        self.set_info(deploy_id, service.name, container_id)

    def get_container_ip(self, name):
        return self.docker('''inspect {} | grep IPAddress | cut -d '"' -f 4'''.format(name))

    def fmt_docker_options(self, image, name, volumes, env, ports, cmd, entrypoint):
        return '{name} {entrypoint} {volumes} {dns} {ports} {env} {image} {cmd}'.format(
            image=image,
            name='--name "{}"'.format(name) if name else '',
            volumes=' '.join(['-v "%s:%s"' % (h, g) for h, g in volumes.items()]),
            env=' '.join(['-e %s="%s"' % (k, v) for k, v in env.items()]),
            ports=' '.join(['-p %s:%s' % (k, v) for k, v in ports.items()]),
            cmd=cmd,
            dns='-dns 10.0.3.1',
            entrypoint='-entrypoint {}'.format(entrypoint) if entrypoint else ''
        )


class AppPlugin(object):
    """Will run a 12-factor style app.
    """

    def __init__(self, host):
        self.host = host
        self.e = self.host.e

    def build(self, deploy_id, service):
        e = self.e
        l = lambda cmd, *a, **kw: self.e(local, cmd.format(*a, **kw), capture=True)

        # Detect the shelve service first
        shelf_ip = self.host.discover('shelf')

        # The given path may be a subdirectory of a repo
        # For git archive to work right we need the sub path relative
        # to the repository root.
        project_path = abspath(service.git)
        with directory(project_path):
            git_root = l('git rev-parse --show-toplevel')
            gitsubdir = project_path[len(git_root):]

        # Determine git version
        with directory(project_path):
            app_version = l('git rev-parse HEAD')[:10]

        release_id = "{}/{}:{}".format(deploy_id, service.name, app_version)

        # Create and push the git archive
        remote_temp = '/tmp/{}'.format(uuid.uuid4().hex)
        with directory(project_path):
            temp = tempfile.mktemp()
            l('git archive HEAD:{} > {}', gitsubdir, temp)
            e(put, temp, remote_temp)
            l('rm {}', temp)

        # Build into a slug
        # Note: buildstep would give us a real exclusive image, rather than a
        # container that presumably needs to unpack the slug every time. Maybe
        # we could also commit the slugrunner container after the first run?
        slug_url = 'http://{}{}'.format(shelf_ip, '/slugs/{}'.format(release_id))
        cache_dir = self.host.cache('slugbuilder', deploy_id, service.name)
        cmds = [
            'mkdir -p "%s"' % cache_dir,
            'cat {} | docker run -v {cache}:/tmp/cache:rw -i -a stdin -a stdout flynn/slugbuilder {outuri}'.format(
                remote_temp, outuri=slug_url, cache=cache_dir
            )
        ]
        self.e(run, ' && '.join(cmds))

        return slug_url

    def deploy(self, deploy_id, service):
        slug_url = self.build(deploy_id, service)

        # In addition to the service defined ENV, add some of our own.
        # These give the container access to service discovery
        env = {
           'APP_ID': deploy_id,
           'SD_NAME': '{}/{}'.format(deploy_id, service.name),
           'SLUG_URL': slug_url,
           'PORT': '8000'
        }
        env.update(service.env)

        self.host.deploy_docker_image(deploy_id, Service(service.name, {
            'image': 'elsdoerfer/slugrunner',
            'cmd': 'start {proc}'.format(proc=service.cmd),
            'env': env,
            'volumes': service.volumes
        }), )


class DomainPlugin(object):
    """

    """

    #def deploy(self, deploy_id, service):
    #    ask discoverd for router RPC address
    #
    #    foreach domain:
    #        register with service name and ssl cert



