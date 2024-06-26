# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import contextlib
import logging
import multiprocessing
import os
import platform
import re
import subprocess
import sys
import warnings
from collections import defaultdict
from functools import lru_cache
from glob import glob
from logging import getLogger
from os.path import join, normpath
from typing import TYPE_CHECKING

from conda.base.constants import (
    CONDA_PACKAGE_EXTENSIONS,
    DEFAULTS_CHANNEL_NAME,
    UNKNOWN_CHANNEL,
)
from conda.base.context import context, reset_context
from conda.common.io import env_vars
from conda.core.index import LAST_CHANNEL_URLS
from conda.core.link import PrefixSetup, UnlinkLinkTransaction
from conda.core.package_cache_data import PackageCacheData, ProgressiveFetchExtract
from conda.core.prefix_data import PrefixData
from conda.exceptions import (
    CondaError,
    LinkError,
    LockError,
    NoPackagesFoundError,
    PaddingError,
    UnsatisfiableError,
)
from conda.gateways.disk.create import TemporaryDirectory
from conda.models.channel import Channel, prioritize_channels
from conda.models.match_spec import MatchSpec
from conda.models.records import PackageRecord

from . import utils
from .exceptions import BuildLockError, DependencyNeedsBuildingError
from .features import feature_list
from .index import get_build_index
from .os_utils import external
from .utils import (
    ensure_list,
    env_var,
    on_mac,
    on_win,
    package_record_to_requirement,
    prepend_bin_path,
)
from .variants import get_default_variant

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any, Iterable, TypedDict

    from .config import Config
    from .metadata import MetaData

    class InstallActionsType(TypedDict):
        PREFIX: str | os.PathLike | Path
        LINK: list[PackageRecord]


log = getLogger(__name__)

# these are things that we provide env vars for more explicitly.  This list disables the
#    pass-through of variant values to env vars for these keys.
LANGUAGES = ("PERL", "LUA", "R", "NUMPY", "PYTHON")
R_PACKAGES = ("r-base", "mro-base", "r-impl")


def get_perl_ver(config):
    return ".".join(
        config.variant.get("perl", get_default_variant(config)["perl"]).split(".")[:2]
    )


def get_lua_ver(config):
    return ".".join(
        config.variant.get("lua", get_default_variant(config)["lua"]).split(".")[:2]
    )


def get_py_ver(config):
    py = config.variant.get("python", get_default_variant(config)["python"])
    if not hasattr(py, "split"):
        py = py[0]
    return ".".join(py.split(".")[:2])


def get_r_ver(config):
    return ".".join(
        config.variant.get("r_base", get_default_variant(config)["r_base"]).split(".")[
            :3
        ]
    )


def get_npy_ver(config):
    conda_npy = "".join(
        str(config.variant.get("numpy") or get_default_variant(config)["numpy"]).split(
            "."
        )
    )
    # Convert int -> string, e.g.
    #   17 -> '1.7'
    #   110 -> '1.10'
    return conda_npy[0] + "." + conda_npy[1:]


def get_lua_include_dir(config):
    return join(config.host_prefix, "include")


@lru_cache(maxsize=None)
def verify_git_repo(
    git_exe, git_dir, git_url, git_commits_since_tag, debug=False, expected_rev="HEAD"
):
    env = os.environ.copy()
    log = utils.get_logger(__name__)

    stderr = None if debug else subprocess.DEVNULL

    if not expected_rev:
        return False

    OK = True

    env["GIT_DIR"] = git_dir
    try:
        # Verify current commit (minus our locally applied patches) matches expected commit
        current_commit = utils.check_output_env(
            [
                git_exe,
                "log",
                "-n1",
                "--format=%H",
                "HEAD" + "^" * git_commits_since_tag,
            ],
            env=env,
            stderr=stderr,
        )
        current_commit = current_commit.decode("utf-8")
        expected_tag_commit = utils.check_output_env(
            [git_exe, "log", "-n1", "--format=%H", expected_rev], env=env, stderr=stderr
        )
        expected_tag_commit = expected_tag_commit.decode("utf-8")

        if current_commit != expected_tag_commit:
            return False

        # Verify correct remote url. Need to find the git cache directory,
        # and check the remote from there.
        cache_details = utils.check_output_env(
            [git_exe, "remote", "-v"], env=env, stderr=stderr
        )
        cache_details = cache_details.decode("utf-8")
        cache_dir = cache_details.split("\n")[0].split()[1]

        if not isinstance(cache_dir, str):
            # On Windows, subprocess env can't handle unicode.
            cache_dir = cache_dir.encode(sys.getfilesystemencoding() or "utf-8")

        try:
            remote_details = utils.check_output_env(
                [git_exe, "--git-dir", cache_dir, "remote", "-v"],
                env=env,
                stderr=stderr,
            )
        except subprocess.CalledProcessError:
            if on_win and cache_dir.startswith("/"):
                cache_dir = utils.convert_unix_path_to_win(cache_dir)
            remote_details = utils.check_output_env(
                [git_exe, "--git-dir", cache_dir, "remote", "-v"],
                env=env,
                stderr=stderr,
            )
        remote_details = remote_details.decode("utf-8")
        remote_url = remote_details.split("\n")[0].split()[1]

        # on windows, remote URL comes back to us as cygwin or msys format.  Python doesn't
        # know how to normalize it.  Need to convert it to a windows path.
        if on_win and remote_url.startswith("/"):
            remote_url = utils.convert_unix_path_to_win(git_url)

        if os.path.exists(remote_url):
            # Local filepaths are allowed, but make sure we normalize them
            remote_url = normpath(remote_url)

        # If the current source directory in conda-bld/work doesn't match the user's
        # metadata git_url or git_rev, then we aren't looking at the right source.
        if not os.path.isdir(remote_url) and remote_url.lower() != git_url.lower():
            log.debug("remote does not match git_url")
            log.debug("Remote: " + remote_url.lower())
            log.debug("git_url: " + git_url.lower())
            OK = False
    except subprocess.CalledProcessError as error:
        log.debug("Error obtaining git information in verify_git_repo.  Error was: ")
        log.debug(str(error))
        OK = False
    return OK


