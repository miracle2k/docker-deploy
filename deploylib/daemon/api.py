import json
import os
from os.path import join as path, dirname
from flask import Flask, Blueprint, g, jsonify, request
import transaction
from deploylib.client.service import ServiceFile
from deploylib.plugins import DataMissing
from .host import DockerHost, Service, DeployError


api = Blueprint('api', __name__)


def connect():
    return DockerHost(
        docker_url=os.environ.get('DOCKER_HOST', None),
        volumes_dir=os.environ.get('DEPLOY_DATA', '/srv/vdata'),
        db_dir=os.environ.get('DEPLOY_STATE', '/srv/vstate')
    )


@api.before_request
def before_request():
    g.host = connect()

@api.teardown_request
def after_request(exception):
    if exception:
        transaction.abort()
    else:
        transaction.commit()
    g.host.close()


@api.before_request
def check_auth():
    is_public = getattr(app.view_functions[request.endpoint], 'is_public', False)
    if is_public:
        return

    if not g.host.db.auth_key:
        return

    if request.headers.get('Authorization') == g.host.db.auth_key:
        return

    return jsonify({'error': 'authorization failed.'})


@api.route('/list')
def list():
    """List all deployments.
    """
    out = {}
    for dname, d in g.host.db.deployments.items():
        out.setdefault(dname, {})
        for sname, s in d.services.items():
            out[dname].setdefault(sname, {'versions': None, 'instances': []})
            for i in s.instances:
                out[dname][sname]['instances'].append(i.container_id)
            out[dname][sname]['versions'] = len(s.versions)

    return jsonify(out)


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
    globals = data['globals']
    force = data['force']

    if not deploy_id in g.host.db.deployments:
        return jsonify({'error':  'no such deployment, create first'})

    deployment = g.host.db.deployments.get(deploy_id)
    globals_changed = deployment.globals != globals
    deployment.globals = globals

    try:
        # Before-deploy steps
        sort_first = g.host.run_plugins('before_deploy', deploy_id, globals, services)

        # Sometimes certain one-time initialization steps require a service
        # to be started before others.
        sorted_services = services.items()
        def sorter(item):
            if not item[0] in sort_first:
                return -1
            return len(sort_first) - sort_first.index(item[0])
        if sort_first:
            sorted_services.sort(key=sorter, reverse=True)

        warnings = []
        for name, service in sorted_services:
            try:
                g.host.deployment_setup_service(
                    deploy_id, Service(name, service), force=globals_changed or force)
            except DataMissing, e:
                warnings.append({
                    'type': 'data-missing',
                    'tag': e.tag,
                    'service_name': name
                })

        # After-deploy steps
        g.host.run_plugins('post_deploy', services, globals)

    except DeployError as e:
        return jsonify({'error': '%s' % e})

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
    """
    usage:
    ./api.py init <auth-key>
    ./api.py [<bind>]
    """
    import docopt
    result = docopt.docopt(run.__doc__)
    if result['init']:
        auth_key = result['<auth-key>']
        with app.app_context():
            g.host = connect()
            g.host.db.auth_key = auth_key
            g.host.create_deployment('', fail=False)
            init_host()
        return

    bind_opt = (result['<bind>'] or '0.0.0.0:5555').split(':', 1)
    if len(bind_opt) == 1:
        host = bind_opt[0]
        port = 5555
    else:
        host, port = bind_opt
    app.run(host, int(port), use_reloader=os.environ.get('RELOADER') == '1')


if __name__ == '__main__':
    run()
