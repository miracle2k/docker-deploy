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
from .utils import OrderedDictYAMLLoader


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


class Plugin(object):

    def __init__(self, host):
        self.host = host
        self.e = self.host.e


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

        from .plugins.app import AppPlugin
        from .plugins.domains import DomainPlugin
        self.plugins = [AppPlugin(self), DomainPlugin(self)]

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

        self.run_plugins('post_deploy', servicefile)

    def deploy_service(self, deploy_id, service, **kwargs):
        if not self.run_plugins('deploy', deploy_id, service):
            return self.deploy_docker_image(deploy_id, service, **kwargs)

    def run_plugins(self, method_name, *args, **kwargs):
        for plugin in self.plugins:
            method = getattr(plugin, method_name, None)
            if not method:
                continue
            if method(*args, **kwargs):
                return True
        else:
            return False

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

