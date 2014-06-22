#!/usr/bin/env python
from contextlib import closing

import sys
import os
from urlparse import urljoin
import json
import ConfigParser

import click
import requests
from clint.textui import puts, indent, colored
from deploylib.plugins import load_plugins, LocalPlugin
from deploylib.client.service import ServiceFile


class Api(object):
    """Simple interface to the deploy daemon.
    """

    def __init__(self, url, auth):
        self.url = url
        self.session = requests.Session()
        self.session.headers['Authorization'] = auth

    def _server_events(self, response):
        """Server streams lines of JSON objects.

        Supported types are, identified by the existence of the key:

        job
            The job being currently processed. This is like a header
            for the log messages that follow.

        log
            A log message within the current job.

        """
        with closing(response):
            for line in response.iter_lines(chunk_size=1):
                if not line:
                    continue
                yield json.loads(line)

    def request(self, method, url, *args, **kwargs):
        url = urljoin(self.url, url)
        if 'json' in kwargs:
            kwargs['data'] = json.dumps(kwargs.pop('json'))
            kwargs.setdefault('headers', {})
            kwargs['headers'].update({'content-type': 'application/json'})
        response = getattr(self.session, method)(url, *args, **kwargs)
        response.raise_for_status()
        if kwargs.get('stream'):
            return self._server_events(response)
        data = response.json()
        return data

    def plugin(self, method, plugin_name, func, **kwargs):
        return self.request(
            'get', '%s/%s' % (plugin_name, func), json=kwargs)

    def list(self):
        return self.request('get', 'list')

    def create(self, deploy_id):
        return self.request('put', 'create', json={'deploy_id': deploy_id})

    def setup(self, deploy_id, servicefile, force=False):
        return self.request('post', 'setup', json={
            'deploy_id': deploy_id,
            'services': servicefile.services,
            'globals': servicefile.globals,
            'force': force}, stream=True)

    def upload(self, deploy_id, service_name, files, data=None):
        return self.request('post', 'upload', files=files, data={
            'deploy_id': deploy_id,
            'service_name': service_name,
            'data': json.dumps(data)}, stream=True)


PLUGINS = load_plugins(LocalPlugin)

def run_plugins(method_name, *args, **kwargs):
    for plugin in PLUGINS:
        method = getattr(plugin, method_name, None)
        if not method:
            continue
        result = method(*args, **kwargs)
        if not result is None:
            return result
    else:
        return False


def with_printer(event_stream):
    """Given a stream of server events, will output the default
    one that relate to the process messages, will pass through those
    that are unknown.
    """
    for event in event_stream:
        if 'job' in event:
            puts('-----> %s' % event['job'])
        elif 'log' in event:
            with indent(7):
                puts('%s' % event['log'])
        elif 'error' in event:
            with indent(7):
                puts(colored.red('Error: %s' % event['error']))
        else:
            yield event


def print_jobs(event_stream):
    """Call :meth:`with_printer`, but consume all events."""
    for event in with_printer(event_stream):
        raise ValueError(event)


def single_result(event):
    error = event.get('error', False)
    print_jobs([event])
    if error:
        raise click.ClickException('Aborted.')


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

    def plugin_call(self, method, plugin, func, kwargs):
        single_result(self.api.plugin(method, plugin, func, **kwargs))


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
        if single_result(api.create(deploy_id)):
            return

    requested_uploads = []
    for event in with_printer(api.setup(deploy_id, service_file, force=force)):
        if 'data-request' in event:
            requested_uploads.append(event)
            continue
        if run_plugins('on_server_event', service_file, deploy_id, event):
            continue
        raise ValueError(event)

    for event in requested_uploads:
        filedata = run_plugins(
            'provide_data',
            service_file.services[event['data-request']],
            event['tag'])
        files = {k: open(v[0], 'rb') for k, v in filedata.items()}
        data = {k: v[1] for k, v in filedata.items()}

        puts('-----> Service %s requested data %s, uploading...' %
             (event['data-request'], event['tag']))

        print_jobs(api.upload(
                deploy_id, event['data-request'], data=data, files=files))


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


# Let plugins add more commands.
run_plugins('provide_cli', main)


def run():
    sys.exit(main(sys.argv[1:]) or None)


if __name__ == '__main__':
    run()
