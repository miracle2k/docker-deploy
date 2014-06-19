from io import BytesIO
import subprocess
import mock
import pytest
from werkzeug.datastructures import FileStorage
from deploylib.daemon.host import canonical_definition
from deploylib.plugins.app import AppPlugin


controller_plugins = [AppPlugin]


@pytest.fixture(autouse=True)
def install_shelf(host):
    # Pretend shelf is installed, so the plugin won't attempt to
    # during tests, which makes counting mocked calls more confusing.
    host.db.deployments['system'].services['shelf'] = True


@pytest.fixture(autouse=True)
def patch_build(request):
    # Mock subprocess calls used by container build
    fake_popen = mock.NonCallableMagicMock()
    fake_popen.stdout = BytesIO("foo")
    fake_popen.returncode = 0
    subprocess_patcher = mock.patch(
        "subprocess.Popen", side_effect=[fake_popen])
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
        assert service.held_version.definition['kwargs']['foo'] == 'bar'

    def test_first_data_upload(self, host):
        """App code for a held service is provided via upload.
        """
        deployment = host.create_deployment('foo')
        host.set_globals('foo', {'a': 1})
        service = deployment.set_service('bar')
        service.hold('bla', service.derive(canonical_definition('bar', {'git': '.'})[1]))

        host.provide_data(
            'foo', 'bar',  {'app': FileStorage()}, {'app': {'version': 42}})

        # docker build was called
        assert len(subprocess.Popen.mock_calls) == 1
        assert 'http://shelf' in subprocess.Popen.mock_calls[0][1][0]
        # Service no longer held
        assert not service.held
        assert not service.held_version   # was cleared
        # A new version was created in the db
        assert len(service.versions) == 1
        assert service.versions[0].definition == canonical_definition('bar', {'git': '.'})[1]
        assert service.versions[0].globals == {'a': 1}
        assert service.versions[0].data['app_version_id'] == 42
        # Also created via the backend.
        assert len(host.backend.start.mock_calls) == 1

    def test_subsequent_data_upload(self, host):
        """Uploading a new piece of data creates new version.
        """
        deployment = host.create_deployment('foo')
        host.set_globals('foo', {'a': 1})
        service = deployment.set_service('bar')
        version = service.append_version(
            service.derive(canonical_definition('bar', {'git': '.'})[1]))
        version.data['app_version_id'] = 3

        host.provide_data(
            'foo', 'bar',  {'app': FileStorage()}, {'app': {'version': 99}})

        # Another slug was built
        assert len(subprocess.Popen.mock_calls) == 1
        assert 'http://shelf' in subprocess.Popen.mock_calls[0][1][0]
        # And deployed as a new version
        assert len(service.versions) == 2
        assert service.versions[0].definition ==service.versions[1].definition
        assert service.versions[0].globals ==service.versions[1].globals
        assert service.versions[1].data['app_version_id'] == 99

    def test_new_version_via_config_change(self, host):
        """Changing the service definition creates a new version
        """
        deployment = host.create_deployment('foo')
        host.set_globals('foo', {'a': 1})
        service = deployment.set_service('bar')
        version = service.append_version(
            service.derive(canonical_definition('bar', {'git': '.'})[1]))
        version.data['app_version_id'] = 3

        service = host.set_service('foo', 'bar', {'git': '.', 'foo': 1})

        # No slug was built
        assert len(subprocess.Popen.mock_calls) == 0
        # But the new one was deployed as a new version
        assert len(service.versions) == 2
        assert service.versions[1].definition == \
               canonical_definition('bar', {'git': '.', 'foo': 1})[1]
        assert service.versions[1].globals ==service.versions[0].globals
        assert service.versions[1].data['app_version_id'] == service.versions[0].data['app_version_id']

