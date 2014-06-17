"""This processes ``Domain`` by adding domain:service maps to the
strowger HTTP router.

It provides a ``setup-strowger`` command which will - currently - run one
instance of strowger as part of the system deployment.
"""

import json
import os
from urlparse import urljoin
from os.path import dirname, normpath, join as path, exists
import click
import requests
from . import Plugin, LocalPlugin
import yaml
from deploylib.client.service import ServiceFile


class StrowgerClient:

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
        response.raise_for_status()
        return response.json()

    def set_http_route(self, domain, service, cert=None, key=None):
        route = {
            'domain': domain,
            'service': service,
            'tls_cert': cert,
            'tls_key': key
        }
        return self.request(
            'PUT', '/routes', {'type': 'http', 'config': route})


STROWGER = \
"""
image: elsdoerfer/strowger
cmd: -httpaddr=":{PORT_HTTP}" --httpsaddr=":{PORT_HTTPS}" --apiaddr=":{PORT_RPC}"
ports: [http, https, rpc]
host_ports: {http: "0.0.0.0:80", https: "0.0.0.0:443"}
"""


@click.command('setup-strowger')
@click.pass_obj
def setup_strowger(app, **kwargs):
    """Run the strowger service.
    """
    from deploylib.client.cli import print_jobs
    # I think I'd prefer this as being done by a special API view.
    strowger_def = yaml.load(STROWGER)
    servicefile = ServiceFile()
    servicefile.globals = {}
    servicefile.services = {'strowger': strowger_def}
    print_jobs(app.api.setup('system', servicefile, force=True))


class LocalDomainPlugin(LocalPlugin):
    """Resolve SSL cert paths."""

    def provide_cli(self, group):
        group.add_command(setup_strowger)

    def file_loaded(self, services, globals, filename=None):
        domains = globals.get('Domains', {})
        if not domains:
            return

        p = lambda s: normpath(path(dirname(filename), s))

        for domain, data in domains.items():
            if 'cert' in data:
                data['cert'] = open(p(data['cert']), 'r').read()
            if 'key' in data:
                key_paths = [p(data['key'])]
                if 'KEY_PATH' in os.environ:
                    key_paths.append(path(os.environ['KEY_PATH'], data['key']))
                key = None
                for candidate in key_paths:
                    if exists(candidate):
                        key = open(candidate, 'r').read()
                        break
                if not key:
                    raise ValueError('key not found in: %s' % key_paths)
                data['key'] = key


class DomainPlugin(Plugin):
    """Will process a Domains section, which defines domains
    and maps them to services, and register those mappings with
    the strowger router.
    """

    def on_globals_changed(self, deployment):
        domains = deployment.globals.get('Domains', {})
        if not domains:
            return

        api_ip = self.host.discover('strowger-api')
        strowger = StrowgerClient(api_ip)

        for domain, data in domains.items():
            service_name = data.get('http')
            if not service_name:
                continue
            strowger.set_http_route(domain, service_name, key=data.get('key'),
                                    cert=data.get('cert'))

        # TODO: Support further plugins to configure the domain DNS
        # TODO: The strowger interaction relates to how we could do
        #    switch-over upgrades, so in the future we might have to
        #    do this not when the globals change, but after the services
        #    are running. I can already see it: The domain definition
        #    points to a "mark". Via the cli we can set the mark to a
        #    new service version. A {VERSION} variable can be used in
        #    service-definitions to register different versions with
        #    discovery.
