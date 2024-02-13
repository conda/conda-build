# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import configparser  # noqa: F401
import os
from functools import partial
from importlib import import_module  # noqa: F401

from conda import __version__ as CONDA_VERSION  # noqa: F401
from conda.auxlib.packaging import (  # noqa: F401
    _get_version_from_git_tag as get_version_from_git_tag,
)
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
    handle_proxy_407,
    hashsum_file,
    human_bytes,
    input,
    lchmod,
    md5_file,
    memoized,
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
from conda.exports import display_actions as _display_actions
from conda.exports import execute_actions as _execute_actions
from conda.exports import execute_plan as _execute_plan
from conda.exports import get_index as _get_index
from conda.exports import install_actions as _install_actions
from conda.exports import linked as _linked
from conda.exports import linked_data as _linked_data
from conda.exports import package_cache as _package_cache
from conda.models.channel import get_conda_build_local_url  # noqa: F401
from conda.models.dist import Dist as _Dist

from .deprecations import deprecated

deprecated.constant("24.1.0", "24.3.0", "Dist", _Dist)
deprecated.constant("24.1.0", "24.3.0", "display_actions", _display_actions)
deprecated.constant("24.1.0", "24.3.0", "execute_actions", _execute_actions)
deprecated.constant("24.1.0", "24.3.0", "execute_plan", _execute_plan)
deprecated.constant("24.1.0", "24.3.0", "get_index", _get_index)
deprecated.constant("24.1.0", "24.3.0", "install_actions", _install_actions)
deprecated.constant("24.1.0", "24.3.0", "linked", _linked)
deprecated.constant("24.1.0", "24.3.0", "linked_data", _linked_data)
deprecated.constant("24.1.0", "24.3.0", "package_cache", _package_cache)

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
