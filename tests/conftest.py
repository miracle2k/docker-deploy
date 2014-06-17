import mock
import os
import pytest
import responses as responses_lib
import transaction
from deploylib.daemon.context import set_context, Context
from deploylib.daemon.host import DockerHost


@pytest.fixture
def host(request, tmpdir):
    """Provide an instance of :class:`DockerHost` for use in testing.
    """
    os.environ['HOST_IP'] = '127.0.0.1'
    host = DockerHost(
        volumes_dir=str(tmpdir.mkdir('volumes')),
        db_dir=str(tmpdir.join('db')))

    # By default we mock the whole backend. However, the test module
    # can disable this.
    if getattr(request.module, "mock_backend", True):
        host.backend = mock.Mock()
        host.backend.prepare.return_value = 'abc'
        host.backend.start.return_value = 'abc'

    # Test version of discovery client
    host.discover = lambda s: s

    # Remove the upstart plugin - in the future we should enable plugins
    # for tests on an as-need basis.
    os.environ['UPSTART_DIR'] = tmpdir.join('upstart').mkdir().strpath

    # Host always has the system deployment
    host.create_deployment('system', fail=False)

    def close():
        transaction.commit()
        host.close()
    request.addfinalizer(close)
    return host


@pytest.fixture()
def mock_backend_docker(host):
    """Most backends have a .client attribute that is the Docker client.

    This will mock out the calls to Docker. It can be used as an alternative
    to mocking the whole backend.
    """
    host.backend.client = mock.Mock()
    host.backend.client.create_container.return_value = {'Id': 'abc'}


@pytest.fixture()
def responses(request):
    """Mock the requests library using responses.

    Return a RequestsMock instance rather than using the global default.
    """
    mock = responses_lib.RequestsMock()
    mock.start()
    request.addfinalizer(mock.stop)
    return mock


@pytest.fixture(autouse=True)
def envsetup(request):
    """Mock out various other things."""

    # Make sure there is always a context available
    class TestContext(Context):
        def custom(self, **kwargs):
            print(kwargs)
    set_context(TestContext())

    def end(): pass
    request.addfinalizer(end)
