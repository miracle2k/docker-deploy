import json
import os
from os.path import join as path, dirname
from flask import Flask, Blueprint, g, jsonify, request
import sys
from deploylib.client.service import ServiceFile
from deploylib.plugins.app import DataMissing
from .host import DockerHost, Service


api = Blueprint('api', __name__)


def connect():
    return DockerHost(
        docker_url='tcp://localhost:4243', #os.environ.get('DOCKER_HOST', None),
        volumes_dir=os.environ.get('DEPLOY_DATA', '/srv/vdata'),
        db_dir=os.environ.get('DEPLOY_STATE', '/srv/vstate')
    )


@api.before_request
def before_request():
    g.host = connect()

@api.after_request
def after_request(response):
    g.host.state.close()
    return response


@api.route('/list')
def list():
    """List all deployments.
    """
    return jsonify(g.host.get_deployments())


@api.route('/create', methods=['PUT'])
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

    warnings = []
    for name, service in services.items():
        try:
            g.host.deployment_setup_service(deploy_id, Service(name, service))
        except DataMissing, e:
            warnings.append({
                'type': 'data-missing',
                'tag': e.tag,
                'service_name': name
            })

    return jsonify({'ok': True, 'warnings': warnings})


@api.route('/upload', methods=['POST'])
def upload():
    """Provide a binary file; usually an app that is supposed to be
    deployed.

    Provide multiple files via multipart-form encoding.

    You also need to provide an "info" key which has to contain a JSON
    object with the following data (the indirection is necessary because
    of limitations of the encoding):

        deploy_id
        service_name
        data = {fileid: {}}
    """

    deploy_id = request.values['deploy_id']
    service = request.values['service_name']
    data = json.loads(request.values.get('data', {}))

    g.host.run_plugins('on_data_provided', deploy_id, service, request.files, data)
    return jsonify({'ok': True})


def init_host():
    """
    Initialize the host. Will make sure core services such as etcd
    and discoverd are running as they should.
    """
    servicefile = ServiceFile.load(path(dirname(__file__), 'Bootstrap'), ordered=True)

    def namer(service):
        # Give the bootstrap services simple accessible names, without
        # attaching ids, deployment id etc. "etcd" vs "sys-etcd-fe438e".
        return service.name
    for name, service in servicefile.services.items():
        g.host.deployment_setup_service(
            '', Service(name, service), namer=namer, force=True)


app = Flask(__name__)
app.debug = True
app.register_blueprint(api)


def run():
    if sys.argv[1:2] == ['init']:
        with app.app_context():
            g.host = g.host = connect()
            g.host.create_deployment('', fail=False)
            init_host()
        return
    app.run()


if __name__ == '__main__':
    run()
