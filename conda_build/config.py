'''
Module to store conda build settings.
'''
from __future__ import absolute_import, division, print_function

import math
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

    def __init__(self, *args, **kw):
        super(Config, self).__init__(*args, **kw)

        self.noarch = False

        self.CONDA_PERL = os.getenv('CONDA_PERL', '5.18.2')
        self.CONDA_LUA = os.getenv('CONDA_LUA', '5.2')
        self.CONDA_PY = int(os.getenv('CONDA_PY', cc.default_python.replace('.',
            '')).replace('.', ''))
        self.CONDA_NPY = os.getenv("CONDA_NPY")
        if not self.CONDA_NPY:
            self.CONDA_NPY = None
        else:
            self.CONDA_NPY = int(self.CONDA_NPY.replace('.', '')) or None
        self.CONDA_R = os.getenv("CONDA_R", "3.2.2")

        self._build_id = ""
        self._prefix_length = 80
        # set default value (not actually None)
        self._croot = None

        # Default to short prefixes
        self.use_long_build_prefix = False

    @property
    def croot(self):
        """This is where source caches and work folders live"""
        if not self._croot:
            _bld_root_env = os.getenv('CONDA_BLD_PATH')
            _bld_root_rc = cc.rc.get('conda-build', {}).get('root-dir')
            if _bld_root_env:
                self._croot = abspath(expanduser(_bld_root_env))
            elif _bld_root_rc:
                self._croot = abspath(expanduser(_bld_root_rc))
            elif cc.root_writable:
                self._croot = join(cc.root_dir, 'conda-bld')
            else:
                self._croot = abspath(expanduser('~/conda-bld'))
        return self._croot

    @croot.setter
    def croot(self, croot):
        """Set croot - if None is passed, then the default value will be used"""
        self._croot = croot


    @property
    def PY3K(self):
        return int(bool(self.CONDA_PY >= 30))

    @property
    def use_MSVC2015(self):
        """Returns whether python version is above 3.4

        (3.5 is compiler switch to MSVC 2015)"""
        return bool(self.CONDA_PY >= 35)

    def get_conda_py(self):
        return self.CONDA_PY

    def _get_python(self, prefix):
        if sys.platform == 'win32':
            import conda.install
            packages = conda.install.linked(prefix)
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
    def build_id(self):
        """This is a per-build (almost) unique id, consisting of the package being built, and the
        time since the epoch, in ms.  It is appended to build and test prefixes, and used to create
        unique work folders for build and test."""
        return self._build_id

    @build_id.setter
    def build_id(self, _build_id):
        self._build_id = _build_id

    @property
    def _build_id_suffix(self):
        return '_' + self.build_id if self.build_id else ""

    @property
    def prefix_length(self):
        return self._prefix_length

    @prefix_length.setter
    def prefix_length(self, length):
        self._prefix_length = length

    @property
    def _short_build_prefix(self):
        return join(self.croot, '_build' + self._build_id_suffix)

    @property
    def _long_build_prefix(self):
        placeholder_length = self.prefix_length
        if self._build_id_suffix:
            placeholder_length -= (len(self._build_id_suffix) + 1)  # + 1 is for '_'
        placeholder = '_placehold'
        repeats = int(math.ceil(self.prefix_length / len(placeholder)) + 1)
        placeholder = (self.short_build_prefix + repeats * placeholder)[:placeholder_length]
        return max(self.short_build_prefix, placeholder) + self._build_id_suffix

    @property
    def build_prefix(self):
        return self._long_build_prefix if self.use_long_build_prefix else self._short_build_prefix

    @property
    def test_prefix(self):
        """The temporary folder where the test environment is created"""
        return join(self.croot, '_test' + self._build_id_suffix)

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

    @property
    def src_cache(self):
        return join(config.croot, 'src_cache')

    @property
    def git_cache(self):
        return join(config.croot, 'git_cache')

    @property
    def hg_cache(self):
        return join(config.croot, 'hg_cache')

    @property
    def svn_cache(self):
        join(config.croot, 'svn_cache')

    @property
    def work_dir(self):
        return join(self.croot, 'work' + self._build_id_suffix)

    @property
    def test_dir(self):
        """The temporary folder where test files are copied to, and where tests start execution"""
        return join(self.croot, 'test' + self._build_id_suffix)


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
