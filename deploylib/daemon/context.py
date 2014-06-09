import gevent.queue


from werkzeug.local import Local
local = Local()
ctx = local('ctx')

def set_context(ctx):
    local.ctx = ctx


class Context(object):

    def __init__(self):
        self.queue = gevent.queue.Queue()

    def custom(self, **obj):
        self.queue.put(obj)
        gevent.sleep(0)

    def job(self, name):
        self.custom(job=name)

    def log(self, msg):
        self.custom(log=msg)

    def error(self, msg):
        self.custom(error=msg)

    def fatal(self, msg):
        self.error(msg)
        self.done()

    def done(self):
        self.queue.put(StopIteration)
