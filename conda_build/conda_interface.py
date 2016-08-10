# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

from functools import partial

from conda import compat, plan
from conda.api import get_index
from conda.cli.common import (Completer, InstalledPackages, add_parser_channels, add_parser_prefix,
                              specs_from_args, spec_from_line)
from conda.cli.conda_argparse import ArgumentParser
from conda.compat import (PY3, StringIO, configparser, input, iteritems, lchmod, string_types,
                          text_type)
from conda.connection import CondaSession
from conda.fetch import TmpDownload, download, fetch_index, handle_proxy_407
from conda.install import (delete_trash, linked, linked_data, move_to_trash, prefix_placeholder,
                           rm_rf, symlink_conda)
from conda.lock import Locked
from conda.misc import untracked, walk_prefix
from conda.resolve import MatchSpec, NoPackagesFound, Resolve, Unsatisfiable, normalized_version
from conda.signature import KEYS_DIR, hash_file, verify
from conda.utils import human_bytes, hashsum_file, md5_file, memoized, unix_path_to_win, url_path
import conda.config as cc

from conda.base.context import context, get_prefix as context_get_prefix
from conda.base.constants import DEFAULT_CHANNELS

get_prefix = partial(context_get_prefix, context)


get_default_urls = lambda: DEFAULT_CHANNELS


default_python = context.default_python


class SignatureError(Exception):
    pass


def which_package(path):
    """
    given the path (of a (presumably) conda installed file) iterate over
    the conda packages the file came from.  Usually the iteration yields
    only one package.
    """
    from os.path import abspath, join
    from conda.install import is_linked
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
