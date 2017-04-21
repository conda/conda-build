# -*- coding: utf-8 -*-
from __future__ import absolute_import, division, print_function, unicode_literals

from functools import partial
import os
from os import lstat
from pkg_resources import parse_version
from enum import Enum

from conda import __version__ as CONDA_VERSION


try:
    # This monkey patch is addressed at #1825. The ensure_use_local is an outdated vestige
    #   and no longer has any relevant effect.
    import conda.cli.common
    conda.cli.common.ensure_use_local = lambda x: None
except ImportError:
    # no need to patch if it doesn't exist
    pass

from conda.plan import display_actions, execute_actions, execute_plan, install_actions

conda_43 = parse_version(CONDA_VERSION) >= parse_version("4.3")

display_actions, execute_actions, execute_plan = display_actions, execute_actions, execute_plan
install_actions = install_actions


if conda_43:
    from conda.exports import TmpDownload, download, handle_proxy_407  # NOQA
    from conda.exports import untracked, walk_prefix  # NOQA
    from conda.exports import MatchSpec, NoPackagesFound, Resolve, Unsatisfiable, normalized_version  # NOQA
    from conda.exports import human_bytes, hashsum_file, md5_file, memoized, unix_path_to_win, win_path_to_unix, url_path  # NOQA
    from conda.exports import get_index  # NOQA
    from conda.exports import (Completer, InstalledPackages, add_parser_channels,
                               add_parser_prefix,  # NOQA
                               specs_from_args, spec_from_line, specs_from_url)  # NOQA
    from conda.exports import ArgumentParser  # NOQA
    from conda.exports import (is_linked, linked, linked_data, prefix_placeholder,  # NOQA
                               rm_rf, symlink_conda, package_cache)  # NOQA
    from conda.exports import CondaSession  # NOQA
    from conda.exports import (PY3,  StringIO, input, iteritems, lchmod, string_types,  # NOQA
                              text_type, TemporaryDirectory)  # NOQA
    from conda.exports import VersionOrder  # NOQA
    from conda.exports import dist_str_in_index
    from conda.core.package_cache import ProgressiveFetchExtract
    from conda.models.dist import Dist, IndexRecord  # NOQA

else:
    from conda.fetch import TmpDownload, download, handle_proxy_407  # NOQA
    from conda.misc import untracked, walk_prefix  # NOQA
    from conda.resolve import MatchSpec, NoPackagesFound, Resolve, Unsatisfiable, normalized_version  # NOQA
    from conda.utils import human_bytes, hashsum_file, md5_file, memoized, unix_path_to_win, win_path_to_unix, url_path  # NOQA
    from conda.api import get_index  # NOQA
    from conda.cli.common import (Completer, InstalledPackages, add_parser_channels,
                                  add_parser_prefix,  # NOQA
                                  specs_from_args, spec_from_line, specs_from_url)  # NOQA
    from conda.cli.conda_argparse import ArgumentParser  # NOQA
    from conda.install import (is_linked, linked, linked_data, prefix_placeholder,  # NOQA
                               rm_rf, symlink_conda, package_cache)  # NOQA
    from conda.connection import CondaSession  # NOQA
    from conda.compat import (PY3, StringIO, input, iteritems, lchmod, string_types,  # NOQA
                              text_type, TemporaryDirectory)  # NOQA
    from conda.version import VersionOrder  # NOQA

    dist_str_in_index = lambda index, dist_str: dist_str in index

    class ProgressiveFetchExtract(object): pass  # NOQA
    class Dist(object): pass # NOQA
    class IndexRecord(object): pass # NOQA

TmpDownload = TmpDownload
download, handle_proxy_407, untracked, walk_prefix = download, handle_proxy_407, untracked, walk_prefix  # NOQA
MatchSpec, Resolve, normalized_version = MatchSpec, Resolve, normalized_version
human_bytes, hashsum_file, md5_file, memoized = human_bytes, hashsum_file, md5_file, memoized
unix_path_to_win, win_path_to_unix, url_path = unix_path_to_win, win_path_to_unix, url_path
get_index, Completer, InstalledPackages = get_index, Completer, InstalledPackages
add_parser_channels, add_parser_prefix = add_parser_channels, add_parser_prefix
specs_from_args, spec_from_line, specs_from_url = specs_from_args, spec_from_line, specs_from_url
is_linked, linked, linked_data, prefix_placeholder = is_linked, linked, linked_data, prefix_placeholder # NOQA
rm_rf, symlink_conda, package_cache = rm_rf, symlink_conda, package_cache
PY3, input, iteritems, lchmod, string_types = PY3, input, iteritems, lchmod, string_types
text_type, TemporaryDirectory = text_type, TemporaryDirectory
ArgumentParser, CondaSession, VersionOrder = ArgumentParser, CondaSession, VersionOrder
dist_str_in_index, ProgressiveFetchExtract = dist_str_in_index, ProgressiveFetchExtract
Dist = Dist


