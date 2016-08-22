# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

from functools import partial
from pkg_resources import parse_version

import conda
from conda import compat, plan  # NOQA
from conda.api import get_index  # NOQA
from conda.cli.common import (Completer, InstalledPackages, add_parser_channels, add_parser_prefix,  # NOQA
                              specs_from_args, spec_from_line, specs_from_url)  # NOQA
from conda.cli.conda_argparse import ArgumentParser  # NOQA
from conda.compat import (PY3, StringIO, configparser, input, iteritems, lchmod, string_types,  # NOQA
                          text_type, TemporaryDirectory)  # NOQA
from conda.connection import CondaSession  # NOQA
from conda.fetch import TmpDownload, download, fetch_index, handle_proxy_407  # NOQA
from conda.install import (delete_trash, is_linked, linked, linked_data, move_to_trash,  # NOQA
                           prefix_placeholder, rm_rf, symlink_conda)  # NOQA
from conda.lock import Locked  # NOQA
from conda.misc import untracked, walk_prefix  # NOQA
from conda.resolve import MatchSpec, NoPackagesFound, Resolve, Unsatisfiable, normalized_version  # NOQA
from conda.signature import KEYS, KEYS_DIR, hash_file, verify  # NOQA
from conda.utils import human_bytes, hashsum_file, md5_file, memoized, unix_path_to_win, win_path_to_unix, url_path  # NOQA
import conda.config as cc  # NOQA
from conda.config import sys_rc_path  # NOQA

if parse_version(conda.__version__) >= parse_version("4.2"):
    # conda 4.2.x
    import conda.base.context
    from conda.base.context import get_prefix as context_get_prefix, non_x86_linux_machines  # NOQA

    from conda.base.constants import DEFAULT_CHANNELS  # NOQA
    get_prefix = partial(context_get_prefix, conda.base.context.context)
    get_default_urls = lambda: DEFAULT_CHANNELS

    arch_name = conda.base.context.context.arch_name
    binstar_upload = conda.base.context.context.binstar_upload
    bits = conda.base.context.context.bits
    default_prefix = conda.base.context.context.default_prefix
    default_python = conda.base.context.context.default_python
    envs_dirs = conda.base.context.context.envs_dirs
    pkgs_dirs = conda.base.context.context.pkgs_dirs
    platform = conda.base.context.context.platform
    root_dir = conda.base.context.context.root_dir
    root_writable = conda.base.context.context.root_writable
    subdir = conda.base.context.context.subdir
    from conda.models.channel import get_conda_build_local_url
    get_rc_urls = lambda: list(conda.base.context.context.channels)
    get_local_urls = lambda: list(get_conda_build_local_url()) or []
    load_condarc = lambda fn: conda.base.context.reset_context([fn])

else:
    from conda.config import get_default_urls, non_x86_linux_machines, load_condarc  # NOQA
    from conda.cli.common import get_prefix  # NOQA

    arch_name = cc.arch_name
    binstar_upload = cc.binstar_upload
    bits = cc.bits
    default_prefix = cc.default_prefix
    default_python = cc.default_python
    envs_dirs = cc.envs_dirs
    pkgs_dirs = cc.pkgs_dirs
    platform = cc.platform
    root_dir = cc.root_dir
    root_writable = cc.root_writable
    subdir = cc.subdir

    get_rc_urls = cc.get_rc_urls
    get_local_urls = cc.get_local_urls


class SignatureError(Exception):
    pass


def which_package(path):
    """
    given the path (of a (presumably) conda installed file) iterate over
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
    given the path (to a (presumably) conda installed file) return the
    environment prefix in which the file in located
    """
    from os.path import abspath, join, isdir, dirname
    prefix = abspath(path)
    while True:
        if isdir(join(prefix, 'conda-meta')):
            # we found the it, so let's return it
            return prefix
        if prefix == dirname(prefix):
            # we cannot chop off any more directories, so we didn't find it
            return None
        prefix = dirname(prefix)
