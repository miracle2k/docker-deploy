from functools import wraps
import json
import os
from os.path import join as path, dirname
import traceback
from flask import Flask, Blueprint, g, jsonify, request, Response, \
    stream_with_context
import transaction
import gevent
import gevent.queue
import gevent.monkey
from .context import Context, set_context, ctx
from deploylib.plugins import load_plugins
from .host import DockerHost, DeployError


api = Blueprint('api', __name__)


def connect():
    return DockerHost(
        docker_url=os.environ.get('DOCKER_HOST', None),
        volumes_dir=os.environ.get('DEPLOY_DATA', '/srv/vdata'),
        db_dir=os.environ.get('DEPLOY_STATE', '/srv/vstate')
    )


@api.before_app_request
def before_request():
    g.host = connect()

@api.teardown_app_request
def after_request(exception):
    print("request done runs now...")
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


class StreamingResponse(Context, Response):

    def __init__(self, *a, **kw):
        Context.__init__(self)

        kw['mimetype'] = 'text/json'
        def generator():
            for item in self.queue:
                yield json.dumps(item)
                yield "\n"
        Response.__init__(self, stream_with_context(generator()), *a, **kw)


def process_in_greenlet(worker, *args, **kwargs):
    """Helper for streaming responses and background operations.

    Runs the worker in a greenlet, after setting our context object that
    will write to the response.

    You need to pass Flask context locals via arguments, because they
    won't resolve in the greenlet.
    """
    ctx = StreamingResponse()
    def wrapped():
        set_context(ctx)
        try:
            worker(*args, **kwargs)
        except DeployError, e:
            traceback.print_exc()
            ctx.fatal('%s' % e)
            transaction.commit()
        except Exception, e:
            traceback.print_exc()
            # Unexpected error cause a transaction rollback
            ctx.fatal('%s' % e)
            transaction.abort()
        else:
            ctx.done()
    gevent.spawn(wrapped)
    return ctx


def json_method(f):
    """Decorator for a flask view that will expand all json keys
    to keyword arguments.
    """
    @wraps(f)
    def decorated_function():
        kwargs = request.json
        if kwargs is None:
            kwargs = {}
        try:
            return jsonify(f(**kwargs))
        except TypeError, e:
            return jsonify({'error': '%s' % e})
    return decorated_function


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
        return jsonify({'job': 'Created deployment %s' % data['deploy_id']})


@api.route('/setup', methods=['POST'])
def setup_services():
    """This API does the following at once:

    - Replace the global data of the deployment.
    - Set (add or replace) one or more services within the deployment.
    """

    data = request.get_json()
    deploy_id = data['deploy_id']
    services = data['services']
    globals = data['globals']
    force = data['force']

    def worker(host):
        if not deploy_id in host.db.deployments:
            ctx.fatal('no such deployment, create first')
            return

        # First, write the new version of the global environment. If it has
        # changed, we need to recreate all services.
        globals_changed = host.set_globals(deploy_id, globals)

        # Deploy the actual services.
        for name, service in services.items():
            host.set_service(deploy_id, name, service,
                             force=globals_changed or force)

    return process_in_greenlet(worker, g.host)


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
    service_name = request.values['service_name']
    data = json.loads(request.values.get('data', {}))

    def worker(host, files):
        host.provide_data(deploy_id, service_name, files, data)

    return process_in_greenlet(worker, g.host, request.files)


app = Flask(__name__)
app.debug = True
app.register_blueprint(api)

# Let plugins contribute blueprints
for blueprint in load_plugins(Blueprint):
    app.register_blueprint(blueprint, url_prefix='/%s' % blueprint.name)


def run():
    """
    usage:
    ./api.py init <auth-key>
    ./api.py [<bind>]
    """
    gevent.monkey.patch_all()

    import docopt
    result = docopt.docopt(run.__doc__)
    if result['init']:
        auth_key = result['<auth-key>']
        with app.app_context():
            g.host = connect()
            g.host.db.auth_key = auth_key
            set_context(Context())
            g.host.create_deployment('system', fail=False)
            g.host.run_plugins('on_system_init')
            transaction.commit()
        return

    bind_opt = (result['<bind>'] or '0.0.0.0:5555').split(':', 1)
    if len(bind_opt) == 1:
        host = bind_opt[0]
        port = 5555
    else:
        host, port = bind_opt

    # from gevent.wsgi import WSGIServer
    # server = WSGIServer((host, int(port)), app)
    # server.serve_forever()
    app.run(host, int(port), use_reloader=os.environ.get('RELOADER') == '1')


if __name__ == '__main__':
    run()
