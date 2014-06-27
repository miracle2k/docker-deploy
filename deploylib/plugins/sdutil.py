"""sdutil is a command line client for discoverd-based service discovery.

This plugin makes it easy to add service discovery to your containers by:

1) Injecting the sdutil binary into containers
2) Rewriting the command line so that sdutil is used.

sdutil can both register your service, as well as consume other services
for you. In both cases, it wraps your actual executable. When consuming
other services, it will provide the addresses of the service you require
via environment variables, and it will start your executable only once
all dependencies are available, and will restart whenever the leader
of a service changes.

Here is an example::

    foo:
        ports: [a, b, c]
        sdutil:
            register: true
            expose:
                bar: BAR

``register`` will cause all ports of the service to be registered with
discoverd; under names like ``deploy_id:foo:a``. ``expose`` will wait
for ``bar`` to be available (``deploy_id:bar``), and put the address
into the environment variable ``BAR``.

If the unnamed default port is used, it will register as
``deploy_id:foo``.

If your container already contains sdutil and you do not want the plugin
to build a new image to include it, you can specify the ``binary`` key::

    foo:
        sdutil:
            register: true
            binary: /bin/sdutil

"""

from io import BytesIO
from deploylib.daemon.context import ctx
from deploylib.plugins import Plugin


class SdutilPlugin(Plugin):

    def before_start(self, service, definition, runcfg, port_assignments):
        deploy_id = service.deployment.id
        cfg = definition['kwargs'].get('sdutil', {})

        # To prefix the command line with sdutil we need to know what
        # it is, and it might be encoded in the image only, not in the
        # service definition.
        entrypoint, cmd = self.read_image_cmdline(runcfg['image'])

        # The values declared in the image are more important though.
        if runcfg['entrypoint']:
            entrypoint = runcfg['entrypoint']
        if runcfg['cmd']:
            cmd = runcfg['cmd']

        # Combine entrypoint and cmd
        current_cmd = []
        if entrypoint:
            current_cmd.append(entrypoint)
        if cmd:
            current_cmd.extend(cmd)
        new_cmd = current_cmd

        # Build a new image with the sdutil binary, or use existing path
        if not 'binary' in cfg:
            runcfg['image'], binary = self.add_to_image(runcfg['image'])
        else:
            binary = cfg.get('binary', '/sdutil')

        # Do service consumption first, such that we won't be registered
        # while still waiting for dependencies.
        if cfg.get('expose'):
            # simple add the expose calls
            deps = []
            for sname, varname in cfg['expose'].items():
                deps.extend(['-d', '{}:{}:{}'.format(varname, deploy_id, sname)])

            new_cmd = [binary, 'expose'] + deps + new_cmd

        # Support registering all ports
        if cfg.get('register'):
            regs = []
            for pname, map in port_assignments.items():
                if not map['host']:
                    continue
                register_as = '{did}:{sname}'.format(
                    did=deploy_id, sname=service.name)
                if pname:
                    # deploy:service:port or deploy:service for the
                    # default port, indicated by an empty string.
                    register_as = '%s:%s' % (register_as, pname)
                regs.extend(['-s', '%s:%s' % (register_as, map['host'][1])])

            new_cmd = [binary, 'exec'] + regs + new_cmd

            # TODO: Should we also expose ports not bound on the host by
            # letting sdutil register with the eth0 interface ip?

        # Be sure to replace both cmd and any existing entrypoint
        if new_cmd != current_cmd:
            runcfg['cmd'] = new_cmd[1:]
            runcfg['entrypoint'] = new_cmd[0]

    def read_image_cmdline(self, imgname):
        """Get Entrypoint and Cmd from image."""
        docker = ctx.cintf.backend.client
        ctx.log('Inspecting image %s' % imgname)
        image_info = docker.inspect_image(imgname)
        entrypoint = image_info['config']['Entrypoint']
        cmd = image_info['config']['Cmd']
        assert isinstance(cmd, list) or cmd is None
        assert isinstance(entrypoint, list) or entrypoint is None
        return entrypoint, cmd

    def add_to_image(self, imgname):
        """Builds a new docker image that contains sdutil.
        """
        docker = ctx.cintf.backend.client
        ctx.job('Building version of %s with sdutil inside' % imgname)
        newimg, _ = docker.build(fileobj=BytesIO("""
FROM {old_img}
ADD https://sdutil.s3.amazonaws.com/sdutil.linux /sdutil
RUN chmod +x /sdutil
""".format(old_img=imgname)))

        return newimg, '/sdutil'
