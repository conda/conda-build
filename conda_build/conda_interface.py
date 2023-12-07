# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import configparser  # noqa: F401
import os
from functools import partial
from importlib import import_module  # noqa: F401
from pathlib import Path
from typing import Iterable

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
    ArgumentParser,  # noqa: F401
    Channel,
    Completer,
    CondaSession,  # noqa: F401
    EntityEncoder,  # noqa: F401
    FileMode,
    InstalledPackages,
    MatchSpec,
    NoPackagesFound,
    PathType,
    Resolve,
    StringIO,
    TemporaryDirectory,
    TmpDownload,
    Unsatisfiable,
    VersionOrder,  # noqa: F401
    _toposort,  # noqa: F401
    add_parser_channels,
    add_parser_prefix,
    display_actions,
    download,
    execute_actions,
    execute_plan,
    get_index,  # noqa: F401
    handle_proxy_407,
    hashsum_file,
    human_bytes,
    input,
    install_actions,
    lchmod,
    linked,
    linked_data,
    md5_file,
    memoized,
    normalized_version,
    package_cache,
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
from conda.models.channel import get_conda_build_local_url  # noqa: F401
from conda.models.dist import Dist  # noqa: F401
from conda.models.records import PackageRecord, PrefixRecord

from .deprecations import deprecated

deprecated.constant(
    "3.28.0",
    "24.1.0",
    "IndexRecord",
    PackageRecord,
    addendum="Use `conda.models.records.PackageRecord` instead.",
)

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


class CrossPlatformStLink:
    def __call__(self, path: str | os.PathLike) -> int:
        return self.st_nlink(path)

    @staticmethod
    @deprecated("3.24.0", "24.1.0", addendum="Use `os.stat().st_nlink` instead.")
    def st_nlink(path: str | os.PathLike) -> int:
        return os.stat(path).st_nlink


@deprecated("3.28.0", "24.1.0")
class SignatureError(Exception):
    # TODO: What is this? 🤔
    pass


@deprecated(
    "3.28.0",
    "24.1.0",
    addendum="Use `conda_build.inspect_pkg.which_package` instead.",
)
def which_package(path: str | os.PathLike | Path) -> Iterable[PrefixRecord]:
    from .inspect_pkg import which_package

    return which_package(path, which_prefix(path))


@deprecated("3.28.0", "24.1.0")
def which_prefix(path: str | os.PathLike | Path) -> Path:
    """
    Given the path (to a (presumably) conda installed file) return the
    environment prefix in which the file in located
    """
    from conda.gateways.disk.test import is_conda_environment

    prefix = Path(path)
    for _ in range(20):
        if is_conda_environment(prefix):
            return prefix
        elif prefix == (parent := prefix.parent):
            # we cannot chop off any more directories, so we didn't find it
            break
        else:
            prefix = parent

    raise RuntimeError("could not determine conda prefix from: %s" % path)


@deprecated("3.28.0", "24.1.0")
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
        vers_inst = [
            dist.split("::", 1)[-1].rsplit("-", 2)[1]
            for dist in linked_pkgs
            if dist.split("::", 1)[-1].rsplit("-", 2)[0] == pkg
        ]
        versions[pkg] = vers_inst[0] if len(vers_inst) == 1 else None
    return versions


# When deactivating envs (e.g. switching from root to build/test) this env var is used,
# except the PR that removed this has been reverted (for now) and Windows doesn't need it.
env_path_backup_var_exists = os.environ.get("CONDA_PATH_BACKUP", None)