GIT_DESCRIBE_REGEX = re.compile(
    r"(?:[_-a-zA-Z]*)"
    r"(?P<version>[a-zA-Z0-9.]+)"
    r"(?:-(?P<post>\d+)-g(?P<hash>[0-9a-f]{7,}))$"
)


def get_version_from_git_tag(tag):
    """Return a PEP440-compliant version derived from the git status.
    If that fails for any reason, return the changeset hash.
    """
    m = GIT_DESCRIBE_REGEX.match(tag)
    if m is None:
        return None
    version, post_commit, hash = m.groups()
    return version if post_commit == "0" else f"{version}.post{post_commit}+{hash}"


def get_git_info(git_exe, repo, debug):
    """
    Given a repo to a git repo, return a dictionary of:
      GIT_DESCRIBE_TAG
      GIT_DESCRIBE_TAG_PEP440
      GIT_DESCRIBE_NUMBER
      GIT_DESCRIBE_HASH
      GIT_FULL_HASH
      GIT_BUILD_STR
    from the output of git describe.
    :return:
    """
    d = {}
    log = utils.get_logger(__name__)

    stderr = None if debug else subprocess.DEVNULL

    # grab information from describe
    env = os.environ.copy()
    env["GIT_DIR"] = repo
    keys = ["GIT_DESCRIBE_TAG", "GIT_DESCRIBE_NUMBER", "GIT_DESCRIBE_HASH"]

    try:
        output = utils.check_output_env(
            [git_exe, "describe", "--tags", "--long", "HEAD"],
            env=env,
            cwd=os.path.dirname(repo),
            stderr=stderr,
        ).splitlines()[0]
        output = output.decode("utf-8")
        parts = output.rsplit("-", 2)
        if len(parts) == 3:
            d.update(dict(zip(keys, parts)))
        d["GIT_DESCRIBE_TAG_PEP440"] = str(get_version_from_git_tag(output))
    except subprocess.CalledProcessError:
        msg = (
            "Failed to obtain git tag information.\n"
            "Consider using annotated tags if you are not already "
            "as they are more reliable when used with git describe."
        )
        log.debug(msg)

    # If there was no tag reachable from HEAD, the above failed and the short hash is not set.
    # Try to get the short hash from describing with all refs (not just the tags).
    if "GIT_DESCRIBE_HASH" not in d:
        try:
            output = utils.check_output_env(
                [git_exe, "describe", "--all", "--long", "HEAD"],
                env=env,
                cwd=os.path.dirname(repo),
                stderr=stderr,
            ).splitlines()[0]
            output = output.decode("utf-8")
            parts = output.rsplit("-", 2)
            if len(parts) == 3:
                # Don't save GIT_DESCRIBE_TAG and GIT_DESCRIBE_NUMBER because git (probably)
                # described a branch. We just want to save the short hash.
                d["GIT_DESCRIBE_HASH"] = parts[-1]
        except subprocess.CalledProcessError as error:
            log.debug("Error obtaining git commit information.  Error was: ")
            log.debug(str(error))

    try:
        # get the _full_ hash of the current HEAD
        output = utils.check_output_env(
            [git_exe, "rev-parse", "HEAD"],
            env=env,
            cwd=os.path.dirname(repo),
            stderr=stderr,
        ).splitlines()[0]
        output = output.decode("utf-8")

        d["GIT_FULL_HASH"] = output
    except subprocess.CalledProcessError as error:
        log.debug("Error obtaining git commit information.  Error was: ")
        log.debug(str(error))

    # set up the build string
    if "GIT_DESCRIBE_NUMBER" in d and "GIT_DESCRIBE_HASH" in d:
        d["GIT_BUILD_STR"] = "{}_{}".format(
            d["GIT_DESCRIBE_NUMBER"], d["GIT_DESCRIBE_HASH"]
        )

    # issues on Windows with the next line of the command prompt being recorded here.
    assert not any("\n" in value for value in d.values())
    return d


def get_hg_build_info(repo):
    env = os.environ.copy()
    env["HG_DIR"] = repo
    env = {str(key): str(value) for key, value in env.items()}

    d = {}
    cmd = [
        "hg",
        "log",
        "--template",
        "{rev}|{node|short}|{latesttag}|{latesttagdistance}|{branch}",
        "--rev",
        ".",
    ]
    output = utils.check_output_env(cmd, env=env, cwd=os.path.dirname(repo))
    output = output.decode("utf-8")
    rev, short_id, tag, distance, branch = output.split("|")
    if tag != "null":
        d["HG_LATEST_TAG"] = tag
    if branch == "":
        branch = "default"
    d["HG_BRANCH"] = branch
    d["HG_NUM_ID"] = rev
    d["HG_LATEST_TAG_DISTANCE"] = distance
    d["HG_SHORT_ID"] = short_id
    d["HG_BUILD_STR"] = "{}_{}".format(d["HG_NUM_ID"], d["HG_SHORT_ID"])
    return d


def get_dict(
    m,
    prefix=None,
    for_env=True,
    skip_build_id=False,
    escape_backslash=False,
    variant=None,
):
    if not prefix:
        prefix = m.config.host_prefix

    m.config._merge_build_host = m.build_is_host

    # conda-build specific vars
    d = conda_build_vars(prefix, m.config)

    # languages
    d.update(python_vars(m, prefix, escape_backslash))
    d.update(perl_vars(m, prefix, escape_backslash))
    d.update(lua_vars(m, prefix, escape_backslash))
    d.update(r_vars(m, prefix, escape_backslash))

    if m:
        d.update(meta_vars(m, skip_build_id=skip_build_id))

    # system
    d.update(os_vars(m, prefix))

    # features
    d.update({feat.upper(): str(int(value)) for feat, value in feature_list})

    variant = variant or m.config.variant
    for k, v in variant.items():
        if not for_env or (k.upper() not in d and k.upper() not in LANGUAGES):
            d[k] = v
    return d


