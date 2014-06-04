import BTrees.OOBTree
from persistent import Persistent
from persistent.list import PersistentList


class DeployDB(object):
    """Our database root object."""

    def __init__(self):
        self.deployments = BTrees.OOBTree.BTree()
        self.auth_key = None


class Deployment(Persistent):
    """A group of containers/services that make up one project."""

    def __init__(self):
        self.services = BTrees.OOBTree.BTree()
        self.data = BTrees.OOBTree.BTree()

        # The globals for this deployment. The thing is, when the
        # globals change we ostensibly should release new versions
        # of all services. I need to think about how all all of this
        # should work. Its important to note we have two different
        # types of globals: Things that do inherit down (like Env vars),
        # and global things like Domain setup which exist on their own.
        self.globals = {}

    def set_service(self, name):
        """Store a new service, or add a new version to an existing
        service.
        """
        if not name in self.services:
            self.services[name] = DeployedService()


class DeployedService(Persistent):
    """One service that is defined as part of a deployment."""

    def __init__(self):
        self.versions = PersistentList()
        self.instances = PersistentList()

    @property
    def latest(self):
        if not self.versions:
            return None
        return self.versions[-1]

    def append_version(self, definition):
        version = ServiceVersion(definition)
        self.versions.append(version)
        return version

    def append_instance(self, container_id):
        self.instances.append(ServiceInstance(container_id, self.latest))


class ServiceVersion(Persistent):
    """A new version is created whenever the service changes.
    """

    def __init__(self, definition):
        self.globals = {}
        self.definition = definition


class ServiceInstance(Persistent):
    """An running instance of a container."""

    def __init__(self, container_id, version):
        self.container_id = container_id
        self.version = version
