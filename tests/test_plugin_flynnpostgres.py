import json


class TestFlynnPostgres(object):

    def test_db_creation(self, host, responses):
        """Test that the plugin runs after both the pg and the pg-api
        containers have been installed for the first time.
        """
        # Mock flynn-postgres-api container
        responses.add(responses.POST, 'http://abc/databases',
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
        assert not deployment.data['flynn-postgres']

        # Bring up the database api container
        host.set_service('foo', 'db-api', {'env': {'FLYNN_POSTGRES': 'abc'}})
        assert 'my-database' in deployment.data['flynn-postgres']

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
        deployment.data['flynn-postgres'] = {'my-database': {
            'dbname': 'foo', 'user': 'bar', 'password': 'baz'
        }}

        # Deploy a service
        host.set_service('foo', 'a-service', {})
        # Have a look at the vars used
        call = host.backend.create.mock_calls[0]
        runcfg = call[1][0]
        assert runcfg['env']['POSTGRES_DATABASE'] == 'foo'
