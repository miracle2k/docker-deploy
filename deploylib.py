import contextlib
import json
import os
from os.path import join as path, dirname, abspath, exists
import random
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


import yaml
import yaml.constructor

try:
    # included in standard lib from Python 2.7
    from collections import OrderedDict
except ImportError:
    # try importing the backported drop-in replacement
    # it's available on PyPI
    from ordereddict import OrderedDict

class OrderedDictYAMLLoader(yaml.Loader):
    """
    A YAML loader that loads mappings into ordered dictionaries.
    """

    def __init__(self, *args, **kwargs):
        yaml.Loader.__init__(self, *args, **kwargs)

        self.add_constructor(u'tag:yaml.org,2002:map', type(self).construct_yaml_map)
        self.add_constructor(u'tag:yaml.org,2002:omap', type(self).construct_yaml_map)

    def construct_yaml_map(self, node):
        data = OrderedDict()
        yield data
        value = self.construct_mapping(node)
        data.update(value)

    def construct_mapping(self, node, deep=False):
        if isinstance(node, yaml.MappingNode):
            self.flatten_mapping(node)
        else:
            raise yaml.constructor.ConstructorError(None, None,
                'expected a mapping node, but found %s' % node.id, node.start_mark)

        mapping = OrderedDict()
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                hash(key)
            except TypeError, exc:
                raise yaml.constructor.ConstructorError('while constructing a mapping',
                    node.start_mark, 'found unacceptable key (%s)' % exc, key_node.start_mark)
            value = self.construct_object(value_node, deep=deep)
            mapping[key] = value
        return mapping


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

    @property
    def ports(self):
        """Ways to specify ports:

        NAME: EXPOSURE
            Provider to container a random mapped port named NAME.

        PORT : EXPOSURE
            Map the specified local PORT to the same host port.

        PORT : PORT
            Map the specified local PORT to the specified host port.

        NAME : PORT
            Illegal.

        (TODO: Needs reworking: What if I want to specify an exposure
        for a PORT:PORT mapping? The strowger bootstrapped service
        is an example of this actually)

        Exposure values for ports are:

        - wan: Map to public host ip.
        - host: Map to docker0 interface.
        """
        ports = self['ports']
        # If a list is specified, assume "host" for all.
        if isinstance(ports, list):
            return {p: 'host' for p in ports}
        return ports

    def path(self, p):
        """Make the given path absolute."""
        return self.from_file.path(p)


