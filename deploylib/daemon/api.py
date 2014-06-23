from functools import wraps
import functools
import json
import traceback
from flask import Flask, Blueprint, g, jsonify, request, Response, \
    stream_with_context, current_app, _app_ctx_stack, _request_ctx_stack
import transaction
import gevent
import gevent.queue
import gevent.monkey
from .context import Context, set_context, ctx
from deploylib.plugins import load_plugins


api = Blueprint('api', __name__)


@api.before_app_request
def check_auth():
    if request.routing_exception:
        return

    view = current_app.view_functions[request.endpoint]
    is_public = getattr(view, 'is_public', False)
    if is_public:
        return

    if not g.cintf.db.auth_key:
        return

    if request.headers.get('Authorization') == g.cintf.db.auth_key:
        return

    return Response(json.dumps({'error': 'authorization failed.'}),
                    content_type='application/xml', status=401)


class StreamingResponse(Context, Response):

    mimetype = 'text/json'

    def __init__(self, controller, *a, **kw):
        Context.__init__(self, controller)

        kw['mimetype'] = self.mimetype
        def generator():
            for item in self.queue:
                for i in self.item(item):
                    yield i
        Response.__init__(self, stream_with_context(generator()), *a, **kw)

    def item(self, item):
        yield json.dumps(item)
        yield "\n"


class TextStreamingResponse(StreamingResponse):
    mimetype = 'text/plain'

    def item(self, item):
        if 'job' in item:
            yield '-----> %s\n' % item['job']
        elif 'log' in item:
            yield '%s\n' % item['log']
        elif 'error' in item:
            yield 'Error: %s\n' % item['error']
        else:
            yield json.dumps(item) + '\n'


def streaming(response_class=StreamingResponse):
    """Decorator to make a view streaming.

    If greenlets were native in Python we could probably have one stream
    content to the response they way we want to, like we'd do in Go.
    Since they are not, WSGI has been spec'ed to use a generator - and I
    can't think of a way to have an arbitrary call tree write to the Flask
    or WSGI response generator; tulip/asyncio fits into this  model nicely,
    as it essentially generatorizes everything.

    I don't see an alternative to running the background process in a
    separate greenlet; which would not be a big deal, if it where not for
    the fact that both Flask and our own code relies on context locals,
    and those would not be available in this second greenlet.

    As a workaround, we pass the current request and current app as
    parameters to the decorated-view function. A new controller instance
    we create ourselves.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            from deploylib.daemon.controller import DeployError

            ctx = response_class(None)

            request = _request_ctx_stack.top.request
            app = _app_ctx_stack.top.app
            def worker(controller):
                # ZODB requirement: We need to create a new connection
                # for a new thread
                ctx.cintf = controller.interface()
                set_context(ctx)

                try:
                    try:
                        func(request, app, *args, **kwargs)
                        transaction.commit()
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
                finally:
                    ctx.cintf.close()

            gevent.spawn(worker, g.controller)
            return ctx
        return wrapped
    return decorator


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
    for dname, d in g.cintf.db.deployments.items():
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
        g.cintf.create_deployment(data['deploy_id'])
    except ValueError, e:
        return jsonify({'error': str(e)})
    else:
        return jsonify({'job': 'Created deployment %s' % data['deploy_id']})


@api.route('/setup', methods=['POST'])
@streaming()
def setup_services(request, app):
    """This API does the following at once:

    - Replace the global data of the deployment.
    - Set (add or replace) one or more services within the deployment.
    """

    data = request.get_json()
    deploy_id = data['deploy_id']
    services = data['services']
    globals = data['globals']
    force = data['force']

    if not deploy_id in ctx.cintf.db.deployments:
        ctx.fatal('no such deployment, create first')
        return

    # First, write the new version of the global environment. If it has
    # changed, we need to recreate all services.
    globals_changed = ctx.cintf.set_globals(deploy_id, globals)

    # Deploy the actual services.
    for name, service in services.items():
        ctx.cintf.set_service(deploy_id, name, service,
                         force=globals_changed or force)


@api.route('/upload', methods=['POST'])
@streaming()
def upload(request, app):
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

    ctx.cintf.provide_data(deploy_id, service_name, request.files, data)


def create_app(controller):
    app = Flask(__name__)
    app.debug = True

    @app.before_request
    def before_request():
        g.controller = controller
        g.cintf = controller.interface()

    @app.teardown_request
    def after_request(exception):
        if exception:
            transaction.abort()
        else:
            transaction.commit()
        g.cintf.close()


    # Register the API
    app.register_blueprint(api)

    # Let plugins contribute blueprints
    for blueprint in load_plugins(Blueprint):
        app.register_blueprint(blueprint, url_prefix='/%s' % blueprint.name)

    return app



