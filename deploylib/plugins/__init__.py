class Plugin(object):
    """Plugin that runs on the server.

    Currently, the following methods are supported:

    on_globals_changed()
        Global data of a deployment has changed.

    on_resource_changed
        A resource was declared as available for this deployment.

    setup()
        Plugins can replace the default "service as a docker container"
        setup, and indicate this by returning ``True``. I can see this
        as being useful for cool things like running on other platforms
        like Heroku.

        Also very useful for holding services back that are still waiting
        for dependencies.

    post_setup()

    setup_resource()
        Before a plugin wants to setup a resource it should call this,
        and delay setup if a truth value is returned.

    rewrite_service()
        Plugins have a chance to rewrite the service definition. Used
        for example to enable apps via the slugrunner image.

    provide_vars()
        Deployment-specific, non-environment variables can be provided
        here, and will replace format strings ala {var}.

    provide_environment()
        When the docker container is created, and the environment variables
        are being put together, this gives a plugin the chance to add some
        of it's own variables.

        # TODO: Can rewrite_service do this?

    before_start()
        Called just before an instance is created. Plugins can modify the
        runcfg.

    before_once()
        Like before_start(), but called when one-off jobs are created.
    """

    priority = 100


class LocalPlugin(object):
    """Plugin that runs on the client."""

    def __init__(self, app):
        self.app = app


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
                    if not 'abstract' in dir(klass) or not getattr(klass, 'abstract', True):
                        result.append(attr(*args, **kwargs))

                if isinstance(attr, klass):
                    result.append(attr)

    return result

