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

    # Mock any backend calls
    host.backend = mock.Mock()
    host.backend.prepare.return_value = 'abc'
    host.backend.start.return_value = 'abc'
    # Test version of discovery client
    host.discover = lambda s: s

    def close():
        transaction.commit()
        host.close()
    request.addfinalizer(close)
    return host


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
    set_context(Context())

    def end(): pass
    request.addfinalizer(end)
