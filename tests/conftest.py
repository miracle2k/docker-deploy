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

    # Test version of discovery client
    controller.discover = lambda s: s

    # By default we mock the whole backend. However, the test module
    # can disable this.
    if getattr(request.module, "mock_backend", True):
        controller.backend = mock.Mock()
        controller.backend.prepare.return_value = 'abc'
        controller.backend.start.return_value = 'abc'
        mock_backend_docker(controller)

    def close():
        controller.close()
    request.addfinalizer(close)

    return controller


class TestContext(Context):
    def __init__(self, *a, **kw):
        Context.__init__(self, *a, **kw)
        self.items = []
    def custom(self, **kwargs):
        self.items.append(kwargs)
        print(kwargs)
    def filter(self, key, value=None):
        items = [i for i in self.items if key in i]
        if value:
            items = [i for i in items if i[key] == value]
        return items


@pytest.fixture
def cintf(request, controller, tmpdir):
    """Provide an instance of :class:`DockerHost` for use in testing.
    """
    os.environ['HOST_IP'] = '127.0.0.1'

    cintf = controller.interface()
    # Every cintf needs a context to operate
    set_context(TestContext(cintf))

    # Remove the upstart plugin - in the future we should enable plugins
    # for tests on an as-need basis.
    os.environ['UPSTART_DIR'] = tmpdir.join('upstart').mkdir().strpath

    # Host always has the system deployment
    cintf.create_deployment('system', fail=False)

    def close():
        transaction.commit()
        cintf.close()
        set_context(None)
    request.addfinalizer(close)
    return cintf


@pytest.fixture()
def mock_backend_docker(controller):
    """Most backends have a .client attribute that is the Docker client.

    This will mock out the calls to Docker. It can be used as an alternative
    to mocking the whole backend.
    """
    controller.backend.client = mock.Mock()
    controller.backend.client.create_container.return_value = {'Id': 'abc'}
    controller.backend.client.inspect_image.return_value = {}
    controller.backend.client.build.return_value = ('built-id', 'build-output')


@pytest.fixture()
def responses(request):
    """Mock the requests library using responses.

    Return a RequestsMock instance rather than using the global default.
    """
    mock = responses_lib.RequestsMock()
    mock.start()
    request.addfinalizer(mock.stop)
    return mock
