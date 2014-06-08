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

    def job(self, name):
        self.queue.put({'job': name})

    def log(self, msg):
        self.queue.put({'log': msg})

    def error(self, msg):
        self.queue.put({'error': msg})

    def fatal(self, msg):
        self.error(msg)
        self.done()

    def done(self):
        self.queue.put(StopIteration)
