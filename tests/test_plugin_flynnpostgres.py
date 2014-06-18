import json
from deploylib.plugins.flynn_postgres import FlynnPostgresPlugin


class TestFlynnPostgres(object):

    def test_db_creation(self, host, responses):
        """Test that the plugin runs after both the pg and the pg-api
        containers have been installed for the first time.
        """
        # Mock flynn-postgres-api container
        responses.add(responses.POST, 'http://abc-api/databases',
                  body=json.dumps({'env': {'PGDATABASE': 1, 'PGUSER': 2,
                                           'PGPASSWORD': 3}}), status=200,
                  content_type='application/json')

        deployment = host.create_deployment('foo')
        host.set_globals('foo', {
            'Flynn-Postgres': {
                'my-database': {
                    'in': 'db',
                    'via': 'db-api',
                    'expose_as': 'POSTGRES_'
                }
            }
        })

        # Bring up the database
        host.set_service('foo', 'db', {})
        assert not deployment.get_resource('my-database')

        # Bring up the database api container
        host.set_service('foo', 'db-api', {'env': {'FLYNN_POSTGRES': 'abc'}})
        assert deployment.get_resource('my-database')

    def test_variable_insertion(self, host):
        """Test that the database variables are inserted into all of
        the deployment's containers.
        """

        deployment = host.create_deployment('foo')
        host.set_globals('foo', {
            'Flynn-Postgres': {
                'my-database': {
                    'in': 'db',
                    'via': 'db-api',
                    'expose_as': 'POSTGRES_'
                }
            }
        })
        host.get_plugin(FlynnPostgresPlugin).set_db_resource(
            deployment, 'my-database', 'foo', 'bar', 'baz'
        )

        # Deploy a service
        host.set_service('foo', 'a-service', {})
        # Have a look at the vars used
        call = host.backend.start.mock_calls[0]
        runcfg = call[1][1]
        assert runcfg['env']['POSTGRES_DATABASE'] == 'foo'