if PY3:
    import configparser  # NOQA
else:
    import ConfigParser as configparser  # NOQA
configparser = configparser


if conda_43:
    from conda.exports import FileMode, PathType
    FileMode, PathType = FileMode, PathType
    from conda.exports import EntityEncoder
    EntityEncoder = EntityEncoder
else:
    from json import JSONEncoder

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

EntityEncoder, FileMode, PathType = EntityEncoder, FileMode, PathType


if parse_version(CONDA_VERSION) >= parse_version("4.2"):
    from conda.exceptions import (CondaError, CondaHTTPError, LinkError, LockError,
                                  NoPackagesFoundError, PaddingError, UnsatisfiableError)

    from conda.base.context import non_x86_linux_machines
    from conda.base.context import context, get_prefix as context_get_prefix, reset_context
    binstar_upload = context.binstar_upload
    bits = context.bits
    conda_private = context.conda_private
    default_python = context.default_python
    envs_dirs = context.envs_dirs
    pkgs_dirs = list(context.pkgs_dirs)
    cc_platform = context.platform
    root_dir = context.root_dir
    root_writable = context.root_writable
    subdir = context.subdir

    get_rc_urls = lambda: list(context.channels)
    get_prefix = partial(context_get_prefix, context)
    cc_conda_build = context.conda_build if hasattr(context, 'conda_build') else {}

    # disallow softlinks.  This avoids a lot of dumb issues, at the potential cost of disk space.
    os.environ[str('CONDA_ALLOW_SOFTLINKS')] = str('false')
    reset_context()

    from conda.models.channel import get_conda_build_local_url
    get_local_urls = lambda: list(get_conda_build_local_url()) or []
    arch_name = context.arch_name

else:
    from conda import config as cc
    from conda.config import non_x86_linux_machines  # NOQA
    from conda.cli.common import get_prefix  # NOQA

    binstar_upload = cc.binstar_upload
    bits = cc.bits
    default_python = cc.default_python
    envs_dirs = cc.envs_dirs
    pkgs_dirs = list(cc.pkgs_dirs)
    cc_platform = cc.platform
    root_dir = cc.root_dir
    root_writable = cc.root_writable
    subdir = cc.subdir
    get_rc_urls = cc.get_rc_urls

    cc_conda_build = cc.rc.get('conda-build', {})

    del locals()['cc']

    class CondaHTTPError(Exception):
        pass

    class PaddingError(Exception):
        pass

    class LockError(Exception):
        pass

    class LinkError(Exception):
        pass

    class NoPackagesFoundError(Exception):
        pass

    class UnsatisfiableError(Exception):
        pass

    class CondaError(Exception):
        pass

    get_local_urls = cc.get_local_urls
    arch_name = cc.arch_name

CondaError, CondaHTTPError, get_prefix, LinkError = CondaError, CondaHTTPError, get_prefix, LinkError  # NOQA
LockError, non_x86_linux_machines, NoPackagesFoundError = LockError, non_x86_linux_machines, NoPackagesFoundError  # NOQA
PaddingError, UnsatisfiableError = PaddingError, UnsatisfiableError


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
    iteration = 0
    while iteration < 20:
        if isdir(join(prefix, 'conda-meta')):
            # we found the it, so let's return it
            break
        if prefix == dirname(prefix):
            # we cannot chop off any more directories, so we didn't find it
            prefix = None
            break
        prefix = dirname(prefix)
        iteration += 1
    return prefix


# when deactivating envs (e.g. switching from root to build/test) this env var is used,
# except the PR that removed this has been reverted (for now) and Windows doesnt need it.
env_path_backup_var_exists = os.environ.get('CONDA_PATH_BACKUP', None)
