import contextlib
import os

import yaml
import yaml.constructor

try:
    # included in standard lib from Python 2.7
    from collections import OrderedDict
except ImportError:
    # try importing the backported drop-in replacement
    # it's available on PyPI
    from ordereddict import OrderedDict


@contextlib.contextmanager
def directory(path):
    old = os.getcwd()
    os.chdir(path)
    yield
    os.chdir(old)
