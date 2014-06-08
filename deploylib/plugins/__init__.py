class DataMissing(Exception):
    def __init__(self, service_name, tag):
        self.service_name = service_name
        self.tag = tag


class Plugin(object):
    """Plugin that runs on the server.

    Currently, the following methods are supported:

    on_globals_changed()
        Global data of a deployment has changed.

    setup()
        Plugins can replace the default "service as a docker container"
        setup, and indicate this by returning ``True``. I can see this
        as being useful for cool things like running on other platforms
        like Heroku.

        Also very useful for holding services back that are still waiting
        for dependencies.

    post_setup()

    rewrite_service()
        Plugins have a chance to rewrite the service definition. Used
        for example to enable apps via the slugrunner image.

    provide_environment()
        When the docker container is created, and the environment variables
        are being put together, this gives a plugin the chance to add some
        of it's own variables.

        # TODO: Can rewrite_service do this?

    before_start()
        Called just before an instance is created. Plugins can modify the
        runcfg.
    """

    def __init__(self, host):
        self.host = host


class LocalPlugin(object):
    """Plugin that runs on the client."""
