'''
Created on Jan 16, 2014

@author: sean
'''
from __future__ import absolute_import, division, print_function

import json
import os

from conda.compat import PY3
from .environ import get_dict as get_environ
from subprocess import check_output, CalledProcessError

_setuptools_data = None

def load_setuptools(setup_file='setup.py'):
    global _setuptools_data

    if _setuptools_data is None:
        _setuptools_data = {}
        def setup(**kw):
            _setuptools_data.update(kw)

        import setuptools
        # Add current directory to path
        import sys
        sys.path.append('.')

        # Patch setuptools
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

def get_git_build_info(src_dir):
    env = os.environ.copy()
#     env['GIT_DIR'] = os.path.join(src_dir, '.git')

    d = {}
    # grab information from describe
    key_name = lambda a: "GIT_DESCRIBE_{}".format(a)
    keys = [key_name("TAG"), key_name("NUMBER"), key_name("HASH")]
    env = {str(key): str(value) for key, value in env.items()}

    try:
        output = check_output(["git", "describe", "--tags", "--long", "HEAD"], env=env, cwd=src_dir)
    except CalledProcessError:
        return None

    output = output.strip()
    output = output.decode('utf-8')
    parts = output.rsplit('-', 2)
    parts_length = len(parts)
    if parts_length == 3:
        d.update(dict(zip(keys, parts)))
    # get the _full_ hash of the current HEAD
    try:
        output = check_output(["git", "rev-parse", "HEAD"], env=env, cwd=src_dir)
    except CalledProcessError:
        return d

    output = output.strip()
    output = output.decode('utf-8')
    d['GIT_FULL_HASH'] = output
    # set up the build string
    if key_name('NUMBER') in d and key_name('HASH') in d:
        d['GIT_BUILD_STR'] = '{}_{}'.format(d[key_name('NUMBER')],
                                            d[key_name('HASH')])

    return d

def git_describe_tag(src_dir=None, default=None):

    if src_dir is None:
        ctx = get_environ()
        src_dir = ctx['SRC_DIR']

    git_info = get_git_build_info(src_dir)
    if git_info is None and default is None:
        raise Exception("The git tag could not be gotten!")

    tag = git_info.get('GIT_DESCRIBE_TAG', None)

    if tag is None:
        raise Exception("The git tag could not be gotten!")
    return tag

def context_processor(meta_path):
    ctx = get_environ()
    ctx['RECIPE_DIR'] = os.path.dirname(meta_path)
    environ = dict(os.environ)
    environ.update(get_environ())

    ctx.update(load_setuptools=load_setuptools,
               load_npm=load_npm,
               environ=environ,
               git_describe_tag=git_describe_tag)
    return ctx
