import json
from deploylib.plugins.flynn_postgres import FlynnPostgresPlugin


controller_plugins = [FlynnPostgresPlugin]


class TestFlynnPostgres(object):

    def test_db_creation(self, cintf, responses):
        """Test that the plugin runs after both the pg and the pg-api
        containers have been installed for the first time.
        """
        # Mock flynn-postgres-api container
        responses.add(responses.POST, 'http://abc-api/databases',
                  body=json.dumps({'env': {'PGDATABASE': 1, 'PGUSER': 2,
                                           'PGPASSWORD': 3}}), status=200,
                  content_type='application/json')

        deployment = cintf.create_deployment('foo')
        cintf.set_globals('foo', {
            'Flynn-Postgres': {
                'my-database': {
                    'in': 'db',
                    'via': 'db-api',
                    'expose_as': 'POSTGRES_'
                }
            }
        })

        # Bring up the database
        cintf.set_service('foo', 'db', {})
        assert not deployment.get_resource('my-database')

        # Bring up the database api container
        cintf.set_service('foo', 'db-api', {'env': {'FLYNN_POSTGRES': 'abc'}})
        assert deployment.get_resource('my-database')

    def test_variable_insertion(self, cintf):
        """Test that the database variables are inserted into all of
        the deployment's containers.
        """

        deployment = cintf.create_deployment('foo')
        cintf.set_globals('foo', {
            'Flynn-Postgres': {
                'my-database': {
                    'in': 'db',
                    'via': 'db-api',
                    'expose_as': 'POSTGRES_'
                }
            }
        })
        cintf.get_plugin(FlynnPostgresPlugin).set_db_resource(
            deployment, 'my-database', 'foo', 'bar', 'baz'
        )

        # Deploy a service
        cintf.set_service('foo', 'a-service', {})
        # Have a look at the vars used
        call = cintf.backend.start.mock_calls[0]
        runcfg = call[1][1]
        assert runcfg['env']['POSTGRES_DATABASE'] == 'foo'
