import sys
if 'threading' in sys.modules:
        raise Exception('threading module loaded before patching!')
import gevent.monkey
gevent.monkey.patch_all()
