"""Supports defining variables, more appropriately called constants::

    Vars:
        ServiceName: foo

TODO: Currently this plugin is disabled, because we need to think about the
design of variables more. It is currently not clear where and when what
is supposed to be replaced, and in particular how this should work for plugins
that run outside the "deploy container" code where the replacement vars
are currently being put together.
"""

from deploylib.plugins import LocalPlugin


class VarsPlugin(LocalPlugin):

    def provide_local_vars(self, service, vars):
        for key, item in service.globals.get('Vars', {}).items():
            vars[key] = item.format(**vars)
