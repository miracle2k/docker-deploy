from io import BytesIO
import subprocess
import mock
import pytest
from werkzeug.datastructures import FileStorage
from deploylib.daemon.controller import canonical_definition
from deploylib.plugins.app import AppPlugin
from deploylib.plugins.shelf import ShelfPlugin


controller_plugins = [AppPlugin, ShelfPlugin]


@pytest.fixture(autouse=True)
def install_shelf(cintf):
    # Pretend shelf is installed, so the plugin won't attempt to
    # during tests, which makes counting mocked calls more confusing.
    cintf.db.deployments['system'].services['shelf'] = True


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

    def test_service_initial_in_hold(self, cintf):
        """Apps are initially set to hold while code is missing.
        """
        cintf.create_deployment('foo')
        service = cintf.set_service('foo', 'bar', {
            'git': '.'
        })

        assert service.held
        assert service.hold_message
        assert not service.versions
        assert not cintf.backend.create_container.called

        # Setting a new version while service is still on hold:
        # Nothing changes
        service = cintf.set_service('foo', 'bar', {
            'git': '.',
            'foo': 'bar'
        })
        assert service.held
        assert service.hold_message
        assert not service.versions
        assert not cintf.backend.create.called
        # New definition of the service has been cached
        assert service.held_version.definition['kwargs']['foo'] == 'bar'

    def test_first_data_upload(self, cintf):
        """App code for a held service is provided via upload.
        """
        deployment = cintf.create_deployment('foo')
        cintf.set_globals('foo', {'a': 1})
        service = deployment.set_service('bar')
        service.hold('bla', service.derive(canonical_definition('bar', {'git': '.'})[1]))

        cintf.provide_data(
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
        assert len(cintf.backend.start.mock_calls) == 1

    def test_subsequent_data_upload(self, cintf):
        """Uploading a new piece of data creates new version.
        """
        deployment = cintf.create_deployment('foo')
        cintf.set_globals('foo', {'a': 1})
        service = deployment.set_service('bar')
        version = service.append_version(
            service.derive(canonical_definition('bar', {'git': '.'})[1]))
        version.data['app_version_id'] = 3

        cintf.provide_data(
            'foo', 'bar',  {'app': FileStorage()}, {'app': {'version': 99}})

        # Another slug was built
        assert len(subprocess.Popen.mock_calls) == 1
        assert 'http://shelf' in subprocess.Popen.mock_calls[0][1][0]
        # And deployed as a new version
        assert len(service.versions) == 2
        assert service.versions[0].definition ==service.versions[1].definition
        assert service.versions[0].globals ==service.versions[1].globals
        assert service.versions[1].data['app_version_id'] == 99

    def test_new_version_via_config_change(self, cintf):
        """Changing the service definition creates a new version
        """
        deployment = cintf.create_deployment('foo')
        cintf.set_globals('foo', {'a': 1})
        service = deployment.set_service('bar')
        version = service.append_version(
            service.derive(canonical_definition('bar', {'git': '.'})[1]))
        version.data['app_version_id'] = 3

        service = cintf.set_service('foo', 'bar', {'git': '.', 'foo': 1})

        # No slug was built
        assert len(subprocess.Popen.mock_calls) == 0
        # But the new one was deployed as a new version
        assert len(service.versions) == 2
        assert service.versions[1].definition == \
               canonical_definition('bar', {'git': '.', 'foo': 1})[1]
        assert service.versions[1].globals ==service.versions[0].globals
        assert service.versions[1].data['app_version_id'] == service.versions[0].data['app_version_id']

