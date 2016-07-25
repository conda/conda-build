from __future__ import absolute_import, division, print_function

from collections import defaultdict
from distutils.dir_util import copy_tree
import fnmatch
from locale import getpreferredencoding
import logging
import operator
import os
from os.path import dirname, getmtime, getsize, isdir, join, isfile, abspath
import sys
import shutil
import tarfile
import tempfile
import zipfile
import subprocess

from conda.utils import md5_file, unix_path_to_win
from conda.compat import PY3, iteritems

from conda_build.os_utils import external

if PY3:
    import urllib.parse as urlparse
    import urllib.request as urllib
else:
    import urlparse
    import urllib


log = logging.getLogger(__file__)

# elsewhere, kept here for reduced duplication.  NOQA because it is not used in this file.
if sys.platform == 'win32':
    from conda.install import move_to_trash as rm_rf  # NOQA
else:
    from conda.install import rm_rf  # NOQA

on_win = (sys.platform == 'win32')


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


def find_recipe(path):
    """recurse through a folder, locating meta.yaml.  Raises error if more than one is found.

    Returns folder containing meta.yaml, to be built.

    If we have a base level meta.yaml and other supplemental ones, use that first"""
    results = rec_glob(path, ["meta.yaml", "conda.yaml"])
    if len(results) > 1:
        base_recipe = os.path.join(path, "meta.yaml")
        if base_recipe in results:
            return os.path.dirname(base_recipe)
        else:
            raise IOError("More than one meta.yaml files found in %s" % path)
    elif not results:
        raise IOError("No meta.yaml files found in %s" % path)
    return os.path.dirname(results[0])


def copy_into(src, dst, symlinks=False):
    "Copy all the files and directories in src to the directory dst"

    if isdir(src):
            merge_tree(src, dst, symlinks)
    else:
        tocopy = [src]
        for afile in tocopy:
            srcname = os.path.join(src, afile)
            dstname = os.path.join(dst, afile)

        try:
            shutil.copy2(srcname, dstname)
        except shutil.Error:
            log.debug("skipping {0} - already exists in {1}".format(srcname, dstname))


def merge_tree(src, dst, symlinks=False):
    """
    Merge src into dst recursively by copying all files from src into dst.
    Return a list of all files copied.

    Like copy_tree(src, dst), but raises an error if merging the two trees
    would overwrite any files.
    """
    new_files = copy_tree(src, dst, preserve_symlinks=symlinks, dry_run=True)
    existing = [f for f in new_files if isfile(f)]

    if existing:
        raise IOError("Can't merge {0} into {1}: file exists: "
                      "{2}".format(src, dst, existing[0]))

    return copy_tree(src, dst, preserve_symlinks=symlinks)


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
