"""Service-Discovery based on flynn/discoverd and etcd.

While this is in a plugin now, the use of this plugin is still hardcoded
in various places, and more work is needed.

This is designed such that an instance of etcd and discoverd runs on every
host, and containers are given the ETCD and DISCOVERD ports of the local
host, which are currently hardcoded to 4001 and 1111.
"""

from deploylib.plugins import Plugin


class DiscoverdEtcdPlugin(Plugin):
    pass
