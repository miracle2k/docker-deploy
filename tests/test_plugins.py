from deploylib.daemon.context import ctx
from deploylib.plugins.vulcand import each_service, SmartPlugin, only_if

ctx


def test(cintf, controller):
    class MyPlugin(SmartPlugin):
        foo_calls = []
        bar_calls = []
        globals_calls = []

        @each_service()
        def foo(self, service):
            self.foo_calls.append((service,))

        @only_if('test.bar')
        @each_service()
        def foo_bar(self, service):
            self.bar_calls.append((service,))

        @each_service(globals='AKey')
        def globals(self, service):
            self.globals_calls.append((service,))

    my_plugin = MyPlugin()
    controller.plugins.append(my_plugin)

    cintf.create_deployment('test')

    # After adding a service, "bar" is not called due to lack of dep
    service = cintf.set_service('test', 'foo', {'git': '.'})
    assert my_plugin.foo_calls == [(service,)]
    assert my_plugin.bar_calls == []

    # After adding the dependency
    service = cintf.set_service('test', 'bar', {})
    assert len(my_plugin.foo_calls) == 2
    assert len(my_plugin.bar_calls) == 1

    # Test service having a global dependency, too
    del my_plugin.globals_calls[:]
    cintf.set_globals('test', {'WrongKey': 42})
    assert len(my_plugin.globals_calls) == 0
    cintf.set_globals('test', {'AKey': 42})
    assert len(my_plugin.globals_calls) == 2  # once for each service


