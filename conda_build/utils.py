from __future__ import absolute_import, division, print_function

import base64
from collections import defaultdict
import contextlib
import fnmatch
from glob2 import glob
import json
from locale import getpreferredencoding
import logging
import logging.config
import mmap
import operator
import os
from os.path import dirname, getmtime, getsize, isdir, join, isfile, abspath, islink
import re
import stat
import subprocess
import sys
import shutil
import tarfile
import tempfile
import time
import yaml
import zipfile

from distutils.version import LooseVersion
import filelock

from conda import __version__ as conda_version

from .conda_interface import hashsum_file, md5_file, unix_path_to_win, win_path_to_unix
from .conda_interface import PY3, iteritems
from .conda_interface import root_dir, pkgs_dirs
from .conda_interface import string_types, url_path, get_rc_urls
from .conda_interface import memoized
from .conda_interface import StringIO
from .conda_interface import VersionOrder, MatchSpec
from .conda_interface import cc_conda_build
# NOQA because it is not used in this file.
from conda_build.conda_interface import rm_rf as _rm_rf # NOQA
from conda_build.os_utils import external

if PY3:
    import urllib.parse as urlparse
    import urllib.request as urllib
    # NOQA because it is not used in this file.
    from contextlib import ExitStack  # NOQA
    PermissionError = PermissionError  # NOQA
else:
    import urlparse
    import urllib
    # NOQA because it is not used in this file.
    from contextlib2 import ExitStack  # NOQA
    PermissionError = OSError


on_win = (sys.platform == 'win32')

codec = getpreferredencoding() or 'utf-8'
on_win = sys.platform == "win32"
root_script_dir = os.path.join(root_dir, 'Scripts' if on_win else 'bin')
mmap_MAP_PRIVATE = 0 if on_win else mmap.MAP_PRIVATE
mmap_PROT_READ = 0 if on_win else mmap.PROT_READ
mmap_PROT_WRITE = 0 if on_win else mmap.PROT_WRITE


PY_TMPL = """
# -*- coding: utf-8 -*-
import re
import sys

from %(module)s import %(import_name)s

if __name__ == '__main__':
    sys.argv[0] = re.sub(r'(-script\.pyw?|\.exe)?$', '', sys.argv[0])
    sys.exit(%(func)s())
"""


def get_recipe_abspath(recipe):
    """resolve recipe dir as absolute path.  If recipe is a tarball rather than a folder,
    extract it and return the extracted directory.

    Returns the absolute path, and a boolean flag that is true if a tarball has been extracted
    and needs cleanup.
    """
    # Don't use byte literals for paths in Python 2
    if not PY3:
        recipe = recipe.decode(getpreferredencoding() or 'utf-8')
    if isfile(recipe):
        if recipe.endswith(('.tar', '.tar.gz', '.tgz', '.tar.bz2')):
            recipe_dir = tempfile.mkdtemp()
            t = tarfile.open(recipe, 'r:*')
            t.extractall(path=recipe_dir)
            # At some stage the old build system started to tar up recipes.
            recipe_tarfile = os.path.join(recipe_dir, 'info', 'recipe.tar')
            if isfile(recipe_tarfile):
                t2 = tarfile.open(recipe_tarfile, 'r:*')
                t2.extractall(path=os.path.join(recipe_dir, 'info'))
                t2.close()
            t.close()
            need_cleanup = True
        else:
            print("Ignoring non-recipe: %s" % recipe)
            return (None, None)
    else:
        recipe_dir = abspath(os.path.join(os.getcwd(), recipe))
        need_cleanup = False
    if not os.path.exists(recipe_dir):
        raise ValueError("Package or recipe at path {0} does not exist".format(recipe_dir))
    return recipe_dir, need_cleanup


@contextlib.contextmanager
def try_acquire_locks(locks, timeout):
    """Try to acquire all locks.  If any lock can't be immediately acquired, free all locks

    http://stackoverflow.com/questions/9814008/multiple-mutex-locking-strategies-and-why-libraries-dont-use-address-comparison
    """
    t = time.time()
    while (time.time() - t < timeout):
        for lock in locks:
            try:
                lock.acquire(timeout=0.1)
            except filelock.Timeout:
                for lock in locks:
                    lock.release()
                break
        break
    yield
    for lock in locks:
        if lock:
            lock.release()


