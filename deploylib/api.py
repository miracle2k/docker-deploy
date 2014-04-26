import os
from flask import Flask, Blueprint, g, jsonify, request
from .host import DockerHost


api = Blueprint('api', __name__)


@api.before_request
def before_request():
    g.host = DockerHost(
        docker_url='tcp://localhost:4243', #os.environ.get('DOCKER_HOST', None),
        volumes_dir=os.environ.get('DEPLOY_DATA', '/srv/vdata'),
        db_dir=os.environ.get('DEPLOY_STATE', '/srv/vstate')

    )

@api.after_request
def after_request(response):
    g.host.state.close()
    return response


@api.route('/list')
def list():
    """List all deployments.
    """
    return jsonify(g.host.get_deployments())


@api.route('/create', methods=['POST'])
def create():
    """Create a new deployment.
    """
    data = request.get_json()
    try:
        g.host.create_deployment(data['deploy_id'])
    except ValueError, e:
        return jsonify({'error': str(e)})
    else:
        return jsonify({'ok': True})


@api.route('/setup', methods=['POST'])
def setup_services():
    """Add or replace services in a deployment.
    """
    data = request.get_json()
    deploy_id = data['deploy_id']
    services = data['services']

    if not deploy_id in g.host.get_deployments():
        return jsonify({'error':  'no such deployment, create first'})

    for service in services:
        g.host.deployment_setup_service(deploy_id, service)
    return jsonify({'ok': True})


#def init():
#    servicefile = ServiceFile.load(path(dirname(__file__), 'Bootstrap'))
#    host = Host(args['<host>'])
#    namer = lambda s: s.name   # Use literal names so we can find them
#    host.deploy_servicefile('_sys_', servicefile, namer=namer)


app = Flask(__name__)
app.debug = True
app.register_blueprint(api)


def run():
    app.run()


if __name__ == '__main__':
    run()
