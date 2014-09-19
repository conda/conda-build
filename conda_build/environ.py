from __future__ import absolute_import, division, print_function

import os
import sys
from os.path import join
import subprocess

import conda.config as cc

from conda_build.config import config

from conda_build import source


def get_perl_ver():
    return str(config.CONDA_PERL)

def get_py_ver():
    return '.'.join(str(config.CONDA_PY))

def get_stdlib_dir():
    return join(config.build_prefix, 'Lib' if sys.platform == 'win32' else
                                'lib/python%s' % get_py_ver())

def get_sp_dir():
    return join(get_stdlib_dir(), 'site-packages')

def get_git_build_info(src_dir):
    env = os.environ.copy()
    env['GIT_DIR'] = join(src_dir, '.git')

    d = {}
    key_name = lambda a: "GIT_DESCRIBE_{}".format(a)
    keys = [key_name("TAG"), key_name("NUMBER"), key_name("HASH")]
    env = {str(key): str(value) for key, value in env.items()}
    process = subprocess.Popen(["git", "describe", "--tags", "--long", "HEAD"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=env)
    output = process.communicate()[0].strip()
    output = output.decode('utf-8')
    parts = output.rsplit('-', 2)
    parts_length = len(parts)
    if parts_length == 3:
        d.update(dict(zip(keys, parts)))

    if key_name('NUMBER') in d and key_name('HASH') in d:
        d['GIT_BUILD_STR'] = '{}_{}'.format(d[key_name('NUMBER')],
                                            d[key_name('HASH')])

    return d

def get_hg_build_info(src_dir):
    env = os.environ.copy()
    env['HG_DIR'] = join(src_dir, '.hg')
    env = {str(key): str(value) for key, value in env.items()}
    
    d = {}
    cmd = ["hg", "log", "--template",
           "{rev}|{node|short}|{latesttag}|{latesttagdistance}|{branch}",
           "--rev", "."]
    process = subprocess.Popen(cmd,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=env,
                               cwd=src_dir)
    output = process.communicate()[0].strip()
    output = output.decode('utf-8')
    rev, short_id, tag, distance, branch = output.split('|')
    if tag != 'null':
        d['HG_LATEST_TAG'] = tag
    if branch == "":
        branch = 'default'
    d['HG_BRANCH'] = branch
    d['HG_NUM_ID'] = rev
    d['HG_LATEST_TAG_DISTANCE'] = distance
    d['HG_SHORT_ID'] = short_id
    d['HG_BUILD_STR'] = '{}_{}'.format(d['HG_NUM_ID'], d['HG_SHORT_ID'])
    return d

def get_dict(m=None, prefix=None):
    if not prefix:
        prefix = config.build_prefix

    python = config.build_python
    d = {'CONDA_BUILD': '1'}
    d['ARCH'] = str(cc.bits)
    d['PREFIX'] = prefix
    d['PYTHON'] = python
    d['PY3K'] = str(config.PY3K)
    d['STDLIB_DIR'] = get_stdlib_dir()
    d['SP_DIR'] = get_sp_dir()
    d['SYS_PREFIX'] = sys.prefix
    d['SYS_PYTHON'] = sys.executable
    d['PERL_VER'] = get_perl_ver()
    d['PY_VER'] = get_py_ver()
    d['SRC_DIR'] = source.get_dir()
    if "LANG" in os.environ:
        d['LANG'] = os.environ['LANG']

    if os.path.isdir(os.path.join(d['SRC_DIR'], '.git')):
        d.update(**get_git_build_info(d['SRC_DIR']))

    if os.path.isdir(os.path.join(d['SRC_DIR'], '.hg')):
        d.update(**get_hg_build_info(d['SRC_DIR']))


    if sys.platform == 'win32':         # -------- Windows
        d['PATH'] = (join(prefix, 'Library', 'bin') + ';' +
                     join(prefix) + ';' +
                     join(prefix, 'Scripts') + ';' + os.getenv('PATH'))
        d['SCRIPTS'] = join(prefix, 'Scripts')
        d['LIBRARY_PREFIX'] = join(prefix, 'Library')
        d['LIBRARY_BIN'] = join(d['LIBRARY_PREFIX'], 'bin')
        d['LIBRARY_INC'] = join(d['LIBRARY_PREFIX'], 'include')
        d['LIBRARY_LIB'] = join(d['LIBRARY_PREFIX'], 'lib')

    else:                               # -------- Unix
        d['PATH'] = '%s/bin:%s' % (prefix, os.getenv('PATH'))
        d['HOME'] = os.getenv('HOME', 'UNKNOWN')
        d['PKG_CONFIG_PATH'] = join(prefix, 'lib', 'pkgconfig')

    if sys.platform == 'darwin':         # -------- OSX
        d['OSX_ARCH'] = 'i386' if cc.bits == 32 else 'x86_64'
        d['CFLAGS'] = '-arch %(OSX_ARCH)s' % d
        d['CXXFLAGS'] = d['CFLAGS']
        d['LDFLAGS'] = d['CFLAGS']
        d['MACOSX_DEPLOYMENT_TARGET'] = '10.5'

    elif sys.platform.startswith('linux'):      # -------- Linux
        d['LD_RUN_PATH'] = prefix + '/lib'

    if m:
        d['PKG_NAME'] = m.name()
        d['PKG_VERSION'] = m.version()
        d['PKG_BUILDNUM'] = str(m.build_number())
        d['RECIPE_DIR'] = m.path

    return d


if __name__ == '__main__':
    e = get_dict()
    for k in sorted(e):
        assert isinstance(e[k], str), k
        print('%s=%s' % (k, e[k]))
