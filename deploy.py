"""
In the future, the CLI might look something like this::

    $ host Servicefile deploy myapp-production

If the service exists, it will sync against YAML file changes.

::

    $ host Servicefile list

Will list all running services.

::

    $ host myapp-production run rethinkdb

Create a new instance of the service within the given deploy.

::

    $ host myapp-production restart rethinkdb

Restart a given instance within the deploy.
"""

import sys
import os
from os.path import join as path, dirname
from docopt import docopt
from urlparse import urljoin
import json
from deploylib.service import ServiceFile
import requests


def main(argv):
    """
    Usage:
      deploy.py create <deploy-id> <service-file>
      deploy.py update <deploy-id> <service-file>
      deploy.py list
      deploy.py init <host>
    """
    args = docopt(main.__doc__, argv)
    deploy_url = os.environ.get('DEPLOY_URL', 'http://localhost:5000/api')

    session = requests.Session()
    session.headers = {'content-type': 'application/json'}

    if args['update'] or args['create']:
        servicefile = ServiceFile.load(args['<service-file>'])
        deploy_id = args['<deploy-id>']

        if args['create']:
            result = session.post(
                urljoin(deploy_url, '/create'),
                data=json.dumps({'deploy_id': deploy_id})).json()

        result = session.post(
                urljoin(deploy_url, '/setup'),
                data=json.dumps({'deploy_id': deploy_id,
                                 'services': servicefile.services})).json()

    elif args['list']:
        result = requests.get(urljoin(deploy_url, '/list'), data={}).json()
        for instance in result:
            print instance
        return

    elif args['init']:
        result = requests.get(urljoin(deploy_url, '/init'), data={}).json()

    if 'error' in result:
        print('Error: %s' % result['error'])
        return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]) or None)
