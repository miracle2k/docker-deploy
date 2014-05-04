import json
from urlparse import urljoin
import requests
from . import Plugin


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


class DomainPlugin(Plugin):
    """Will process a Domains section, which defines domains
    and maps them to services, and register those mappings with
    the strowger router.
    """

    def provide_data(self):
        pass
        #cert = open(servicefile.path(data['cert']), 'r').read()
        #key_paths = [servicefile.path(data['key'])]
        #if 'KEY_PATH' in os.environ:
        #    key_paths.append(path(os.environ['KEY_PATH'], data['key']))
        #for candidate in key_paths:
        #    if exists(candidate):
        #        key = open(candidate, 'r').read()
        #if not key:
        #    raise ValueError('key not found in: %s' % key_paths)

    def post_deploy(self, services, globals):
        domains = globals.get('Domains', {})
        if not domains:
            return

        api_ip = self.host.discover('strowger-api')
        strowger = StrowgerClient(api_ip)

        for domain, data in domains.items():
            service_name = domain.get('http')
            if not service_name:
                continue
            strowger.set_http_route(domain, service_name)

        # TODO: Support further plugins to configure the domain DNS
