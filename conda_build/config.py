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

    def __init__(self, *args, **kwargs):
        super(Config, self).__init__()

        self.CONDA_PERL = kwargs.get('perl', os.getenv('CONDA_PERL', '5.18.2'))
        self.CONDA_LUA = kwargs.get('lua', os.getenv('CONDA_LUA', '5.2'))
        self.CONDA_PY = int(kwargs.get('python', os.getenv('CONDA_PY', cc.default_python))
                            .replace('.', ''))
        self.CONDA_NPY = kwargs.get('numpy', os.getenv("CONDA_NPY", None))
        if self.CONDA_NPY:
            self.CONDA_NPY = int(self.CONDA_NPY.replace('.', '')) or None
        self.CONDA_R = kwargs.get('r', os.getenv("CONDA_R", "3.2.2"))

        self._build_id = kwargs.get('build_id', "")
        self._prefix_length = kwargs.get("prefix_length", 80)
        # set default value (not actually None)
        self._croot = kwargs.get('croot', None)

        # Default to short prefixes
        self.use_long_build_prefix = kwargs.get("use_long_build_prefix", False)

        self.activate = kwargs.get('activate', True)
        self.anaconda_upload = kwargs.get('anaconda_upload', cc.binstar_upload)
        self.channel_urls = kwargs.get("channel_urls", ())
        self.dirty = kwargs.get('dirty', False)
        self.include_recipe = kwargs.get('include_recipe', True)
        self.keep_old_work = kwargs.get('keep_old_work', False)
        self.noarch = kwargs.get("noarch", False)
        self.no_download_source = kwargs.get('no_download_source', False)
        self.override_channels = kwargs.get("override_channels", False)
        self.skip_existing = kwargs.get("skip_existing", False)
        self.token = kwargs.get('token', None)
        self.user = kwargs.get('user', None)
        self.verbose = kwargs.get("verbose", True)

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
    def build_folder(self):
        """This is the core folder for a given build.
        It has the environments and work directories."""
        return os.path.join(self.croot, self.build_id)

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
    def prefix_length(self):
        return self._prefix_length

    @prefix_length.setter
    def prefix_length(self, length):
        self._prefix_length = length

    @property
    def build_prefix(self):
        stub = join(self.build_folder, '_build_env')
        placeholder_length = self.prefix_length - len(stub)
        placeholder = '_placehold'
        repeats = int(math.ceil(placeholder_length / len(placeholder)) + 1)
        placeholder = (stub + repeats * placeholder)[:self.prefix_length]
        return max(stub, placeholder)

    @property
    def test_prefix(self):
        """The temporary folder where the test environment is created"""
        return join(self.build_folder, '_test_env')

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
        return join(self.croot, 'src_cache')

    @property
    def git_cache(self):
        return join(self.croot, 'git_cache')

    @property
    def hg_cache(self):
        return join(self.croot, 'hg_cache')

    @property
    def svn_cache(self):
        return join(self.croot, 'svn_cache')

    @property
    def work_dir(self):
        return join(self.build_folder, 'work')

    @property
    def test_dir(self):
        """The temporary folder where test files are copied to, and where tests start execution"""
        return join(self.build_folder, 'test_tmp')


def show(config):
    print('CONDA_PY:', config.CONDA_PY)
    print('CONDA_NPY:', config.CONDA_NPY)
    print('subdir:', cc.subdir)
    print('croot:', config.croot)
    print('build packages directory:', config.bldpkgs_dir)


if __name__ == '__main__':
    show(Config())
