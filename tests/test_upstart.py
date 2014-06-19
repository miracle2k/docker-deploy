import os
import pytest
from deploylib.plugins.upstart import UpstartPlugin


controller_plugins = [UpstartPlugin]
mock_backend = False


@pytest.fixture
def upstart(tmpdir):
    upstart_dir = tmpdir.join('upstart').ensure(dir=True)
    os.environ['UPSTART_DIR'] = str(upstart_dir)
    return upstart_dir


@pytest.mark.usefixtures('mock_backend_docker')
class TestUpstart(object):

    def test_create_deployment_file(self, cintf, upstart):
        """An upstart file is created for each deployment."""
        cintf.create_deployment('foo')
        assert upstart.join('foo.conf').exists()

    def test_create_service_file(self, cintf, upstart):
        """An upstart file is created for each service, and deleted.
        """
        cintf.create_deployment('foo')
        cintf.set_service('foo', 'bar', {})
        assert upstart.join('foo-bar-1-1.conf').exists()

        cintf.set_service('foo', 'bar', {}, force=True)
        assert upstart.join('foo-bar-2-1.conf').exists()
        assert not upstart.join('foo-bar-1-1.conf').exists()
