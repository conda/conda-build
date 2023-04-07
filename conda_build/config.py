# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
Module to store conda build settings.
"""

import copy
import math
import os
import re
import shutil
import sys
import time
import warnings
from collections import namedtuple
from os.path import abspath, expanduser, expandvars, join

from .conda_interface import (
    binstar_upload,
    cc_conda_build,
    cc_platform,
    root_dir,
    root_writable,
    subdir,
    url_path,
)
from .utils import get_build_folders, get_conda_operation_locks, get_logger, rm_rf
from .variants import get_default_variant

on_win = sys.platform == "win32"
invocation_time = ""


def set_invocation_time():
    global invocation_time
    invocation_time = str(int(time.time() * 1000))


set_invocation_time()


# Don't "save" an attribute of this module for later, like build_prefix =
# conda_build.config.config.build_prefix, as that won't reflect any mutated
# changes.

conda_build = "conda-build"

filename_hashing_default = "true"
_src_cache_root_default = None
error_overlinking_default = "false"
error_overdepending_default = "false"
noarch_python_build_age_default = 0
enable_static_default = "true"
no_rewrite_stdout_env_default = "false"
ignore_verify_codes_default = []
exit_on_verify_error_default = False
conda_pkg_format_default = None
zstd_compression_level_default = 19


def python2_fs_encode(strin):
    warnings.warn(
        "`conda_build.config.python2_fs_encode` is pending deprecation and will be removed in a future release.",
        PendingDeprecationWarning,
    )
    return strin


def _ensure_dir(path: os.PathLike):
    """Try to ensure a directory exists

    Args:
        path (os.PathLike): Path to directory
    """
    # this can fail in parallel operation, depending on timing.  Just try to make the dir,
    #    but don't bail if fail.
    warnings.warn(
        "`conda_build.config._ensure_dir` is pending deprecation and will be removed "
        "in a future release. Please use `pathlib.Path.mkdir(exist_ok=True)` or "
        "`os.makedirs(exist_ok=True)` instead",
        PendingDeprecationWarning,
    )
    os.makedirs(path, exist_ok=True)


# we need this to be accessible to the CLI, so it needs to be more static.
DEFAULT_PREFIX_LENGTH = 255

# translate our internal more meaningful subdirs to the ones that conda understands
SUBDIR_ALIASES = {
    "linux-cos5-x86_64": "linux-64",
    "linux-cos6-x86_64": "linux-64",
    "linux-cos5-x86": "linux-32",
    "linux-cos6-x86": "linux-32",
    "osx-109-x86_64": "osx-64",
    "win-x86_64": "win-64",
    "win-x86": "win-32",
}


Setting = namedtuple("ConfigSetting", "name, default")


def _get_default_settings():
    return [
        Setting("activate", True),
        Setting("anaconda_upload", binstar_upload),
        Setting("force_upload", True),
        Setting("channel_urls", []),
        Setting("dirty", False),
        Setting("include_recipe", True),
        Setting("no_download_source", False),
        Setting("override_channels", False),
        Setting("skip_existing", False),
        Setting("token", None),
        Setting("user", None),
        Setting("labels", []),
        Setting("verbose", True),
        Setting("debug", False),
        Setting("timeout", 900),
        Setting("set_build_id", True),
        Setting("disable_pip", False),
        Setting("_output_folder", None),
        Setting("prefix_length_fallback", True),
        Setting("_prefix_length", DEFAULT_PREFIX_LENGTH),
        Setting("long_test_prefix", True),
        Setting("locking", True),
        Setting("max_env_retry", 3),
        Setting("remove_work_dir", True),
        Setting("_host_platform", None),
        Setting("_host_arch", None),
        Setting("test_run_post", False),
        Setting(
            "filename_hashing",
            cc_conda_build.get("filename_hashing", filename_hashing_default).lower()
            == "true",
        ),
        Setting("keep_old_work", False),
        Setting(
            "_src_cache_root",
            abspath(expanduser(expandvars(cc_conda_build.get("cache_dir"))))
            if cc_conda_build.get("cache_dir")
            else _src_cache_root_default,
        ),
        Setting("copy_test_source_files", True),
        # should rendering cut out any skipped metadata?
        Setting("trim_skip", True),
        # Use channeldata.json for run_export information during rendering.
        # Falls back to downloading packages if False or channeldata does
        # not exist for the channel.
        Setting("use_channeldata", False),
        # Disable the overlinking test for this package. This test checks that transitive DSOs
        # are not referenced by DSOs in the package being built. When this happens something
        # has gone wrong with:
        # 1. Linker flags not being passed, or not working correctly:
        #    (GNU ld: -as-needed, Apple ld64: -dead_strip_dylibs -no_implicit_dylibs)
        # 2. A missing package in reqs/run (maybe that package is missing run_exports?)
        # 3. A missing (or broken) CDT package in reqs/build or (on systems without CDTs)
        # 4. .. a missing value in the hard-coded but metadata-augmentable library whitelist
        # It is important that packages do not suffer from 2 because uninstalling that missing
        # package leads to an inability to run this package.
        #
        # default to not erroring with overlinking for now.  We have specified in
        #    cli/main_build.py that this default will switch in conda-build 4.0.
        Setting(
            "error_overlinking",
            cc_conda_build.get("error_overlinking", error_overlinking_default).lower()
            == "true",
        ),
        Setting(
            "error_overdepending",
            cc_conda_build.get(
                "error_overdepending", error_overdepending_default
            ).lower()
            == "true",
        ),
        Setting(
            "noarch_python_build_age",
            cc_conda_build.get(
                "noarch_python_build_age", noarch_python_build_age_default
            ),
        ),
        Setting(
            "enable_static",
            cc_conda_build.get("enable_static", enable_static_default).lower()
            == "true",
        ),
        Setting(
            "no_rewrite_stdout_env",
            cc_conda_build.get(
                "no_rewrite_stdout_env", no_rewrite_stdout_env_default
            ).lower()
            == "true",
        ),
        Setting("index", None),
        # support legacy recipes where only build is specified and expected to be the
        #    folder that packaging is done on
        Setting("build_is_host", False),
        # these are primarily for testing.  They override the native build platform/arch,
        #     which is useful in tests, but makes little sense on actual systems.
        Setting("_platform", None),
        Setting("_arch", None),
        Setting("_target_subdir", None),
        # variants
        Setting("variant_config_files", []),
        # these files preclude usage of any system-wide or cwd config files.
        #    Config files in recipes are still respected, and they override this file.
        Setting("exclusive_config_files", []),
        Setting("ignore_system_variants", False),
        Setting("hash_length", 7),
        # append/clobber metadata section data (for global usage.  Can also add files to
        #    recipe.)
        Setting("append_sections_file", None),
        Setting("clobber_sections_file", None),
        Setting("bootstrap", None),
        Setting("extra_meta", {}),
        # source provisioning.
        Setting("git_commits_since_tag", 0),
        # pypi upload settings (twine)
        Setting("password", None),
        Setting("sign", False),
        Setting("sign_with", "gpg"),
        Setting("identity", None),
        Setting("config_file", None),
        Setting("repository", "pypitest"),
        Setting("verify", True),
        Setting(
            "ignore_verify_codes",
            cc_conda_build.get("ignore_verify_codes", ignore_verify_codes_default),
        ),
        Setting(
            "exit_on_verify_error",
            cc_conda_build.get("exit_on_verify_error", exit_on_verify_error_default),
        ),
        # Recipes that have no host section, only build, should bypass the build/host line.
        # This is to make older recipes still work with cross-compiling.  True cross-compiling
        # involving compilers (not just python) will still require recipe modification to have
        # distinct host and build sections, but simple python stuff should work without.
        Setting("merge_build_host", False),
        # this one is the state that can be set elsewhere, which affects how
        #    the "build_prefix" works.  The one above is a setting.
        Setting("_merge_build_host", False),
        # path to output build statistics to
        Setting("stats_file", None),
        # extra deps to add to test env creation
        Setting("extra_deps", []),
        # customize this so pip doesn't look in places we don't want.  Per-build path by default.
        Setting("_pip_cache_dir", None),
        Setting(
            "zstd_compression_level",
            cc_conda_build.get(
                "zstd_compression_level", zstd_compression_level_default
            ),
        ),
        # this can be set to different values (currently only 2 means anything) to use package formats
        Setting(
            "conda_pkg_format",
            cc_conda_build.get("pkg_format", conda_pkg_format_default),
        ),
        Setting("suppress_variables", False),
        Setting("build_id_pat", cc_conda_build.get("build_id_pat", "{n}_{t}")),
    ]


def print_function_deprecation_warning(func):
    def func_wrapper(*args, **kw):
        log = get_logger(__name__)
        log.warn(
            "WARNING: attribute {} is deprecated and will be removed in conda-build 4.0.  "
            "Please update your code - file issues on the conda-build issue tracker "
            "if you need help.".format(func.__name__)
        )
        return func(*args, **kw)

    return func_wrapper


class Config:
    __file__ = __path__ = __file__
    __package__ = __package__
    __doc__ = __doc__

    def __init__(self, variant=None, **kwargs):
        super().__init__()
        # default variant is set in render's distribute_variants
        self.variant = variant or {}
        self.set_keys(**kwargs)
        if self._src_cache_root:
            self._src_cache_root = os.path.expanduser(self._src_cache_root)

    def _set_attribute_from_kwargs(self, kwargs, attr, default):
        value = kwargs.get(
            attr, getattr(self, attr) if hasattr(self, attr) else default
        )
        setattr(self, attr, value)
        if attr in kwargs:
            del kwargs[attr]

    def set_keys(self, **kwargs):
        def env(lang, default):
            version = kwargs.pop(lang, None)
            if not version:
                # Hooray for corner cases.
                if lang == "python":
                    lang = "py"
                elif lang == "numpy":
                    lang = "npy"
                elif lang == "r_base":
                    lang = "r"
                var = "CONDA_" + lang.upper()
                version = os.getenv(var) if os.getenv(var) else default
            elif isinstance(version, list) and len(version) == 1:
                version = version[0]
            return version

        def set_lang(variant, lang):
            value = env(lang, self.variant.get(lang))
            if value:
                if "." not in str(value):
                    value = ".".join((value[0], value[1:]))
                variant[lang] = value

        # this is where we override any variant config files with the legacy CONDA_* vars
        #     or CLI params
        for lang in ("perl", "lua", "python", "numpy", "r_base"):
            set_lang(self.variant, lang)

        self._build_id = kwargs.pop("build_id", getattr(self, "_build_id", ""))
        source_cache = kwargs.pop("cache_dir", None)
        croot = kwargs.pop("croot", None)

        if source_cache:
            self._src_cache_root = os.path.abspath(
                os.path.normpath(os.path.expanduser(source_cache))
            )
        if croot:
            self._croot = os.path.abspath(os.path.normpath(os.path.expanduser(croot)))
        else:
            # set default value (not actually None)
            self._croot = getattr(self, "_croot", None)

        # handle known values better than unknown (allow defaults)
        for value in _get_default_settings():
            self._set_attribute_from_kwargs(kwargs, value.name, value.default)

        # dangle remaining keyword arguments as attributes on this class
        for name, value in kwargs.items():
            setattr(self, name, value)

    @property
    def arch(self):
        """Always the native (build system) arch, except when pretending to be some
        other platform"""
        return self._arch or subdir.rsplit("-", 1)[1]

    @arch.setter
    def arch(self, value):
        log = get_logger(__name__)
        log.warn(
            "Setting build arch. This is only useful when pretending to be on another "
            "arch, such as for rendering necessary dependencies on a non-native arch. "
            "I trust that you know what you're doing."
        )
        self._arch = str(value)

    @property
    def platform(self):
        """Always the native (build system) OS, except when pretending to be some
        other platform"""
        return self._platform or subdir.rsplit("-", 1)[0]

    @platform.setter
    def platform(self, value):
        log = get_logger(__name__)
        log.warn(
            "Setting build platform. This is only useful when "
            "pretending to be on another platform, such as "
            "for rendering necessary dependencies on a non-native "
            "platform. I trust that you know what you're doing."
        )
        if value == "noarch":
            raise ValueError(
                "config platform should never be noarch.  Set host_platform instead."
            )
        self._platform = value

    @property
    def build_subdir(self):
        """Determines channel to download build env packages from.
        Should generally be the native platform.  Does not preclude packages from noarch.
        """
        return "-".join((self.platform, self.arch))

    @property
    def host_arch(self):
        try:
            variant_arch = self.variant.get("target_platform", self.build_subdir).split(
                "-", 1
            )[1]
        except IndexError:
            variant_arch = 64
        return self._host_arch or variant_arch

    @host_arch.setter
    def host_arch(self, value):
        self._host_arch = value

    @property
    def noarch(self):
        return self.host_platform == "noarch"

    def reset_platform(self):
        if not self.platform == cc_platform:
            self.platform = cc_platform

    @property
    def subdir(self):
        return "-".join([self.platform, str(self.arch)])

    @property
    def host_platform(self):
        return (
            self._host_platform
            or self.variant.get("target_platform", self.build_subdir).split("-", 1)[0]
        )

    @host_platform.setter
    def host_platform(self, value):
        self._host_platform = value

    @property
    def host_subdir(self):
        subdir = self.variant.get("target_platform", self.build_subdir)
        if self.host_platform == "noarch":
            subdir = self.host_platform
        elif subdir != "-".join([self.host_platform, str(self.host_arch)]):
            subdir = "-".join([self.host_platform, str(self.host_arch)])
        return SUBDIR_ALIASES.get(subdir, subdir)

    @host_subdir.setter
    def host_subdir(self, value):
        value = SUBDIR_ALIASES.get(value, value)
        values = value.rsplit("-", 1)
        self.host_platform = values[0]
        if len(values) > 1:
            self.host_arch = values[1]

    @property
    def target_subdir(self):
        return self._target_subdir or self.host_subdir

    @target_subdir.setter
    def target_subdir(self, value):
        self._target_subdir = value

    @property
    def exclusive_config_file(self):
        if self.exclusive_config_files:
            return self.exclusive_config_files[0]
        return None

    @exclusive_config_file.setter
    def exclusive_config_file(self, value):
        if len(self.exclusive_config_files) > 1:
            raise ValueError(
                "Cannot set singular exclusive_config_file "
                "if multiple exclusive_config_files are present."
            )
        if value is None:
            self.exclusive_config_files = []
        else:
            self.exclusive_config_files = [value]

    @property
    def src_cache_root(self):
        return self._src_cache_root if self._src_cache_root else self.croot

    @src_cache_root.setter
    def src_cache_root(self, value):
        self._src_cache_root = value

    @property
    def croot(self):
        """This is where source caches and work folders live"""
        if not self._croot:
            _bld_root_env = os.getenv("CONDA_BLD_PATH")
            _bld_root_rc = cc_conda_build.get("root-dir")
            if _bld_root_env:
                self._croot = abspath(expanduser(_bld_root_env))
            elif _bld_root_rc:
                self._croot = abspath(expanduser(expandvars(_bld_root_rc)))
            elif root_writable:
                self._croot = join(root_dir, "conda-bld")
            else:
                self._croot = abspath(expanduser("~/conda-bld"))
        return self._croot

    @croot.setter
    def croot(self, croot):
        """Set croot - if None is passed, then the default value will be used"""
        self._croot = croot

    @property
    def output_folder(self):
        return self._output_folder or self.croot

    @output_folder.setter
    def output_folder(self, value):
        self._output_folder = value

    @property
    def build_folder(self):
        """This is the core folder for a given build.
        It has the environments and work directories."""
        return os.path.join(self.croot, self.build_id)

    # back compat for conda-build-all - expects CONDA_* vars to be attributes of the config object
    @property
    @print_function_deprecation_warning
    def CONDA_LUA(self):
        return self.variant.get("lua", get_default_variant(self)["lua"])

    @CONDA_LUA.setter
    @print_function_deprecation_warning
    def CONDA_LUA(self, value):
        self.variant["lua"] = value

    @property
    @print_function_deprecation_warning
    def CONDA_PY(self):
        value = self.variant.get("python", get_default_variant(self)["python"])
        return int("".join(value.split(".")))

    @CONDA_PY.setter
    @print_function_deprecation_warning
    def CONDA_PY(self, value):
        value = str(value)
        self.variant["python"] = ".".join((value[0], value[1:]))

    @property
    @print_function_deprecation_warning
    def CONDA_NPY(self):
        value = self.variant.get("numpy", get_default_variant(self)["numpy"])
        return int("".join(value.split(".")))

    @CONDA_NPY.setter
    @print_function_deprecation_warning
    def CONDA_NPY(self, value):
        value = str(value)
        self.variant["numpy"] = ".".join((value[0], value[1:]))

    @property
    @print_function_deprecation_warning
    def CONDA_PERL(self):
        return self.variant.get("perl", get_default_variant(self)["perl"])

    @CONDA_PERL.setter
    @print_function_deprecation_warning
    def CONDA_PERL(self, value):
        self.variant["perl"] = value

    @property
    @print_function_deprecation_warning
    def CONDA_R(self):
        return self.variant.get("r_base", get_default_variant(self)["r_base"])

    @CONDA_R.setter
    @print_function_deprecation_warning
    def CONDA_R(self, value):
        self.variant["r_base"] = value

    def _get_python(self, prefix, platform):
        if platform.startswith("win") or (
            platform == "noarch" and sys.platform == "win32"
        ):
            if os.path.isfile(os.path.join(prefix, "python_d.exe")):
                res = join(prefix, "python_d.exe")
            else:
                res = join(prefix, "python.exe")
        else:
            res = join(prefix, "bin/python")
        return res

    def _get_perl(self, prefix, platform):
        if platform.startswith("win"):
            res = join(prefix, "Library", "bin", "perl.exe")
        else:
            res = join(prefix, "bin/perl")
        return res

    # TODO: This is probably broken on Windows, but no one has a lua package on windows to test.
    def _get_lua(self, prefix, platform):
        lua_ver = self.variant.get("lua", get_default_variant(self)["lua"])
        binary_name = "luajit" if (lua_ver and lua_ver[0] == "2") else "lua"
        if platform.startswith("win"):
            res = join(prefix, "Library", "bin", f"{binary_name}.exe")
        else:
            res = join(prefix, f"bin/{binary_name}")
        return res

    def _get_r(self, prefix, platform):
        if platform.startswith("win") or (
            platform == "noarch" and sys.platform == "win32"
        ):
            res = join(prefix, "Scripts", "R.exe")
            # MRO test:
            if not os.path.exists(res):
                res = join(prefix, "bin", "R.exe")
        else:
            res = join(prefix, "bin", "R")
        return res

    def _get_rscript(self, prefix, platform):
        if platform.startswith("win"):
            res = join(prefix, "Scripts", "Rscript.exe")
            # MRO test:
            if not os.path.exists(res):
                res = join(prefix, "bin", "Rscript.exe")
        else:
            res = join(prefix, "bin", "Rscript")
        return res

    def compute_build_id(self, package_name, package_version="0", reset=False):
        time_re = r"([_-])([0-9]{13})"
        pat_dict = {"n": package_name, "v": str(package_version), "t": "{t}"}
        # Use the most recent build with matching recipe name, or else the recipe name.
        build_folders = []
        if not self.dirty:
            if reset:
                set_invocation_time()
        else:
            old_build_id_t = self.build_id_pat if self.build_id_pat else "{n}-{v}_{t}"
            old_build_id_t = old_build_id_t.format(**pat_dict)
            build_folders_all = get_build_folders(self.croot)
            for folder_full in build_folders_all:
                folder = os.path.basename(folder_full)
                untimed_folder = re.sub(time_re, r"\g<1>{t}", folder, flags=re.UNICODE)
                if untimed_folder == old_build_id_t:
                    build_folders.append(folder_full)
            prev_build_id = None
        if build_folders:
            # Use the most recent build with matching recipe name
            prev_build_id = os.path.basename(build_folders[-1])
            old_dir = os.path.join(build_folders[-1], "work")
        else:
            # Maybe call set_invocation_time() here?
            pat_dict["t"] = invocation_time
            test_old_dir = self.work_dir
            old_dir = test_old_dir if os.path.exists(test_old_dir) else None

        if self.set_build_id and (not self._build_id or reset):
            assert not os.path.isabs(package_name), (
                "package name should not be a absolute path, "
                "to preserve croot during path joins"
            )
            if self.dirty and prev_build_id:
                old_dir = self.work_dir if len(os.listdir(self.work_dir)) > 0 else None
                self._build_id = prev_build_id
            else:
                # important: this is recomputing prefixes and determines where work folders are.
                build_id = self.build_id_pat if self.build_id_pat else "{n}-{v}_{t}"
                self._build_id = build_id.format(**pat_dict)
                if old_dir:
                    work_dir = self.work_dir
                    if old_dir != work_dir:
                        rm_rf(work_dir)
                        shutil.move(old_dir, work_dir)

    @property
    def build_id(self):
        """This is a per-build (almost) unique id, consisting of the package being built, and the
        time since the epoch, in ms.  It is appended to build and test prefixes, and used to create
        unique work folders for build and test."""
        return self._build_id

    @build_id.setter
    def build_id(self, _build_id):
        _build_id = _build_id.rstrip("/").rstrip("\\")
        assert not os.path.isabs(_build_id), (
            "build_id should not be an absolute path, "
            "to preserve croot during path joins"
        )
        self._build_id = _build_id

    @property
    def prefix_length(self):
        return self._prefix_length

    @prefix_length.setter
    def prefix_length(self, length):
        self._prefix_length = length

    @property
    def _short_host_prefix(self):
        return join(self.build_folder, "_h_env")

    @property
    def _long_host_prefix(self):
        placeholder_length = self.prefix_length - len(self._short_host_prefix)
        placeholder = "_placehold"
        repeats = int(math.ceil(placeholder_length / len(placeholder)) + 1)
        placeholder = (self._short_host_prefix + repeats * placeholder)[
            : self.prefix_length
        ]
        return max(self._short_host_prefix, placeholder)

    @property
    def build_prefix(self):
        """The temporary folder where the build environment is created.  The build env contains
        libraries that may be linked, but only if the host env is not specified.  It is placed on
        PATH."""
        if self._merge_build_host:
            prefix = self.host_prefix
        else:
            prefix = join(self.build_folder, "_build_env")
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
        return join(self.build_folder, "_test_env")

    def _long_prefix(self, base_prefix):
        placeholder_length = self.prefix_length - len(base_prefix)
        placeholder = "_placehold"
        repeats = int(math.ceil(placeholder_length / len(placeholder)) + 1)
        placeholder = (base_prefix + repeats * placeholder)[: self.prefix_length]
        return max(base_prefix, placeholder)

    @property
    def test_prefix(self):
        """The temporary folder where the test environment is created"""
        if on_win or not self.long_test_prefix:
            return self._short_test_prefix
        # Reduce the length of the prefix by 2 characters to check if the null
        # byte padding causes issues
        return self._long_prefix(self._short_test_prefix)[:-2]

    @property
    def build_python(self):
        return self.python_bin(self.build_prefix, self.platform)

    @property
    def host_python(self):
        return self._get_python(self.host_prefix, self.host_platform)

    @property
    def test_python(self):
        return self.python_bin(self.test_prefix, self.host_platform)

    def python_bin(self, prefix, platform):
        return self._get_python(prefix, platform)

    def perl_bin(self, prefix, platform):
        return self._get_perl(prefix, platform)

    def lua_bin(self, prefix, platform):
        return self._get_lua(prefix, platform)

    def r_bin(self, prefix, platform):
        return self._get_r(prefix, platform)

    def rscript_bin(self, prefix, platform):
        return self._get_rscript(prefix, platform)

    @property
    def info_dir(self):
        """Path to the info dir in the build prefix, where recipe metadata is stored"""
        path = join(self.host_prefix, "info")
        os.makedirs(path, exist_ok=True)
        return path

    @property
    def meta_dir(self):
        """Path to the conda-meta dir in the build prefix, where package index json files are
        stored"""
        path = join(self.host_prefix, "conda-meta")
        os.makedirs(path, exist_ok=True)
        return path

    @property
    def broken_dir(self):
        """Where packages that fail the test phase are placed"""
        path = join(self.croot, "broken")
        os.makedirs(path, exist_ok=True)
        return path

    @property
    def bldpkgs_dir(self):
        """Dir where the package is saved."""
        path = join(self.croot, self.host_subdir)
        os.makedirs(path, exist_ok=True)
        return path

    @property
    def bldpkgs_dirs(self):
        """Dirs where previous build packages might be."""
        # The first two *might* be the same, but might not, depending on if this is a cross-compile.
        #     subdir should be the native platform, while self.subdir would be the host platform.
        return {
            join(self.croot, self.host_subdir),
            join(self.croot, subdir),
            join(self.croot, "noarch"),
        }

    @property
    def src_cache(self):
        """Where tarballs and zip files are downloaded and stored"""
        path = join(self.src_cache_root, "src_cache")
        os.makedirs(path, exist_ok=True)
        return path

    @property
    def git_cache(self):
        """Where local clones of git sources are stored"""
        path = join(self.src_cache_root, "git_cache")
        os.makedirs(path, exist_ok=True)
        return path

    @property
    def hg_cache(self):
        """Where local clones of hg sources are stored"""
        path = join(self.src_cache_root, "hg_cache")
        os.makedirs(path, exist_ok=True)
        return path

    @property
    def svn_cache(self):
        """Where local checkouts of svn sources are stored"""
        path = join(self.src_cache_root, "svn_cache")
        os.makedirs(path, exist_ok=True)
        return path

    @property
    def work_dir(self):
        """Where the source for the build is extracted/copied to."""
        path = join(self.build_folder, "work")
        os.makedirs(path, exist_ok=True)
        return path

    @property
    def pip_cache_dir(self):
        path = self._pip_cache_dir or join(self.build_folder, "pip_cache")
        os.makedirs(path, exist_ok=True)
        return path

    @pip_cache_dir.setter
    def pip_cache_dir(self, path):
        self._pip_cache_dir = path

    @property
    def test_dir(self):
        """The temporary folder where test files are copied to, and where tests start execution"""
        path = join(self.build_folder, "test_tmp")
        os.makedirs(path, exist_ok=True)
        return path

    @property
    def subdirs_same(self):
        return self.host_subdir == self.build_subdir

    def clean(self, remove_folders=True):
        # build folder is the whole burrito containing envs and source folders
        #   It will only exist if we download source, or create a build or test environment
        if (
            remove_folders
            and not getattr(self, "dirty")
            and not getattr(self, "keep_old_work")
        ):
            if self.build_id:
                if os.path.isdir(self.build_folder):
                    rm_rf(self.build_folder)
            else:
                for path in [
                    self.work_dir,
                    self.test_dir,
                    self.build_prefix,
                    self.test_prefix,
                ]:
                    if os.path.isdir(path):
                        rm_rf(path)
            if os.path.isfile(os.path.join(self.build_folder, "prefix_files")):
                rm_rf(os.path.join(self.build_folder, "prefix_files"))
        else:
            print(
                "\nLeaving build/test directories:" "\n  Work:\n",
                self.work_dir,
                "\n  Test:\n",
                self.test_dir,
                "\nLeaving build/test environments:" "\n  Test:\nsource activate ",
                self.test_prefix,
                "\n  Build:\nsource activate ",
                self.build_prefix,
                "\n\n",
            )

        for lock in get_conda_operation_locks(self.locking, self.bldpkgs_dirs):
            if os.path.isfile(lock.lock_file):
                rm_rf(lock.lock_file)

    def clean_pkgs(self):
        for folder in self.bldpkgs_dirs:
            rm_rf(folder)

    def copy(self):
        new = copy.copy(self)
        new.variant = copy.deepcopy(self.variant)
        if hasattr(self, "variants"):
            new.variants = copy.deepcopy(self.variants)
        return new

    # context management - automatic cleanup if self.dirty or self.keep_old_work is not True
    def __enter__(self):
        pass

    def __exit__(self, e_type, e_value, traceback):
        if (
            not getattr(self, "dirty")
            and e_type is None
            and not getattr(self, "keep_old_work")
        ):
            get_logger(__name__).info(
                "--dirty flag and --keep-old-work not specified. "
                "Removing build/test folder after successful build/test.\n"
            )
            self.clean()
        else:
            self.clean(remove_folders=False)


def get_or_merge_config(config, variant=None, **kwargs):
    """Always returns a new object - never changes the config that might be passed in."""
    if not config:
        config = Config(variant=variant)
    else:
        # decouple this config from whatever was fed in.  People must change config by
        #    accessing and changing this attribute.
        config = config.copy()
    if kwargs:
        config.set_keys(**kwargs)
    if variant:
        config.variant.update(variant)
    return config


def get_channel_urls(args):
    channel_urls = args.get("channel") or args.get("channels") or ()
    final_channel_urls = []

    for url in channel_urls:
        # allow people to specify relative or absolute paths to local channels
        #    These channels still must follow conda rules - they must have the
        #    appropriate platform-specific subdir (e.g. win-64)
        if os.path.isdir(url):
            if not os.path.isabs(url):
                url = os.path.normpath(os.path.abspath(os.path.join(os.getcwd(), url)))
            url = url_path(url)
        final_channel_urls.append(url)

    return final_channel_urls


# legacy exports for conda
croot = Config().croot
