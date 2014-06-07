import mock
import pytest
import transaction
from deploylib.daemon.host import DockerHost


@pytest.fixture
def host(request, tmpdir):
    """Provide an instance of :class:`DockerHost` for use in testing.
    """
    host = DockerHost(
        volumes_dir=str(tmpdir.mkdir('volumes')),
        db_dir=str(tmpdir.join('db')))

    # Mock any backend calls
    host.backend = mock.Mock()
    # Test version of discovery client
    host.discover = lambda s: s

    def close():
        transaction.commit()
        host.close()
    request.addfinalizer(close)
    return host

