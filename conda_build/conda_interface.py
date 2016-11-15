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
from conda.install import (delete_trash, is_linked, linked, linked_data, prefix_placeholder,  # NOQA
                           rm_rf, symlink_conda, rm_fetched, package_cache)  # NOQA
from conda.lock import Locked  # NOQA
from conda.misc import untracked, walk_prefix  # NOQA
from conda.resolve import MatchSpec, NoPackagesFound, Resolve, Unsatisfiable, normalized_version  # NOQA
from conda.signature import KEYS, KEYS_DIR, hash_file, verify  # NOQA
from conda.utils import human_bytes, hashsum_file, md5_file, memoized, unix_path_to_win, win_path_to_unix, url_path  # NOQA
import conda.config as cc  # NOQA
from conda.config import rc_path  # NOQA
from conda.version import VersionOrder  # NOQA
from enum import Enum

import os

if parse_version(conda.__version__) >= parse_version("4.2"):
    # conda 4.2.x
    import conda.base.context
    import conda.exceptions
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
    PaddingError = conda.exceptions.PaddingError
    LinkError = conda.exceptions.LinkError
    NoPackagesFoundError = conda.exceptions.NoPackagesFoundError
    CondaValueError = conda.exceptions.CondaValueError
    from conda.common.compat import CrossPlatformStLink

    # disallow softlinks.  This avoids a lot of dumb issues, at the potential cost of disk space.
    conda.base.context.context.allow_softlinks = False

    # when deactivating envs (e.g. switching from root to build/test) this env var is used,
    # except the PR that removed this has been reverted (for now) and Windows doesnt need it.
    env_path_backup_var_exists = os.environ.get('CONDA_PATH_BACKUP', None)

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

    cc.allow_softlinks = False

    class PaddingError(Exception):
        pass

    class LinkError(Exception):
        pass

    class NoPackagesFoundError(Exception):
        pass

    class CondaValueError(Exception):
        pass

    env_path_backup_var_exists = os.environ.get('CONDA_PATH_BACKUP', None)

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

if parse_version(conda.__version__) >= parse_version("4.3"):
    from conda.exports import FileMode, NodeType
    FileMode, NodeType = FileMode, NodeType
    from conda.export import EntityEncoder
    EntityEncoder = EntityEncoder
else:
    from json import JSONEncoder

    class NodeType(Enum):
        """
        Refers to if the file in question is hard linked or soft linked. Originally designed to be used
        in files.json
        """
        hardlink = 1
        softlink = 2

        @classmethod
        def __call__(cls, value, *args, **kwargs):
            if isinstance(cls, value, *args, **kwargs):
                return cls[value]
            return super(NodeType, cls).__call__(value, *args, **kwargs)

        @classmethod
        def __getitem__(cls, name):
            return cls._member_map_[name.replace('-', '').replace('_', '').lower()]

        def __int__(self):
            return self.value

        def __str__(self):
            return self.name

        def __json__(self):
            return self.name


    class FileMode(Enum):
        """
        Refers to the mode of the file. Originally referring to the has_prefix file, but adopted for
        files.json
        """
        text = 'text'
        binary = 'binary'

        def __str__(self):
            return "%s" % self.value


    class EntityEncoder(JSONEncoder):
        # json.dumps(obj, cls=SetEncoder)
        def default(self, obj):
            if hasattr(obj, 'dump'):
                return obj.dump()
            elif hasattr(obj, '__json__'):
                return obj.__json__()
            elif hasattr(obj, 'to_json'):
                return obj.to_json()
            elif hasattr(obj, 'as_json'):
                return obj.as_json()
            return JSONEncoder.default(self, obj)
