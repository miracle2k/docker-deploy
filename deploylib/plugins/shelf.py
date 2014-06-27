"""shelf is a tiny little file server. This plugin will run it as part of
the system deployment.

Various other plugins may depend on it; for example, the app plugin uses
it to store compiled slugs.
"""

import click
from flask import Blueprint
import yaml
from deploylib.daemon.api import streaming
from deploylib.daemon.context import ctx
from deploylib.plugins import Plugin, LocalPlugin


SHELF = """
image: elsdoerfer/shelf
cmd: -s /var/lib/shelf
volumes: {data: /var/lib/shelf}
"""


class ShelfPlugin(Plugin):

    def is_setup(self):
        return 'shelf' in ctx.cintf.db.deployments['system'].services

    def setup_shelf(self):
        shelf_def = yaml.load(SHELF)
        ctx.cintf.set_service('system', 'shelf', shelf_def, force=True)


shelf_api = Blueprint('shelf', __name__)

@shelf_api.route('/setup', methods=['POST'])
@streaming()
def api_setup(request, app):
    ctx.cintf.controller.get_plugin(ShelfPlugin).setup_shelf()


@click.group('shelf')
def shelf_cli():
    """Manage shelf."""
    pass


@shelf_cli.command('setup')
@click.pass_obj
def setup_shelf(app, **kwargs):
    app.plugin_call('post', 'shelf', 'setup', {})


class LocalGitReceivePlugin(LocalPlugin):
    def provide_cli(self, group):
        group.add_command(shelf_cli)


