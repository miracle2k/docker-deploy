"""Can wrap containers with sdutil for service discovery registration
and consumption:

foo:
    ports: [a, b, c]
    sdutil:
        # Register all mapped ports with discoverd
        register: true
        expose:
            service: ENV_VAR

For now, requires ``/sdutil`` binary to exist in the container.

NOTE: This does not read the entrypoint from the image, so you need
to re-declare the entrypoint in the service definition, or otherwise
things will likely not work.
"""

from deploylib.plugins import Plugin


class SdutilPlugin(Plugin):

    def before_start(self, service, definition, runcfg, port_assignments):

        deploy_id = service.deployment.id
        cfg = definition['kwargs'].get('sdutil', {})
        binary = cfg.get('binary', '/sdutil')

        current_cmd = []
        if runcfg['entrypoint']:
            current_cmd.append(runcfg['entrypoint'])
        if runcfg['cmd']:
            current_cmd.extend(runcfg['cmd'])
        new_cmd = current_cmd

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

