"""Extends the app-plugin to allow deploying new versions via git-push.

This will automatically run a "gitreceive" ssh server as part of the
"system" deployment.

To make "git push" work it needs some minimal configuration: The git
urls used need to be routed to the actual service. There are two options:


Proxy + Service discovery
-------------------------

The gitreceive service will register with service discovery under the
name ``gitreceive``, and you could set up a TCP proxy to it:

    Domains:
        githost:
            # Register this domain/backend route with strowger
            tcp: 22, gitreceive


You need to set the gitreceive "hostname" option to "githost".


WAN mapping
------------

You can have the gitreceive service to declare a WAN port directly
using the "wan_port" option (e.g. ``secondip:22``).

You need to set the gitreceive "hostname" option to point to something
sensible as well.

"""

import subprocess
from BTrees._OOBTree import OOTreeSet
import click
from clint.textui import puts
from flask import Blueprint, g, request
from Crypto.PublicKey import RSA
from persistent import Persistent
import yaml
from deploylib.daemon.api import json_method, streaming, TextStreamingResponse
from deploylib.daemon.context import ctx
from deploylib.plugins import Plugin, LocalPlugin
from deploylib.plugins.app import LocalAppPlugin


class GitReceiveConfig(Persistent):
    @classmethod
    def load(cls, db):
        if not hasattr(db, 'gitreceive'):
            db.gitreceive = GitReceiveConfig()
        return db.gitreceive

    def __init__(self):
        self.auth_keys = OOTreeSet()
        self.hostname = ''
        self.wan_port = ''
        self.host_key = ''


GITRECEIVE = """
image: elsdoerfer/gitreceive
volumes:
    cache: /srv/repos
env:
    SSH_PRIVATE_KEYS: ""
    CONTROLLER_AUTH_KEY: {authkey}
"""


def generate_ssh_private_key():
    """I would have preferred to use cryptography.io, but it doesn't
    support a key export feature yet.
    """
    return RSA.generate(2048).exportKey()


class GitReceivePlugin(Plugin):

    def needs_app_code(self, service, version):
        """Replaces the app-plugin default handling; rather than requiring
        the client to upload, we have it setup an endpoint.
        """
        if not 'git' in version.definition['kwargs']:
            return False

        # If the gitreceive service has not yet been setup, do so now
        if not 'gitreceive' in ctx.cintf.db.deployments['system'].services:
            self.setup_gitreceive()

        ctx.custom(**{'gitreceive': service.name, 'url': self.get_url(service)})
        return True

    def setup_gitreceive(self):
        """Setup the gitreceive SSH daemon.
        """
        config = GitReceiveConfig.load(ctx.cintf.db)
        gitreceive_def = yaml.load(GITRECEIVE.format(
            authkey=ctx.cintf.db.auth_key,
            hostkey=''
        ))
        if not getattr(config, 'host_key', False):
            config.host_key = generate_ssh_private_key()
        gitreceive_def['env']['SSH_PRIVATE_KEYS'] = config.host_key
        if getattr(config, 'wan_port'):
            gitreceive_def['wan_map'] = {config.wan_port: ''}
        ctx.cintf.set_service(
            'system', 'gitreceive', gitreceive_def, force=True)

    def get_url(self, service):
        """Generate a url for this service to our gitreceive daemon.
        """
        config = GitReceiveConfig.load(ctx.cintf.db)
        hostname = config.hostname
        if not hostname:
            # TODO: If WAN bound, use this address automatically.
            hostname = ctx.cintf.discover('system:gitreceive')

        if ':' in hostname:
            # If the hostname has a port, the remote will only work in
            # git if we use the ssh:// schema.
            fmt = 'ssh://git@{hostname}/{deploy_id}/{service}'
        else:
            fmt = 'git@{hostname}:{deploy_id}/{service}'
        return fmt.format(
            hostname=hostname,
            deploy_id=service.deployment.id, service=service.name)


################################################################################


gitreceive_api = Blueprint('gitreceive', __name__)


def parse_public_key(keydata):
    parts = keydata.split(' ')
    if not len(parts) in (2, 3):
        raise ValueError('Not a valid SSH public key')
    # Parts should be (type, key, name)
    if len(parts) == 2:
        parts.append('')
    return parts