class ServiceFile(object):
    """A file listing multiple services."""

    @classmethod
    def load(cls, filename):
        with open(filename, 'r') as f:
            # Services should generally not depend on a specific order,
            # instead rely on service discovery.
            # There is one exception though: When deploying an initial
            # template, a database might need to be initialized first
            # to setup a user account, before that user account can be
            # added to another containers environment.
            opts={'Loader': OrderedDictYAMLLoader}
            structure = yaml.load(f, **opts)

        servicefile = cls()
        servicefile.filename = filename
        for name, service in structure.items():
            if name == '?':
                # Special id gives the name
                servicefile.name = name
                continue
            if name[0].isupper():
                # Uppercase idents are non-service types
                servicefile.data.update({name: service})
                continue
            service = Service(name, service)
            service.from_file = servicefile
            servicefile.services.append(service)

        # Resolve includes:
        for include in servicefile.data.get('Includes', []):
            sf = ServiceFile.load(include)
            sf.from_file = servicefile
            new_data = sf.data
            # Merge one level deep
            for key, value in servicefile.data.items():
                if isinstance(value, dict):
                    new_data.setdefault(key, {})
                    new_data[key].update(value)
                # TODO: lists
                else:
                    new_data[key] = value
            servicefile.data = new_data
            servicefile.services.extend(sf.services)

        return servicefile

    def __init__(self, name=None, services=None, other_data=None):
        self.data = other_data or {}
        self.name = name
        self.services = services or []
        self.from_file = None

    def path(self, p):
        """Make the given path absolute."""
        return abspath(path(dirname(self.filename), p))

    def __getitem__(self, item):
        return self.data[item]

    @property
    def root(self):
        """If a service file was included, this finds the root."""
        sf = self
        while sf.from_file:
            sf = sf.from_file
        return sf

    @property
    def env(self):
        return self.root.data.get('Env') or {}


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

    def discover(self, servicename):
        # sdutil does not support specifying a discoverd host yet, which is
        # fine with us for now since all is running on the same host.
        return self.e(run, 'DISCOVERD={} sdutil services -1 {}'.format(
            '{}:1111'.format(self.get_ip('discoverd')),
            servicename))

    def deploy_servicefile(self, deploy_id, servicefile, **kwargs):
        for service in servicefile.services:
            self.deploy_service(deploy_id, service, **kwargs)

        DomainPlugin(self).post_deploy(servicefile)

    def deploy_service(self, deploy_id, service, **kwargs):
        if 'git' in service:
            return AppPlugin(self).deploy(deploy_id, service)
        else:
            return self.deploy_docker_image(deploy_id, service, **kwargs)

    def deploy_docker_image(self, deploy_id, service, namer=None):
        """Deploy a regular docker image.
        """

        portvars = self.get_ports().get(deploy_id, {})
        cmd_vars = portvars.copy()

        host_ip = self.get_ip(interface='docker0')
        cmd_vars['HOST'] = host_ip

        # Make sure the docker image is available
        #self.docker('pull {}', service.image)

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

        # For now, all services may only run once. See if the container
        # has been run before, if yes, kill it first.
        existing_id = self.get_info(deploy_id, service.name)
        if existing_id:
            try:
                self.docker('kill {name} && docker rm {name}', name=existing_id)
            except:
                pass

        # Construct a name, for informative purposes only
        container_name = namer(service) if namer else "{}-{}".format(deploy_id, uuid.uuid4().hex[:5])

        # Make sure the volumes exist
        for host_path in cmd_volumes.keys():
            self.e(run, 'mkdir -p "{}"'.format(host_path))

        # Wrap the command in sdutil calls if desired. This requires the
        # images to a) have /sdutil b) not rely on an entrypoint.
        # TODO: We need a solution for this sdutil-for-all problem:
        #    - docker in docker: a container with sdutil
        #    - shouldn't flynn-host / "docker-run" do the service
        #        discovery, at least in a setup where it knows all the data?
        #    - the sdutil mode (see ticket) to watch an external process...
        #    - patch sdutil into the image using "createContainer" API and
        #      "docker insert", or by executing a docker build file.
        if 'register' in service:
            cmd = service.cmd
            for port, pname in service.register.items():
                cmd = '/sdutil exec -i eth0 {did}:{sname}:{pname}:{p} {cmd}'.format(
                    did=deploy_id, sname=service.name, pname=pname, p=port, cmd=cmd)
            service.cmd = cmd[len('/sdutil '):]
            service.entrypoint = '/sdutil'

        # Run the container
        optstring = self.fmt_docker_options(
            service.image, container_name, cmd_volumes, cmd_env, cmd_ports,
            service.cmd, service.entrypoint)
        optstring = optstring.format(**cmd_vars)
        print(optstring)
        new_id = self.docker('run -d {}', optstring)

        # Store used ports
        self.set_ports(portvars)

        # splitlines to ignore e.g. deprecation warnings printed before
        container_id = new_id.splitlines()[-1]
        self.set_info(deploy_id, service.name, container_id)

    def get_ip(self, container=None, interface=None):
        if container:
            return self.docker('''inspect {} | grep IPAddress | cut -d '"' -f 4'''.format(container))
        else:
            return self.e(run, "/sbin/ifconfig %s | grep 'inet addr' | cut -d: -f2 | awk '{print $1}'" % interface)


    def fmt_docker_options(self, image, name, volumes, env, ports, cmd, entrypoint):
        return '{name} {entrypoint} {volumes} {ports} {env} {image} {cmd}'.format(
            image=image,
            name='--name "{}"'.format(name) if name else '',
            volumes=' '.join(['-v "%s:%s"' % (h, g) for h, g in volumes.items()]),
            env=' '.join(['-e %s="%s"' % (k, v) for k, v in env.items()]),
            ports=' '.join(['-p %s:%s' % (k, v) for k, v in ports.items()]),
            cmd=cmd,
            entrypoint='-entrypoint {}'.format(entrypoint) if entrypoint else ''
        )


