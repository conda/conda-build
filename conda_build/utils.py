from __future__ import absolute_import, division, print_function

import os
import sys
import shutil
import tarfile
import zipfile
import subprocess
from os.path import (dirname, getmtime, getsize, isdir, isfile,
                     islink, join, normpath)

from conda.utils import md5_file

from conda_build import external

# Backwards compatibility import. Do not remove.
from conda.install import rm_rf

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
    f = dirname(f).split('/')
    if f == ['']:
        return './' + normpath('/'.join(d))
    while d and f and d[0] == f[0]:
        d.pop(0)
        f.pop(0)
    return normpath((len(f) * '../') + '/'.join(d))


def _check_call(args, **kwargs):
    try:
        subprocess.check_call(args, **kwargs)
    except subprocess.CalledProcessError:
        sys.exit('Command failed: %s' % ' '.join(args))


def tar_xf(tarball, dir_path, mode='r:*'):
    if tarball.endswith('.tar.xz'):
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


if __name__ == '__main__':
    for f, r in [
        ('bin/python', '../lib'),
        ('lib/libhdf5.so', '.'),
        ('lib/python2.6/foobar.so', '..'),
        ('lib/python2.6/lib-dynload/zlib.so', '../..'),
        ('lib/python2.6/site-packages/pyodbc.so', '../..'),
        ('lib/python2.6/site-packages/bsdiff4/core.so', '../../..'),
        ('xyz', './lib'),
        ('bin/somedir/cmd', '../../lib'),
        ]:
        res = relative(f)
        assert res == r, '%r != %r' % (res, r)

    for d, f, r in [
        ('lib', 'bin/python', '../lib'),
        ('lib', 'lib/libhdf5.so', '.'),
        ('lib', 'lib/python2.6/foobar.so', '..'),
        ('lib', 'lib/python2.6/lib-dynload/zlib.so', '../..'),
        ('lib', 'lib/python2.6/site-packages/pyodbc.so', '../..'),
        ('lib', 'lib/python2.6/site-packages/bsdiff3/core.so', '../../..'),
        ('lib', 'xyz', './lib'),
        ('lib', 'bin/somedir/cmd', '../../lib'),
        ('lib', 'bin/somedir/somedir2/cmd', '../../../lib'),
        ('lib/sub', 'bin/somedir/cmd', '../../lib/sub'),
        ('lib/sub', 'bin/python', '../lib/sub'),
        ('lib/sub', 'lib/sub/libhdf5.so', '.'),
        ('a/b/c', 'a/b/c/libhdf5.so', '.'),
        ('a/b/c/d', 'a/b/x/y/libhdf5.so', '../../c/d'),
        ]:
        res = relative(f, d)
        assert res == r, '%r != %r' % (res, r)
