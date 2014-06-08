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

    def setup(self, service, version):
        definition = version.definition
        requirements = iterablify(definition['kwargs'].get('require'))
        if not requirements:
            return

        deployment = service.deployment

        # Make sure all requirements are available
        for dep in requirements:
            if not dep in deployment.services:
                break
            if deployment.services[dep].held:
                break
        else:
            # Yes they are, go ahead
            return

        # No they are not, hold this service for now
        service.hold('waiting for requirement: %s' % dep, version)
        return True

    def post_setup(self, service, _):
        """Search for any service that has been held due to lack of
        this service that has just been set up.
        """
        for existing_service in service.deployment.services.values():
            if not existing_service.held:
                continue
            version = existing_service.held_version
            if service.name in iterablify(version.definition['kwargs']['require']):
                # Attempt to setup this service now (which will recursively
                # trigger this plugin again if there are complex deps).
                print('Dependency for held service %s now available' % existing_service.name)
                self.host.setup_version(existing_service, version)
