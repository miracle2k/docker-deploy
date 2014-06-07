import os
import mock
import pytest
import subprocess
from werkzeug.datastructures import FileStorage
from deploylib.daemon.host import ServiceDef
from . import host


@pytest.fixture(autouse=True)
def envsetup(request):
    os.environ['HOST_IP'] = '127.0.0.1'

    def container_id(a, **kwargs): return 'container-id'
    subprocess_patcher = mock.patch(
        "subprocess.check_output", side_effect=container_id)
    subprocess_patcher.start()

    def end():
        subprocess_patcher.stop()
    request.addfinalizer(end)


class TestAppPlugin(object):

    def test_service_initial_in_hold(self, host):
        """Apps are initially set to hold while code is missing.
        """
        host.create_deployment('foo')
        service = host.set_service('foo', 'bar', {
            'git': '.'
        })

        assert service.held
        assert service.hold_message
        assert not service.versions
        assert not host.backend.create_container.called

        # Setting a new version while service is still on hold:
        # Nothing changes
        service = host.set_service('foo', 'bar', {
            'git': '.',
            'foo': 'bar'
        })
        assert service.held
        assert service.hold_message
        assert not service.versions
        assert not host.backend.create.called
        # New definition of the service has been cached
        assert service.definition['kwargs']['foo'] == 'bar'

    def test_first_data_upload(self, host):
        """App code for a held service is provided via upload.
        """
        deployment = host.create_deployment('foo')
        host.set_globals('foo', {'a': 1})
        service = deployment.set_service('bar')
        service.hold('bla', ServiceDef('bar', {}))

        host.provide_data(
            'foo', 'bar',  {'app': FileStorage()}, {'app': {'version': 42}})

        # docker build was called
        assert len(subprocess.check_output.mock_calls) == 1
        assert 'http://shelf' in subprocess.check_output.mock_calls[0][1][0]
        # Service no longer held
        assert not service.held
        assert not service.definition   # was cleared
        # A new version was created in the db
        assert len(service.versions) == 1
        assert service.versions[0].definition == ServiceDef('bar', {})
        assert service.versions[0].globals == {'a': 1}
        assert service.versions[0].app_version_id == 42
        # Also created via the backend.
        assert len(host.backend.create.mock_calls) == 1

    def test_subsequent_data_upload(self, host):
        """Uploading a new piece of data creates new version.
        """
        deployment = host.create_deployment('foo')
        host.set_globals('foo', {'a': 1})
        service = deployment.set_service('bar')
        version = service.append_version(ServiceDef('bar', {}))
        version.app_version_id = 3

        host.provide_data(
            'foo', 'bar',  {'app': FileStorage()}, {'app': {'version': 99}})

        # Another slug was built
        assert len(subprocess.check_output.mock_calls) == 1
        assert 'http://shelf' in subprocess.check_output.mock_calls[0][1][0]
        # And deployed as a new version
        assert len(service.versions) == 2
        assert service.versions[0].definition ==service.versions[1].definition
        assert service.versions[0].globals ==service.versions[1].globals
        assert service.versions[1].app_version_id == 99

    def test_new_version_via_config_change(self, host):
        """Changing the service definition creates a new version
        """
        deployment = host.create_deployment('foo')
        host.set_globals('foo', {'a': 1})
        service = deployment.set_service('bar')
        version = service.append_version(ServiceDef('bar', {}))
        version.app_version_id = 3

        service = host.set_service('foo', 'bar', {'git': '.'})

        # No slug was built
        assert len(subprocess.check_output.mock_calls) == 0
        # But the new one was deployed as a new version
        assert len(service.versions) == 2
        assert service.versions[1].definition == ServiceDef('bar', {'git': '.'})
        assert service.versions[1].globals ==service.versions[0].globals
        assert service.versions[1].app_version_id == service.versions[0].app_version_id

