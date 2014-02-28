'''
Created on Jan 16, 2014

@author: sean
'''
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import json
import os
import sys
from io import open

from conda_build import environ

_setuptools_data = None

def load_setuptools():
    global _setuptools_data

    if _setuptools_data is None:
        _setuptools_data = {}
        def setup(**kw):
            _setuptools_data.update(kw)

        import setuptools
        #Patch setuptools
        setuptools_setup = setuptools.setup
        setuptools.setup = setup
        exec(open('setup.py', encoding='utf-8').read())
        setuptools.setup = setuptools_setup

    return _setuptools_data

def load_npm():
    # json module expects bytes in Python 2 and str in Python 3.
    if sys.version_info >= (3, 0):
        file_mode = 'w'
    else:
        file_mode = 'wb'
    with open('package.json', file_mode, encoding='utf-8') as pkg:
        return json.load(pkg)

def context_processor():
    ctx = environ.get_dict()
    ctx.update(load_setuptools=load_setuptools,
               load_npm=load_npm,
               environ=os.environ)
    return ctx
