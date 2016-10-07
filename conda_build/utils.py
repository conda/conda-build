from __future__ import absolute_import, division, print_function

from collections import defaultdict
import contextlib
from difflib import get_close_matches
from distutils.dir_util import copy_tree
import fnmatch
from glob import glob
from locale import getpreferredencoding
import logging
import operator
import os
from os.path import dirname, getmtime, getsize, isdir, join, isfile, abspath
import re
import subprocess
import sys
import shutil
import tarfile
import tempfile
import zipfile

import filelock

from .conda_interface import md5_file, unix_path_to_win, win_path_to_unix
from .conda_interface import PY3, iteritems
from .conda_interface import linked
from .conda_interface import bits, root_dir

from conda_build.os_utils import external

if PY3:
    import urllib.parse as urlparse
    import urllib.request as urllib
else:
    import urlparse
    import urllib


log = logging.getLogger(__file__)

# elsewhere, kept here for reduced duplication.  NOQA because it is not used in this file.
from .conda_interface import rm_rf  # NOQA

on_win = (sys.platform == 'win32')

codec = getpreferredencoding() or 'utf-8'
on_win = sys.platform == "win32"
log = logging.getLogger(__file__)
root_script_dir = os.path.join(root_dir, 'Scripts' if on_win else 'bin')


PY_TMPL = """\
if __name__ == '__main__':
    import sys
    import %(module)s

    sys.exit(%(module)s.%(func)s())
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
            t.close()
            need_cleanup = True
        else:
            print("Ignoring non-recipe: %s" % recipe)
            return (None, None)
    else:
        recipe_dir = abspath(recipe)
        need_cleanup = False
    return recipe_dir, need_cleanup


def copy_into(src, dst, timeout=90, symlinks=False):
    "Copy all the files and directories in src to the directory dst"
    if isdir(src):
        merge_tree(src, dst, symlinks, timeout=timeout)

    else:
        if isdir(dst):
            dst_fn = os.path.join(dst, os.path.basename(src))
        else:
            dst_fn = dst

        lock = None
        if os.path.isabs(src):
            src_folder = os.path.dirname(src)
            lock = filelock.SoftFileLock(join(src_folder, ".conda_lock"))
        try:
            if os.path.sep in dst_fn and not os.path.isdir(os.path.dirname(dst_fn)):
                os.makedirs(os.path.dirname(dst_fn))
            if lock:
                lock.acquire(timeout=timeout)
            # with each of these, we are copying less metadata.  This seems to be necessary
            #   to cope with some shared filesystems with some virtual machine setups.
            #  See https://github.com/conda/conda-build/issues/1426
            try:
                shutil.copy2(src, dst_fn)
            except OSError:
                try:
                    shutil.copy(src, dst_fn)
                except OSError:
                    shutil.copyfile(src, dst_fn)
        except shutil.Error:
            log.debug("skipping %s - already exists in %s", os.path.basename(src), dst)
        finally:
            if lock:
                lock.release()


def merge_tree(src, dst, symlinks=False, timeout=90):
    """
    Merge src into dst recursively by copying all files from src into dst.
    Return a list of all files copied.

    Like copy_tree(src, dst), but raises an error if merging the two trees
    would overwrite any files.
    """
    assert src not in dst, ("Can't merge/copy source into subdirectory of itself.  Please create "
                            "separate spaces for these things.")

    new_files = copy_tree(src, dst, preserve_symlinks=symlinks, dry_run=True)
    # do not copy lock files
    new_files = [f for f in new_files if not f.endswith('.conda_lock')]
    existing = [f for f in new_files if isfile(f)]

    if existing:
        raise IOError("Can't merge {0} into {1}: file exists: "
                      "{2}".format(src, dst, existing[0]))

    lock = filelock.SoftFileLock(join(src, ".conda_lock"))
    lock.acquire(timeout=timeout)
    try:
        copy_tree(src, dst, preserve_symlinks=symlinks)
    except:
        raise
    finally:
        lock.release()
        rm_rf(os.path.join(dst, '.conda_lock'))


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


def _check_call(args, **kwargs):
    try:
        subprocess.check_call(args, **kwargs)
    except subprocess.CalledProcessError:
        sys.exit('Command failed: %s' % ' '.join(args))


def tar_xf(tarball, dir_path, mode='r:*'):
    if tarball.lower().endswith('.tar.z'):
        uncompress = external.find_executable('uncompress')
        if not uncompress:
            uncompress = external.find_executable('gunzip')
        if not uncompress:
            sys.exit("""\
