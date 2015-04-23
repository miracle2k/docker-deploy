"""This processes ``Domain`` by adding domain:service maps to the
vulcand HTTP router.

vulcand is a pretty full featured proxy supporting HTTPS with SNI, and
middlewares that can implement authentication, for example.
"""

import json
import os
from hashlib import md5
from urlparse import urljoin
from os.path import dirname, normpath, join as path, exists
import click
import requests
from . import Plugin, LocalPlugin
import yaml
from deploylib.client.service import ServiceFile
from deploylib.daemon.context import ctx
from deploylib.plugins.strowger import LocalDomainResolver


ETCD_ADDRESS = 'http://etcd-4001.service.consul:4001'


class VulcanClient:

    def __init__(self, url):
        self.session = requests.Session()
        self.session.headers = {'content-type': 'application/json'}

        if url.startswith(':'):
            url = 'localhost%s' % url
        if not url.startswith('http://'):
            url = 'http://%s' % url
        self.api_url = url

    def request(self, method, url, data=None):
        url = urljoin(self.api_url, url)
        response = self.session.request(
            method, url, data=json.dumps(data) if data else None)
        print response.json()
        response.raise_for_status()
        return response.json()

    def set_http_route(self, domain, service, cert=None, key=None, auth=None,
                       auth_realm='protected', auth_mode='digest'):
        if auth:
            print "Skipping route that requires auth"
            return
        if cert or key:
            print "Skipping HTTPs route"
            return

        route = {
            'Frontend': {
                'Id': domain,
                'Type': 'http',
                'BackendId': service.replace(':', '-'),
                'Route': 'Host("%s")' % domain
            }
        }
        return self.request(
            'POST', '/v2/frontends', route)


VULCAND = \
"""
image: mailgun/vulcand:v0.8.0-beta.3
cmd: vulcand -etcd=%s  -apiInterface=0.0.0.0 -logSeverity=INFO -port 80
ports:
  http: 80
  https: 443
  api: 8182
wan_map: {"0.0.0.0:80": http, "0.0.0.0:443": https}
""" % ETCD_ADDRESS


@click.group('vulcand')
def vulcand_cli():
    """Manage vulcand."""
    pass

@vulcand_cli.command('setup')
@click.pass_obj
def setup_vulcand(app, **kwargs):
    from deploylib.client.cli import print_jobs
    vulcan_def = yaml.load(VULCAND)
    servicefile = ServiceFile()
    servicefile.globals = {}
    servicefile.services = {'vulcand': vulcan_def}
    print_jobs(app.api.setup('system', servicefile, force=True))


class LocalVulcanPlugin(LocalDomainResolver):
    def provide_cli(self, group):
        group.add_command(vulcand_cli)


class VulcanPlugin(Plugin):
    """Will process a Domains section, which defines domains
    and maps them to services, and register those mappings with
    the vulcan router.

    (The reason we have this run on the server: We want a database of
     domains in our control on the server, so we can enable a different
     router plugin easily).
    """

    def post_setup(self, service, version):
        # The first time vulcan is setup, add routes to all domains
        # that we know about.
        if service.name != 'vulcand' or service.deployment.id != 'system':
            return
        if service.versions:
            return

        for name, deployment in ctx.cintf.db.deployments.items():
            ctx.cintf.get_plugin(VulcanPlugin).on_globals_changed(deployment)

    def on_globals_changed(self, deployment):
        domains = deployment.globals.get('Domains', {})
        if not domains:
            return

        # If vulcan is not setup, do nothing.
        if not 'vulcand' in ctx.cintf.db.deployments['system'].services:
            return

        api_ip = ctx.cintf.discover('system-vulcand-api')
        vulcan = VulcanClient(api_ip)

        ctx.job('Setting up routes')
        for domain, data in domains.items():
            if not data:
                continue
            service_name = data.get('http')
            if not service_name:
                continue
            ctx.log('%s -> %s' % (domain, service_name))
            vulcan.set_http_route(
                domain, service_name, key=data.get('key'),
                cert=data.get('cert'), auth=data.get('auth'),
                auth_mode=data.get('auth_mode'))
