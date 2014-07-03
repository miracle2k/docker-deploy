from deploylib.plugins.exec_resource import ExecPlugin
from deploylib.plugins.setup_require import RequiresPlugin
from tests.conftest import get_last_runcfg


controller_plugins = [ExecPlugin, RequiresPlugin]


class TestExec(object):

    def test_exec_service(self, cintf):
        deployment = cintf.create_deployment('foo')

        # The run resource waits for now, the "db" service is not available
        cintf.set_globals('foo', {'Exec': {
            'Foo': {
                'service': 'db',
                'cmd': 'create name user pass'
            }}})
        assert not get_last_runcfg(cintf, 'once')

        # Provide the service: make sure it has an provided requirement
        cintf.set_service('foo', 'db', {'require': 'dep'})

        # The Foo resource has now run; it does not care that the service
        # is held; it only uses the specified service as a template.
        assert deployment.get_resource('Foo')
        runcfg = get_last_runcfg(cintf, 'once')
        assert runcfg['cmd'] == ['create name user pass']
        assert runcfg['env']

    def test_required_exec_resource(self, cintf):
        """A Exec resource that requires others first.
        """

        deployment = cintf.create_deployment('foo')

        # The run resource waits for now, the "db" service is not available
        cintf.set_globals('foo', {'Exec': {
            'Foo': {
                'require': 'db',
                'service': 'forum',
                'cmd': 'initdb'
            }}})
        assert not get_last_runcfg(cintf, 'once')

        # Provide the service serving as template; this is not enough
        # to run the exec resource.
        cintf.set_service('foo', 'forum', {})
        assert not get_last_runcfg(cintf, 'once')

        # Now, provide the service specified in the requirements.
        cintf.set_service('foo', 'db', {})

        # The Foo resource has now run; it does not care that the service
        # is held; it only uses the specified service as a template.
        assert deployment.get_resource('Foo')
        assert get_last_runcfg(cintf, 'once')
