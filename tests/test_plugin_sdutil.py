import pytest
from deploylib.plugins.sdutil import SdutilPlugin
from tests.conftest import get_last_runcfg


controller_plugins = [SdutilPlugin]


@pytest.fixture(autouse=True)
def default_image_inspect(cintf):
    # sdutil will try to get entrypoint/cmd from image
    cintf.backend.client.inspect_image.return_value = {
        'config': {'Entrypoint': ['/imgentry'], 'Cmd': ['imgcmd']}
    }


class TestSdutilPlugin(object):

    def test_register(self, cintf):
        """Test sdutil registering.
        """
        cintf.create_deployment('foo')

        # Create a service with a default port, register it.
        service = cintf.set_service('foo', 'bar', {
            'image': 'bar',
            'entrypoint': ['/entry'],
            'sdutil': {
                'register': True,
                'binary': '/my-sdutil'
            }
        })

        runcfg_used = get_last_runcfg(cintf)
        assert runcfg_used['entrypoint'] == ['/my-sdutil']
        assert runcfg_used['cmd'][:2] == ['exec', '-s']
        assert runcfg_used['cmd'][2].startswith('foo:bar:')
        assert runcfg_used['cmd'][3:5] == ['/entry', 'imgcmd']

    def test_expose(self, cintf):
        """Test sdutil service exposure.
        """
        cintf.create_deployment('foo')

        # Create a service with a default port, define a dependency
        service = cintf.set_service('foo', 'bar', {
            'image': 'bar',
            'entrypoint': ['/entry'],
            'cmd': ['a-command'],
            'sdutil': {
                'binary': '/my-sdutil',
                'expose': {
                    'dep': 'DEP'
                }
            }
        })

        runcfg_used = get_last_runcfg(cintf)
        assert runcfg_used['entrypoint'] == ['/my-sdutil']
        assert runcfg_used['cmd'] == [
            'expose', '-d', 'DEP:foo:dep', '/entry', 'a-command']

    def test_image_rebuild(self, cintf):
        """Test insertion of sdutil.
        """
        cintf.create_deployment('foo')

        # Create a service with a default port, define a dependency
        service = cintf.set_service('foo', 'bar', {
            'image': 'bar',
            'entrypoint': ['/entry'],
            'cmd': ['a-command'],
            'sdutil': {
                'register': True

            }
        })

        runcfg_used = get_last_runcfg(cintf)
        assert runcfg_used['image'] == 'built-id'
        assert runcfg_used['entrypoint'] == ['/sdutil']
