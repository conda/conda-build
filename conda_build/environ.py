from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import os
import sys
from os.path import join

import conda.config as cc

from conda_build.config import (CONDA_PERL, CONDA_PY, PY3K, build_prefix,
                                _get_python)
from conda_build import source


# Python 2.x backward compatibility
if sys.version_info < (3, 0):
    str = unicode


PERL_VER =  str(CONDA_PERL)
PY_VER = '.'.join(str(CONDA_PY))
STDLIB_DIR = join(build_prefix, 'Lib' if sys.platform == 'win32' else
                                'lib/python%s' % PY_VER)
SP_DIR = join(STDLIB_DIR, 'site-packages')


def get_dict(m=None, prefix=build_prefix):
    python = _get_python(prefix)
    d = {'CONDA_BUILD': '1'}
    d['ARCH'] = str(cc.bits)
    d['PREFIX'] = prefix
    d['PYTHON'] = python
    d['PY3K'] = str(PY3K)
    d['STDLIB_DIR'] = STDLIB_DIR
    d['SP_DIR'] = SP_DIR
    d['SYS_PREFIX'] = sys.prefix
    d['SYS_PYTHON'] = sys.executable
    d['PERL_VER'] = PERL_VER
    d['PY_VER'] = PY_VER
    d['SRC_DIR'] = source.get_dir()
    if "LANG" in os.environ:
        d['LANG'] = os.environ['LANG']

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
