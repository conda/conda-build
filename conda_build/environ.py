from __future__ import print_function, division, absolute_import

import os
import sys
from os.path import join

import conda.config as cc

from conda_build.config import (CONDA_PERL, CONDA_PY, PY3K, build_prefix,
                                _get_python)
from conda_build import source

perl_ver =  str(CONDA_PERL)
py_ver = '.'.join(str(CONDA_PY))
stdlib_dir = join(build_prefix, 'Lib' if sys.platform == 'win32' else
                                'lib/python%s' % py_ver)
sp_dir = join(stdlib_dir, 'site-packages')


def get_dict(m=None, prefix=build_prefix):
    stdlib_dir = join(prefix, 'Lib' if sys.platform == 'win32' else
        'lib/python%s' % py_ver)
    sp_dir = join(stdlib_dir, 'site-packages')
    python = _get_python(prefix)
    d = {'CONDA_BUILD': '1'}
    d['ARCH'] = str(cc.bits)
    d['PREFIX'] = prefix
    d['PYTHON'] = python
    d['PY3K'] = str(PY3K)
    d['STDLIB_DIR'] = stdlib_dir
    d['SP_DIR'] = sp_dir
    d['SYS_PREFIX'] = sys.prefix
    d['SYS_PYTHON'] = sys.executable
    d['PY_VER'] = py_ver
    d['PERL_VER'] = perl_ver
    d['SRC_DIR'] = source.get_dir()

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
