"""
what happens on plugin install?
-------------------------------

http /set-service
http /resource-complete

- if set-service fails, nothing would be changed
- resource-complete fails, the whole job would retry and it should be fine since set-service should be idempotent

plugins may be able to define their services via a system
----------------------------------------------------

the plugin manager would execute the above logic just fine


what if a set-service would trigger another set-service?
--------------------------------------------------------

http /set-service
    http /set-service

?? imagine sidebar container...


what if it triggers something else that fails?
----------------------------------------------

http /set-service
    http consul set

- point is it might happen in this case that wthe consul-set executes but the set-service does not finish;
        this should not happen
- consul set should be it's own post-job



==> key is that pre-start no data commit should happen until the service starts



what is so special about starting the container that we have the commit issue?
go through the rest of the plugins to test the commit issue?
"""


"""shelf is a tiny little file server. This plugin will run it as part of
the system deployment.

Various other plugins may depend on it; for example, the app plugin uses
it to store compiled slugs.
"""

"""


class Logger():
    # could be a in-memory store, or in case of qless, a storage


class PluginDefinedRegisterStep():
    pass


class RunStep():
    Backend.run(service)


class TransformStep():
    run_plugins('transform_service')
    if service_changed:
        Backend.create(service)
        save_service()

        yield RunStep()


def run_job():
    logger = Logger()
    job_instance = clazz(logger)
    job_instance.exec()
    job_registry.add(job_instance)
    # in the easiest case, can run in-process. can even use peristance.
    # if more is needed, use qless.


def on_set(request):
    service_def = {}

    job = run_job(SetServiceStep)
    return stream_job(job)

"""

import click
from flask import Blueprint
import yaml
from deploylib.daemon.api import streaming
from deploylib.daemon.context import ctx
from deploylib.plugins import Plugin, LocalPlugin


SHELF_SD_NAME = 'system-shelf'

SHELF = """
image: flynn/blobstore
entrypoint: /bin/flynn-blobstore
cmd: ["-s", "/var/lib/shelf"]
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


