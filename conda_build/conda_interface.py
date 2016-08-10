# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

from conda import compat, plan
from conda.api import get_index
from conda.cli.common import (Completer, InstalledPackages, add_parser_channels, add_parser_prefix,
                              get_prefix, specs_from_args, spec_from_line)
from conda.cli.conda_argparse import ArgumentParser
from conda.compat import (PY3, StringIO, configparser, input, iteritems, lchmod, string_types,
                          text_type)
from conda.config import default_python, get_default_urls
from conda.connection import CondaSession
from conda.fetch import TmpDownload, download, fetch_index, handle_proxy_407
from conda.install import (delete_trash, linked, linked_data, move_to_trash, prefix_placeholder,
                           rm_rf, symlink_conda)
from conda.lock import Locked
from conda.misc import untracked, walk_prefix, which_package
from conda.resolve import MatchSpec, NoPackagesFound, Resolve, Unsatisfiable, normalized_version
from conda.signature import KEYS_DIR, SignatureError, hash_file, verify
from conda.utils import human_bytes, hashsum_file, md5_file, memoized, unix_path_to_win, url_path
import conda.config as cc