@gitreceive_api.route('/push-data', methods=['POST'])
@streaming(TextStreamingResponse)
def api_pushdata(request, app):
    """Called by git received with a new tarball from git.
    """
    deployment, service = request.args['name'].split('/', 1)
    request.files['tarball']
    ctx.cintf.provide_data(
        deployment, service,
        {'app': request.files['tarball']},
        {'app': {'version': request.args['version']}})


@gitreceive_api.route('/check-key', methods=['GET'])
def api_checkkey():
    """Verify the given public key is authorized.
    """
    config = GitReceiveConfig.load(g.cintf.db)
    key = parse_public_key(request.args['key'])
    if not key[:2] in [k[:2] for k in config.auth_keys]:
        return 'unauthorized'
    return 'ok'


@gitreceive_api.route('/check-repo', methods=['GET'])
def api_checkrepo():
    """Verify the given repo exists.
    """
    try:
        deployment, service = request.args['name'].split('/', 1)
    except ValueError:
        return 'unauthorized'
    if not deployment in g.cintf.db.deployments:
        return 'unauthorized'
    if not service in g.cintf.db.deployments[deployment].services:
        return 'unauthorized'
    return 'ok'


@gitreceive_api.route('/setup', methods=['POST'])
@streaming()
def api_setup(request, app):
    """Setup git receive.
    """
    ctx.cintf.controller.get_plugin(GitReceivePlugin).setup_gitreceive()


@gitreceive_api.route('/add-key', methods=['GET'])
@json_method
def api_addkey(keydata):
    """Register a new key for gitreceive.
    """
    config = GitReceiveConfig.load(g.cintf.db)
    config.auth_keys.add(parse_public_key(keydata))
    return {'job': 'Authorized key for gitreceive use'}


@gitreceive_api.route('/set-config', methods=['GET'])
@json_method
def api_setconfig(hostname=None, wan_port=None):
    """Change gitreceive configuration
    """
    config = GitReceiveConfig.load(g.cintf.db)
    if hostname is not None:
        config.hostname = hostname
    if wan_port is not None:
        config.wan_port = wan_port
    return {'job': 'Updated configuration, manual restart required'}


################################################################################


@click.group('gitreceive')
def gitreceive_cli():
    """Manage gitreceive."""
    pass


@gitreceive_cli.command('add-key')
@click.argument('keyfile', type=click.File())
@click.pass_obj
def gitreceive_addkey(app, keyfile):
    """Register a public key for gitreceive.
    """
    app.plugin_call('get', 'gitreceive', 'add-key', {'keydata': keyfile.read()})


@gitreceive_cli.command('config-set')
@click.option('--hostname', help="this host is used when adding the git url"
                                 "to a repository; your gitreceive service"
                                 "should be accessible here")
@click.option('--wan-port', help="if the gitreceive service should be mapped"
                                 "to a wan port")
@click.pass_obj
def gitreceive_config(app, hostname, wan_port):
    """Set gitreceive configuration.
    """
    app.plugin_call(
        'get', 'gitreceive', 'set-config',
        {'hostname': hostname, 'wan_port': wan_port})


@gitreceive_cli.command('setup')
@click.pass_obj
def gitreceive_setup(app):
    """Setup the gitreceive service.
    """
    app.plugin_call('post', 'gitreceive', 'setup', {})


class LocalGitReceivePlugin(LocalPlugin):

    def provide_cli(self, group):
        group.add_command(gitreceive_cli)

    def on_server_event(self, servicefile, deploy_id, event):
        if not 'gitreceive' in event:
            return

        service = event['gitreceive']
        self.setup_gitremote(servicefile.services[service], event['url'])
        return True

    def setup_gitremote(self, service, url):
        run = subprocess.check_output
        from deploylib.client.utils import directory

        project_path = self.app.get_plugin(LocalAppPlugin).find_project_repo(
            service, service['git'])
        with directory(project_path):
            remotes = run('git remote', shell=True).splitlines()
            if not 'deploy' in remotes:
                run('git remote add %s %s' % ('deploy', url), shell=True)
                puts('-----> Added remote "deploy" to %s' % project_path)
            else:
                puts('-----> Push %s to remote "deploy" to provide code.' % project_path)