def conda_build_vars(prefix, config):
    src_dir = (
        config.test_dir if os.path.basename(prefix)[:2] == "_t" else config.work_dir
    )
    return {
        "CONDA_BUILD": "1",
        "PYTHONNOUSERSITE": "1",
        "CONDA_DEFAULT_ENV": config.host_prefix,
        "ARCH": str(config.host_arch),
        # This is the one that is most important for where people put artifacts that get bundled.
        #     It is fed from our function argument, and can be any of:
        #     1. Build prefix - when host requirements are not explicitly set,
        #        then prefix = build prefix = host prefix
        #     2. Host prefix - when host requirements are explicitly set, prefix = host prefix
        #     3. Test prefix - during test runs, this points at the test prefix
        "PREFIX": prefix,
        # This is for things that are specifically build tools.  Things that run on the build
        #    platform, but probably should not be linked against, since they may not run on the
        #    destination host platform
        # It can be equivalent to config.host_prefix if the host section is not explicitly set.
        "BUILD_PREFIX": config.build_prefix,
        "SYS_PREFIX": sys.prefix,
        "SYS_PYTHON": sys.executable,
        "SUBDIR": config.host_subdir,
        "build_platform": config.build_subdir,
        "SRC_DIR": src_dir,
        "HTTPS_PROXY": os.getenv("HTTPS_PROXY", ""),
        "HTTP_PROXY": os.getenv("HTTP_PROXY", ""),
        "REQUESTS_CA_BUNDLE": os.getenv("REQUESTS_CA_BUNDLE", ""),
        "DIRTY": "1" if config.dirty else "",
        "ROOT": context.root_prefix,
    }


def python_vars(metadata, prefix, escape_backslash):
    py_ver = get_py_ver(metadata.config)
    stdlib_dir = utils.get_stdlib_dir(prefix, py_ver)
    sp_dir = utils.get_site_packages(prefix, py_ver)

    if utils.on_win and escape_backslash:
        stdlib_dir = stdlib_dir.replace("\\", "\\\\")
        sp_dir = sp_dir.replace("\\", "\\\\")

    vars_ = {
        "CONDA_PY": "".join(py_ver.split(".")[:2]),
        "PY3K": str(int(int(py_ver[0]) >= 3)),
        "PY_VER": py_ver,
        "STDLIB_DIR": stdlib_dir,
        "SP_DIR": sp_dir,
    }
    build_or_host = "host" if metadata.is_cross else "build"
    deps = [str(ms.name) for ms in metadata.ms_depends(build_or_host)]
    if "python" in deps or metadata.name() == "python":
        python_bin = metadata.config.python_bin(prefix, metadata.config.host_subdir)

        if utils.on_win and escape_backslash:
            python_bin = python_bin.replace("\\", "\\\\")

        vars_.update(
            {
                # host prefix is always fine, because it is the same as build when is_cross is False
                "PYTHON": python_bin,
            }
        )

    np_ver = metadata.config.variant.get(
        "numpy", get_default_variant(metadata.config)["numpy"]
    )
    vars_["NPY_VER"] = ".".join(np_ver.split(".")[:2])
    vars_["CONDA_NPY"] = "".join(np_ver.split(".")[:2])
    vars_["NPY_DISTUTILS_APPEND_FLAGS"] = "1"
    return vars_


def perl_vars(metadata, prefix, escape_backslash):
    vars_ = {
        "PERL_VER": get_perl_ver(metadata.config),
        "CONDA_PERL": get_perl_ver(metadata.config),
    }
    build_or_host = "host" if metadata.is_cross else "build"
    deps = [str(ms.name) for ms in metadata.ms_depends(build_or_host)]
    if "perl" in deps or metadata.name() == "perl":
        perl_bin = metadata.config.perl_bin(prefix, metadata.config.host_subdir)

        if utils.on_win and escape_backslash:
            perl_bin = perl_bin.replace("\\", "\\\\")

        vars_.update(
            {
                # host prefix is always fine, because it is the same as build when is_cross is False
                "PERL": perl_bin,
            }
        )
    return vars_


def lua_vars(metadata, prefix, escape_backslash):
    vars_ = {
        "LUA_VER": get_lua_ver(metadata.config),
        "CONDA_LUA": get_lua_ver(metadata.config),
    }
    build_or_host = "host" if metadata.is_cross else "build"
    deps = [str(ms.name) for ms in metadata.ms_depends(build_or_host)]
    if "lua" in deps:
        lua_bin = metadata.config.lua_bin(prefix, metadata.config.host_subdir)
        lua_include_dir = get_lua_include_dir(metadata.config)

        if utils.on_win and escape_backslash:
            lua_bin = lua_bin.replace("\\", "\\\\")
            lua_include_dir = lua_include_dir.replace("\\", "\\\\")

        vars_.update(
            {
                "LUA": lua_bin,
                "LUA_INCLUDE_DIR": lua_include_dir,
            }
        )
    return vars_


def r_vars(metadata, prefix, escape_backslash):
    vars_ = {
        "R_VER": get_r_ver(metadata.config),
        "CONDA_R": get_r_ver(metadata.config),
    }

    build_or_host = "host" if metadata.is_cross else "build"
    deps = [str(ms.name) for ms in metadata.ms_depends(build_or_host)]
    if any(r_pkg in deps for r_pkg in R_PACKAGES) or metadata.name() in R_PACKAGES:
        r_bin = metadata.config.r_bin(prefix, metadata.config.host_subdir)
        # set R_USER explicitly to prevent crosstalk with existing R_LIBS_USER packages
        r_user = join(prefix, "Libs", "R")

        if utils.on_win and escape_backslash:
            r_bin = r_bin.replace("\\", "\\\\")

        vars_.update(
            {
                "R": r_bin,
                "R_USER": r_user,
            }
        )
    return vars_


