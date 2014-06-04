class DataMissing(Exception):
    def __init__(self, service_name, tag):
        self.service_name = service_name
        self.tag = tag


class Plugin(object):
    """Plugin that runs on the server."""

    def __init__(self, host):
        self.host = host

    def plugin_storage(self, deploy_id, plugin_name):
        d = self.host.db.deployments[deploy_id].data
        d = d.setdefault(plugin_name, {})
        return d


class LocalPlugin(object):
    """Plugin that runs on the client."""
