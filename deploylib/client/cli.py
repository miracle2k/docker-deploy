#!/usr/bin/env python

import sys
import os
from urlparse import urljoin
import json
import ConfigParser

import click
import requests

from deploylib.plugins.app import LocalAppPlugin
from deploylib.client.service import ServiceFile
from deploylib.plugins.domains import LocalDomainPlugin


class Api(object):
    """Simple interface to the deploy daemon.
    """

    def __init__(self, url, auth):
        self.url = url
        self.session = requests.Session()
        self.session.headers['Authorization'] = auth

    def request(self, method, url, *args, **kwargs):
        url = urljoin(self.url, url)
        if 'json' in kwargs:
            kwargs['data'] = json.dumps(kwargs.pop('json'))
            kwargs.setdefault('headers', {})
            kwargs['headers'].update({'content-type': 'application/json'})
        response = getattr(self.session, method)(url, *args, **kwargs)
        response.raise_for_status()
        data = response.json()
        if 'error' in data:
            raise RuntimeError(data['error'])
        return data

    def list(self):
        return self.request('get', 'list')

    def create(self, deploy_id):
        return self.request('put', 'create', json={'deploy_id': deploy_id})

    def setup(self, deploy_id, servicefile, force=False):
        return self.request('post', 'setup', json={
            'deploy_id': deploy_id,
            'services': servicefile.services,
            'globals': servicefile.globals,
            'force': force})

    def upload(self, deploy_id, service_name, files, data=None):
        return self.request('post', 'upload', files=files, data={
            'deploy_id': deploy_id,
            'service_name': service_name,
            'data': json.dumps(data)})


PLUGINS = [
    LocalAppPlugin(),
    LocalDomainPlugin()
]

def run_plugins(method_name, *args, **kwargs):
    for plugin in PLUGINS:
        method = getattr(plugin, method_name, None)
        if not method:
            continue
        result = method(*args, **kwargs)
        if not result is False:
            return result
    else:
        return False


class Config(ConfigParser.ConfigParser):

    def __init__(self):
        ConfigParser.ConfigParser.__init__(self)
        self.filename = os.path.expanduser('~/.calzion')
        self.read(self.filename)

    def save(self):
        with open(self.filename, 'w') as configfile:
            self.write(configfile)

    def __getitem__(self, item):
        return dict(self.items(item))



class App(object):
    def __init__(self):
        self.config = config = Config()

        # Determine the server to interact with
        deploy_url = 'http://localhost:5555/api'
        auth = ''
        # Should we use a predefined server?
        servername = os.environ.get('SERVER')
        if servername:
            if not config.has_section('server "%s"' % servername):
                raise EnvironmentError("Server %s is not configured" % servername)
            deploy_url = config['server "%s"' % servername].get('url', deploy_url)
            auth = config['server "%s"' % servername].get('auth', auth)
        # Explicit overrides
        deploy_url = os.environ.get('DEPLOY_URL', deploy_url)
        auth = os.environ.get('AUTH', auth)

        self.api = Api(deploy_url, auth)


@click.group()
@click.pass_context
def main(ctx):
    ctx.obj = App()


@main.command()
@click.option('--create', default=False, is_flag=True)
@click.option('--force', default=False, is_flag=True)
@click.argument('service-file', type=click.Path())
@click.argument('deploy-id')
@click.pass_obj
def deploy(app, service_file, deploy_id, create, force):
    """Take a template, deploy it to the server.
    """
    api = app.api
    service_file = ServiceFile.load(service_file, plugin_runner=run_plugins)

    if create:
        api.create(deploy_id)

    result = api.setup(deploy_id, service_file, force=force)

    for warning in result.get('warnings', []):
        if warning['type'] != 'data-missing':
            raise RuntimeError(warning['type'])

        filedata = run_plugins(
            'provide_data', service_file.services[warning['service_name']],
            warning['tag'])
        files = {k: open(v[0], 'rb') for k, v in filedata.items()}
        data = {k: v[1] for k, v in filedata.items()}

        api.upload(deploy_id, warning['service_name'],
                   data=data, files=files)


@main.command()
@click.pass_obj
def list(app):
    """List deployments and services.
    """
    result = app.api.list()
    for name, instance in result.items():
        print '%s (%s services)' % (name, len(instance))
        for service, data in instance.items():
            print('  %s (%s versions)' % (service, data['versions']))
            for i in data['instances']:
                print('    %s' % i)


@main.command('add-server')
@click.argument('name')
@click.argument('url')
@click.argument('auth')
@click.pass_obj
def add_server(app, name, url, auth):
    """Remember a new server address.
    """
    app.config.add_section('server "%s"' % name)
    app.config.set('server "%s"' % name, 'url', url)
    app.config.set('server "%s"' % name, 'auth', auth)
    app.config.save()




def run():
    sys.exit(main(sys.argv[1:]) or None)


if __name__ == '__main__':
    run()
