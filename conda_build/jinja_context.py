'''
Created on Jan 16, 2014

@author: sean
'''
from __future__ import absolute_import, division, print_function

import json
import os

from conda.compat import PY3
from .environ import get_dict as get_environ

_setuptools_data = None

def load_setuptools(setup_file='setup.py'):
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
        exec(open(setup_file).read())
        setuptools.setup = setuptools_setup
        del sys.path[-1]
    return _setuptools_data

def load_npm():
    # json module expects bytes in Python 2 and str in Python 3.
    mode_dict = {'mode': 'r', 'encoding': 'utf-8'} if PY3 else {'mode': 'rb'}
    with open('package.json', **mode_dict) as pkg:
        return json.load(pkg)

def context_processor(initial_metadata=None):
    """
    Return a dictionary to use as context for jinja templates.

    initial_metadata: Augment the context with values from this MetaData object.
                      Used to bootstrap metadata contents via multiple parsing passes.
    """
    ctx = get_environ(m=initial_metadata)
    environ = dict(os.environ)
    environ.update(get_environ(m=initial_metadata))

    ctx.update(load_setuptools=load_setuptools,
               load_npm=load_npm,
               environ=environ)
    return ctx