# with each of these, we are copying less metadata.  This seems to be necessary
#   to cope with some shared filesystems with some virtual machine setups.
#  See https://github.com/conda/conda-build/issues/1426
def _copy_with_shell_fallback(src, dst):
    is_copied = False
    for func in (shutil.copy2, shutil.copy, shutil.copyfile):
        try:
            func(src, dst)
            is_copied = True
            break
        except (IOError, OSError, PermissionError):
            continue
    if not is_copied:
        try:
            subprocess.check_call('cp -a {} {}'.format(src, dst), shell=True,
                                  stderr=subprocess.PIPE, stdout=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            if not os.path.isfile(dst):
                raise OSError("Failed to copy {} to {}.  Error was: {}".format(src, dst, e))


def get_prefix_replacement_paths(src, dst):
    ssplit = src.split(os.path.sep)
    dsplit = dst.split(os.path.sep)
    while ssplit and ssplit[-1] == dsplit[-1]:
        del ssplit[-1]
        del dsplit[-1]
    return os.path.join(*ssplit), os.path.join(*dsplit)


def copy_into(src, dst, timeout=90, symlinks=False, lock=None, locking=True, clobber=False):
    """Copy all the files and directories in src to the directory dst"""
    log = get_logger(__name__)
    if symlinks and islink(src):
        try:
            os.makedirs(os.path.dirname(dst))
        except OSError:
            pass
        if os.path.lexists(dst):
            os.remove(dst)
        src_base, dst_base = get_prefix_replacement_paths(src, dst)
        src_target = os.readlink(src)
        src_replaced = src_target.replace(src_base, dst_base)
        os.symlink(src_replaced, dst)
        try:
            st = os.lstat(src)
            mode = stat.S_IMODE(st.st_mode)
            os.lchmod(dst, mode)
        except:
            pass  # lchmod not available
    elif isdir(src):
        merge_tree(src, dst, symlinks, timeout=timeout, lock=lock, locking=locking, clobber=clobber)

    else:
        if isdir(dst):
            dst_fn = os.path.join(dst, os.path.basename(src))
        else:
            dst_fn = dst

        if os.path.isabs(src):
            src_folder = os.path.dirname(src)
        else:
            if os.path.sep in dst_fn:
                src_folder = os.path.dirname(dst_fn)
                if not os.path.isdir(src_folder):
                    os.makedirs(src_folder)
            else:
                src_folder = os.getcwd()

        if os.path.islink(src) and not os.path.exists(os.path.realpath(src)):
            log.warn('path %s is a broken symlink - ignoring copy', src)
            return

        if not lock and locking:
            lock = get_lock(src_folder, timeout=timeout)
        locks = [lock] if locking else []
        with try_acquire_locks(locks, timeout):
            # if intermediate folders not not exist create them
            dst_folder = os.path.dirname(dst)
            if dst_folder and not os.path.exists(dst_folder):
                try:
                    os.makedirs(dst_folder)
                except OSError:
                    pass
            try:
                _copy_with_shell_fallback(src, dst_fn)
            except shutil.Error:
                log.debug("skipping %s - already exists in %s",
                            os.path.basename(src), dst)


# http://stackoverflow.com/a/22331852/1170370
def copytree(src, dst, symlinks=False, ignore=None, dry_run=False):
    if not os.path.exists(dst):
        os.makedirs(dst)
        shutil.copystat(src, dst)
    lst = os.listdir(src)
    if ignore:
        excl = ignore(src, lst)
        lst = [x for x in lst if x not in excl]

    # do not copy lock files
    if '.conda_lock' in lst:
        lst.remove('.conda_lock')

    dst_lst = [os.path.join(dst, item) for item in lst]

    if not dry_run:
        for idx, item in enumerate(lst):
            s = os.path.join(src, item)
            d = dst_lst[idx]
            if symlinks and os.path.islink(s):
                if os.path.lexists(d):
                    os.remove(d)
                os.symlink(os.readlink(s), d)
                try:
                    st = os.lstat(s)
                    mode = stat.S_IMODE(st.st_mode)
                    os.lchmod(d, mode)
                except:
                    pass  # lchmod not available
            elif os.path.isdir(s):
                copytree(s, d, symlinks, ignore)
            else:
                _copy_with_shell_fallback(s, d)

    return dst_lst


def merge_tree(src, dst, symlinks=False, timeout=90, lock=None, locking=True, clobber=False):
    """
    Merge src into dst recursively by copying all files from src into dst.
    Return a list of all files copied.

    Like copytree(src, dst), but raises an error if merging the two trees
    would overwrite any files.
    """
    dst = os.path.normpath(os.path.normcase(dst))
    src = os.path.normpath(os.path.normcase(src))
    assert not dst.startswith(src), ("Can't merge/copy source into subdirectory of itself.  "
                                     "Please create separate spaces for these things.")

    new_files = copytree(src, dst, symlinks=symlinks, dry_run=True)
    existing = [f for f in new_files if isfile(f)]

    if existing and not clobber:
        raise IOError("Can't merge {0} into {1}: file exists: "
                      "{2}".format(src, dst, existing[0]))

    locks = []
    if locking:
        if not lock:
            lock = get_lock(src, timeout=timeout)
        locks = [lock]
    with try_acquire_locks(locks, timeout):
        copytree(src, dst, symlinks=symlinks)


# purpose here is that we want *one* lock per location on disk.  It can be locked or unlocked
#    at any time, but the lock within this process should all be tied to the same tracking
#    mechanism.
_lock_folders = (os.path.join(root_dir, 'locks'),
                 os.path.expanduser(os.path.join('~', '.conda_build_locks')))


def get_lock(folder, timeout=90):
    fl = None
    try:
        location = os.path.abspath(os.path.normpath(folder))
    except OSError:
        location = folder
    b_location = location
    if hasattr(b_location, 'encode'):
        b_location = b_location.encode()
    lock_filename = base64.urlsafe_b64encode(b_location)[:20]
    if hasattr(lock_filename, 'decode'):
        lock_filename = lock_filename.decode()
    for locks_dir in _lock_folders:
        try:
            if not os.path.isdir(locks_dir):
                os.makedirs(locks_dir)
            lock_file = os.path.join(locks_dir, lock_filename)
            with open(lock_file, 'w') as f:
                f.write("")
            fl = filelock.FileLock(lock_file, timeout)
            break
        except (OSError, IOError):
            continue
    else:
        raise RuntimeError("Could not write locks folder to either system location ({0})"
                           "or user location ({1}).  Aborting.".format(*_lock_folders))
    return fl


def get_conda_operation_locks(locking=True, bldpkgs_dirs=None, timeout=90):
    locks = []
    bldpkgs_dirs = ensure_list(bldpkgs_dirs)
    # locks enabled by default
    if locking:
        _pkgs_dirs = pkgs_dirs[:1]
        locked_folders = _pkgs_dirs + list(bldpkgs_dirs)
        for folder in locked_folders:
            if not os.path.isdir(folder):
                os.makedirs(folder)
            lock = get_lock(folder, timeout=timeout)
            locks.append(lock)
        # lock used to generally indicate a conda operation occurring
        locks.append(get_lock('conda-operation', timeout=timeout))
    return locks


def relative(f, d='lib'):
    assert not f.startswith('/'), f
    assert not d.startswith('/'), d
    d = d.strip('/').split('/')
    if d == ['.']:
        d = []
    f = dirname(f).split('/')
    if f == ['']:
        f = []
    while d and f and d[0] == f[0]:
        d.pop(0)
        f.pop(0)
    return '/'.join(((['..'] * len(f)) if f else ['.']) + d)


def tar_xf(tarball, dir_path, mode='r:*'):
    if tarball.lower().endswith('.tar.z'):
        uncompress = external.find_executable('uncompress')
        if not uncompress:
            uncompress = external.find_executable('gunzip')
        if not uncompress:
            sys.exit("""\
uncompress (or gunzip) is required to unarchive .z source files.
""")
        check_call_env([uncompress, '-f', tarball])
        tarball = tarball[:-2]
    if not PY3 and tarball.endswith('.tar.xz'):
        unxz = external.find_executable('unxz')
        if not unxz:
            sys.exit("""\
unxz is required to unarchive .xz source files.
""")

        check_call_env([unxz, '-f', '-k', tarball])
        tarball = tarball[:-3]
    t = tarfile.open(tarball, mode)
    if not PY3:
        t.extractall(path=dir_path.encode(codec))
    else:
        t.extractall(path=dir_path)
    t.close()


def unzip(zip_path, dir_path):
    z = zipfile.ZipFile(zip_path)
    for info in z.infolist():
        name = info.filename
        if name.endswith('/'):
            continue
        path = join(dir_path, *name.split('/'))
        dp = dirname(path)
        if not isdir(dp):
            os.makedirs(dp)
        with open(path, 'wb') as fo:
            fo.write(z.read(name))
        unix_attributes = info.external_attr >> 16
        if unix_attributes:
            os.chmod(path, unix_attributes)
    z.close()


def file_info(path):
    return {'size': getsize(path),
            'md5': md5_file(path),
            'sha256': hashsum_file(path, 'sha256'),
            'mtime': getmtime(path)}

# Taken from toolz


def groupby(key, seq):
    """ Group a collection by a key function
    >>> names = ['Alice', 'Bob', 'Charlie', 'Dan', 'Edith', 'Frank']
    >>> groupby(len, names)  # doctest: +SKIP
    {3: ['Bob', 'Dan'], 5: ['Alice', 'Edith', 'Frank'], 7: ['Charlie']}
    >>> iseven = lambda x: x % 2 == 0
    >>> groupby(iseven, [1, 2, 3, 4, 5, 6, 7, 8])  # doctest: +SKIP
    {False: [1, 3, 5, 7], True: [2, 4, 6, 8]}
    Non-callable keys imply grouping on a member.
    >>> groupby('gender', [{'name': 'Alice', 'gender': 'F'},
    ...                    {'name': 'Bob', 'gender': 'M'},
    ...                    {'name': 'Charlie', 'gender': 'M'}]) # doctest:+SKIP
    {'F': [{'gender': 'F', 'name': 'Alice'}],
     'M': [{'gender': 'M', 'name': 'Bob'},
           {'gender': 'M', 'name': 'Charlie'}]}
    See Also:
        countby
    """
    if not callable(key):
        key = getter(key)
    d = defaultdict(lambda: [].append)
    for item in seq:
        d[key(item)](item)
    rv = {}
    for k, v in iteritems(d):
        rv[k] = v.__self__
    return rv


def getter(index):
    if isinstance(index, list):
        if len(index) == 1:
            index = index[0]
            return lambda x: (x[index],)
        elif index:
            return operator.itemgetter(*index)
        else:
            return lambda x: ()
    else:
        return operator.itemgetter(index)


def comma_join(items):
    """
    Like ', '.join(items) but with and

    Examples:

    >>> comma_join(['a'])
    'a'
    >>> comma_join(['a', 'b'])
    'a and b'
    >>> comma_join(['a', 'b', 'c])
    'a, b, and c'
    """
    return ' and '.join(items) if len(items) <= 2 else ', '.join(items[:-1]) + ', and ' + items[-1]


def safe_print_unicode(*args, **kwargs):
    """
    prints unicode strings to stdout using configurable `errors` handler for
    encoding errors

    :param args: unicode strings to print to stdout
    :param sep: separator (defaults to ' ')
    :param end: ending character (defaults to '\n')
    :param errors: error handler for encoding errors (defaults to 'replace')
    """
    sep = kwargs.pop('sep', u' ')
    end = kwargs.pop('end', u'\n')
    errors = kwargs.pop('errors', 'replace')
    if PY3:
        func = sys.stdout.buffer.write
    else:
        func = sys.stdout.write
    line = sep.join(args) + end
    encoding = sys.stdout.encoding or 'utf8'
    func(line.encode(encoding, errors))


def rec_glob(path, patterns):
    result = []
    for d_f in os.walk(path):
        # ignore the .git folder
        # if '.git' in d_f[0]:
        #     continue
        m = []
        for pattern in patterns:
            m.extend(fnmatch.filter(d_f[2], pattern))
        if m:
            result.extend([os.path.join(d_f[0], f) for f in m])
    return result


def convert_unix_path_to_win(path):
    if external.find_executable('cygpath'):
        cmd = "cygpath -w {0}".format(path)
        if PY3:
            path = subprocess.getoutput(cmd)
        else:
            path = subprocess.check_output(cmd.split()).rstrip().rstrip("\\")

    else:
        path = unix_path_to_win(path)
    return path


def convert_win_path_to_unix(path):
    if external.find_executable('cygpath'):
        cmd = "cygpath -u {0}".format(path)
        if PY3:
            path = subprocess.getoutput(cmd)
        else:
            path = subprocess.check_output(cmd.split()).rstrip().rstrip("\\")

    else:
        path = win_path_to_unix(path)
    return path


# Used for translating local paths into url (file://) paths
#   http://stackoverflow.com/a/14298190/1170370
def path2url(path):
    return urlparse.urljoin('file:', urllib.pathname2url(path))


def get_stdlib_dir(prefix, py_ver):
    if sys.platform == 'win32':
        lib_dir = os.path.join(prefix, 'Lib')
    else:
        lib_dir = os.path.join(prefix, 'lib', 'python{}'.format(py_ver))
    return lib_dir


def get_site_packages(prefix, py_ver):
    return os.path.join(get_stdlib_dir(prefix, py_ver), 'site-packages')


def get_build_folders(croot):
    # remember, glob is not a regex.
    return glob(os.path.join(croot, "*" + "[0-9]" * 10 + "*"))


def prepend_bin_path(env, prefix, prepend_prefix=False):
    # bin_dirname takes care of bin on *nix, Scripts on win
    env['PATH'] = join(prefix, bin_dirname) + os.pathsep + env['PATH']
    if sys.platform == "win32":
        env['PATH'] = join(prefix, "Library", "mingw-w64", "bin") + os.pathsep + \
                      join(prefix, "Library", "usr", "bin") + os.pathsep + os.pathsep + \
                      join(prefix, "Library", "bin") + os.pathsep + \
                      join(prefix, "Scripts") + os.pathsep + \
                      env['PATH']
        prepend_prefix = True  # windows has Python in the prefix.  Use it.
    if prepend_prefix:
        env['PATH'] = prefix + os.pathsep + env['PATH']
    return env


# not currently used.  Leaving in because it may be useful for when we do things
#   like load setup.py data, and we need the modules from some prefix other than
#   the root prefix, which is what conda-build runs from.
@contextlib.contextmanager
def sys_path_prepended(prefix):
    path_backup = sys.path[:]
    if on_win:
        sys.path.insert(1, os.path.join(prefix, 'lib', 'site-packages'))
    else:
        lib_dir = os.path.join(prefix, 'lib')
        python_dir = glob(os.path.join(lib_dir, 'python[0-9\.]*'))
        if python_dir:
            python_dir = python_dir[0]
            sys.path.insert(1, os.path.join(python_dir, 'site-packages'))
    try:
        yield
    finally:
        sys.path = path_backup


@contextlib.contextmanager
def path_prepended(prefix):
    old_path = os.environ['PATH']
    os.environ['PATH'] = prepend_bin_path(os.environ.copy(), prefix, True)['PATH']
    try:
        yield
    finally:
        os.environ['PATH'] = old_path


bin_dirname = 'Scripts' if sys.platform == 'win32' else 'bin'

entry_pat = re.compile('\s*([\w\-\.]+)\s*=\s*([\w.]+):([\w.]+)\s*$')


def iter_entry_points(items):
    for item in items:
        m = entry_pat.match(item)
        if m is None:
            sys.exit("Error cound not match entry point: %r" % item)
        yield m.groups()


def create_entry_point(path, module, func, config):
    import_name = func.split('.')[0]
    pyscript = PY_TMPL % {
        'module': module, 'func': func, 'import_name': import_name}
    if on_win:
        with open(path + '-script.py', 'w') as fo:
            if os.path.isfile(os.path.join(config.host_prefix, 'python_d.exe')):
                fo.write('#!python_d\n')
            fo.write(pyscript)
            arch = config.host_arch or config.arch
            copy_into(join(dirname(__file__), 'cli-{}.exe'.format(arch)),
                    path + '.exe', config.timeout)
    else:
        if os.path.islink(path):
            os.remove(path)
        with open(path, 'w') as fo:
            if not config.noarch:
                fo.write('#!%s\n' % config.build_python)
            fo.write(pyscript)
        os.chmod(path, 0o775)


def create_entry_points(items, config):
    if not items:
        return
    bin_dir = join(config.host_prefix, bin_dirname)
    if not isdir(bin_dir):
        os.mkdir(bin_dir)
    for cmd, module, func in iter_entry_points(items):
        create_entry_point(join(bin_dir, cmd), module, func, config)


# Return all files in dir, and all its subdirectories, ending in pattern
def get_ext_files(start_path, pattern):
    for root, _, files in os.walk(start_path):
        for f in files:
            if f.endswith(pattern):
                yield os.path.join(root, f)


def _func_defaulting_env_to_os_environ(func, *popenargs, **kwargs):
    if 'env' not in kwargs:
        kwargs = kwargs.copy()
        env_copy = os.environ.copy()
        kwargs.update({'env': env_copy})
    kwargs['env'] = {str(key): str(value) for key, value in kwargs['env'].items()}
    _args = []
    if 'stdin' not in kwargs:
        kwargs['stdin'] = subprocess.PIPE
    for arg in popenargs:
        # arguments to subprocess need to be bytestrings
        if sys.version_info.major < 3 and hasattr(arg, 'encode'):
            arg = arg.encode(codec)
        elif sys.version_info.major >= 3 and hasattr(arg, 'decode'):
            arg = arg.decode(codec)
        _args.append(str(arg))
    return func(_args, **kwargs)


def check_call_env(popenargs, **kwargs):
    return _func_defaulting_env_to_os_environ(subprocess.check_call, *popenargs, **kwargs)


def check_output_env(popenargs, **kwargs):
    return _func_defaulting_env_to_os_environ(subprocess.check_output, *popenargs, **kwargs)\
        .rstrip()


_posix_exes_cache = {}


def convert_path_for_cygwin_or_msys2(exe, path):
    "If exe is a Cygwin or MSYS2 executable then filters it through `cygpath -u`"
    if sys.platform != 'win32':
        return path
    if exe not in _posix_exes_cache:
        with open(exe, "rb") as exe_file:
            exe_binary = exe_file.read()
            msys2_cygwin = re.findall(b'(cygwin1.dll|msys-2.0.dll)', exe_binary)
            _posix_exes_cache[exe] = True if msys2_cygwin else False
    if _posix_exes_cache[exe]:
        try:
            path = check_output_env(['cygpath', '-u',
                                     path]).splitlines()[0].decode(getpreferredencoding())
        except WindowsError:
            log = get_logger(__name__)
            log.debug('cygpath executable not found.  Passing native path.  This is OK for msys2.')
    return path


def print_skip_message(metadata):
    print("Skipped: {} defines build/skip for this "
          "configuration.".format(metadata.path))


@memoized
def package_has_file(package_path, file_path):
    try:
        locks = get_conda_operation_locks()
        with try_acquire_locks(locks, timeout=90):
            with tarfile.open(package_path) as t:
                try:
                    # internal paths are always forward slashed on all platforms
                    file_path = file_path.replace('\\', '/')
                    text = t.extractfile(file_path).read()
                    return text
                except KeyError:
                    return False
                except OSError as e:
                    raise RuntimeError("Could not extract %s (%s)" % (package_path, e))
    except tarfile.ReadError:
        raise RuntimeError("Could not extract metadata from %s. "
                            "File probably corrupt." % package_path)


def ensure_list(arg):
    if (isinstance(arg, string_types) or not hasattr(arg, '__iter__')):
        if arg:
            arg = [arg]
        else:
            arg = []
    return arg


@contextlib.contextmanager
def tmp_chdir(dest):
    curdir = os.getcwd()
    try:
        os.chdir(dest)
        yield
    finally:
        os.chdir(curdir)


def expand_globs(path_list, root_dir):
    log = get_logger(__name__)
    files = []
    for path in path_list:
        if not os.path.isabs(path):
            path = os.path.join(root_dir, path)
        if os.path.islink(path):
            files.append(path.replace(root_dir + os.path.sep, ''))
        elif os.path.isdir(path):
            files.extend(os.path.join(root, f).replace(root_dir + os.path.sep, '')
                            for root, _, fs in os.walk(path) for f in fs)
        elif os.path.isfile(path):
            files.append(path.replace(root_dir + os.path.sep, ''))
        else:
            # File compared to the globs use / as separator indenpendently of the os
            glob_files = [f.replace(root_dir + os.path.sep, '')
                          for f in glob(path)]
            if not glob_files:
                log.error('invalid recipe path: {}'.format(path))
            files.extend(glob_files)
    files = [f.replace(os.path.sep, '/') for f in files]
    return files


def find_recipe(path):
    """recurse through a folder, locating meta.yaml.  Raises error if more than one is found.

    Returns folder containing meta.yaml, to be built.

    If we have a base level meta.yaml and other supplemental ones, use that first"""
    if os.path.isfile(path) and os.path.basename(path) in ["meta.yaml", "conda.yaml"]:
        return os.path.dirname(path)
    results = rec_glob(path, ["meta.yaml", "conda.yaml"])
    if len(results) > 1:
        base_recipe = os.path.join(path, "meta.yaml")
        if base_recipe in results:
            get_logger(__name__).warn("Multiple meta.yaml files found. "
                                      "The meta.yaml file in the base directory "
                                      "will be used.")
            results = [base_recipe]
        else:
            raise IOError("More than one meta.yaml files found in %s" % path)
    elif not results:
        raise IOError("No meta.yaml or conda.yaml files found in %s" % path)
    return results[0]


class LoggingContext(object):
    loggers = ['conda', 'binstar', 'install', 'conda.install', 'fetch', 'conda.instructions',
               'fetch.progress', 'print', 'progress', 'dotupdate', 'stdoutlog', 'requests',
               'conda.core.package_cache', 'conda.plan', 'conda.gateways.disk.delete']

    def __init__(self, level=logging.WARN, handler=None, close=True):
        self.level = level
        self.old_levels = {}
        self.handler = handler
        self.close = close

    def __enter__(self):
        for logger in LoggingContext.loggers:
            log = logging.getLogger(logger)
            self.old_levels[logger] = log.level
            log.setLevel(self.level if ('install' not in logger or
                                        self.level < logging.INFO) else self.level + 10)
        if self.handler:
            self.logger.addHandler(self.handler)

    def __exit__(self, et, ev, tb):
        for logger, level in self.old_levels.items():
            logging.getLogger(logger).setLevel(level)
        if self.handler:
            self.logger.removeHandler(self.handler)
        if self.handler and self.close:
            self.handler.close()
        # implicit return of None => don't swallow exceptions


def get_installed_packages(path):
    '''
    Scan all json files in 'path' and return a dictionary with their contents.
    Files are assumed to be in 'index.json' format.
    '''
    installed = dict()
    for filename in glob(os.path.join(path, 'conda-meta', '*.json')):
        with open(filename) as file:
            data = json.load(file)
            installed[data['name']] = data
    return installed


def _convert_lists_to_sets(_dict):
    for k, v in _dict.items():
        if hasattr(v, 'keys'):
            _dict[k] = HashableDict(_convert_lists_to_sets(v))
        elif hasattr(v, '__iter__') and not isinstance(v, string_types):
            try:
                _dict[k] = sorted(list(set(v)))
            except TypeError:
                _dict[k] = sorted(list(set(tuple(_) for _ in v)))
    return _dict


class HashableDict(dict):
    """use hashable frozen dictionaries for resources and resource types so that they can be in sets
    """
    def __init__(self, *args, **kwargs):
        super(HashableDict, self).__init__(*args, **kwargs)
        self = _convert_lists_to_sets(self)

    def __hash__(self):
        return hash(json.dumps(self, sort_keys=True))


def represent_hashabledict(dumper, data):
    value = []

    for item_key, item_value in data.items():
        node_key = dumper.represent_data(item_key)
        node_value = dumper.represent_data(item_value)

        value.append((node_key, node_value))

    return yaml.nodes.MappingNode(u'tag:yaml.org,2002:map', value)


yaml.add_representer(HashableDict, represent_hashabledict)


# http://stackoverflow.com/a/10743550/1170370
@contextlib.contextmanager
def capture():
    import sys
    oldout, olderr = sys.stdout, sys.stderr
    try:
        out = [StringIO(), StringIO()]
        sys.stdout, sys.stderr = out
        yield out
    finally:
        sys.stdout, sys.stderr = oldout, olderr
        out[0] = out[0].getvalue()
        out[1] = out[1].getvalue()


# copied from conda; added in 4.3, not currently part of exported functionality
@contextlib.contextmanager
def env_var(name, value, callback=None):
    # NOTE: will likely want to call reset_context() when using this function, so pass
    #       it as callback
    name, value = str(name), str(value)
    saved_env_var = os.environ.get(name)
    try:
        os.environ[name] = value
        if callback:
            callback()
        yield
    finally:
        if saved_env_var:
            os.environ[name] = saved_env_var
        else:
            del os.environ[name]
        if callback:
            callback()


def collect_channels(config, is_host=False):
    urls = [url_path(config.croot)] + get_rc_urls() + ['local', ]
    if config.channel_urls:
        urls.extend(config.channel_urls)
    # defaults has a very limited set of repo urls.  Omit it from the URL list so
    #     that it doesn't fail.
    if config.is_cross and is_host:
        urls.remove('defaults')
        urls.remove('local')
    return urls


def trim_empty_keys(dict_):
    to_remove = set()
    negative_means_empty = ('final', 'noarch_python', 'zip_keys')
    for k, v in dict_.items():
        if hasattr(v, 'keys'):
            trim_empty_keys(v)
        # empty lists and empty strings, and None are always empty.
        if v == list() or v == '' or v is None or v == dict():
            to_remove.add(k)
        # other things that evaluate as False may not be "empty" - things can be manually set to
        #     false, and we need to keep that setting.
        if not v and k in negative_means_empty:
            to_remove.add(k)
    if 'zip_keys' in dict_ and not any(v for v in dict_['zip_keys']):
        to_remove.add('zip_keys')
    for k in to_remove:
        del dict_[k]


def conda_43():
    """Conda 4.3 broke compatibility in lots of new fun and exciting ways.  This function is for
    changing conda-build's behavior when conda 4.3 or higher is installed."""
    return LooseVersion(conda_version) >= LooseVersion('4.3')


def _increment(version, alpha_ver):
    try:
        if alpha_ver:
            suffix = 'a'
        else:
            suffix = '.0a0'
        last_version = str(int(version) + 1) + suffix
    except ValueError:
        last_version = chr(ord(version) + 1)
    return last_version


def apply_pin_expressions(version, min_pin='x.x.x.x.x.x.x', max_pin='x'):
    pins = [len(p.split('.')) if p else None for p in (min_pin, max_pin)]
    parsed_version = VersionOrder(version).version[1:]
    nesting_position = None
    flat_list = []
    for idx, item in enumerate(parsed_version):
        if isinstance(item, list):
            nesting_position = idx
            flat_list.extend(item)
        else:
            flat_list.append(item)
    versions = ['', '']
    # first idx is lower bound pin; second is upper bound pin.
    #    pin value is number of places to pin.
    for p_idx, pin in enumerate(pins):
        if pin:
            # flat_list is the blown-out representation of the version
            for v_idx, v in enumerate(flat_list[:pin]):
                # upper bound pin
                if p_idx == 1 and v_idx == pin - 1:
                    # is the last place an alphabetic character?  OpenSSL, JPEG
                    alpha_ver = str(flat_list[min(pin, len(flat_list) - 1)]).isalpha()
                    v = _increment(v, alpha_ver)
                versions[p_idx] += str(v)
                if v_idx != nesting_position:
                    versions[p_idx] += '.'
            if versions[p_idx][-1] == '.':
                versions[p_idx] = versions[p_idx][:-1]
    if versions[0]:
        versions[0] = '>=' + versions[0]
    if versions[1]:
        versions[1] = '<' + versions[1]
    return ','.join([v for v in versions if v])


def filter_files(files_list, prefix, filter_patterns=('(.*[\\\\/])?\.git[\\\\/].*',
                                                      '(.*[\\\\/])?\.git$',
                                                      '(.*)?\.DS_Store.*',
                                                      '(.*)?\.gitignore',
                                                      'conda-meta.*',
                                                      '(.*)?\.gitmodules')):
    """Remove things like .git from the list of files to be copied"""
    for pattern in filter_patterns:
        r = re.compile(pattern)
        files_list = set(files_list) - set(filter(r.match, files_list))
    return [f.replace(prefix + os.path.sep, '') for f in files_list
            if not os.path.isdir(os.path.join(prefix, f)) or
            os.path.islink(os.path.join(prefix, f))]


def rm_rf(path, config=None):
    if on_win:
        # native windows delete is potentially much faster
        try:
            if os.path.isfile(path):
                subprocess.check_call('del {}'.format(path), shell=True)
            elif os.path.isdir(path):
                subprocess.check_call('rd /s /q {}'.format(path), shell=True)
            else:
                pass
        except subprocess.CalledProcessError:
            pass
    conda_log_level = logging.WARN
    if config and config.debug:
        conda_log_level = logging.DEBUG
    with LoggingContext(conda_log_level):
        _rm_rf(path)


# https://stackoverflow.com/a/31459386/1170370
class LessThanFilter(logging.Filter):
    def __init__(self, exclusive_maximum, name=""):
        super(LessThanFilter, self).__init__(name)
        self.max_level = exclusive_maximum

    def filter(self, record):
        # non-zero return means we log this message
        return 1 if record.levelno < self.max_level else 0


class GreaterThanFilter(logging.Filter):
    def __init__(self, exclusive_minimum, name=""):
        super(GreaterThanFilter, self).__init__(name)
        self.min_level = exclusive_minimum

    def filter(self, record):
        # non-zero return means we log this message
        return 1 if record.levelno > self.min_level else 0


# unclutter logs - show messages only once
class DuplicateFilter(logging.Filter):
    def __init__(self):
        self.msgs = set()

    def filter(self, record):
        log = record.msg not in self.msgs
        self.msgs.add(record.msg)
        return int(log)


dedupe_filter = DuplicateFilter()
info_debug_stdout_filter = LessThanFilter(logging.WARNING)
warning_error_stderr_filter = GreaterThanFilter(logging.INFO)


def reset_deduplicator():
    """Most of the time, we want the deduplication.  There are some cases (tests especially)
    where we want to be able to control the duplication."""
    global dedupe_filter
    dedupe_filter = DuplicateFilter()


def get_logger(name, level=logging.INFO, dedupe=True, add_stdout_stderr_handlers=True):
    config_file = cc_conda_build.get('log_config_file')
    # by loading config file here, and then only adding handlers later, people
    # should be able to override conda-build's logger settings here.
    if config_file:
        with open(config_file) as f:
            config_dict = yaml.safe_load(f)
        logging.config.dictConfig(config_dict)
        level = config_dict.get('loggers', {}).get(name, {}).get('level', level)
    log = logging.getLogger(name)
    log.setLevel(level)
    if dedupe:
        log.addFilter(dedupe_filter)

    # these are defaults.  They can be overridden by configuring a log config yaml file.
    if not log.handlers and add_stdout_stderr_handlers:
        stdout_handler = logging.StreamHandler(sys.stdout)
        stderr_handler = logging.StreamHandler(sys.stderr)
        stdout_handler.addFilter(info_debug_stdout_filter)
        stderr_handler.addFilter(warning_error_stderr_filter)
        stdout_handler.setLevel(level)
        stderr_handler.setLevel(level)
        log.addHandler(stdout_handler)
        log.addHandler(stderr_handler)
    return log


def _equivalent(base_value, value, path):
    equivalent = value == base_value
    if isinstance(value, string_types) and isinstance(base_value, string_types):
        if not os.path.isabs(base_value):
            base_value = os.path.abspath(os.path.normpath(os.path.join(path, base_value)))
        if not os.path.isabs(value):
            value = os.path.abspath(os.path.normpath(os.path.join(path, value)))
        equivalent |= base_value == value
    return equivalent


def merge_or_update_dict(base, new, path, merge, raise_on_clobber=False):
    log = get_logger(__name__)
    for key, value in new.items():
        base_value = base.get(key, value)
        if hasattr(value, 'keys'):
            base_value = merge_or_update_dict(base_value, value, path, merge,
                                              raise_on_clobber=raise_on_clobber)
            base[key] = base_value
        elif hasattr(value, '__iter__') and not isinstance(value, string_types):
            if merge:
                if base_value and base_value != value:
                    base_value.extend(value)
                try:
                    base[key] = list(set(base_value))
                except TypeError:
                    base[key] = base_value
            else:
                base[key] = value
        else:
            if (base_value and merge and not _equivalent(base_value, value, path) and
                    raise_on_clobber):
                log.debug('clobbering key {} (original value {}) with value {}'.format(key,
                                                                            base_value, value))
            base[key] = value
    return base


def merge_dicts_of_lists(dol1, dol2):
    '''
    From Alex Martelli: https://stackoverflow.com/a/1495821/3257826
    '''
    keys = set(dol1).union(dol2)
    no = []
    return dict((k, dol1.get(k, no) + dol2.get(k, no)) for k in keys)


def prefix_files(prefix):
    '''
    Returns a set of all files in prefix.
    '''
    res = set()
    for root, dirs, files in os.walk(prefix):
        for fn in files:
            res.add(join(root, fn)[len(prefix) + 1:])
        for dn in dirs:
            path = join(root, dn)
            if islink(path):
                res.add(path[len(prefix) + 1:])
    res = set(expand_globs(res, prefix))
    return res


def mmap_mmap(fileno, length, tagname=None, flags=0, prot=mmap_PROT_READ | mmap_PROT_WRITE,
              access=None, offset=0):
    '''
    Hides the differences between mmap.mmap on Windows and Unix.
    Windows has `tagname`.
    Unix does not, but makes up for it with `flags` and `prot`.
    On both, the defaule value for `access` is determined from how the file
    was opened so must not be passed in at all to get this default behaviour
    '''
    if on_win:
        if access:
            return mmap.mmap(fileno, length, tagname=tagname, access=access, offset=offset)
        else:
            return mmap.mmap(fileno, length, tagname=tagname)
    else:
        if access:
            return mmap.mmap(fileno, length, flags=flags, prot=prot, access=access, offset=offset)
        else:
            return mmap.mmap(fileno, length, flags=flags, prot=prot)


def remove_pycache_from_scripts(build_prefix):
    """Remove pip created pycache directory from bin or Scripts."""
    if on_win:
        scripts_path = os.path.join(build_prefix, 'Scripts')
    else:
        scripts_path = os.path.join(build_prefix, 'bin')

    for entry in os.listdir(scripts_path):
        entry_path = os.path.join(scripts_path, entry)
        if os.path.isdir(entry_path) and entry.strip(os.sep) == '__pycache__':
            shutil.rmtree(entry_path)

        elif os.path.isfile(entry_path) and entry_path.endswith('.pyc'):
            os.remove(entry_path)


def sort_list_in_nested_structure(dictionary, omissions=''):
    """Recurse through a nested dictionary and sort any lists that are found.

    If the list that is found contains anything but strings, it is skipped
    as we can't compare lists containing different types. The omissions argument
    allows for certain sections of the dictionary to be omitted from sorting.
    """
    for field, value in dictionary.items():
        if isinstance(value, dict):
            for key in value.keys():
                section = dictionary[field][key]
                if isinstance(section, dict):
                    sort_list_in_nested_structure(section)
                elif (isinstance(section, list) and
                    '{}/{}' .format(field, key) not in omissions and
                        all(isinstance(item, str) for item in section)):
                    section.sort()

        # there's a possibility for nested lists containing dictionaries
        # in this case we recurse until we find a list to sort
        elif isinstance(value, list):
            for element in value:
                if isinstance(element, dict):
                    sort_list_in_nested_structure(element)
            try:
                value.sort()
            except TypeError:
                pass


# group one: package name
# group two: version (allows _, +, . in version)
# group three: build string - mostly not used here.  Match primarily matters
#        to specify when not to add .*

# if you are seeing mysterious unsatisfiable errors, with the package you're building being the
#    unsatisfiable part, then you probably need to update this regex.

spec_needing_star_re = re.compile(r"([\w\d\.\-\_]+)\s+((?<![><=])[\w\d\.\-\_]+?(?!\*))(\s+[\w\d\.\_]+)?$")  # NOQA
spec_ver_needing_star_re = re.compile("^([0-9a-zA-Z\.]+)$")


def ensure_valid_spec(spec, warn=False):
    if isinstance(spec, MatchSpec):
        if (hasattr(spec, 'version') and spec.version and
                spec_ver_needing_star_re.match(str(spec.version))):
            if str(spec.name) not in ('python', 'numpy') or str(spec.version) != 'x.x':
                spec = MatchSpec("{} {}".format(str(spec.name), str(spec.version) + '.*'))
    else:
        match = spec_needing_star_re.match(spec)
        # ignore exact pins (would be a 3rd group)
        if match and not match.group(3):
            if match.group(1) in ('python', 'numpy') and match.group(2) == 'x.x':
                spec = spec_needing_star_re.sub(r"\1 \2", spec)
            else:
                if "*" not in spec:
                    if match.group(1) != 'python' and warn:
                        log = get_logger(__name__)
                        log.warn("Adding .* to spec '{}' to ensure satisfiability.  Please "
                                 "consider putting {{{{ var_name }}}}.* or some relational "
                                 "operator (>/</>=/<=) on this spec in meta.yaml, or if req is "
                                 "also a build req, using {{{{ pin_compatible() }}}} jinja2 "
                                 "function instead.  See "
                "https://conda.io/docs/user-guide/tasks/build-packages/variants.html#pinning-at-the-variant-level"  # NOQA
                        .format(spec))
                    spec = spec_needing_star_re.sub(r"\1 \2.*", spec)
    return spec


def insert_variant_versions(metadata, env):
    reqs = metadata.get_value('requirements/' + env)
    for key, val in metadata.config.variant.items():
        regex = re.compile(r'^(%s)(?:\s*$)' % key.replace('_', '[-_]'))
        matches = [regex.match(pkg) for pkg in reqs]
        if any(matches):
            for i, x in enumerate(matches):
                if x:
                    del reqs[i]
                    reqs.insert(i, ensure_valid_spec(' '.join((x.group(1), val))))

    xx_re = re.compile("([0-9a-zA-Z\.\-\_]+)\s+x\.x")

    matches = [xx_re.match(pkg) for pkg in reqs]
    if any(matches):
        for i, x in enumerate(matches):
            if x:
                del reqs[i]
                reqs.insert(i, ensure_valid_spec(' '.join((x.group(1),
                                                metadata.config.variant.get(x.group(1))))))
    metadata.meta['requirements'][env] = reqs
