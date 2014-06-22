"""Extends the app-plugin to allow deploying new versions via git-push.

This will automatically run a "gitreceive" ssh server as part of the
"system" deployment.

Currently, you need to provide the host ip to map to as a configuration
value, to not conflict with the regular SSH service you are probably
also running on the host.

In the future, I imagine it might work something like this::

    Domains:
        githost:
            # Register this domain/backend route with strowger
            tcp: 22, backend
            # But only for strowger instances serving the second realm
            realm: second

Have a "realm" plugin that will automatically setup a strowger instances
for each realm, each running on separate ips, chosen from an IP pool,
spread among multiple hosts.
"""

import subprocess
from BTrees._OOBTree import OOTreeSet
import click
from flask import Blueprint, g, request
from persistent import Persistent
import yaml
from deploylib.daemon.api import json_method, streaming, TextStreamingResponse
from deploylib.daemon.context import ctx
from deploylib.plugins import Plugin, LocalPlugin


class GitReceiveConfig(Persistent):
    @classmethod
    def load(cls, db):
        if not hasattr(db, 'gitreceive'):
            db.gitreceive = GitReceiveConfig()
        return db.gitreceive

    def __init__(self):
        self.auth_keys = OOTreeSet()
        self.hostname = 'deployhost'
        self.host_ip = ''


GITRECEIVE = """
image: elsdoerfer/gitreceive
volumes:
    cache: /srv/repos
host_ports:
    '': "{hostip}:25"
env:
    SSH_PRIVATE_KEYS: ""
    CONTROLLER_AUTH_KEY: {authkey}
"""


class GitReceivePlugin(Plugin):

    def needs_app_code(self, service, version):
        """Replaces the app-plugin default handling; rather than requiring
        the client to upload, we have it setup an endpoint.
        """
        if not 'git' in version.definition['kwargs']:
            return False

        config = GitReceiveConfig.load(ctx.cintf.db)

        # If the gitreceive service has not yet been setup, do so now
        if not 'gitreceive' in ctx.cintf.db.deployments['system'].services or True:
            gitreceive_def = yaml.load(GITRECEIVE.format(
                authkey=ctx.cintf.db.auth_key,
                hostip=config.host_ip,
                hostkey=''
            ))
            gitreceive_def['env']['SSH_PRIVATE_KEYS']
            print(gitreceive_def)
            ctx.cintf.set_service(
                'system', 'gitreceive', gitreceive_def, force=True)

        url = 'git@{}:{d}/{s}'.format(
            config.hostname, d=service.deployment.id, s=service.name)
        ctx.custom(**{'gitreceive': service.name, 'url': url})
        return True


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
def api_setconfig(hostname=None, hostip=None):
    """Change gitreceive configuration
    """
    config = GitReceiveConfig.load(g.cintf.db)
    if hostname:
        config.hostname = hostname
    if hostip:
        config.host_ip = hostip
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
@click.option('--hostname')
@click.option('--hostip')
@click.pass_obj
def gitreceive_config(app, hostname, hostip):
    """Set gitreceive configuration.
    """
    app.plugin_call(
        'get', 'gitreceive', 'set-config',
        {'hostname': hostname, 'hostip': hostip})


class LocalGitReceivePlugin(LocalPlugin):

    def provide_cli(self, group):
        group.add_command(gitreceive_cli)

    def on_server_event(self, servicefile, deploy_id, event):
        if not 'gitreceive' in event:
            return

        service = event['gitreceive']
        self.setup_gitremote(servicefile.services[service], event['url'])

    def setup_gitremote(self, service, url):
        run = subprocess.check_output
        from deploylib.client.utils import directory

        project_path = service.path(service['git'])
        with directory(project_path):
            run('git remote add %s %s' % ('deploy', url), shell=True)
