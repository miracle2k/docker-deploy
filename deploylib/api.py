from flask import Flask, Blueprint, g, jsonify, request
from .host import DockerHost


api = Blueprint('api', __name__)

@api.before_request
def before_request():
    g.host = DockerHost()


@api.route('/list')
def list():
    return jsonify(g.host.get_instances())


@api.route('/create', methods=['POST'])
def create():
    {'Domains': {},
     'service': 'foo'
     }
    return jsonify(request.get_json())


@api.route('/update')
def update():
    servicefile = ServiceFile.load(args['<service-file>'])

    if not g.host.get_deployment(deploy_id):
        return {'error':  'no such deployment, create first'}

    for service in servicefile.services:
        self.deploy_service(deploy_id, service, **kwargs)
    self.run_plugins('post_deploy', servicefile)


def init():
    servicefile = ServiceFile.load(path(dirname(__file__), 'Bootstrap'))
    host = Host(args['<host>'])
    namer = lambda s: s.name   # Use literal names so we can find them
    host.deploy_servicefile('_sys_', servicefile, namer=namer)


app = Flask(__name__)
app.debug = True
app.register_blueprint(api)


def run():
    app.run()


if __name__ == '__main__':
    run()