def meta_vars(meta: MetaData, skip_build_id=False):
    d = {}
    for var_name in ensure_list(meta.get_value("build/script_env", [])):
        if "=" in var_name:
            var_name, value = var_name.split("=", 1)
        else:
            value = os.getenv(var_name)
        if value is None:
            warnings.warn(
                f"The environment variable '{var_name}' specified in script_env is undefined.",
                UserWarning,
            )
        else:
            d[var_name] = value
            warnings.warn(
                f"The environment variable '{var_name}' is being passed through with value "
                f"'{'<hidden>' if meta.config.suppress_variables else value}'.  "
                "If you are splitting build and test phases with --no-test, please ensure "
                "that this value is also set similarly at test time.",
                UserWarning,
            )

    folder = meta.get_value("source/0/folder", "")
    repo_dir = join(meta.config.work_dir, folder)
    git_dir = join(repo_dir, ".git")
    hg_dir = join(repo_dir, ".hg")

    if not isinstance(git_dir, str):
        # On Windows, subprocess env can't handle unicode.
        git_dir = git_dir.encode(sys.getfilesystemencoding() or "utf-8")

    git_exe = external.find_executable("git", meta.config.build_prefix)
    if git_exe and os.path.exists(git_dir):
        # We set all 'source' metavars using the FIRST source entry in meta.yaml.
        git_url = meta.get_value("source/0/git_url")

        if os.path.exists(git_url):
            if on_win:
                git_url = utils.convert_unix_path_to_win(git_url)
            # If git_url is a relative path instead of a url, convert it to an abspath
            git_url = normpath(join(meta.path, git_url))

        _x = False

        if git_url:
            _x = verify_git_repo(
                git_exe,
                git_dir,
                git_url,
                meta.config.git_commits_since_tag,
                meta.config.debug,
                meta.get_value("source/0/git_rev", "HEAD"),
            )

        if _x or meta.get_value("source/0/path"):
            d.update(get_git_info(git_exe, git_dir, meta.config.debug))

    elif external.find_executable("hg", meta.config.build_prefix) and os.path.exists(
        hg_dir
    ):
        d.update(get_hg_build_info(hg_dir))

    d["PKG_NAME"] = meta.name()
    d["PKG_VERSION"] = meta.version()
    d["PKG_BUILDNUM"] = str(meta.build_number())
    if meta.final and not skip_build_id:
        d["PKG_BUILD_STRING"] = meta.build_id()
        d["PKG_HASH"] = meta.hash_dependencies()
    else:
        d["PKG_BUILD_STRING"] = "placeholder"
        d["PKG_HASH"] = "1234567"
    d["RECIPE_DIR"] = meta.path
    return d


@lru_cache(maxsize=None)
def get_cpu_count():
    if on_mac:
        # multiprocessing.cpu_count() is not reliable on OSX
        # See issue #645 on github.com/conda/conda-build
        out, _ = subprocess.Popen(
            "sysctl -n hw.logicalcpu", shell=True, stdout=subprocess.PIPE
        ).communicate()
        return out.decode("utf-8").strip()
    else:
        try:
            return str(multiprocessing.cpu_count())
        except NotImplementedError:
            return "1"


def get_shlib_ext(host_platform):
    # Return the shared library extension.
    if host_platform.startswith("win"):
        return ".dll"
    elif host_platform in ["osx", "darwin"]:
        return ".dylib"
    elif host_platform.startswith("linux") or host_platform.endswith("-wasm32"):
        return ".so"
    elif host_platform == "noarch":
        # noarch packages should not contain shared libraries, use the system
        # platform if this is requested
        return get_shlib_ext(sys.platform)
    else:
        raise NotImplementedError(host_platform)


def windows_vars(m, get_default, prefix):
    """This is setting variables on a dict that is part of the get_default function"""
    # We have gone for the clang values here.
    win_arch = "i386" if str(m.config.host_arch) == "32" else "amd64"
    win_msvc = "19.0.0"
    library_prefix = join(prefix, "Library")
    drive, tail = m.config.host_prefix.split(":")
    get_default("SCRIPTS", join(prefix, "Scripts"))
    get_default("LIBRARY_PREFIX", library_prefix)
    get_default("LIBRARY_BIN", join(library_prefix, "bin"))
    get_default("LIBRARY_INC", join(library_prefix, "include"))
    get_default("LIBRARY_LIB", join(library_prefix, "lib"))
    get_default(
        "CYGWIN_PREFIX", "".join(("/cygdrive/", drive.lower(), tail.replace("\\", "/")))
    )
    # see https://en.wikipedia.org/wiki/Environment_variable#Default_values
    get_default("ALLUSERSPROFILE")
    get_default("APPDATA")
    get_default("CommonProgramFiles")
    get_default("CommonProgramFiles(x86)")
    get_default("CommonProgramW6432")
    get_default("COMPUTERNAME")
    get_default("ComSpec")
    get_default("HOMEDRIVE")
    get_default("HOMEPATH")
    get_default("LOCALAPPDATA")
    get_default("LOGONSERVER")
    get_default("NUMBER_OF_PROCESSORS")
    get_default("PATHEXT")
    get_default("ProgramData")
    get_default("ProgramFiles")
    get_default("ProgramFiles(x86)")
    get_default("ProgramW6432")
    get_default("PROMPT")
    get_default("PSModulePath")
    get_default("PUBLIC")
    get_default("SystemDrive")
    get_default("SystemRoot")
    get_default("TEMP")
    get_default("TMP")
    get_default("USERDOMAIN")
    get_default("USERNAME")
    get_default("USERPROFILE")
    get_default("windir")
    # CPU data, see https://github.com/conda/conda-build/issues/2064
    get_default("PROCESSOR_ARCHITEW6432")
    get_default("PROCESSOR_ARCHITECTURE")
    get_default("PROCESSOR_IDENTIFIER")
    get_default("BUILD", win_arch + "-pc-windows-" + win_msvc)
    for k in os.environ.keys():
        if re.match("VS[0-9]{2,3}COMNTOOLS", k):
            get_default(k)
        elif re.match("VS[0-9]{4}INSTALLDIR", k):
            get_default(k)


def unix_vars(m, get_default, prefix):
    """This is setting variables on a dict that is part of the get_default function"""
    get_default("HOME", "UNKNOWN")
    get_default("PKG_CONFIG_PATH", join(prefix, "lib", "pkgconfig"))
    get_default("CMAKE_GENERATOR", "Unix Makefiles")
    get_default("SSL_CERT_FILE")


