#!/usr/bin/env python

import sys
import os
from urlparse import urljoin
import json
import ConfigParser

from docopt import docopt
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


def main(argv):
    """
    Usage:
      deploy.py deploy [--create] [--force] <service-file> <deploy-id>
      deploy.py list
      deploy.py list <deploy_id>
      deploy.py init <host>
      deploy.py add-server <name> <url> <auth>
    """
    args = docopt(main.__doc__, argv)
    config = Config()

    # Determine the server to interact with
    deploy_url = 'http://localhost:5555/api'
    auth = ''
    # Should we use a predefined server?
    servername = os.environ.get('SERVER')
    if servername:
        if not config.has_section('server "%s"' % servername):
            raise EnvironmentError("Server %s is not configured" % servername)
        deploy_url = config['server "%s"' % servername].get('url', deploy_url)
        auth = config['server "%s"' % servername].get('url', auth)
    # Explicit overrides
    deploy_url = os.environ.get('DEPLOY_URL', deploy_url)
    auth = os.environ.get('AUTH', auth)

    api = Api(deploy_url, auth)

    if args['deploy']:
        servicefile = ServiceFile.load(args['<service-file>'], plugin_runner=run_plugins)
        deploy_id = args['<deploy-id>']

        if args['--create']:
            api.create(deploy_id)

        result = api.setup(deploy_id, servicefile, force=args['--force'])

        for warning in result.get('warnings', []):
            if warning['type'] != 'data-missing':
                raise RuntimeError(warning['type'])

            filedata = run_plugins(
                'provide_data', servicefile.services[warning['service_name']],
                warning['tag'])
            files = {k: open(v[0], 'rb') for k, v in filedata.items()}
            data = {k: v[1] for k, v in filedata.items()}

            api.upload(deploy_id, warning['service_name'],
                       data=data, files=files)


    elif args['list']:
        result = api.list()
        for name, instance in result.items():
            print '%s (%s services)' % (name, len(instance))
        return

    elif args['init']:
        # Connect to the host via SSH, install this package.
        raise NotImplementedError()

    elif args['add-server']:
        config.add_section('server "%s"' % args['<name>'])
        config.set('server "%s"' % args['<name>'], 'url', args['<url>'])
        config.set('server "%s"' % args['<name>'], 'auth', args['<auth>'])
        config.save()


def run():
    sys.exit(main(sys.argv[1:]) or None)


if __name__ == '__main__':
    run()
