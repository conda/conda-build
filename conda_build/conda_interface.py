# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

import configparser as _configparser
import os as _os
from builtins import input as _input
from functools import partial as _partial
from importlib import import_module as _import_module
from io import StringIO as _StringIO

from conda import __version__
from conda.base.context import context as _context
from conda.base.context import determine_target_prefix as _determine_target_prefix
from conda.base.context import non_x86_machines as _non_x86_linux_machines
from conda.base.context import reset_context as _reset_context
from conda.common.path import win_path_to_unix as _win_path_to_unix
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
from conda.misc import untracked as _untracked
from conda.misc import walk_prefix as _walk_prefix
from conda.models.channel import Channel as _Channel
from conda.models.channel import get_conda_build_local_url as _get_conda_build_local_url
from conda.utils import unix_path_to_win as _unix_path_to_win
from conda.utils import url_path as _url_path

from .deprecations import deprecated

deprecated.constant(
    "24.5",
    "24.7",
    "unix_path_to_win",
    _unix_path_to_win,
    addendum="Use `conda.utils.unix_path_to_win` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "untracked",
    _untracked,
    addendum="Use `conda.misc.untracked` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "url_path",
    _url_path,
    addendum="Use `conda.utils.url_path` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "walk_prefix",
    _walk_prefix,
    addendum="Use `conda.misc.walk_prefix` instead.",
)
deprecated.constant(
    "24.5",
    "24.7",
    "win_path_to_unix",
    _win_path_to_unix,
    addendum="Use `conda.common.path.win_path_to_unix` instead.",
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
    "input",
    _input,
    addendum="Use `input` instead.",
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
deprecated.constant(
    "24.5",
    "24.7",
    "cc_conda_build",
    _context.conda_build,
    addendum="Use `conda.base.context.context.conda_build` instead.",
)

deprecated.constant(
    "24.5",
    "24.7",
    "get_conda_channel",
    _Channel.from_value,
    addendum="Use `conda.models.channel.Channel.from_value` instead.",
)

deprecated.constant(
    "24.5",
    "24.7",
    "env_path_backup_var_exists",
    _os.getenv("CONDA_PATH_BACKUP"),
    addendum="Unused.",
)


deprecated.constant(
    "24.5",
    "24.7",
    "CONDA_VERSION",
    __version__,
    addendum="Use `conda.__version__` instead.",
)
