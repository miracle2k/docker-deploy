from deploylib.plugins.generate import GeneratePlugin
from tests.conftest import get_last_runcfg


controller_plugins = [GeneratePlugin]


class TestGenerate(object):

    def test_generate(self, cintf):
        cintf.create_deployment('foo')
        cintf.set_globals('foo', {'Generate': {'Foo': {}}})

        service = cintf.set_service('foo', 'bar', {
            'image': 'bar',
            'env': {'a': "{Foo}"}
        })

        runcfg_used = get_last_runcfg(cintf)
        assert len(runcfg_used['env']['a']) == 64
        prev_key = runcfg_used['env']['a']

        # Run again, get the same result
        service = cintf.set_service('foo', 'bar', {
            'image': 'bar',
            'env': {'a': "{Foo}"}
        })
        runcfg_used = get_last_runcfg(cintf)
        assert runcfg_used['env']['a'] == prev_key
