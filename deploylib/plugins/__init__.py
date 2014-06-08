class DataMissing(Exception):
    def __init__(self, service_name, tag):
        self.service_name = service_name
        self.tag = tag


class Plugin(object):
    """Plugin that runs on the server.

    Currently, the following methods are supported:

    setup()
        Plugins can replace the default "service as a docker container"
        setup, and indicate this by returning ``True``.

        Used for example for 12-factor apps that are run via slugrunner.
        But you could even use this to run things on other hosters like
        Heroku.

        A plugin can use the ``self.host.create_container`` API, and *MUST*
        take care of setting up the proper new ``ServiceVersion`` instances.

    post_setup()

    provide_environment()
        When the docker container is created, and the environment variables
        are being put together, this gives a plugin the chance to add some
        of it's own variables.

    before_start()
        Called just before an instance is created. Plugins can modify the
        runcfg.
    """

    def __init__(self, host):
        self.host = host


class LocalPlugin(object):
    """Plugin that runs on the client."""