def osx_vars(m, get_default, prefix):
    """This is setting variables on a dict that is part of the get_default function"""
    if str(m.config.host_arch) == "32":
        OSX_ARCH = "i386"
        MACOSX_DEPLOYMENT_TARGET = 10.9
    elif str(m.config.host_arch) == "arm64":
        OSX_ARCH = "arm64"
        MACOSX_DEPLOYMENT_TARGET = 11.0
    else:
        OSX_ARCH = "x86_64"
        MACOSX_DEPLOYMENT_TARGET = 10.9

    if str(m.config.arch) == "32":
        BUILD = "i386-apple-darwin13.4.0"
    elif str(m.config.arch) == "arm64":
        BUILD = "arm64-apple-darwin20.0.0"
    else:
        BUILD = "x86_64-apple-darwin13.4.0"
    # 10.7 install_name_tool -delete_rpath causes broken dylibs, I will revisit this ASAP.
    # rpath = ' -Wl,-rpath,%(PREFIX)s/lib' % d # SIP workaround, DYLD_* no longer works.
    # d['LDFLAGS'] = ldflags + rpath + ' -arch %(OSX_ARCH)s' % d
    get_default("OSX_ARCH", OSX_ARCH)
    get_default("MACOSX_DEPLOYMENT_TARGET", MACOSX_DEPLOYMENT_TARGET)
    get_default("BUILD", BUILD)


@lru_cache(maxsize=None)
def _machine_and_architecture():
    return platform.machine(), platform.architecture()


def linux_vars(m, get_default, prefix):
    """This is setting variables on a dict that is part of the get_default function"""
    platform_machine, platform_architecture = _machine_and_architecture()
    build_arch = platform_machine
    # Python reports x86_64 when running a i686 Python binary on a 64-bit CPU
    # unless run through linux32. Issue a warning when we detect this.
    if build_arch == "x86_64" and platform_architecture[0] == "32bit":
        print("Warning: You are running 32-bit Python on a 64-bit linux installation")
        print("         but have not launched it via linux32. Various qeuries *will*")
        print("         give unexpected results (uname -m, platform.machine() etc)")
        build_arch = "i686"
    # the GNU triplet is powerpc, not ppc. This matters.
    if build_arch.startswith("ppc"):
        build_arch = build_arch.replace("ppc", "powerpc")
    if (
        build_arch.startswith("powerpc")
        or build_arch.startswith("aarch64")
        or build_arch.startswith("s390x")
    ):
        build_distro = "cos7"
    else:
        build_distro = "cos6"
    # There is also QEMU_SET_ENV, but that needs to be
    # filtered so it only contains the result of `linux_vars`
    # which, before this change was empty, and after it only
    # contains other QEMU env vars.
    get_default("CFLAGS")
    get_default("CXXFLAGS")
    get_default("LDFLAGS")
    get_default("QEMU_LD_PREFIX")
    get_default("QEMU_UNAME")
    get_default("DEJAGNU")
    get_default("DISPLAY")
    get_default("LD_RUN_PATH", prefix + "/lib")
    get_default("BUILD", build_arch + "-conda_" + build_distro + "-linux-gnu")


def set_from_os_or_variant(out_dict, key, variant, default):
    value = os.getenv(key)
    if not value:
        value = variant.get(key, default)
    if value:
        out_dict[key] = value


def system_vars(env_dict, m, prefix):
    warnings.warn(
        "`conda_build.environ.system_vars` is pending deprecation and will be removed in a "
        "future release. Please use `conda_build.environ.os_vars` instead.",
        PendingDeprecationWarning,
    )
    return os_vars(m, prefix)


def os_vars(m, prefix):
    d = dict()
    # note the dictionary is passed in here - variables are set in that dict if they are non-null
    get_default = lambda key, default="": set_from_os_or_variant(
        d, key, m.config.variant, default
    )

    get_default("CPU_COUNT", get_cpu_count())
    get_default("LANG")
    get_default("LC_ALL")
    get_default("MAKEFLAGS")
    d["SHLIB_EXT"] = get_shlib_ext(m.config.host_platform)
    d["PATH"] = os.environ.copy()["PATH"]

    if not m.config.activate:
        d = prepend_bin_path(d, m.config.host_prefix)

    if on_win:
        windows_vars(m, get_default, prefix)
    else:
        unix_vars(m, get_default, prefix)

    if m.config.host_platform == "osx":
        osx_vars(m, get_default, prefix)
    elif m.config.host_platform == "linux":
        linux_vars(m, get_default, prefix)

    return d


cached_precs: dict[
    tuple[tuple[str | MatchSpec, ...], Any, Any, Any, bool], list[PackageRecord]
] = {}
last_index_ts = 0


