from io import BytesIO
import os
import mock
import pytest
from deploylib.plugins.upstart import UpstartPlugin


controller_plugins = [UpstartPlugin]
mock_backend = False


@pytest.fixture
def upstart(tmpdir):
    upstart_dir = tmpdir.join('upstart').ensure(dir=True)
    os.environ['UPSTART_DIR'] = str(upstart_dir)
    return upstart_dir


@pytest.fixture(autouse=True)
def patch_initctl(request):
    # Mock subprocess calls used by container build
    fake_popen = mock.NonCallableMagicMock()
    fake_popen.stdout = BytesIO("foo")
    fake_popen.returncode = 0
    fake_popen.poll.side_effect = lambda: 0
    subprocess_patcher = mock.patch(
        "gevent.subprocess.Popen", side_effect=lambda *a, **kw: fake_popen)
    subprocess_patcher.start()

    def end():
        subprocess_patcher.stop()
    request.addfinalizer(end)


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
