import mock
import os
import pytest
import responses as responses_lib
import transaction
from deploylib.daemon.context import set_context, Context
from deploylib.daemon.controller import Controller


@pytest.fixture
def controller(request, tmpdir):
    controller = Controller(
        volumes_dir=str(tmpdir.mkdir('volumes')),
        db_dir=str(tmpdir.join('db')),
        plugins=getattr(request.module, "controller_plugins", []))

    def close():
        controller.close()
    request.addfinalizer(close)

    return controller


@pytest.fixture
def cintf(request, controller, tmpdir):
    """Provide an instance of :class:`DockerHost` for use in testing.
    """
    os.environ['HOST_IP'] = '127.0.0.1'

    cintf = controller.interface()

    # Every cintf needs a context to operate
    class TestContext(Context):
        def custom(self, **kwargs):
            print(kwargs)
    set_context(TestContext(cintf))

    # By default we mock the whole backend. However, the test module
    # can disable this.
    if getattr(request.module, "mock_backend", True):
        cintf.backend = mock.Mock()
        cintf.backend.prepare.return_value = 'abc'
        cintf.backend.start.return_value = 'abc'

    # Test version of discovery client
    cintf.discover = lambda s: s

    # Remove the upstart plugin - in the future we should enable plugins
    # for tests on an as-need basis.
    os.environ['UPSTART_DIR'] = tmpdir.join('upstart').mkdir().strpath

    # Host always has the system deployment
    cintf.create_deployment('system', fail=False)

    def close():
        transaction.commit()
        cintf.close()
    request.addfinalizer(close)
    return cintf


@pytest.fixture()
def mock_backend_docker(cintf):
    """Most backends have a .client attribute that is the Docker client.

    This will mock out the calls to Docker. It can be used as an alternative
    to mocking the whole backend.
    """
    cintf.backend.client = mock.Mock()
    cintf.backend.client.create_container.return_value = {'Id': 'abc'}


@pytest.fixture()
def responses(request):
    """Mock the requests library using responses.

    Return a RequestsMock instance rather than using the global default.
    """
    mock = responses_lib.RequestsMock()
    mock.start()
    request.addfinalizer(mock.stop)
    return mock
