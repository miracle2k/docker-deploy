"""This plugin is specifically to setup databases with the
flynn-postgres appliance.

Here is my thought process on initializing database resources:

1. In principal, we specifically chose a design where containers interact only
   through service discovery; the order in which they are started does not
   matter.

2. However, for initializing something like a database resource that requires
   passwords, we have to fundamentally introduce a ordered step.

3. The only possible scenario where this is not required is when the database
   initialization "dissolves" entirely within the container setup, that is,
   the database container only registers with discovery when it has
   initialized itself with auth data that is known to us beforehand.

   (It's not feasible to write a web app in such a way that it can deal with
   a database server being available but waiting for the actual database
   configuration to be setup).

4. So I don't see an alternative to having an ordered "bootstrap" step. This
   step would be required to run before any containers do, and further may
   force particular containers to be started before others.

   This means that once a deployment is initialized, the containers will
   subsequently still be entirely independent from each other.


We should support the following different approaches to setting up a database:

- The case described above: Setting up the database via an initialization
  step.

- This includes cases where the database container itself may generate the
  auth information and exposes it via the filesystem for example.

- A database container which has the setup step builtin: Taking the
  user/pw/name data via env and registering with discovery when done.

- For cases where all else fails, maybe because we are working with a backend
  where we cannot start the db container ourselves, we should make it as
  simple as possible to get manual user interaction involved to do the
  initialization.

This plugin uses a global Flynn-Postgres section::

    Flynn-Postgres:
        foobar:
            in: db
            via: db-api
            expose_as: POSTGRES_

``in`` is the flynn/postgres API service to use. ``expose_as`` is the
environment variable prefix to use. These variables like ``POSTGRES_HOST``
will be available to all containers, so it works perfectly if multiple
containers depend on it. An dict structure can be used for multiple
databases. The key is used to allow renaming the ``expose_as`` option
w/o triggering a new setup.

TODO: Should support a mode where the actual postgres containers are
run externally (so the plugin can just assume they are running), and
containers can instead use "require" to reference the database defined.
"""

from subprocess import CalledProcessError
import time
from requests import ConnectionError
import requests

from deploylib.plugins import Plugin


class FlynnPostgresPlugin(Plugin):

    def _make_env(self, expose_as, user=None, password=None, dbname=None):
        expose_as = expose_as or 'PG'
        return {
            '%s%s' % (expose_as, 'USER'): user,
            '%s%s' % (expose_as, 'PASSWORD'): password,
            '%s%s' % (expose_as, 'DATABASE'): dbname,
        }

    def provide_environment(self, deployment, service, env):
        """If the database has already been setup, we inject it's
        data into every service we provide.
        """
        section = deployment.globals.get('Flynn-Postgres')
        if not section:
            return

        data = deployment.data.get('flynn-postgres', {})
        for dbid, created_db in data.items():
            env.update(self._make_env(section[dbid].get('expose_as'), **data[dbid]))

    def post_setup(self, service, version):
        """After both the postgres container itself and the api container
        have been setup, we now have to create the database.
        """

        deployment = service.deployment
        if not 'Flynn-Postgres' in deployment.globals:
            return

        for dbid, dbcfg in deployment.globals['Flynn-Postgres'].items():
            self.setup_database(deployment, service, dbid, dbcfg)

    def setup_database(self, deployment, service, dbid, dbcfg):
        data = deployment.data.setdefault('flynn-postgres', {})

        # Has this database already been setup? We don't need to anything
        if dbid in data:
            return

        # We go into action once the second of the pg and pg-api
        # services have been set up.
        if not service.name in (dbcfg['in'], dbcfg['via']):
            return
        if not dbcfg['in'] in deployment.services or not \
                dbcfg['via'] in deployment.services:
            return

        # Determine the service discovery name of the API container.
        # This is a bit of a hack.
        api_service = deployment.services[dbcfg['via']]
        discovery_name = api_service.latest.definition['env']['FLYNN_POSTGRES']
        discovery_name = discovery_name.format(DEPLOY_ID=deployment.id)

        start = time.time()
        while time.time() - start < 40:
            try:
                httpurl = 'http://%s/databases' % self.host.discover(
                    discovery_name)
            except (CalledProcessError, ConnectionError):
                time.sleep(1)
                continue

            try:
                created = requests.post(httpurl).json()
            except (ConnectionError):
                time.sleep(1)
            else:
                data[dbid] = {}
                data[dbid]['dbname'] = created['env']['PGDATABASE']
                data[dbid]['user'] = created['env']['PGUSER']
                data[dbid]['password'] = created['env']['PGPASSWORD']
                break

        else:
            raise EnvironmentError(
                "Cannot find flynn-postgres API: %s" % discovery_name)



