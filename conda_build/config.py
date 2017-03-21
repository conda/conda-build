'''
Module to store conda build settings.
'''
from __future__ import absolute_import, division, print_function

import copy
from collections import namedtuple
import math
import os
from os.path import abspath, expanduser, join
import sys
import time

from .conda_interface import root_dir, root_writable
from .conda_interface import binstar_upload
from .variants import get_default_variants
from .conda_interface import cc_platform, cc_conda_build, subdir

from .utils import get_build_folders, rm_rf, trim_empty_keys, get_logger

on_win = (sys.platform == 'win32')

# Don't "save" an attribute of this module for later, like build_prefix =
# conda_build.config.config.build_prefix, as that won't reflect any mutated
# changes.

conda_build = "conda-build"


def _ensure_dir(path):
    # this can fail in parallel operation, depending on timing.  Just try to make the dir,
    #    but don't bail if fail.
    if not os.path.isdir(path):
        try:
            os.makedirs(path)
        except OSError:
            pass


# we need this to be accessible to the CLI, so it needs to be more static.
DEFAULT_PREFIX_LENGTH = 255

# translate our internal more meaningful subdirs to the ones that conda understands
SUBDIR_ALIASES = {
    'linux-cos5-x86_64': 'linux-64',
    'linux-cos5-x86': 'linux-32',
    'osx-109-x86_64': 'osx-64',
    'win-x86_64': 'win-64',
    'win-x86': 'win-32',
}


Setting = namedtuple("ConfigSetting", "name, default")
DEFAULTS = [Setting('activate', True),
            Setting('anaconda_upload', binstar_upload),
            Setting('channel_urls', []),
            Setting('dirty', False),
            Setting('include_recipe', True),
            Setting('no_download_source', False),
            Setting('override_channels', False),
            Setting('skip_existing', False),
            Setting('token', None),
            Setting('user', None),
            Setting('verbose', True),
            Setting('debug', False),
            Setting('timeout', 90),
            Setting('set_build_id', True),
            Setting('disable_pip', False),
            Setting('output_folder', None),
            Setting('prefix_length_fallback', True),
            Setting('_prefix_length', DEFAULT_PREFIX_LENGTH),
            Setting('long_test_prefix', True),
            Setting('locking', True),
            Setting('max_env_retry', 3),
            Setting('remove_work_dir', True),
            Setting('_host_platform', None),
            Setting('_host_arch', None),
            Setting('has_separate_host_prefix', False),

            Setting('index', None),

            # these are primarily for testing.  They override the native build platform/arch,
            #     which is useful in tests, but makes little sense on actual systems.
            Setting('_platform', None),
            Setting('_arch', None),

            # variants
            Setting('variant_config_files', []),
            Setting('ignore_system_variants', False),
            Setting('hash_length', 7),

            # append/clobber metadata section data (for global usage.  Can also add files to
            #    recipe.)
            Setting('append_sections_file', None),
            Setting('clobber_sections_file', None),
            Setting('bootstrap', None),

            # source provisioning.
            Setting('git_commits_since_tag', 0),

            # pypi upload settings (twine)
            Setting('password', None),
            Setting('sign', False),
            Setting('sign_with', 'gpg'),
            Setting('identity', None),
            Setting('config_file', None),
            Setting('repository', 'pypitest'),

            Setting('ignore_recipe_verify_scripts',
                  cc_conda_build.get('ignore_recipe_verify_scripts', [])),
            Setting('ignore_package_verify_scripts',
                    cc_conda_build.get('ignore_package_verify_scripts', [])),
            Setting('run_recipe_verify_scripts',
                    cc_conda_build.get('run_package_verify_scripts', [])),
            Setting('run_package_verify_scripts',
                    cc_conda_build.get('run_package_verify_scripts', [])),
            ]


