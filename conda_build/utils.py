from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import os
import sys
import shutil
import tarfile
import zipfile
import subprocess
from io import open
from os.path import (dirname, getmtime, getsize, isdir, isfile,
                     islink, join, normpath)

from conda.utils import md5_file

from conda_build import external


def rel_lib(f):
    assert not f.startswith('/')
    if f.startswith('lib/'):
        return normpath((f.count('/') - 1) * '../')
    else:
        return normpath(f.count('/') * '../') + '/lib'


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

    try:
        t = tarfile.open(tarball, mode)
        t.extractall(path=dir_path)
        t.close()
    except tarfile.ReadError:
        subprocess.check_call(['tar', '-x', '-v', '-p', '-f', tarball, '-C', dir_path])


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


def rm_rf(path):
    if islink(path) or isfile(path):
        os.unlink(path)

    elif isdir(path):
        if sys.platform == 'win32':
            subprocess.check_call(['cmd', '/c', 'rd', '/s', '/q', path])
        else:
            shutil.rmtree(path)


def file_info(path):
    return {'size': getsize(path),
            'md5': md5_file(path),
            'mtime': getmtime(path)}
