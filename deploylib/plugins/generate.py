"""
on global key set - generates the passwords as a resource

- either add to all env in before_start
- or come up with a system for variable replacement...
"""

"""Supports generating text strings, like passwords::

    Generate:
        DatabasePassword:
            - hex: 15

These will be made available as local variables, that you can add to
the environment::

    Env:
        POSTGRES_PASSWORD: "{DatabasePassword}"
"""

import os
import binascii
from persistent.mapping import PersistentMapping
from deploylib.plugins import Plugin


class GeneratePlugin(Plugin):

    def on_globals_changed(self, deployment):
        keys = deployment.globals.get('Generate', {})
        if not keys:
            return

        store = deployment.data.setdefault('Generate', PersistentMapping())
        for key, options in keys.items():
            if key in store:
                # Has already been generated
                continue

            bytes = options.get('hex', 32)
            string = binascii.b2a_hex(os.urandom(bytes))
            store[key] = string

    def provide_vars(self, service, version, definition, vars):
        keys = service.deployment.data.get('Generate', {})
        vars.update(keys)
