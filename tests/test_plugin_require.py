from deploylib.plugins.setup_require import RequiresPlugin


controller_plugins = [RequiresPlugin]


class TestRequires(object):

    def test_with_services(self, cintf):
        deployment = cintf.create_deployment('foo')

        service1 = cintf.set_service('foo', 's1', {'require': 's2'})
        assert service1.held

        service2 = cintf.set_service('foo', 's2', {'require': 's3'})
        assert service2.held

        service3 = cintf.set_service('foo', 's3', {})

        # All three are now setup
        assert not service3.held
        assert not service2.held
        assert not service1.held

    def test_with_resources(self, cintf):
        deployment = cintf.create_deployment('foo')

        service1 = cintf.set_service('foo', 's1', {'require': 's2'})
        assert service1.held

        cintf.set_resource('foo', 's2', 5)
        assert not service1.held
