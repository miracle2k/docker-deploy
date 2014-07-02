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
from zope.generations.generations import PersistentDict
from deploylib.plugins import Plugin


class GeneratePlugin(Plugin):

    def on_globals_changed(self, deployment):
        keys = deployment.globals.get('Generate', {})
        if not keys:
            return

        store = deployment.data.setdefault('Generate', PersistentDict())
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
