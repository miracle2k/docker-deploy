from deploylib.plugins.sdutil import SdutilPlugin


controller_plugins = [SdutilPlugin]


class TestSdutilPlugin(object):

    def test_register(self, cintf):
        """Test sdutil registering.
        """
        cintf.create_deployment('foo')

        # Create a service with a default port, register it.
        service = cintf.set_service('foo', 'bar', {
            'image': 'bar',
            'entrypoint': '/entry',
            'cmd': 'a-command',
            'sdutil': {
                'register': True
            }
        })

        first_call = cintf.backend.start.mock_calls[0]
        args = first_call[1]
        runcfg_used = args[1]
        assert runcfg_used['entrypoint'] == '/sdutil'
        assert runcfg_used['cmd'][:2] == ['exec', '-s']
        assert runcfg_used['cmd'][2].startswith('foo:bar:')
        assert runcfg_used['cmd'][3:5] == ['/entry', 'a-command']

    def test_expose(self, cintf):
        """Test sdutil service exposure.
        """

        cintf.create_deployment('foo')

        # Create a service with a default port, define a dependency
        service = cintf.set_service('foo', 'bar', {
            'image': 'bar',
            'entrypoint': '/entry',
            'cmd': 'a-command',
            'sdutil': {
                'expose': {
                    'dep': 'DEP'
                }
            }
        })

        first_call = cintf.backend.start.mock_calls[0]
        args = first_call[1]
        runcfg_used = args[1]

        assert runcfg_used['entrypoint'] == '/sdutil'
        assert runcfg_used['cmd'] == [
            'expose', '-d', 'DEP:foo:dep', '/entry', 'a-command']
