from __future__ import absolute_import, division, print_function

import os
import sys
import shutil
import tarfile
import zipfile
import subprocess
import operator
from os.path import dirname, getmtime, getsize, isdir, join
from collections import defaultdict

from conda.utils import md5_file
from conda.compat import PY3, iteritems

from conda_build import external

# Backwards compatibility import. Do not remove.
from conda.install import rm_rf
rm_rf

def copy_into(src, dst):
    "Copy all the files and directories in src to the directory dst"

    tocopy = os.listdir(src)
    for afile in tocopy:
        srcname = os.path.join(src, afile)
        dstname = os.path.join(dst, afile)

        if os.path.isdir(srcname):
            shutil.copytree(srcname, dstname)
        else:
            shutil.copy2(srcname, dstname)


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
