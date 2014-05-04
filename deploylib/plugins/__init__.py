class DataMissing(Exception):
    def __init__(self, service_name, tag):
        self.service_name = service_name
        self.tag = tag


class Plugin(object):
    """Plugin that runs on the server."""

    def __init__(self, host):
        self.host = host


class LocalPlugin(object):
    """Plugin that runs on the client."""
