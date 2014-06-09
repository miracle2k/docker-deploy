from functools import wraps


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


def load_plugins(klass, *args, **kwargs):
    """Search all plugin modules for subclasses of ``klass``,
    instantiate using ``args`` and ``kwargs``, return as list.

    TODO: consider stevedore.
    """
    import os
    from os import path
    import warnings
    import inspect
    from importlib import import_module

    result = []
    current_dir = path.dirname(__file__)
    for name in os.listdir(current_dir):
        if not name.endswith('.py'):
            continue
        name = path.splitext(name)[0]
        module_name = 'deploylib.plugins.%s' % name
        try:
            module = import_module(module_name)
        except Exception as e:
            warnings.warn('Error while loading builtin plugin module '
                          '\'%s\': %s' % (module_name, e))
        else:
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if inspect.isclass(attr) and issubclass(attr, klass) and not \
                        attr is klass:
                    result.append(attr(*args, **kwargs))

                if isinstance(attr, klass):
                    result.append(attr)

    return result

