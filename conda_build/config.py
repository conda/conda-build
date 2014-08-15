'''
Module to store conda build settings.
'''

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import os
import sys
from os.path import abspath, expanduser, join

import conda.config as cc

# We fake a module here so that we can mutate things and have them propagate
# (we can't have @property methods on a module object), while still keeping
# backwards compatibility with the API. Don't import things from this module
# directly using from conda_build.config import CONDA_PY. Rather, access
# conda_build.config.CONDA_PY, etc.

module = type(os)

class Config(module):
    __file__ = __path__ = __file__
    __package__ = __package__
    __doc__ = __doc__

    CONDA_PERL = os.getenv('CONDA_PERL', '5.18.2')
    CONDA_PY = int(os.getenv('CONDA_PY', cc.default_python.replace('.',
        '')).replace('.', ''))
    CONDA_NPY = int(os.getenv('CONDA_NPY', '18').replace('.', ''))

    PY3K = int(bool(CONDA_PY >= 30))

    def get_conda_py(self):
        return self.CONDA_PY

    _bld_root_env = os.getenv('CONDA_BLD_PATH')
    _bld_root_rc = cc.rc.get('conda-build', {}).get('root-dir')
    if _bld_root_env:
        croot = abspath(expanduser(_bld_root_env))
    elif _bld_root_rc:
        croot = abspath(expanduser(_bld_root_rc))
    elif cc.root_writable:
        croot = join(cc.root_dir, 'conda-bld')
    else:
        croot = abspath(expanduser('~/conda-bld'))

    build_prefix = join(cc.envs_dirs[0], '_build'+'_')
    test_prefix = join(cc.envs_dirs[0], '_test')

    def _get_python(self, prefix):
        if sys.platform == 'win32':
            res = join(prefix, 'python.exe')
        else:
            res = join(prefix, 'bin/python')
        return res

    def _get_perl(self, prefix):
        if sys.platform == 'win32':
            res = join(prefix, 'perl.exe')
        else:
            res = join(prefix, 'bin/perl')
        return res

    @property
    def build_python(self):
        return self._get_python(self.build_prefix)

    @property
    def test_python(self):
        return self._get_python(self.test_prefix)

    @property
    def build_perl(self):
        return self._get_perl(self.build_prefix)

    @property
    def test_perl(self):
        return self._get_perl(self.test_prefix)

    bldpkgs_dir = join(croot, cc.subdir)

m = Config('conda_build.config')
sys.modules['conda_build.config'] = m

def show():
    import conda.config as cc

    print('CONDA_PY:', m.CONDA_PY)
    print('CONDA_NPY:', m.CONDA_NPY)
    print('subdir:', cc.subdir)
    print('croot:', m.croot)
    print('build packages directory:', m.bldpkgs_dir)


if __name__ == '__main__':
    show()
