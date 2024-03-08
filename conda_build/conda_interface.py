# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import configparser  # noqa: F401
import os
from functools import partial
from importlib import import_module  # noqa: F401

from conda import __version__ as CONDA_VERSION  # noqa: F401
from conda.base.context import context, determine_target_prefix, reset_context
from conda.base.context import non_x86_machines as non_x86_linux_machines  # noqa: F401
from conda.core.package_cache import ProgressiveFetchExtract  # noqa: F401
from conda.exceptions import (  # noqa: F401
    CondaError,
    CondaHTTPError,
    LinkError,
    LockError,
    NoPackagesFoundError,
    PaddingError,
    UnsatisfiableError,
)
from conda.exports import (  # noqa: F401
    ArgumentParser,
    Channel,
    Completer,
    CondaSession,
    EntityEncoder,
    FileMode,
    InstalledPackages,
    MatchSpec,
    NoPackagesFound,
    PackageRecord,
    PathType,
    Resolve,
    StringIO,
    TemporaryDirectory,
    TmpDownload,
    Unsatisfiable,
    VersionOrder,
    _toposort,
    add_parser_channels,
    add_parser_prefix,
    download,
    human_bytes,
    input,
    lchmod,
    normalized_version,
    prefix_placeholder,
    rm_rf,
    spec_from_line,
    specs_from_args,
    specs_from_url,
    symlink_conda,
    unix_path_to_win,
    untracked,
    url_path,
    walk_prefix,
    win_path_to_unix,
)
from conda.gateways.disk.read import compute_sum
from conda.models.channel import get_conda_build_local_url  # noqa: F401

from .deprecations import deprecated

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
get_prefix = partial(determine_target_prefix, context)
cc_conda_build = context.conda_build if hasattr(context, "conda_build") else {}

get_conda_channel = Channel.from_value

# Disallow softlinks. This avoids a lot of dumb issues, at the potential cost of disk space.
os.environ["CONDA_ALLOW_SOFTLINKS"] = "false"
reset_context()

# When deactivating envs (e.g. switching from root to build/test) this env var is used,
# except the PR that removed this has been reverted (for now) and Windows doesn't need it.
env_path_backup_var_exists = os.environ.get("CONDA_PATH_BACKUP", None)


@deprecated(
    "24.3",
    "24.5",
    addendum="Handled by `conda.gateways.connection.session.CondaSession`.",
)
def handle_proxy_407(x, y):
    pass


deprecated.constant(
    "24.3",
    "24.5",
    "hashsum_file",
    compute_sum,
    addendum="Use `conda.gateways.disk.read.compute_sum` instead.",
)


@deprecated(
    "24.3",
    "24.5",
    addendum="Use `conda.gateways.disk.read.compute_sum(path, 'md5')` instead.",
)
def md5_file(path: str | os.PathLike) -> str:
    return compute_sum(path, "md5")


@deprecated(
    "24.3",
    "24.5",
    addendum="Use `conda_build.environ.get_version_from_git_tag` instead.",
)
def get_version_from_git_tag(tag):
    from .environ import get_version_from_git_tag

    return get_version_from_git_tag(tag)
