# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import configparser as _configparser
import os as _os
from functools import partial as _partial
from importlib import import_module as _import_module
from io import StringIO as _StringIO

from conda import __version__
from conda.auxlib.entity import EntityEncoder as _EntityEncoder
from conda.base.context import context as _context
from conda.base.context import determine_target_prefix as _determine_target_prefix
from conda.base.context import non_x86_machines as _non_x86_linux_machines
from conda.base.context import reset_context as _reset_context
from conda.cli.conda_argparse import ArgumentParser as _ArgumentParser
from conda.cli.helpers import add_parser_channels as _add_parser_channels
from conda.cli.helpers import add_parser_prefix as _add_parser_prefix
from conda.core.package_cache_data import (
    ProgressiveFetchExtract as _ProgressiveFetchExtract,
)
from conda.exceptions import CondaError as _CondaError
from conda.exceptions import CondaHTTPError as _CondaHTTPError
from conda.exceptions import LinkError as _LinkError
from conda.exceptions import LockError as _LockError
from conda.exceptions import NoPackagesFoundError as _NoPackagesFoundError
from conda.exceptions import PaddingError as _PaddingError
from conda.exceptions import UnsatisfiableError as _UnsatisfiableError
from conda.exports import (  # noqa: F401
    Completer,  # unused
    CondaSession,  # unused
    InstalledPackages,  # unused
    NoPackagesFound,  # unused
    Unsatisfiable,
    VersionOrder,
    _toposort,
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
from conda.exports import get_index as _get_index
from conda.gateways.connection.download import TmpDownload as _TmpDownload
from conda.gateways.connection.download import download as _download
from conda.gateways.disk.create import TemporaryDirectory as _TemporaryDirectory
from conda.gateways.disk.read import compute_sum as _compute_sum
from conda.models.channel import Channel as _Channel
from conda.models.channel import get_conda_build_local_url as _get_conda_build_local_url
from conda.models.enums import FileMode as _FileMode
from conda.models.enums import PathType as _PathType
from conda.models.match_spec import MatchSpec as _MatchSpec
from conda.models.records import PackageRecord as _PackageRecord
from conda.resolve import Resolve as _Resolve

from .deprecations import deprecated

deprecated.constant(
    "24.5",
    "24.7",
    "ArgumentParser",
    _ArgumentParser,
    addendum="Use `conda.cli.conda_argparse.ArgumentParser` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "add_parser_channels",
    _add_parser_channels,
    addendum="Use `conda.cli.helpers.add_parser_channels` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "add_parser_prefix",
    _add_parser_prefix,
    addendum="Use `conda.cli.helpers.add_parser_prefix` instead.",
)

deprecated.constant(
    "24.5",
    "24.7",
    "Channel",
    _Channel,
    addendum="Use `conda.models.channel.Channel` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "FileMode",
    _FileMode,
    addendum="Use `conda.models.enums.FileMode` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "PathType",
    _PathType,
    addendum="Use `conda.models.enums.PathType` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "MatchSpec",
    _MatchSpec,
    addendum="Use `conda.models.match_spec.MatchSpec` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "PackageRecord",
    _PackageRecord,
    addendum="Use `conda.models.records.PackageRecord` instead.",
)

deprecated.constant(
    "24.5",
    "24.7",
    "EntityEncoder",
    _EntityEncoder,
    addendum="Use `conda.auxlib.entity.EntityEncoder` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "Resolve",
    _Resolve,
    addendum="Use `conda.resolve.Resolve` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "TemporaryDirectory",
    _TemporaryDirectory,
    addendum="Use `conda.gateways.disk.create.TemporaryDirectory` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "TmpDownload",
    _TmpDownload,
    addendum="Use `conda.gateways.connection.download.TmpDownload` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "download",
    _download,
    addendum="Use `conda.gateways.connection.download.download` instead.",
)

deprecated.constant(
    "24.5",
    "24.7",
    "configparser",
    _configparser,
    addendum="Use `configparser` instead.",
)
deprecated.constant("24.5", "24.7", "os", _os, addendum="Use `os` instead.")
deprecated.constant(
    "24.5",
    "24.7",
    "partial",
    _partial,
    addendum="Use `functools.partial` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "import_module",
    _import_module,
    addendum="Use `importlib.import_module` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "StringIO",
    _StringIO,
    addendum="Use `io.StringIO` instead.",
)

deprecated.constant(
    "24.5",
    "24.7",
    "context",
    _context,
    addendum="Use `conda.base.context.context` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "determine_target_prefix",
    _determine_target_prefix,
    addendum="Use `conda.base.context.determine_target_prefix` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "non_x86_linux_machines",
    _non_x86_linux_machines,
    addendum="Use `conda.base.context.non_x86_machines` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "ProgressiveFetchExtract",
    _ProgressiveFetchExtract,
    addendum="Use `conda.core.package_cache_data.ProgressiveFetchExtract` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "CondaError",
    _CondaError,
    addendum="Use `conda.exceptions.CondaError` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "CondaHTTPError",
    _CondaHTTPError,
    addendum="Use `conda.exceptions.CondaHTTPError` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "LinkError",
    _LinkError,
    addendum="Use `conda.exceptions.LinkError` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "LockError",
    _LockError,
    addendum="Use `conda.exceptions.LockError` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "NoPackagesFoundError",
    _NoPackagesFoundError,
    addendum="Use `conda.exceptions.NoPackagesFoundError` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "PaddingError",
    _PaddingError,
    addendum="Use `conda.exceptions.PaddingError` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "UnsatisfiableError",
    _UnsatisfiableError,
    addendum="Use `conda.exceptions.UnsatisfiableError` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "get_conda_build_local_url",
    _get_conda_build_local_url,
    addendum="Use `conda.models.channel.get_conda_build_local_url` instead.",
)
deprecated.constant(
    "24.1.0",
    "24.5.0",
    "get_index",
    _get_index,
    addendum="Use `conda.core.index.get_index` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "reset_context",
    _reset_context,
    addendum="Use `conda.base.context.reset_context` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "binstar_upload",
    _context.binstar_upload,
    addendum="Use `conda.base.context.context.binstar_upload` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "default_python",
    _context.default_python,
    addendum="Use `conda.base.context.context.default_python` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "envs_dirs",
    _context.envs_dirs,
    addendum="Use `conda.base.context.context.envs_dirs` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "pkgs_dirs",
    list(_context.pkgs_dirs),
    addendum="Use `conda.base.context.context.pkgs_dirs` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "cc_platform",
    _context.platform,
    addendum="Use `conda.base.context.context.platform` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "root_dir",
    _context.root_prefix,
    addendum="Use `conda.base.context.context.root_prefix` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "root_writable",
    _context.root_writable,
    addendum="Use `conda.base.context.context.root_writable` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "subdir",
    _context.subdir,
    addendum="Use `conda.base.context.context.subdir` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "create_default_packages",
    _context.create_default_packages,
    addendum="Use `conda.base.context.context.create_default_packages` instead.",
)

deprecated.constant(
    "24.5",
    "24.7",
    "get_rc_urls",
    lambda: list(_context.channels),
    addendum="Use `conda.base.context.context.channels` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "get_prefix",
    _partial(_determine_target_prefix, _context),
    addendum="Use `conda.base.context.context.target_prefix` instead.",
)
cc_conda_build = _context.conda_build if hasattr(_context, "conda_build") else {}

deprecated.constant(
    "24.5",
    "24.7",
    "get_conda_channel",
    _Channel.from_value,
    addendum="Use `conda.models.channel.Channel.from_value` instead.",
)

# When deactivating envs (e.g. switching from root to build/test) this env var is used,
# except the PR that removed this has been reverted (for now) and Windows doesn't need it.
env_path_backup_var_exists = _os.getenv("CONDA_PATH_BACKUP")


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
    _compute_sum,
    addendum="Use `conda.gateways.disk.read.compute_sum` instead.",
)


@deprecated(
    "24.3",
    "24.5",
    addendum="Use `conda.gateways.disk.read.compute_sum(path, 'md5')` instead.",
)
def md5_file(path: str | _os.PathLike) -> str:
    return _compute_sum(path, "md5")


deprecated.constant(
    "24.5",
    "24.7",
    "CONDA_VERSION",
    __version__,
    addendum="Use `conda.__version__` instead.",
)


@deprecated(
    "24.3",
    "24.5",
    addendum="Use `conda_build.environ.get_version_from_git_tag` instead.",
)
def get_version_from_git_tag(tag):
    from .environ import get_version_from_git_tag

    return get_version_from_git_tag(tag)
