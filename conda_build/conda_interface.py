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
import conda.base.context
import conda.exceptions
from conda.models.channel import get_conda_build_local_url
from conda.cli.main import _main


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
get_rc_urls = lambda: list(conda.base.context.context.channels)
get_local_urls = lambda: list(get_conda_build_local_url()) or []
load_condarc = lambda fn: conda.base.context.reset_context([fn])
PaddingError = conda.exceptions.PaddingError
LinkError = conda.exceptions.LinkError
NoPackagesFoundError = conda.exceptions.NoPackagesFoundError
PackageNotFoundError = conda.exceptions.PackageNotFoundError
UnsatisfiableError = conda.exceptions.UnsatisfiableError
CondaValueError = conda.exceptions.CondaValueError
CondaHTTPError = conda.exceptions.CondaHTTPError
LockError = conda.exceptions.LockError
reset_context = conda.base.context.reset_context
conda_main = _main

# disallow softlinks.  This avoids a lot of dumb issues, at the potential cost of disk space.
conda.base.context.context.allow_softlinks = False

# when deactivating envs (e.g. switching from root to build/test) this env var is used,
# except the PR that removed this has been reverted (for now) and Windows doesnt need it.
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
    from conda.exports import FileMode, PathType
    FileMode, PathType = FileMode, PathType
    from conda.exports import EntityEncoder
    EntityEncoder = EntityEncoder
    from conda.exports import CrossPlatformStLink
    CrossPlatformStLink = CrossPlatformStLink
else:
    from json import JSONEncoder
    from os import lstat
    import os

    class PathType(Enum):
        """
        Refers to if the file in question is hard linked or soft linked. Originally designed to be
        used in paths.json
        """
        hardlink = "hardlink"
        softlink = "softlink"

        def __str__(self):
            return self.value

        def __json__(self):
            return self.name

    class FileMode(Enum):
        """
        Refers to the mode of the file. Originally referring to the has_prefix file, but adopted
        for paths.json
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

    # work-around for python bug on Windows prior to python 3.2
    # https://bugs.python.org/issue10027
    # Adapted from the ntfsutils package, Copyright (c) 2012, the Mozilla Foundation
    class CrossPlatformStLink(object):
        _st_nlink = None

        def __call__(self, path):
            return self.st_nlink(path)

        @classmethod
        def st_nlink(cls, path):
            if cls._st_nlink is None:
                cls._initialize()
            return cls._st_nlink(path)

        @classmethod
        def _standard_st_nlink(cls, path):
            return lstat(path).st_nlink

        @classmethod
        def _windows_st_nlink(cls, path):
            st_nlink = cls._standard_st_nlink(path)
            if st_nlink != 0:
                return st_nlink
            else:
                # cannot trust python on Windows when st_nlink == 0
                # get value using windows libraries to be sure of its true value
                # Adapted from the ntfsutils package, Copyright (c) 2012, the Mozilla Foundation
                GENERIC_READ = 0x80000000
                FILE_SHARE_READ = 0x00000001
                OPEN_EXISTING = 3
                hfile = cls.CreateFile(path, GENERIC_READ, FILE_SHARE_READ, None,
                                       OPEN_EXISTING, 0, None)
                if hfile is None:
                    from ctypes import WinError
                    raise WinError(
                        "Could not determine determine number of hardlinks for %s" % path)
                info = cls.BY_HANDLE_FILE_INFORMATION()
                rv = cls.GetFileInformationByHandle(hfile, info)
                cls.CloseHandle(hfile)
                if rv == 0:
                    from ctypes import WinError
                    raise WinError("Could not determine file information for %s" % path)
                return info.nNumberOfLinks

        @classmethod
        def _initialize(cls):
            if os.name != 'nt':
                cls._st_nlink = cls._standard_st_nlink
            else:
                # http://msdn.microsoft.com/en-us/library/windows/desktop/aa363858
                import ctypes
                from ctypes import POINTER
                from ctypes.wintypes import DWORD, HANDLE, BOOL

                cls.CreateFile = ctypes.windll.kernel32.CreateFileW
                cls.CreateFile.argtypes = [ctypes.c_wchar_p, DWORD, DWORD, ctypes.c_void_p,
                                           DWORD, DWORD, HANDLE]
                cls.CreateFile.restype = HANDLE

                # http://msdn.microsoft.com/en-us/library/windows/desktop/ms724211
                cls.CloseHandle = ctypes.windll.kernel32.CloseHandle
                cls.CloseHandle.argtypes = [HANDLE]
                cls.CloseHandle.restype = BOOL

                class FILETIME(ctypes.Structure):
                    _fields_ = [("dwLowDateTime", DWORD),
                                ("dwHighDateTime", DWORD)]

                class BY_HANDLE_FILE_INFORMATION(ctypes.Structure):
                    _fields_ = [("dwFileAttributes", DWORD),
                                ("ftCreationTime", FILETIME),
                                ("ftLastAccessTime", FILETIME),
                                ("ftLastWriteTime", FILETIME),
                                ("dwVolumeSerialNumber", DWORD),
                                ("nFileSizeHigh", DWORD),
                                ("nFileSizeLow", DWORD),
                                ("nNumberOfLinks", DWORD),
                                ("nFileIndexHigh", DWORD),
                                ("nFileIndexLow", DWORD)]

                cls.BY_HANDLE_FILE_INFORMATION = BY_HANDLE_FILE_INFORMATION

                # http://msdn.microsoft.com/en-us/library/windows/desktop/aa364952
                cls.GetFileInformationByHandle = ctypes.windll.kernel32.GetFileInformationByHandle
                cls.GetFileInformationByHandle.argtypes = [HANDLE,
                                                           POINTER(BY_HANDLE_FILE_INFORMATION)]
                cls.GetFileInformationByHandle.restype = BOOL

                cls._st_nlink = cls._windows_st_nlink
