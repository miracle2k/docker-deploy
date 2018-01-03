"""
we might not need this so importantly at the beginning, if we have a way to open shells manually
- what is the usecase? for example, running a "createdb" command.

- we do have a resource system
- consider that resources could be resolved in the client only
- difficulty: how do we handle resources that take very long to comlete and might in fact initially fail?

if we do have a server system:
    - there might be a formalized system for resources
    - this system might be a plugin
         (a compiled-in plugin, calling executable via CGI, simply a system to handle global gets)
    - it would handle before_start to block the start

but we want to keep it simple; this should be written in code, and be first-class.

"""


"""Declare run-once resources::

    Run:
        InitAssets:
            service: forum
            cmd: push-assets

    forum:
        require: InitAssets

In this example, the controller will run a version of the ``forum`` service
once with ``cmd`` set to ``push-assets``. The resource is considered
available when the service completes with exit code 0.

In the example, the actual ''forum`` service is held back until that has
happened.
"""

from deploylib.daemon.context import ctx
from deploylib.daemon.controller import DeployError
from deploylib.plugins import Plugin


class ExecPlugin(Plugin):

    def on_globals_changed(self, deployment):
        self.execute_runs(deployment)

    def post_setup(self, service, version):
        self.execute_runs(service.deployment)

    def execute_runs(self, deployment):
        """Execute any outstanding Run resources that are ready.
        """
        keys = deployment.globals.get('Exec', {})
        if not keys:
            return

        for name, options in keys.items():
            # Already provided
            if deployment.get_resource(name):
                continue

            # The run resource will have dependencies of its own,
            # are they available yet?
            if 'service' in options:
                if not deployment.has_service(options['service'], allow_hold=True):
                    continue
            if ctx.cintf.run_plugins('setup_resource', deployment, name, options):
                continue

            # Run the command now
            ctx.job('Executing "{cmd}" of service {service}'.format(**options))
            service = deployment.services[options['service']]
            self._run_image(service, service.version, options['cmd'])
            ctx.cintf.set_resource(deployment.id, name, True)

    def _run_image(self, service, version, cmd):
        runcfg, definition, _ = ctx.cintf.generate_runcfg(service, version)
        runcfg['cmd'] = [cmd]

        ctx.cintf.run_plugins('before_once', service, definition, runcfg)
        exitcode = ctx.cintf.backend.once(runcfg)
        if exitcode:
            raise DeployError('Run job returned exit code %s' % exitcode)