# NOTE: The function has to retain the "get_install_actions" name for now since
#       conda_libmamba_solver.solver.LibMambaSolver._called_from_conda_build
#       checks for this name in the call stack explicitly.
def get_install_actions(
    prefix: str | os.PathLike | Path,
    specs: Iterable[str | MatchSpec],
    env,  # unused
    retries: int = 0,
    subdir=None,
    verbose: bool = True,
    debug: bool = False,
    locking: bool = True,
    bldpkgs_dirs=None,
    timeout=900,
    disable_pip: bool = False,
    max_env_retry: int = 3,
    output_folder=None,
    channel_urls=None,
) -> list[PackageRecord]:
    global cached_precs
    global last_index_ts

    log = utils.get_logger(__name__)
    conda_log_level = logging.WARN
    specs = list(specs)
    if specs:
        specs.extend(context.create_default_packages)
    if verbose or debug:
        capture = contextlib.nullcontext
        if debug:
            conda_log_level = logging.DEBUG
    else:
        capture = utils.capture
    for feature, value in feature_list:
        if value:
            specs.append(f"{feature}@")

    bldpkgs_dirs = ensure_list(bldpkgs_dirs)

    index, index_ts, _ = get_build_index(
        subdir,
        list(bldpkgs_dirs)[0],
        output_folder=output_folder,
        channel_urls=channel_urls,
        debug=debug,
        verbose=verbose,
        locking=locking,
        timeout=timeout,
    )
    specs = tuple(
        utils.ensure_valid_spec(spec) for spec in specs if not str(spec).endswith("@")
    )

    precs: list[PackageRecord] = []
    if (
        specs,
        env,
        subdir,
        channel_urls,
        disable_pip,
    ) in cached_precs and last_index_ts >= index_ts:
        precs = cached_precs[(specs, env, subdir, channel_urls, disable_pip)].copy()
    elif specs:
        # this is hiding output like:
        #    Fetching package metadata ...........
        #    Solving package specifications: ..........
        with utils.LoggingContext(conda_log_level):
            with capture():
                try:
                    _actions = _install_actions(prefix, index, specs, subdir=subdir)
                    precs = _actions["LINK"]
                except (NoPackagesFoundError, UnsatisfiableError) as exc:
                    raise DependencyNeedsBuildingError(exc, subdir=subdir)
                except (
                    SystemExit,
                    PaddingError,
                    LinkError,
                    DependencyNeedsBuildingError,
                    CondaError,
                    AssertionError,
                    BuildLockError,
                ) as exc:
                    if "lock" in str(exc):
                        log.warning(
                            "failed to get package records, retrying.  exception was: %s",
                            str(exc),
                        )
                    elif (
                        "requires a minimum conda version" in str(exc)
                        or "link a source that does not" in str(exc)
                        or isinstance(exc, AssertionError)
                    ):
                        locks = utils.get_conda_operation_locks(
                            locking, bldpkgs_dirs, timeout
                        )
                        with utils.try_acquire_locks(locks, timeout=timeout):
                            pkg_dir = str(exc)
                            folder = 0
                            while (
                                os.path.dirname(pkg_dir) not in context.pkgs_dirs
                                and folder < 20
                            ):
                                pkg_dir = os.path.dirname(pkg_dir)
                                folder += 1
                            log.warning(
                                "I think conda ended up with a partial extraction for %s. "
                                "Removing the folder and retrying",
                                pkg_dir,
                            )
                            if pkg_dir in context.pkgs_dirs and os.path.isdir(pkg_dir):
                                utils.rm_rf(pkg_dir)
                    if retries < max_env_retry:
                        log.warning(
                            "failed to get package records, retrying.  exception was: %s",
                            str(exc),
                        )
                        precs = get_package_records(
                            prefix,
                            specs,
                            env,
                            retries=retries + 1,
                            subdir=subdir,
                            verbose=verbose,
                            debug=debug,
                            locking=locking,
                            bldpkgs_dirs=tuple(bldpkgs_dirs),
                            timeout=timeout,
                            disable_pip=disable_pip,
                            max_env_retry=max_env_retry,
                            output_folder=output_folder,
                            channel_urls=tuple(channel_urls),
                        )
                    else:
                        log.error(
                            "Failed to get package records, max retries exceeded."
                        )
                        raise
        if disable_pip:
            for pkg in ("pip", "setuptools", "wheel"):
                # specs are the raw specifications, not the conda-derived actual specs
                #   We're testing that pip etc. are manually specified
                if not any(
                    re.match(rf"^{pkg}(?:$|[\s=].*)", str(dep)) for dep in specs
                ):
                    precs = [prec for prec in precs if prec.name != pkg]
        cached_precs[(specs, env, subdir, channel_urls, disable_pip)] = precs.copy()
        last_index_ts = index_ts
    return precs


get_package_records = get_install_actions
del get_install_actions


