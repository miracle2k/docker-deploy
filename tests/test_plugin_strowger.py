import json
import pytest
from deploylib.plugins.strowger import StrowgerPlugin


controller_plugins = [StrowgerPlugin]


@pytest.fixture(autouse=True)
def strowger_api(responses):
    responses.add(
        responses.PUT, 'http://strowger-api/routes', body=json.dumps({}))


class TestStrowger(object):

    def test_strowger_service_not_setup(self, cintf, responses):
        # If the strowger router has not yet been setup, do nothing
        cintf.create_deployment('foo')
        cintf.set_globals('foo', {
            'Domains': {
                'foo.org': {
                    'http': 'service-name'
                }
            }})

        assert not responses.calls

    def test_no_service_specified(self, cintf, responses):
        """We only act if a domain contains certain keys like
        referencing the service to link to.
        """
        cintf.set_service('system', 'strowger', {})

        cintf.create_deployment('foo')
        cintf.set_globals('foo', {
            'Domains': {
                'foo.org': {
                    'registrar': 'godaddy'
                }
            }})
        assert not responses.calls

    def test_http_service(self, cintf, responses):
        """Registering a HTTP domain with strowger."""
        cintf.set_service('system', 'strowger', {})

        cintf.create_deployment('foo')
        cintf.set_globals('foo', {
            'Domains': {
                'foo.org': {
                    'http': 'service-name'
                }
            }})

        assert json.loads(responses.calls[0][0].body)\
            ['config']['domain'] == 'foo.org'

    def test_register_with_auth(self, cintf, responses):
        """Registering a HTTP domain with strowger, with
        auth-protection enabled.
        """
        cintf.set_service('system', 'strowger', {})

        cintf.create_deployment('foo')
        cintf.set_globals('foo', {
            'Domains': {
                'foo.org': {
                    'http': 'service-name',
                    'auth': {'user': 'pw'}
                }
            }})

        result = json.loads(responses.calls[0][0].body)
        print(result)
        assert result['config']['domain'] == 'foo.org'
        assert result['config']['auth_type'] == 'digest'
        assert result['config']['http_auth'] == \
            {u'user': u'0554c44c150f03f1d9f21be67902a067'}

    def test_ignore_empty_domains(self, cintf, responses):
        """[Regression]  Do not fail on empty domains."""
        cintf.set_service('system', 'strowger', {})

        cintf.create_deployment('foo')
        cintf.set_globals('foo', {
            'Domains': {
                'foo.org': None
            }})

        assert not responses.calls