uncompress (or gunzip) is required to unarchive .z source files.
""")
        subprocess.check_call([uncompress, '-f', tarball])
        tarball = tarball[:-2]
    if not PY3 and tarball.endswith('.tar.xz'):
        unxz = external.find_executable('unxz')
        if not unxz:
            sys.exit("""\
unxz is required to unarchive .xz source files.
""")

        subprocess.check_call([unxz, '-f', '-k', tarball])
        tarball = tarball[:-3]
    t = tarfile.open(tarball, mode)
    t.extractall(path=dir_path)
    t.close()


def unzip(zip_path, dir_path):
    z = zipfile.ZipFile(zip_path)
    for name in z.namelist():
        if name.endswith('/'):
            continue
        path = join(dir_path, *name.split('/'))
        dp = dirname(path)
        if not isdir(dp):
            os.makedirs(dp)
        with open(path, 'wb') as fo:
            fo.write(z.read(name))
    z.close()


def file_info(path):
    return {'size': getsize(path),
            'md5': md5_file(path),
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


def get_site_packages(prefix):
    if sys.platform == 'win32':
        sp = os.path.join(prefix, 'Lib', 'site-packages')
    else:
        sp = os.path.join(prefix, 'lib', 'python%s' % sys.version[:3], 'site-packages')
    return sp


def get_build_folders(croot):
    # remember, glob is not a regex.
    return glob(os.path.join(croot, "*" + "[0-9]" * 10 + "*"))


def silence_loggers(show_warnings_and_errors=True):
    if show_warnings_and_errors:
        log_level = logging.WARN
    else:
        log_level = logging.CRITICAL + 1
    logging.getLogger(os.path.dirname(__file__)).setLevel(log_level)
    # This squelches a ton of conda output that is not hugely relevant
    logging.getLogger("conda").setLevel(log_level)
    logging.getLogger("binstar").setLevel(log_level)
    logging.getLogger("install").setLevel(log_level + 10)
    logging.getLogger("conda.install").setLevel(log_level + 10)
    logging.getLogger("fetch").setLevel(log_level)
    logging.getLogger("print").setLevel(log_level)
    logging.getLogger("progress").setLevel(log_level)
    logging.getLogger("dotupdate").setLevel(log_level)
    logging.getLogger("stdoutlog").setLevel(log_level)
    logging.getLogger("requests").setLevel(log_level)


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
    pyscript = PY_TMPL % {'module': module, 'func': func}
    if sys.platform == 'win32':
        with open(path + '-script.py', 'w') as fo:
            packages = linked(config.build_prefix)
            packages_names = (pkg.split('-')[0] for pkg in packages)
            if 'debug' in packages_names:
                fo.write('#!python_d\n')
            fo.write(pyscript)
        copy_into(join(dirname(__file__), 'cli-%d.exe' % bits), path + '.exe', config.timeout)
    else:
        with open(path, 'w') as fo:
            fo.write('#!%s\n' % config.build_python)
            fo.write(pyscript)
        os.chmod(path, 0o775)


def create_entry_points(items, config):
    if not items:
        return
    bin_dir = join(config.build_prefix, bin_dirname)
    if not isdir(bin_dir):
        os.mkdir(bin_dir)
    for cmd, module, func in iter_entry_points(items):
        create_entry_point(join(bin_dir, cmd), module, func, config)


def guess_license_family(license_name, allowed_license_families):
    # Tend towards the more clear GPL3 and away from the ambiguity of GPL2.
    if 'GPL (>= 2)' in license_name or license_name == 'GPL':
        return 'GPL3'
    elif 'LGPL' in license_name:
        return 'LGPL'
    else:
        return get_close_matches(license_name,
                                 allowed_license_families, 1, 0.0)[0]


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
    args = []
    for arg in popenargs:
        # arguments to subprocess need to be bytestrings
        if hasattr(arg, 'encode'):
            arg = arg.encode(codec)
        args.append(arg)
    return func(*args, **kwargs)


def check_call_env(*popenargs, **kwargs):
    return _func_defaulting_env_to_os_environ(subprocess.check_call, *popenargs, **kwargs)


def check_output_env(*popenargs, **kwargs):
    return _func_defaulting_env_to_os_environ(subprocess.check_output, *popenargs, **kwargs)


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
        return check_output_env(['cygpath', '-u',
                                 path]).splitlines()[0].decode(getpreferredencoding())
    return path


def print_skip_message(metadata):
    print("Skipped: {} defines build/skip for this "
          "configuration.".format(metadata.path))


def package_has_file(package_path, file_path):
    try:
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