class Config(object):
    __file__ = __path__ = __file__
    __package__ = __package__
    __doc__ = __doc__

    def __init__(self, variant=None, **kwargs):
        super(Config, self).__init__()
        # default variant is set in render's distribute_variants
        self.variant = variant or {}
        self.set_keys(**kwargs)

    def _set_attribute_from_kwargs(self, kwargs, attr, default):
        value = kwargs.get(attr, getattr(self, attr) if hasattr(self, attr) else default)
        setattr(self, attr, value)
        if attr in kwargs:
            del kwargs[attr]

    def set_keys(self, **kwargs):
        def env(lang, default):
            version = kwargs.get(lang)
            if not version:
                # Hooray for corner cases.
                if lang == 'python':
                    lang = 'py'
                elif lang == 'numpy':
                    lang = 'npy'
                elif lang == 'r_base':
                    lang = 'r'
                var = 'CONDA_' + lang.upper()
                version = os.getenv(var) if os.getenv(var) else default
            elif isinstance(version, list) and len(version) == 1:
                version = version[0]
            return version

        # this is where we override any variant config files with the legacy CONDA_* vars
        #     or CLI params
        self.variant.update({'perl': env('perl', self.variant.get('perl')),
                             'lua': env('lua', self.variant.get('lua')),
                             'python': env('python', self.variant.get('python')),
                             'numpy': env('numpy', self.variant.get('numpy')),
                             'r_base': env('r_base', self.variant.get('r_base')),
                             })
        trim_empty_keys(self.variant)

        self._build_id = kwargs.get('build_id', getattr(self, '_build_id', ""))
        croot = kwargs.get('croot')
        if croot:
            self._croot = os.path.abspath(os.path.normpath(croot))
        else:
            # set default value (not actually None)
            self._croot = getattr(self, '_croot', None)

        # handle known values better than unknown (allow defaults)
        for value in DEFAULTS:
            self._set_attribute_from_kwargs(kwargs, value.name, value.default)

        # dangle remaining keyword arguments as attributes on this class
        for name, value in kwargs.items():
            setattr(self, name, value)

    @property
    def arch(self):
        """Always the native (build system) arch, except when pretending to be some
        other platform"""
        return self._arch or subdir.split('-')[-1]

    @arch.setter
    def arch(self, value):
        log = get_logger(__name__)
        log.warn("setting build arch.  This is only useful when pretending to be on another "
                 "arch, such as for rendering necessary dependencies on a non-native arch."
                 "  I trust that you know what you're doing.")
        self._arch = str(value)

    @property
    def platform(self):
        """Always the native (build system) OS, except when pretending to be some
        other platform"""
        return self._platform or cc_platform

    @platform.setter
    def platform(self, value):
        log = get_logger(__name__)
        log.warn("setting build platform. This is only useful when "
                "pretending to be on another " "another platform, such as "
                "for rendering necessary dependencies on a non-native "
                "platform. I trust that you know what you're doing.")
        self._platform = value

    @property
    def build_subdir(self):
        """Determines channel to download build env packages from.
        Should generally be the native platform.  Does not preclude packages from noarch."""
        return '-'.join((self.platform, self.arch))

    @property
    def host_arch(self):
        return self._host_arch or self.arch

    @host_arch.setter
    def host_arch(self, value):
        self._host_arch = value

    @property
    def noarch(self):
        return self.host_platform == 'noarch'

    def reset_platform(self):
        if not self.platform == cc_platform:
            self.platform = cc_platform

    @property
    def subdir(self):
        return "-".join([self.platform, str(self.arch)])

    @property
    def host_platform(self):
        return self._host_platform or self.platform

    @host_platform.setter
    def host_platform(self, value):
        self._host_platform = value

    @property
    def host_subdir(self):
        if self.host_platform == 'noarch':
            subdir = self.platform
        else:
            subdir = "-".join([self.host_platform, str(self.host_arch)])
        return SUBDIR_ALIASES.get(subdir, subdir)

    @host_subdir.setter
    def host_subdir(self, value):
        value = SUBDIR_ALIASES.get(value, value)
        values = value.split('-')
        self.host_platform = values[0]
        if len(values) > 1:
            self.host_arch = values[1]

    @property
    def is_cross(self):
        return self.build_subdir != self.host_subdir

    @property
    def croot(self):
        """This is where source caches and work folders live"""
        if not self._croot:
            _bld_root_env = os.getenv('CONDA_BLD_PATH')
            _bld_root_rc = cc_conda_build.get('root-dir')
            if _bld_root_env:
                self._croot = abspath(expanduser(_bld_root_env))
            elif _bld_root_rc:
                self._croot = abspath(expanduser(_bld_root_rc))
            elif root_writable:
                self._croot = join(root_dir, 'conda-bld')
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

    def _get_python(self, prefix):
        if sys.platform == 'win32':
            if os.path.isfile(os.path.join(prefix, 'python_d.exe')):
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
        lua_ver = self.variant.get('lua', get_default_variants()[0]['lua'])
        binary_name = "luajit" if (lua_ver and lua_ver[0] == "2") else "lua"
        if sys.platform == 'win32':
            res = join(prefix, '{}.exe'.format(binary_name))
        else:
            res = join(prefix, 'bin/{}'.format(binary_name))
        return res

    def compute_build_id(self, package_name, reset=False):
        if self.set_build_id and (not self._build_id or reset):
            assert not os.path.isabs(package_name), ("package name should not be a absolute path, "
                                                     "to preserve croot during path joins")
            build_folders = sorted([build_folder for build_folder in get_build_folders(self.croot)
                                if package_name in build_folder])

            if self.dirty and build_folders:
                # Use the most recent build with matching recipe name
                self._build_id = build_folders[-1]
            else:
                # here we uniquely name folders, so that more than one build can happen concurrently
                #    keep 6 decimal places so that prefix < 80 chars
                build_id = package_name + "_" + str(int(time.time() * 1000))
                # important: this is recomputing prefixes and determines where work folders are.
                self._build_id = build_id

    @property
    def build_id(self):
        """This is a per-build (almost) unique id, consisting of the package being built, and the
        time since the epoch, in ms.  It is appended to build and test prefixes, and used to create
        unique work folders for build and test."""
        return self._build_id

    @build_id.setter
    def build_id(self, _build_id):
        _build_id = _build_id.rstrip("/").rstrip("\\")
        assert not os.path.isabs(_build_id), ("build_id should not be an absolute path, "
                                              "to preserve croot during path joins")
        self._build_id = _build_id

    @property
    def prefix_length(self):
        return self._prefix_length

    @prefix_length.setter
    def prefix_length(self, length):
        self._prefix_length = length

    @property
    def _short_host_prefix(self):
        return join(self.build_folder, '_h_env')

    @property
    def _long_host_prefix(self):
        placeholder_length = self.prefix_length - len(self._short_host_prefix)
        placeholder = '_placehold'
        repeats = int(math.ceil(placeholder_length / len(placeholder)) + 1)
        placeholder = (self._short_host_prefix + repeats * placeholder)[:self.prefix_length]
        return max(self._short_host_prefix, placeholder)

    @property
    def build_prefix(self):
        """The temporary folder where the build environment is created.  The build env contains
        libraries that may be linked, but only if the host env is not specified.  It is placed on
        PATH."""
        if self.has_separate_host_prefix:
            prefix = join(self.build_folder, '_build_env')
        else:
            prefix = self.host_prefix
        return prefix

    @property
    def host_prefix(self):
        """The temporary folder where the host environment is created.  The host env contains
        libraries that may be linked.  It is not placed on PATH."""
        if on_win:
            return self._short_host_prefix
        return self._long_host_prefix

    @property
    def _short_test_prefix(self):
        return join(self.build_folder, '_test_env')

    def _long_prefix(self, base_prefix):
        placeholder_length = self.prefix_length - len(base_prefix)
        placeholder = '_placehold'
        repeats = int(math.ceil(placeholder_length / len(placeholder)) + 1)
        placeholder = (base_prefix + repeats * placeholder)[:self.prefix_length]
        return max(base_prefix, placeholder)

    @property
    def test_prefix(self):
        """The temporary folder where the test environment is created"""
        if on_win or not self.long_test_prefix:
            return self._short_test_prefix
        return self._long_prefix(self._short_test_prefix)

    @property
    def build_python(self):
        return self.python_bin(self.build_prefix)

    @property
    def host_python(self):
        return self._get_python(self.host_prefix)

    @property
    def test_python(self):
        return self.python_bin(self.test_prefix)

    def python_bin(self, prefix):
        return self._get_python(prefix)

    def perl_bin(self, prefix):
        return self._get_perl(prefix)

    def lua_bin(self, prefix):
        return self._get_lua(prefix)

    @property
    def info_dir(self):
        """Path to the info dir in the build prefix, where recipe metadata is stored"""
        path = join(self.build_prefix, 'info')
        _ensure_dir(path)
        return path

    @property
    def meta_dir(self):
        """Path to the conda-meta dir in the build prefix, where package index json files are
        stored"""
        path = join(self.host_prefix, 'conda-meta')
        _ensure_dir(path)
        return path

    @property
    def broken_dir(self):
        """Where packages that fail the test phase are placed"""
        path = join(self.croot, "broken")
        _ensure_dir(path)
        return path

    @property
    def bldpkgs_dir(self):
        """ Dir where the package is saved. """
        path = join(self.croot, self.host_subdir)
        _ensure_dir(path)
        return path

    @property
    def bldpkgs_dirs(self):
        """ Dirs where previous build packages might be. """
        # The first two *might* be the same, but might not, depending on if this is a cross-compile.
        #     cc.subdir should be the native platform, while self.subdir would be the host platform.
        return {join(self.croot, self.host_subdir), join(self.croot, subdir),
                join(self.croot, "noarch"), }

    @property
    def src_cache(self):
        """Where tarballs and zip files are downloaded and stored"""
        path = join(self.croot, 'src_cache')
        _ensure_dir(path)
        return path

    @property
    def git_cache(self):
        """Where local clones of git sources are stored"""
        path = join(self.croot, 'git_cache')
        _ensure_dir(path)
        return path

    @property
    def hg_cache(self):
        """Where local clones of hg sources are stored"""
        path = join(self.croot, 'hg_cache')
        _ensure_dir(path)
        return path

    @property
    def svn_cache(self):
        """Where local checkouts of svn sources are stored"""
        path = join(self.croot, 'svn_cache')
        _ensure_dir(path)
        return path

    @property
    def work_dir(self):
        """Where the source for the build is extracted/copied to.  If only a single folder is in
        that folder, this function returns that level one deeper."""
        path = join(self.build_folder, 'work')
        _ensure_dir(path)
        if os.path.isdir(path):
            lst = [fn for fn in os.listdir(path) if not fn.startswith('.')]
            if len(lst) == 1:
                dir_path = join(path, lst[0])
                if os.path.isdir(dir_path):
                    return dir_path
        return path

    @property
    def test_dir(self):
        """The temporary folder where test files are copied to, and where tests start execution"""
        path = join(self.build_folder, 'test_tmp')
        _ensure_dir(path)
        return path

    def clean(self):
        # build folder is the whole burrito containing envs and source folders
        #   It will only exist if we download source, or create a build or test environment
        if self.build_id:
            if os.path.isdir(self.build_folder):
                rm_rf(self.build_folder)
        else:
            for path in [self.work_dir, self.test_dir, self.build_prefix, self.test_prefix]:
                if os.path.isdir(path):
                    rm_rf(path)

    def clean_pkgs(self):
        for folder in self.bldpkgs_dirs:
            rm_rf(folder)

    def copy(self):
        new = copy.copy(self)
        new.variant = copy.deepcopy(self.variant)
        if hasattr(self, 'variants'):
            new.variants = copy.deepcopy(self.variants)
        return new

    # context management - automatic cleanup if self.dirty or self.keep_old_work is not True
    def __enter__(self):
        pass

    def __exit__(self, e_type, e_value, traceback):
        if not getattr(self, 'dirty') and e_type is None:
            get_logger(__name__).info("--dirty flag not specified.  Removing build"
                                      " folder after successful build/test.\n")
            self.clean()


def get_or_merge_config(config, variant=None, **kwargs):
    if not config:
        config = Config(variant=variant)
    if kwargs:
        config.set_keys(**kwargs)
    if variant:
        config.variant.update(variant)
    return config


# legacy exports for conda
croot = Config().croot
