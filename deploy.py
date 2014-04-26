#!/usr/bin/env python

import sys
import os
from docopt import docopt
from urlparse import urljoin
import json
from deploylib.service import ServiceFile
import requests


class Api(object):
    """Simple interface to the deploy daemon.
    """

    def __init__(self, url):
        self.url = url
        self.session = requests.Session()
        self.session.headers = {'content-type': 'application/json'}

    def request(self, method, url, *args, **kwargs):
        url = urljoin(self.url, url)
        if 'data' in kwargs:
            kwargs['data'] = json.dumps(kwargs['data'])
        response = getattr(self.session, method)(url, *args, **kwargs)
        response.raise_for_status()
        data = response.json()
        if 'error' in data:
            raise RuntimeError(data['error'])
        return data

    def list(self):
        return self.request('get', 'list')

    def create(self, deploy_id):
        return self.request('put', 'create', data={'deploy_id': deploy_id})

    def setup(self, deploy_id, servicefile):
        return self.request('post', 'setup', data={
            'deploy_id': deploy_id,
            'services': servicefile.services})



def main(argv):
    """
    Usage:
      deploy.py deploy [--create] <service-file> <deploy-id>
      deploy.py list
      deploy.py list <deploy_id>
      deploy.py init <host>
    """
    args = docopt(main.__doc__, argv)
    deploy_url = os.environ.get('DEPLOY_URL', 'http://localhost:5000/api')

    api = Api(deploy_url)

    if args['deploy']:
        servicefile = ServiceFile.load(args['<service-file>'])
        deploy_id = args['<deploy-id>']

        if args['--create']:
            api.create(deploy_id)
        api.setup(deploy_id, servicefile)

    elif args['list']:
        result = api.list()
        for name, instance in result.items():
            print '%s (%s services)' % (name, len(instance))
        return

    elif args['init']:
        requests.get(urljoin(deploy_url, '/init'), data={}).json()


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]) or None)