def create_env(
    prefix: str | os.PathLike | Path,
    specs_or_precs: Iterable[str | MatchSpec] | Iterable[PackageRecord],
    env,
    config,
    subdir,
    clear_cache: bool = True,
    retry: int = 0,
    locks=None,
    is_cross: bool = False,
    is_conda: bool = False,
) -> None:
    """
    Create a conda envrionment for the given prefix and specs.
    """
    if config.debug:
        external_logger_context = utils.LoggingContext(logging.DEBUG)
    else:
        external_logger_context = utils.LoggingContext(logging.WARN)

    if os.path.exists(prefix):
        for entry in glob(os.path.join(prefix, "*")):
            utils.rm_rf(entry)

    with external_logger_context:
        log = utils.get_logger(__name__)

        # if os.path.isdir(prefix):
        #     utils.rm_rf(prefix)

        specs_or_precs = tuple(ensure_list(specs_or_precs))
        if specs_or_precs:  # Don't waste time if there is nothing to do
            log.debug("Creating environment in %s", prefix)
            log.debug(str(specs_or_precs))

            if not locks:
                locks = utils.get_conda_operation_locks(config)
            try:
                with utils.try_acquire_locks(locks, timeout=config.timeout):
                    # input is a list of specs in MatchSpec format
                    if not isinstance(specs_or_precs[0], PackageRecord):
                        precs = get_package_records(
                            prefix,
                            tuple(set(specs_or_precs)),
                            env,
                            subdir=subdir,
                            verbose=config.verbose,
                            debug=config.debug,
                            locking=config.locking,
                            bldpkgs_dirs=tuple(config.bldpkgs_dirs),
                            timeout=config.timeout,
                            disable_pip=config.disable_pip,
                            max_env_retry=config.max_env_retry,
                            output_folder=config.output_folder,
                            channel_urls=tuple(config.channel_urls),
                        )
                    else:
                        precs = specs_or_precs
                    index, _, _ = get_build_index(
                        subdir=subdir,
                        bldpkgs_dir=config.bldpkgs_dir,
                        output_folder=config.output_folder,
                        channel_urls=config.channel_urls,
                        debug=config.debug,
                        verbose=config.verbose,
                        locking=config.locking,
                        timeout=config.timeout,
                    )
                    _display_actions(prefix, precs)
                    if utils.on_win:
                        for k, v in os.environ.items():
                            os.environ[k] = str(v)
                    with env_var("CONDA_QUIET", not config.verbose, reset_context):
                        with env_var("CONDA_JSON", not config.verbose, reset_context):
                            _execute_actions(prefix, precs)
            except (
                SystemExit,
                PaddingError,
                LinkError,
                DependencyNeedsBuildingError,
                CondaError,
                BuildLockError,
            ) as exc:
                if (
                    "too short in" in str(exc)
                    or re.search(
                        "post-link failed for: (?:[a-zA-Z]*::)?openssl", str(exc)
                    )
                    or isinstance(exc, PaddingError)
                ) and config.prefix_length > 80:
                    if config.prefix_length_fallback:
                        log.warning(
                            "Build prefix failed with prefix length %d",
                            config.prefix_length,
                        )
                        log.warning("Error was: ")
                        log.warning(str(exc))
                        log.warning(
                            "One or more of your package dependencies needs to be rebuilt "
                            "with a longer prefix length."
                        )
                        log.warning(
                            "Falling back to legacy prefix length of 80 characters."
                        )
                        log.warning(
                            "Your package will not install into prefixes > 80 characters."
                        )
                        config.prefix_length = 80

                        create_env(
                            (
                                config.host_prefix
                                if "_h_env" in prefix
                                else config.build_prefix
                            ),
                            specs_or_precs,
                            config=config,
                            subdir=subdir,
                            env=env,
                            clear_cache=clear_cache,
                            is_cross=is_cross,
                        )
                    else:
                        raise
                elif "lock" in str(exc):
                    if retry < config.max_env_retry:
                        log.warning(
                            "failed to create env, retrying.  exception was: %s",
                            str(exc),
                        )
                        create_env(
                            prefix,
                            specs_or_precs,
                            config=config,
                            subdir=subdir,
                            env=env,
                            clear_cache=clear_cache,
                            retry=retry + 1,
                            is_cross=is_cross,
                        )
                elif "requires a minimum conda version" in str(
                    exc
                ) or "link a source that does not" in str(exc):
                    with utils.try_acquire_locks(locks, timeout=config.timeout):
                        pkg_dir = str(exc)
                        folder = 0
                        while (
                            os.path.dirname(pkg_dir) not in context.pkgs_dirs
                            and folder < 20
                        ):
                            pkg_dir = os.path.dirname(pkg_dir)
                            folder += 1
                        log.warning(
                            "I think conda ended up with a partial extraction for %s.  "
                            "Removing the folder and retrying",
                            pkg_dir,
                        )
                        if os.path.isdir(pkg_dir):
                            utils.rm_rf(pkg_dir)
                    if retry < config.max_env_retry:
                        log.warning(
                            "failed to create env, retrying.  exception was: %s",
                            str(exc),
                        )
                        create_env(
                            prefix,
                            specs_or_precs,
                            config=config,
                            subdir=subdir,
                            env=env,
                            clear_cache=clear_cache,
                            retry=retry + 1,
                            is_cross=is_cross,
                        )
                    else:
                        log.error("Failed to create env, max retries exceeded.")
                        raise
                else:
                    raise
            # HACK: some of the time, conda screws up somehow and incomplete packages result.
            #    Just retry.
            except (
                AssertionError,
                OSError,
                ValueError,
                RuntimeError,
                LockError,
            ) as exc:
                if isinstance(exc, AssertionError):
                    with utils.try_acquire_locks(locks, timeout=config.timeout):
                        pkg_dir = os.path.dirname(os.path.dirname(str(exc)))
                        log.warning(
                            "I think conda ended up with a partial extraction for %s.  "
                            "Removing the folder and retrying",
                            pkg_dir,
                        )
                        if os.path.isdir(pkg_dir):
                            utils.rm_rf(pkg_dir)
                if retry < config.max_env_retry:
                    log.warning(
                        "failed to create env, retrying.  exception was: %s", str(exc)
                    )
                    create_env(
                        prefix,
                        specs_or_precs,
                        config=config,
                        subdir=subdir,
                        env=env,
                        clear_cache=clear_cache,
                        retry=retry + 1,
                        is_cross=is_cross,
                    )
                else:
                    log.error("Failed to create env, max retries exceeded.")
                    raise


def get_pkg_dirs_locks(dirs, config):
    return [utils.get_lock(folder, timeout=config.timeout) for folder in dirs]


def clean_pkg_cache(dist: str, config: Config) -> None:
    with utils.LoggingContext(logging.DEBUG if config.debug else logging.WARN):
        locks = get_pkg_dirs_locks((config.bldpkgs_dir, *context.pkgs_dirs), config)
        with utils.try_acquire_locks(locks, timeout=config.timeout):
            for pkgs_dir in context.pkgs_dirs:
                if any(
                    os.path.exists(os.path.join(pkgs_dir, f"{dist}{ext}"))
                    for ext in ("", *CONDA_PACKAGE_EXTENSIONS)
                ):
                    log.debug(
                        "Conda caching error: %s package remains in cache after removal",
                        dist,
                    )
                    log.debug("manually removing to compensate")
                    package_cache = PackageCacheData.first_writable([pkgs_dir])
                    for cache_pkg_id in package_cache.query(dist):
                        package_cache.remove(cache_pkg_id)

        # Note that this call acquires the relevant locks, so this must be called
        # outside the lock context above.
        remove_existing_packages(context.pkgs_dirs, [dist], config)


def remove_existing_packages(dirs, fns, config):
    locks = get_pkg_dirs_locks(dirs, config) if config.locking else []

    with utils.try_acquire_locks(locks, timeout=config.timeout):
        for folder in dirs:
            for fn in fns:
                all_files = [fn]
                if not os.path.isabs(fn):
                    all_files = glob(os.path.join(folder, fn + "*"))
                for entry in all_files:
                    utils.rm_rf(entry)


