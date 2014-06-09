import os
import pytest
from deploylib.plugins.upstart import UpstartPlugin


mock_backend = False


@pytest.fixture
def upstart(tmpdir):
    upstart_dir = tmpdir.join('upstart').ensure(dir=True)
    os.environ['UPSTART_DIR'] = str(upstart_dir)
    return upstart_dir


@pytest.mark.usefixtures('mock_backend_docker')
class TestUpstart(object):

    def test_create_deployment_file(self, host, upstart):
        """An upstart file is created for each deployment."""
        host.create_deployment('foo')
        assert upstart.join('foo.conf').exists()

    def test_create_service_file(self, host, upstart):
        """An upstart file is created for each service."""
        host.create_deployment('foo')
        host.set_service('foo', 'bar', {})
        assert upstart.join('foo-bar-1-1.conf').exists()

    def test_system_init(self, host, upstart):
        # Call the event handler directly, easiest for testing
        host.get_plugin(UpstartPlugin).on_system_init()
        assert upstart.join('etcd.conf').exists()
        assert upstart.join('discoverd.conf').exists()
        assert upstart.join('shelf.conf').exists()
        assert upstart.join('strowger.conf').exists()
        assert upstart.join('docker-deploy.conf').exists()
