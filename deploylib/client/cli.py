#!/usr/bin/env python

import sys
import os
from urlparse import urljoin
import json

from docopt import docopt
import requests

from deploylib.plugins.app import LocalAppPlugin
from deploylib.client.service import ServiceFile
from deploylib.plugins.domains import LocalDomainPlugin


class Api(object):
    """Simple interface to the deploy daemon.
    """

    def __init__(self, url):
        self.url = url
        self.session = requests.Session()
        self.session.headers['Authorization'] = os.environ.get('AUTH')

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


def main(argv):
    """
    Usage:
      deploy.py deploy [--create] [--force] <service-file> <deploy-id>
      deploy.py list
      deploy.py list <deploy_id>
      deploy.py init <host>
    """
    args = docopt(main.__doc__, argv)
    deploy_url = os.environ.get('DEPLOY_URL', 'http://localhost:5555/api')

    api = Api(deploy_url)

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


def run():
    sys.exit(main(sys.argv[1:]) or None)


if __name__ == '__main__':
    run()
