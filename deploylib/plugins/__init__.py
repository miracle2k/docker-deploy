class DataMissing(Exception):
    def __init__(self, service_name, tag):
        self.service_name = service_name
        self.tag = tag


class Plugin(object):

    def __init__(self, host):
        self.host = host
