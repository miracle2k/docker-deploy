from deploylib.daemon.context import ctx
from deploylib.plugins import Plugin


def iterablify(obj):
    if obj is None:
        return obj
    if isinstance(obj, (list, tuple)):
        return obj
    return (obj,)


class RequiresPlugin(Plugin):
    """Supports a ``requires`` service key that will hold a service until
    the required service have been setup first.

    See the documentation on holding services, but the key information to
    note is that *this is not a replacement for service discovery*. This
    will only function for the initial setup of a service and its
    dependencies, and can be used i.e. to execute a "create database".
    Once services have been added to a deployment for the first time, they
    will subsequently start in arbitrary order.

    NOTE: This plugin should be one of the last ones, so that other plugins
    can use their own ``post_setup()``methods to post-process the containers
    before this plugin releases holds on their dependent services.
    """

    priority = 20

    def setup(self, service, version):
        definition = version.definition
        requirements = iterablify(definition['kwargs'].get('require'))
        if not requirements:
            return

        deployment = service.deployment

        # Make sure all requirements are available
        missing_deps = []
        for dep in requirements:
            if dep in deployment.resources:
                continue
            if dep in deployment.services:
                if not deployment.services[dep].held:
                    continue

            missing_deps.append(dep)

        if missing_deps:
            # No they are not, hold this service for now
            service.hold(
                'waiting for requirement(s): %s' % ', '.join(missing_deps),
                version)
            return True

        # Yes they are, go ahead
        return

    def post_setup(self, service, _):
        if not service.held:
            self.trigger_dependency(service.deployment, service.name)

    def on_resource_changed(self, deployment, name, data):
        self.trigger_dependency(deployment, name)

    def trigger_dependency(self, deployment, depname):
        """Search for any service that has been held due to lack of the
        given requirement.
        """
        for existing_service in deployment.services.values():
            if not existing_service.held:
                continue

            # See if the service has a require key (it may be held for
            # other reasons).
            version = existing_service.held_version
            reqs = iterablify(version.definition['kwargs'].get('require'))
            if not reqs:
                continue

            if depname in reqs:
                # Attempt to setup this service now (which will recursively
                # trigger this plugin again if there are complex deps).
                print('Dependency for held service %s now available' %
                      existing_service.name)
                ctx.cintf.setup_version(existing_service, version)
