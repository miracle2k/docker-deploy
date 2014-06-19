import json
from deploylib.daemon.api import create_app


class TestApi(object):

    def test_streaming(self, controller):
        app = create_app(controller)

        with app.test_client() as c:
            rep = c.post('/setup', content_type="application/json", data=json.dumps({
                'deploy_id': 1,
                'services': [],
                'globals': {},
                'force': False,
            }))

            assert 'error' in json.loads(rep.get_data().splitlines()[0])

