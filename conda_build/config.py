'''
Module to store conda build settings.
'''
from __future__ import absolute_import, division, print_function

import os
import sys
from os.path import abspath, expanduser, join

from .conda_interface import cc

on_win = (sys.platform == 'win32')

# Don't "save" an attribute of this module for later, like build_prefix =
# conda_build.config.config.build_prefix, as that won't reflect any mutated
# changes.


class Config(object):
    __file__ = __path__ = __file__
    __package__ = __package__
    __doc__ = __doc__

    CONDA_PERL = os.getenv('CONDA_PERL', '5.18.2')
    CONDA_LUA = os.getenv('CONDA_LUA', '5.2')
    CONDA_PY = int(os.getenv('CONDA_PY', cc.default_python.replace('.',
        '')).replace('.', ''))
    CONDA_NPY = os.getenv("CONDA_NPY")
    if not CONDA_NPY:
        CONDA_NPY = None
    else:
        CONDA_NPY = int(CONDA_NPY.replace('.', '')) or None
    CONDA_R = os.getenv("CONDA_R", "3.2.2")

    @property
    def PY3K(self):
        return int(bool(self.CONDA_PY >= 30))

    @property
    def use_MSVC2015(self):
        """Returns whether python version is above 3.4

        (3.5 is compiler switch to MSVC 2015)"""
        return bool(self.CONDA_PY >= 35)

    noarch = False

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

    prefix_length = 255

    short_build_prefix = join(cc.envs_dirs[0], '_build')

    # XXX: Make this None to be more rigorous about requiring the build_prefix
    # to be known before it is used.
    use_long_build_prefix = False
    test_prefix = join(cc.envs_dirs[0], '_test')

    def _get_python(self, prefix):
        if sys.platform == 'win32':
            from .conda_interface import linked
            packages = linked(prefix)
            packages_names = (pkg.split('-')[0] for pkg in packages)
            if 'debug' in packages_names:
                res = join(prefix, 'python_d.exe')
            else:
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

    def _get_lua(self, prefix):
        binary_name = "luajit" if "2" == self.CONDA_LUA[0] else "lua"
        if sys.platform == 'win32':
            res = join(prefix, '{}.exe'.format(binary_name))
        else:
            res = join(prefix, 'bin/{}'.format(binary_name))
        return res

    @property
    def long_build_prefix(self):
        return max(self.short_build_prefix,
                            (self.short_build_prefix +
                             int(self.prefix_length / 10) * '_placehold')[:self.prefix_length])

    @property
    def build_prefix(self):
        if on_win:
            return self.short_build_prefix
        return self.long_build_prefix

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
    def build_lua(self):
        return self._get_lua(self.build_prefix)

    @property
    def test_lua(self):
        return self._get_lua(self.test_prefix)

    @property
    def info_dir(self):
        return join(self.build_prefix, 'info')

    @property
    def meta_dir(self):
        return join(self.build_prefix, 'conda-meta')

    @property
    def broken_dir(self):
        return join(self.croot, "broken")

    @property
    def bldpkgs_dir(self):
        """ Dir where the package is saved. """
        if self.noarch:
            return join(self.croot, "noarch")
        else:
            return join(self.croot, cc.subdir)

    @property
    def bldpkgs_dirs(self):
        """ Dirs where previous build packages might be. """
        return join(self.croot, cc.subdir), join(self.croot, "noarch")

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
