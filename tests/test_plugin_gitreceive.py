from StringIO import StringIO
from subprocess import check_output
import transaction
from deploylib.client.cli import run_plugins
from deploylib.client.service import ServiceFile, Service
from deploylib.daemon.api import create_app
from deploylib.daemon.context import ctx
from deploylib.plugins.app import AppPlugin
from deploylib.plugins.gitreceive import GitReceivePlugin, GitReceiveConfig, \
    parse_public_key
from deploylib.plugins.shelf import ShelfPlugin


from .test_plugin_app import patch_build


controller_plugins = [AppPlugin, GitReceivePlugin, ShelfPlugin]


class TestGitReceive(object):

    def test_setup_new_app(self, cintf):
        """Apps are still initially held, but with this plugin rather
        than requesting an upload, we are given a git remote url."""

        cintf.create_deployment('foo')
        service = cintf.set_service('foo', 'bar', {
            'git': '.'
        })

        assert service.held
        assert ctx.filter('url') == [
            {'url': 'git@deployhost:foo/bar', 'gitreceive': 'bar'}]

    def test_key_check(self, controller):
        """Test validating an SSH public key.
        """
        app = create_app(controller)

        with app.test_client() as c:
            rep = c.get(
                '/gitreceive/check-key',
                query_string={'key': 'a b c'})
            assert rep.get_data() == 'unauthorized'

        with controller.interface() as cintf:
            config = GitReceiveConfig.load(cintf.db)
            config.auth_keys.add(parse_public_key('a b foo'))

        with app.test_client() as c:
            rep = c.get(
                '/gitreceive/check-key',
                query_string={'key': 'a b foo'})
            assert rep.get_data() == 'ok'

    def test_check_repo(self, cintf, controller):
        """Test validating a repo name.
        """
        cintf.create_deployment('foo')
        service = cintf.set_service('foo', 'bar', {
            'git': '.'
        })

        app = create_app(controller)

        with app.test_client() as c:
            rep = c.get('/gitreceive/check-repo', query_string={'name': 'foo'})
            assert rep.get_data() == 'unauthorized'

            rep = c.get('/gitreceive/check-repo', query_string={'name': 'foo/nope'})
            assert rep.get_data() == 'unauthorized'

            rep = c.get('/gitreceive/check-repo', query_string={'name': 'foo/bar'})
            assert rep.get_data() == 'ok'

    def test_push(self, cintf, controller):
        """Test pushing new versions.
        """
        cintf.create_deployment('foo')
        service = cintf.set_service('foo', 'bar', {
            'git': '.'
        })
        transaction.commit()

        app = create_app(controller)
        with app.test_client() as c:
            rep = c.post('/gitreceive/push-data',
                        query_string={'name': 'foo/bar', 'version': '123'},
                        data={'tarball': (StringIO(''), '')})
            assert 'building slug for bar, version 123' in rep.get_data()

    def test_add_remote(self, tmpdir, cintf):
        with tmpdir.mkdir('repo').as_cwd():
            check_output('git init', shell=True)

        service = Service({'git': tmpdir.join('repo').strpath})
        service.filename = tmpdir.strpath
        servicefile = ServiceFile()
        servicefile.filename = tmpdir.strpath
        servicefile.globals = {}
        servicefile.services = {'bar': service}

        run_plugins('on_server_event', servicefile, 'nomatter',
            {'url': 'git@deployhost:foo/bar', 'gitreceive': 'bar'})

        with tmpdir.join('repo').as_cwd():
            output = check_output('git remote -v', shell=True)
            assert 'git@deployhost:foo/bar' in output