class Plugin(object):

    def __init__(self, host):
        self.host = host
        self.e = self.host.e


class AppPlugin(Plugin):
    """Will run a 12-factor style app.
    """

    def build(self, deploy_id, service):
        e = self.e
        l = lambda cmd, *a, **kw: self.e(local, cmd.format(*a, **kw), capture=True)

        # Detect the shelve service first
        shelf_ip = self.host.discover('shelf')

        # The given path may be a subdirectory of a repo
        # For git archive to work right we need the sub path relative
        # to the repository root.
        project_path = service.path(service.git)
        with directory(project_path):
            git_root = l('git rev-parse --show-toplevel')
            gitsubdir = project_path[len(git_root):]

        # Determine git version
        with directory(project_path):
            app_version = l('git rev-parse HEAD')[:10]

        release_id = "{}/{}:{}".format(deploy_id, service.name, app_version)
        slug_url = 'http://{}{}'.format(shelf_ip, '/slugs/{}'.format(release_id))

        # Check if the file exists already
        statuscode = e(run, "curl -s -o /dev/null -w '%{http_code}' --head " + slug_url)
        if statuscode == '200':
            return slug_url

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
        cache_dir = self.host.cache('slugbuilder', deploy_id, service.name)
        env = self.get_env(deploy_id, service, slug_url)
        cmds = [
            'mkdir -p "%s"' % cache_dir,
            'cat {} | docker run -v {cache}:/tmp/cache:rw {env} -i -a stdin -a stdout elsdoerfer/slugbuilder {outuri}'.format(
                remote_temp, outuri=slug_url, cache=cache_dir,
                env=' '.join(['-e %s="%s"' % (k, v) for k, v in env.items()]),
            )
        ]
        self.e(run, ' && '.join(cmds))

        return slug_url

    def get_env(self, deploy_id, service, slug_url):
        # In addition to the service defined ENV, add some of our own.
        # These give the container access to service discovery
        env = {
           'APP_ID': deploy_id,
           'SLUG_URL': slug_url,
           'PORT': '8000',
           'SD_ARGS': 'exec -i eth0 {}:{}:{}'.format(deploy_id, service.name, 8000)
        }
        env.update(service.env)
        return env

    def deploy(self, deploy_id, service):
        slug_url = self.build(deploy_id, service)

        env = self.get_env(deploy_id, service, slug_url)

        deps = ['-d {}:{}:{}'.format(varname, deploy_id, sname)
                for sname, varname in service.get('expose', {}).items()]
        if deps:
            env['SD_ARGS'] = 'expose {deps} {cmd}'.format(
                deps=' '.join(deps),
                cmd='sdutil %s' % env['SD_ARGS']
            )

        self.host.deploy_docker_image(deploy_id, Service(service.name, {
            'image': 'elsdoerfer/slugrunner',
            'cmd': 'start {proc}'.format(proc=service.cmd),
            'env': env,
            'volumes': service.volumes,
            'from_file': service.from_file
        }), )


class DomainPlugin(Plugin):
    """Will process a Domains section, which defines domains
    and maps them to services, and register those mappings with
    the strowger router.
    """

    def post_deploy(self, servicefile):
        domains = servicefile.data.get('Domains', {})
        if not domains:
            return

        rpc_ip = self.host.discover('flynn-strowger-rpc')

        for domain, data in domains.items():
            cert = key = None
            if 'cert' in data:
                cert = open(servicefile.path(data['cert']), 'r').read()
                key_paths = [servicefile.path(data['key'])]
                if 'KEY_PATH' in os.environ:
                    key_paths.append(path(os.environ['KEY_PATH'], data['key']))
                for candidate in key_paths:
                    if exists(candidate):
                        key = open(candidate, 'r').read()
                if not key:
                    raise ValueError('key not found in: %s' % key_paths)

            self.host.e(run,
                'strowger-rpc -rpc {rpc} {ssh} {domain} {sname}'.format(
                    rpc=rpc_ip,
                    ssh='-cert "{cert}" -key "{key}"'.format(cert=cert, key=key) if cert else '',
                    domain=domain,
                    sname=data['service-name']
                ))

        # TODO: Support further plugins to configure the domain DNS
