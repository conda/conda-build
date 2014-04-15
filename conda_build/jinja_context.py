'''
Created on Jan 16, 2014

@author: sean
'''
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import json
import os
from io import open

from conda.compat import PY3
from conda_build import environ
from .environ import get_dict as get_environ

_setuptools_data = None

def load_setuptools():
    global _setuptools_data

    if _setuptools_data is None:
        _setuptools_data = {}
        def setup(**kw):
            _setuptools_data.update(kw)

        import setuptools
        #Add current directory to path
        import sys
        sys.path.append('.')

        #Patch setuptools
        setuptools_setup = setuptools.setup
        setuptools.setup = setup
        exec(open('setup.py', encoding='utf-8').read())
        setuptools.setup = setuptools_setup
        del sys.path[-1]
    return _setuptools_data

def load_npm():
    # json module expects bytes in Python 2 and str in Python 3.
    mode_dict = {'mode': 'r', 'encoding': 'utf-8'} if PY3 else {'mode': 'rb'}
    with open('package.json', **mode_dict) as pkg:
        return json.load(pkg)

def context_processor():
    ctx = environ.get_dict()
    environ = dict(os.environ)
    environ.update(get_environ())

    ctx.update(load_setuptools=load_setuptools,
               load_npm=load_npm,
               environ=environ)
    return ctx
