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

    def __init__(self, id):
        self.id = id
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
            self.services[name] = DeployedService(self, name)
        return self.services[name]


class DeployedService(Persistent):
    """One service that is defined as part of a deployment."""

    def __init__(self, deployment, name):
        self.name = name
        self.deployment = deployment
        self.versions = PersistentList()
        self.instances = PersistentList()

        self.held = False
        self.hold_message = None

    @property
    def latest(self):
        if not self.versions:
            return None
        return self.versions[-1]

    def hold(self, reason, definition):
        """Held services are registered with the deployment and will be
        started once missing parts become available.

        Our philosophy is that services are only interconnected via service
        discovery; therefore, order does not matter. Ideally, the "database
        service" will not register itself before the necessary databases have
        been created. In real life, often the service discovery registration
        happens inside the container, and database creation is down from the
        outside.

        To ease those cases, hold mechanism is a workaround by which the
        database consumer could be held until the database has been setup.

        It is also used for services that simply rely on additional data
        before they can run, for example the code of the application that
        would need to be uploaded first.
        """
        if self.versions:
            raise ValueError("Cannot hold a service that has versions")
        self.held = True
        self.hold_message = reason
        # Remember the service definition so we can later create a version
        self.definition = definition

    def _remove_hold(self):
        self.definition = None
        self.hold_message = False
        self.held = False

    def append_version(self, definition):
        if self.held:
            self._remove_hold()

        version = ServiceVersion(definition, self.deployment.globals.copy())
        self.versions.append(version)
        return version

    def append_instance(self, container_id):
        self.instances.append(ServiceInstance(container_id, self.latest))


class ServiceVersion(Persistent):
    """A new version is created whenever the service changes.
    """

    def __init__(self, definition, globals):
        self.definition = definition
        self.globals = globals


class ServiceInstance(Persistent):
    """An running instance of a container."""

    def __init__(self, container_id, version):
        self.container_id = container_id
        self.version = version
