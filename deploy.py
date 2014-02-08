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
from os.path import join as path, dirname
from docopt import docopt
from deploylib import ServiceFile, Host


def main(argv):
    """
    Usage:
      deploy.py --host=<host> create <deploy-id> <service-file>
      deploy.py --host=<host> update <deploy-id> <service-file>
      deploy.py --host=<host> list
      deploy.py init <host>
    """
    args = docopt(main.__doc__, argv)

    if args['update']:
        # TODO: Validate the instance exists.
        servicefile = ServiceFile.load(args['<service-file>'])
        host = Host(args['--host'])
        deploy_id = args['<deploy-id>']
        host.deploy_servicefile(deploy_id, servicefile)

    elif args['create']:
        # TODO: not that different than update, but validate the instance
        # does not yet exist.
        raise NotImplementedError()

    elif args['list']:
        host = Host(args['--host'])
        for i in host.get_instances():
            print(i)

    elif args['init']:
        # Apply the Bootstrap service file
        servicefile = ServiceFile.load(path(dirname(__file__), 'Bootstrap'), ordered=True)
        host = Host(args['<host>'])
        namer = lambda s: s.name   # Use literal names so we can find them
        host.deploy_servicefile('_sys_', servicefile, namer=namer)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]) or None)
