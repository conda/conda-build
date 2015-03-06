from __future__ import absolute_import, division, print_function

import os
import sys
from os.path import join
import subprocess
import multiprocessing

import conda.config as cc

from conda_build.config import config

from conda_build import source


def get_perl_ver():
    return str(config.CONDA_PERL)

def get_py_ver():
    return '.'.join(str(config.CONDA_PY))

def get_npy_ver():
    return '.'.join(str(config.CONDA_NPY))

def get_stdlib_dir():
    return join(config.build_prefix, 'Lib' if sys.platform == 'win32' else
                                'lib/python%s' % get_py_ver())

def get_sp_dir():
    return join(get_stdlib_dir(), 'site-packages')

def get_git_build_info(m, src_dir):
    env = os.environ.copy()
    d = {}
    git_dir = join(src_dir, '.git')
    if os.path.isdir(git_dir):
        env['GIT_DIR'] = git_dir
    else:
        return d

    # grab information from describe
    keys = ["GIT_DESCRIBE_TAG", "GIT_DESCRIBE_NUMBER", "GIT_DESCRIBE_HASH"]
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
    # get the _full_ hash of the current HEAD
    process = subprocess.Popen(["git", "rev-parse", "HEAD"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=env)
    output = process.communicate()[0].strip()
    output = output.decode('utf-8')
    d['GIT_FULL_HASH'] = output
    # set up the build string
    if "GIT_DESCRIBE_NUMBER" in d and "GIT_DESCRIBE_HASH" in d:
        if not m:
            build_id = d["GIT_DESCRIBE_NUMBER"]
        else:
            build_id = m.default_build_id(int(d["GIT_DESCRIBE_NUMBER"]))

        d['GIT_BUILD_STR'] = '{}_{}'.format(d["GIT_DESCRIBE_HASH"],
                                            build_id)

    return d

def get_dict(m=None, prefix=None):
    if not prefix:
        prefix = config.build_prefix

    python = config.build_python
    d = {'CONDA_BUILD': '1', 'PYTHONNOUSERSITE': '1'}
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
    d['NPY_VER'] = get_npy_ver()
    d['SRC_DIR'] = source.get_dir()

    if m:
        for var_name in m.get_value('build/script_env'):
            value = os.getenv(var_name)
            if value is None:
                value = '<UNDEFINED>'
            d[var_name] = value

    try:
        d['CPU_COUNT'] = str(multiprocessing.cpu_count())
    except NotImplementedError:
        d['CPU_COUNT'] = "1"

    d.update(**get_git_build_info(m, d['SRC_DIR']))

    if sys.platform == 'win32':         # -------- Windows
        d['PATH'] = (join(prefix, 'Library', 'bin') + ';' +
                     join(prefix) + ';' +
                     join(prefix, 'Scripts') + ';%PATH%')
        d['SCRIPTS'] = join(prefix, 'Scripts')
        d['LIBRARY_PREFIX'] = join(prefix, 'Library')
        d['LIBRARY_BIN'] = join(d['LIBRARY_PREFIX'], 'bin')
        d['LIBRARY_INC'] = join(d['LIBRARY_PREFIX'], 'include')
        d['LIBRARY_LIB'] = join(d['LIBRARY_PREFIX'], 'lib')
        # This probably should be done more generally
        d['CYGWIN_PREFIX'] = prefix.replace('\\', '/').replace('C:', '/cygdrive/c')

        d['R'] = join(prefix, 'Scripts', 'R.exe')
    else:                               # -------- Unix
        d['PATH'] = '%s/bin:%s' % (prefix, os.getenv('PATH'))
        d['HOME'] = os.getenv('HOME', 'UNKNOWN')
        d['PKG_CONFIG_PATH'] = join(prefix, 'lib', 'pkgconfig')
        d['INCLUDE_PATH'] = join(prefix, 'include')
        d['LIBRARY_PATH'] = join(prefix, 'lib')

        d['R'] = join(prefix, 'bin', 'R')

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
