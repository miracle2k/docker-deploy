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
        route = {
            'Frontend': {
                'Id': domain,
                'Type': 'http',
                'BackendId': service.replace(':', '-'),
                'Route': 'Host("%s")' % domain
            }
        }
        self.request(
            'POST', '/v2/frontends', route)

        if auth:
            if auth_mode == 'digest':
                print "vulcand does not support digest auth, using basic"
            if len(auth) > 1:
                print "vulcand currently only supports one user/pass pair, ignoring others."

            user, password = auth.items()[0]
            middleware = {
                'Middleware': {
                    "Id": "auth",
                    "Priority": 1,
                    "Type":"auth",
                    "Middleware":{
                        "Password": password,
                        "Username": user
                    }
                }
            }

            self.request(
                'POST', '/v2/frontends/%s/middlewares' % domain, middleware)

        if cert and key:
            hostconfig = {
                "Host": {
                    "Name": domain,
                    "Settings": {
                        "KeyPair": {
                            "Cert": cert,
                            "Key": key
                        }
                    }
                }
            }
            self.request('POST', '/v2/hosts', hostconfig)

            # Make sure the HTTPs listener is setup
            listener = {
                "Listener": {
                    "Id": "https",
                    "Protocol": "https",
                    "Address": {
                        "Network":"tcp",
                        "Address":"0.0.0.0:443"
                    }
                }
            }
            self.request('POST', '/v2/listeners', listener)


VULCAND = \
"""
image: elsdoerfer/vulcand
cmd: ["-etcd=%s", "-apiInterface=0.0.0.0", "-logSeverity=INFO", "-port=80"]
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


class Listener(dict):
    pass



def only_if(service=None):
    """A listener is only executed if the conditions (evaluated globally)
    apply.
    """

    def decorator(func):
        if not hasattr(func, '_listener'):
            raise TypeError('@only_if: function does not have a listener yet.')

        if not '.' in service:
            raise ValueError('@only_if service needs to be in deployment.service format')
        func._listener['required_services'] = [service.split('.', 1)]

        return func
    return decorator


def each_service(globals=None):
    """Define a handler that will be executed per-service.
    """

    def decorator(func):
        if hasattr(func, '_listener'):
            raise TypeError('This function already has a listener.')

        func._listener = Listener({
            'type': 'service',
            'global_keys': [globals] if globals else []
        })

        return func
    return decorator


def resolve_service(service):
    deploy_name, service_name = service
    return ctx.cintf.db.deployments[deploy_name].has_service(service_name)



class SmartPlugin(Plugin):
    """Writing the event handler logic can be complex, since there is often
    some dependency logic involved. For example, the plugin should do something
    when a service is installed, but only if the plugin's own service is
    already running. Once the plugin's service is installed, the processing
    code needs to run for all existing services.

    This allows to define the callbacks on a dependency basis. I.e. "run
    this function" for every service, rather than on an event basis.

    XXX: This has another advantage; it means that if the callback cannot
    finished, maybe because the vulcand API is not available now, it can
    trigger a temporary error, and the smart plugin system can reschedule
    the call.
    """

    def _get_listeners(self):
        # Find any listeners defined on the current class.
        for name in dir(self):
            attr = getattr(self, name)
            if not hasattr(attr, '_listener'):
                continue
            l = attr._listener.copy()
            l['func'] = attr
            yield l

    def _active_listeners(self, type):
        """Return all listeners that are active, that is, their dependencies
        are fullfilled.
        """
        for listener in self._get_listeners():
            if listener['type'] != type:
                continue

            # We only do anything if all requirements are passing
            one_missing = False
            for deploy_name, service_name in listener.get('required_services', []):
                if not deploy_name in ctx.cintf.db.deployments or not \
                        ctx.cintf.db.deployments[deploy_name].has_service(service_name):
                    one_missing = True
                    break
            if one_missing:
                continue

            yield listener

    def _call(self, listener, *args):
        listener['func'](*args)

    def post_setup(self, service, version):
        for listener in self._active_listeners(type='service'):
            reqs = map(resolve_service, listener.get('required_services', []))
            if service in reqs:
                # Just enabled, trigger for all services
                for name, deployment in ctx.cintf.db.deployments.items():
                    for service in deployment.services.values():
                        self._call(listener, service)

            else:
                self._call(listener, service)

    def on_globals_changed(self, deployment):
        for listener in self._active_listeners(type='service'):
            # See if the listener depends on any of the keys in the globals here
            for key in listener['global_keys']:
                if key in deployment.globals:
                    # Call listener for all services in this deployment
                    for service in deployment.services.values():
                        self._call(listener, service)
                    break


class VulcanPlugin(SmartPlugin):
    """Will process a Domains section, which defines domains
    and maps them to services, and register those mappings with
    the vulcan router.

    (The reason we have this run on the server: We want a database of
     domains in our control on the server, so we can enable a different
     router plugin easily).
    """

    @only_if(service='system.vulcand')
    @each_service(globals='Domains')
    def setup_domains(self, service):
        # are there any domains defined in the globals for this service?
        deployment = service.deployment

        domains = deployment.globals.get('Domains', {})

        api_ip = ctx.cintf.discover('system-vulcand-api')
        vulcan = VulcanClient(api_ip)

        ctx.job('Setting up routes')
        for domain, data in domains.items():
            if not data:
                continue
            service_name = data.get('http')
            if not service_name:
                continue

            # Vulcand does not support setting a frontend before setting
            # the backend. Therefore, we need to delay this until the service
            # has been setup (at which point this plugin will register the backend).
            if not deployment.has_service(service_name):
                continue

            ctx.log('%s -> %s' % (domain, service_name))
            vulcan.set_http_route(
                domain, service_name, key=data.get('key'),
                cert=data.get('cert'), auth=data.get('auth'),
                auth_mode=data.get('auth_mode'))

    @only_if(service='system.vulcand')
    @each_service()
    def setup_backends_for_service(self, service):
        #register a backend for this service with vulcand
        pass
