'''
Module to store conda build settings.
'''
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import os
import sys
from os.path import abspath, expanduser, join

import conda.config as cc

# Don't "save" an attribute of this module for later, like build_prefix =
# conda_build.config.config.build_prefix, as that won't reflect any mutated
# changes.

class Config(object):
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

    short_build_prefix = join(cc.envs_dirs[0], '_build')
    long_build_prefix = (short_build_prefix + 8 * '_placehold')[:80]
    # XXX: Make this None to be more rigorous about requiring the build_prefix
    # to be known before it is used.
    use_long_build_prefix = False
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
    def build_prefix(self):
        if self.use_long_build_prefix is None:
            raise Exception("I don't know which build prefix to use yet")
        if self.use_long_build_prefix:
            return self.long_build_prefix
        return self.short_build_prefix

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

    @property
    def info_dir(self):
        return join(self.build_prefix, 'info')

    @property
    def broken_dir(self):
        return join(self.croot, "broken")

    bldpkgs_dir = join(croot, cc.subdir)


def import_name_from_module(import_name):
    def parse_import_name(import_name):
        # Can be any callable qualified Python name (class or function).
        assert '.' in import_name
        ix = import_name.rfind('.')
        modulename, callname = import_name[:ix], import_name[ix+1:]
        return modulename, callname
    import importlib
    modulename, callname = parse_import_name(import_name)
    module = importlib.import_module(modulename)
    return getattr(module, callname)


verify_rpaths = True
ignore_link_errors = cc.rc.get('ignore_link_errors', False)
use_new_rpath_logic = bool(cc.rc.get('use_new_rpath_logic', True))
link_errors_handler_name = cc.rc.get('link_errors_handler', 'conda_build.link.LinkErrorHandler')
link_errors_handler = import_name_from_module(link_errors_handler_name)

config = Config()

croot = config.croot


def show():
    print('CONDA_PY:', config.CONDA_PY)
    print('CONDA_NPY:', config.CONDA_NPY)
    print('subdir:', cc.subdir)
    print('croot:', croot)
    print('build packages directory:', config.bldpkgs_dir)


if __name__ == '__main__':
    show()