def get_pinned_deps(m, section):
    with TemporaryDirectory(prefix="_") as tmpdir:
        precs = get_package_records(
            tmpdir,
            tuple(m.ms_depends(section)),
            section,
            subdir=m.config.target_subdir,
            debug=m.config.debug,
            verbose=m.config.verbose,
            locking=m.config.locking,
            bldpkgs_dirs=tuple(m.config.bldpkgs_dirs),
            timeout=m.config.timeout,
            disable_pip=m.config.disable_pip,
            max_env_retry=m.config.max_env_retry,
            output_folder=m.config.output_folder,
            channel_urls=tuple(m.config.channel_urls),
        )
    return [package_record_to_requirement(prec) for prec in precs]


# NOTE: The function has to retain the "install_actions" name for now since
#       conda_libmamba_solver.solver.LibMambaSolver._called_from_conda_build
#       checks for this name in the call stack explicitly.
def install_actions(
    prefix: str | os.PathLike | Path,
    index,
    specs: Iterable[str | MatchSpec],
    subdir: str | None = None,
) -> InstallActionsType:
    # This is copied over from https://github.com/conda/conda/blob/23.11.0/conda/plan.py#L471
    # but reduced to only the functionality actually used within conda-build.
    subdir_kwargs = {}
    if subdir not in (None, "", "noarch"):
        subdir_kwargs["CONDA_SUBDIR"] = subdir

    with env_vars(
        {
            "CONDA_ALLOW_NON_CHANNEL_URLS": "true",
            "CONDA_SOLVER_IGNORE_TIMESTAMPS": "false",
            **subdir_kwargs,
        },
        callback=reset_context,
    ):
        # a hack since in conda-build we don't track channel_priority_map
        channels: tuple[Channel, ...] | None
        subdirs: tuple[str, ...] | None
        if LAST_CHANNEL_URLS:
            channel_priority_map = prioritize_channels(LAST_CHANNEL_URLS)
            # tuple(dict.fromkeys(...)) removes duplicates while preserving input order.
            channels = tuple(
                dict.fromkeys(Channel(url) for url in channel_priority_map)
            )
            subdirs = (
                tuple(
                    dict.fromkeys(
                        subdir for channel in channels if (subdir := channel.subdir)
                    )
                )
                or context.subdirs
            )
        else:
            channels = subdirs = None

        mspecs = tuple(MatchSpec(spec) for spec in specs)

        PrefixData._cache_.clear()

        solver_backend = context.plugin_manager.get_cached_solver_backend()
        solver = solver_backend(prefix, channels, subdirs, specs_to_add=mspecs)
        if index:
            # Solver can modify the index (e.g., Solver._prepare adds virtual
            # package) => Copy index (just outer container, not deep copy)
            # to conserve it.
            solver._index = index.copy()
        txn = solver.solve_for_transaction(prune=False, ignore_pinned=False)
        prefix_setup = txn.prefix_setups[prefix]
        return {
            "PREFIX": prefix,
            "LINK": [prec for prec in prefix_setup.link_precs],
        }


_install_actions = install_actions
del install_actions


def _execute_actions(prefix, precs):
    # This is copied over from https://github.com/conda/conda/blob/23.11.0/conda/plan.py#L575
    # but reduced to only the functionality actually used within conda-build.
    assert prefix

    # Always link menuinst first/last on windows in case a subsequent
    # package tries to import it to create/remove a shortcut
    precs = [
        *(prec for prec in precs if prec.name == "menuinst"),
        *(prec for prec in precs if prec.name != "menuinst"),
    ]

    progressive_fetch_extract = ProgressiveFetchExtract(precs)
    progressive_fetch_extract.prepare()

    stp = PrefixSetup(prefix, (), precs, (), [], ())
    unlink_link_transaction = UnlinkLinkTransaction(stp)

    log.debug(" %s(%r)", "PROGRESSIVEFETCHEXTRACT", progressive_fetch_extract)
    progressive_fetch_extract.execute()
    log.debug(" %s(%r)", "UNLINKLINKTRANSACTION", unlink_link_transaction)
    unlink_link_transaction.execute()


def _display_actions(prefix, precs):
    # This is copied over from https://github.com/conda/conda/blob/23.11.0/conda/plan.py#L58
    # but reduced to only the functionality actually used within conda-build.

    builder = ["", "## Package Plan ##\n"]
    if prefix:
        builder.append(f"  environment location: {prefix}")
        builder.append("")
    print("\n".join(builder))

    show_channel_urls = context.show_channel_urls

    def channel_str(rec):
        if rec.get("schannel"):
            return rec["schannel"]
        if rec.get("url"):
            return Channel(rec["url"]).canonical_name
        if rec.get("channel"):
            return Channel(rec["channel"]).canonical_name
        return UNKNOWN_CHANNEL

    def channel_filt(s):
        if show_channel_urls is False:
            return ""
        if show_channel_urls is None and s == DEFAULTS_CHANNEL_NAME:
            return ""
        return s

    packages = defaultdict(lambda: "")
    features = defaultdict(lambda: "")
    channels = defaultdict(lambda: "")

    for prec in precs:
        assert isinstance(prec, PackageRecord)
        pkg = prec["name"]
        channels[pkg] = channel_filt(channel_str(prec))
        packages[pkg] = prec["version"] + "-" + prec["build"]
        features[pkg] = ",".join(prec.get("features") or ())

    fmt = {}
    if packages:
        maxpkg = max(len(p) for p in packages) + 1
        maxver = max(len(p) for p in packages.values())
        maxfeatures = max(len(p) for p in features.values())
        maxchannels = max(len(p) for p in channels.values())
        for pkg in packages:
            # That's right. I'm using old-style string formatting to generate a
            # string with new-style string formatting.
            fmt[pkg] = f"{{pkg:<{maxpkg}}} {{vers:<{maxver}}}"
            if maxchannels:
                fmt[pkg] += f" {{channel:<{maxchannels}}}"
            if features[pkg]:
                fmt[pkg] += f" [{{features:<{maxfeatures}}}]"

    lead = " " * 4

    def format(s, pkg):
        return lead + s.format(
            pkg=pkg + ":",
            vers=packages[pkg],
            channel=channels[pkg],
            features=features[pkg],
        )

    if packages:
        print("\nThe following NEW packages will be INSTALLED:\n")
        for pkg in sorted(packages):
            print(format(fmt[pkg], pkg))
    print()
