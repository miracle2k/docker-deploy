class TestRequires(object):

    def test(self, host):
        deployment = host.create_deployment('foo')

        service1 = host.set_service('foo', 's1', {'require': 's2'})
        assert service1.held

        service2 = host.set_service('foo', 's2', {'require': 's3'})
        assert service2.held

        service3 = host.set_service('foo', 's3', {})

        # All three are now setup
        assert not service3.held
        assert not service2.held
        assert not service1.held
