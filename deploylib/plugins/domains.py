import json
import os
from urlparse import urljoin
from os.path import dirname, normpath, join as path, exists
import requests
from . import Plugin, LocalPlugin


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
            'Domain': domain,
            'Service': service,
            'TLSCert': cert,
            'TLSKey': key
        }
        return self.request(
            'POST', '/routes', {'type': 'http', 'config': route})


class LocalDomainPlugin(LocalPlugin):
    """Resolve SSL cert paths."""

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

    def post_deploy(self, services, globals):
        domains = globals.get('Domains', {})
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
