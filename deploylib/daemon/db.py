from copy import deepcopy
import BTrees.OOBTree
from persistent import Persistent
from persistent.list import PersistentList



class DeployDB(object):
    """Old, not persistent root object; DEPRECATED: delete"""

    def __init__(self):
        self.deployments = BTrees.OOBTree.BTree()
        self.auth_key = None
        self.config = {}


class DeployDBNew(Persistent):
    """Our root."""

    def __init__(self):
        self.deployments = BTrees.OOBTree.BTree()
        self.auth_key = None
        self.config = {}


class Deployment(Persistent):
    """A group of containers/services that make up one project."""

    def __init__(self, id):
        self.id = id
        self.services = BTrees.OOBTree.BTree()
        self.data = BTrees.OOBTree.BTree()
        self.resources = BTrees.OOBTree.BTree()

        # The globals for this deployment. The thing is, when the
        # globals change we ostensibly should release new versions
        # of all services. I need to think about how all all of this
        # should work. Its important to note we have two different
        # types of globals: Things that do inherit down (like Env vars),
        # and global things like Domain setup which exist on their own.
        self.globals = {}

    def has_service(self, name, allow_hold=False):
        """True if a service with the name exists and is ready."""
        if not name in self.services:
            return False
        if not allow_hold and self.services[name].held:
            return False
        return True

    def set_service(self, name):
        """Store a new service, or add a new version to an existing
        service.
        """
        if not name in self.services:
            self.services[name] = DeployedService(self, name)
        return self.services[name]

    def set_resource(self, name, value=True):
        """Declare the given resource as available, store a value along
        side it.

        If the resource was available before, the stored value is changed.

        Resources are things like databases; services may depend on
        resources being available before they can be set up.
        """
        self.resources[name] = value

    def get_resource(self, name):
        """Return the value of the resource, or None if it does not exist.
        """
        return self.resources.get(name, None)


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
    def full_name(self):
        return '%s-%s' % (self.deployment.id, self.name)

    @property
    def latest(self):
        if not self.versions:
            return None
        return self.versions[-1]

    @property
    def version(self):
        if self.held:
            return self.held_version
        return self.latest

    def hold(self, reason, version):
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
        self.held_version = version

    def _remove_hold(self):
        self.held_version = None
        self.hold_message = False
        self.held = False

    def derive(self, definition=None):
        """Derive a new version from the latest one, or create the first.

        This version is not yet added to the service; to this later using
        :meth:``append_version`` after you have setup the version.
        """
        if definition is None:
            definition = self.latest.definition
        data = deepcopy(self.latest.data) if self.latest else {}

        return ServiceVersion(definition, self.deployment.globals, data=data)

    def append_version(self, version):
        if self.held:
            self._remove_hold()

        version.service = self
        self.versions.append(version)
        return version

    def append_instance(self, id, backend_id):
        instance = ServiceInstance(id, backend_id, self.latest)
        self.instances.append(instance)
        self.latest.instance_count += 1
        return instance


class ServiceVersion(Persistent):
    """A new version is created whenever the service changes.
    """

    def __init__(self, definition, globals, data=None):
        self.definition = definition
        self.globals = globals
        self.data = BTrees.OOBTree.BTree(data or {})
        self.instance_count = 0


class ServiceInstance(Persistent):
    """An running instance of a container."""

    def __init__(self, id, backend_id, version):
        self._id = id
        self.container_id = backend_id
        self.version = version

    @property
    def id(self):
        if hasattr(self, '_id'):
            return self._id
        return self.container_id
