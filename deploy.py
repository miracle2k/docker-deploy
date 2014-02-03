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
from deploylib import ServiceFile, Host


def main(argv):
    print('Usage: ./cmd <service-file> <host>')

    servicefile = ServiceFile.load(argv[0])
    host = Host(argv[1])
    deploy_id = argv[2]

    host.deploy_servicefile(deploy_id, servicefile)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]) or None)
