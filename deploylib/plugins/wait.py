"""Waits for an URL to become available before starting a service.

This really should not be used. We only need it for the initial bootstrap.
"""

import socket
from urlparse import urlparse

from deploylib.plugins import Plugin


class WaitPlugin(Plugin):

    def setup(self, service, version):
        # TODO: Make sure this runs before other setup() hooks.
        definition = version.definition
        if not 'wait' in definition['kwargs']:
            return

        url = urlparse(definition['kwargs']['wait'])

        is_closed = True
        print("Waiting for %s" % definition['kwargs']['wait'])
        while not is_closed:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            is_closed = sock.connect_ex((url.host, url.port))
            sock.close()
