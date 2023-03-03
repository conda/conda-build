# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from functools import partial
import os
from importlib import import_module  # noqa: F401
import warnings

from conda import __version__ as CONDA_VERSION  # noqa: F401

from conda.exports import (  # noqa: F401
    Channel,
    display_actions,
    execute_actions,
    execute_plan,
    install_actions,
)

from conda.exports import _toposort  # noqa: F401

from conda.auxlib.packaging import (  # noqa: F401
    _get_version_from_git_tag as get_version_from_git_tag,
)

from conda.exports import TmpDownload, download, handle_proxy_407  # noqa: F401
from conda.exports import untracked, walk_prefix  # noqa: F401
from conda.exports import (  # noqa: F401
    MatchSpec,
    NoPackagesFound,
    Resolve,
    Unsatisfiable,
    normalized_version,
)
from conda.exports import (  # noqa: F401
    human_bytes,
    hashsum_file,
    md5_file,
    memoized,
    unix_path_to_win,
    win_path_to_unix,
    url_path,
)
from conda.exports import get_index  # noqa: F401
from conda.exports import (  # noqa: F401
    Completer,
    InstalledPackages,
    add_parser_channels,
    add_parser_prefix,
    specs_from_args,
    spec_from_line,
    specs_from_url,
)
from conda.exports import ArgumentParser  # noqa: F401
from conda.exports import (  # noqa: F401
    is_linked,
    linked,
    linked_data,
    prefix_placeholder,
    rm_rf,
    symlink_conda,
    package_cache,
)
from conda.exports import CondaSession  # noqa: F401
from conda.exports import StringIO, input, lchmod, TemporaryDirectory  # noqa: F401
from conda.exports import VersionOrder  # noqa: F401

from conda.core.package_cache import ProgressiveFetchExtract  # noqa: F401
from conda.models.dist import Dist, IndexRecord  # noqa: F401

import configparser  # noqa: F401

from conda.exports import FileMode, PathType  # noqa: F401
from conda.exports import EntityEncoder  # noqa: F401
from conda.exceptions import (  # noqa: F401
    CondaError,
    CondaHTTPError,
    LinkError,
    LockError,
    NoPackagesFoundError,
    PaddingError,
    UnsatisfiableError,
)
from conda.base.context import (  # noqa: F401
    non_x86_machines as non_x86_linux_machines,
    context,
    get_prefix,
    reset_context,
)
from conda.models.channel import get_conda_build_local_url  # noqa: F401

# TODO: Go to references of all properties below and import them from `context` instead
binstar_upload = context.binstar_upload
default_python = context.default_python
envs_dirs = context.envs_dirs
pkgs_dirs = list(context.pkgs_dirs)
cc_platform = context.platform
root_dir = context.root_dir
root_writable = context.root_writable
subdir = context.subdir
create_default_packages = context.create_default_packages

get_rc_urls = lambda: list(context.channels)
get_prefix = partial(context_get_prefix, context)  # noqa: F811, F821
cc_conda_build = context.conda_build if hasattr(context, 'conda_build') else {}

get_conda_channel = Channel.from_value

# Disallow softlinks. This avoids a lot of dumb issues, at the potential cost of disk space.
os.environ['CONDA_ALLOW_SOFTLINKS'] = 'false'
reset_context()


class CrossPlatformStLink:
    def __call__(self, path: str | os.PathLike) -> int:
        return self.st_nlink(path)

    @classmethod
    def st_nlink(cls, path: str | os.PathLike) -> int:
        warnings.warn(
            "`conda_build.conda_interface.CrossPlatformStLink` is pending deprecation and will be removed in a "
            "future release. Please use `os.stat().st_nlink` instead.",
            PendingDeprecationWarning,
        )
        return os.stat(path).st_nlink


class SignatureError(Exception):
    # TODO: What is this? 🤔
    pass


def which_package(path):
    """
    Given the path (of a (presumably) conda installed file) iterate over
    the conda packages the file came from.  Usually the iteration yields
    only one package.
    """
    from os.path import abspath, join
    path = abspath(path)
    prefix = which_prefix(path)
    if prefix is None:
        raise RuntimeError("could not determine conda prefix from: %s" % path)
    for dist in linked(prefix):
        meta = is_linked(prefix, dist)
        if any(abspath(join(prefix, f)) == path for f in meta['files']):
            yield dist


def which_prefix(path):
    """
    Given the path (to a (presumably) conda installed file) return the
    environment prefix in which the file in located
    """
    from os.path import abspath, join, isdir, dirname
    prefix = abspath(path)
    iteration = 0
    while iteration < 20:
        if isdir(join(prefix, 'conda-meta')):
            # we found it, so let's return it
            break
        if prefix == dirname(prefix):
            # we cannot chop off any more directories, so we didn't find it
            prefix = None
            break
        prefix = dirname(prefix)
        iteration += 1
    return prefix


def get_installed_version(prefix, pkgs):
    """
    Primarily used by conda-forge, but may be useful in general for checking when
    a package needs to be updated
    """
    from conda_build.utils import ensure_list
    pkgs = ensure_list(pkgs)
    linked_pkgs = linked(prefix)
    versions = {}
    for pkg in pkgs:
        vers_inst = [dist.split('::', 1)[-1].rsplit('-', 2)[1] for dist in linked_pkgs
            if dist.split('::', 1)[-1].rsplit('-', 2)[0] == pkg]
        versions[pkg] = vers_inst[0] if len(vers_inst) == 1 else None
    return versions


# When deactivating envs (e.g. switching from root to build/test) this env var is used,
# except the PR that removed this has been reverted (for now) and Windows doesn't need it.
env_path_backup_var_exists = os.environ.get('CONDA_PATH_BACKUP', None)
