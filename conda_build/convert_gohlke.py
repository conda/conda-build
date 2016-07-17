import re
import json
import os
import sys
import calendar
import shutil
import tarfile
import tempfile
import zipfile
from os.path import basename, isdir, join

if sys.version_info[0] == 2:
    from cStringIO import StringIO as BytesIO
else:
    from io import BytesIO


fn_pat = re.compile(
    r'([\w\.-]+)-([\w\.]+)\.(win32|win-amd64)-py(\d\.\d)\.exe$')

arch_map = {'win32': 'x86', 'win-amd64': 'x86_64'}

subdir_map = {'x86': 'win-32', 'x86_64': 'win-64'}

file_map = [
    ('PLATLIB/', 'Lib/site-packages/'),
    ('PURELIB/', 'Lib/site-packages/'),
    ('SCRIPTS/', 'Scripts/'),
    ('DATA/', ''),
]


def info_from_fn(fn):
    m = fn_pat.match(fn)
    if m is None:
        return
    py_ver = m.group(4)
    return {
        "name": m.group(1).lower(),
        "version": m.group(2),
        "build": "py" + py_ver.replace('.', ''),
        "build_number": 0,
        "depends": ['python %s*' % py_ver],
        "platform": "win",
        "arch": arch_map[m.group(3)],
    }


def repack(src_path, t, verbose=False):
    z = zipfile.ZipFile(src_path)
    for src in z.namelist():
        if src.endswith(('/', '\\')):
            continue
        for a, b in file_map:
            if src.startswith(a):
                dst = b + src[len(a):]
                break
        else:
            raise RuntimeError("Don't know how to handle file %s" % src)

        if verbose:
            print('    %s -> %s' % (src, dst))
        zinfo = z.getinfo(src)
        zdata = z.read(src)
        ti = tarfile.TarInfo(dst)
        ti.size = len(zdata)
        ti.mtime = calendar.timegm(zinfo.date_time)
        t.addfile(ti, BytesIO(zdata))
    z.close()


def write_info(t, info):
    tmp_dir = tempfile.mkdtemp()
    with open(join(tmp_dir, 'files'), 'w') as fo:
        for m in t.getmembers():
            fo.write('%s\n' % m.path)
    with open(join(tmp_dir, 'index.json'), 'w') as fo:
        json.dump(info, fo, indent=2, sort_keys=True)
    for fn in os.listdir(tmp_dir):
        t.add(join(tmp_dir, fn), 'info/' + fn)
    shutil.rmtree(tmp_dir)


def convert(path, repo_dir='.', add_depends=None, verbose=False):
    fn1 = basename(path)
    info = info_from_fn(fn1)
    if info is None:
        print("WARNING: Invalid .exe filename '%s', skipping" % fn1)
        return
    fn2 = '%(name)s-%(version)s-%(build)s.tar.bz2' % info
    subdir = subdir_map[info['arch']]
    if verbose:
        print('%s -> %s/%s' % (fn1, subdir, fn2))

    if add_depends:
        info['depends'].extend(add_depends)

    output_dir = join(repo_dir, subdir)
    if not isdir(output_dir):
        os.makedirs(output_dir)
    output_path = join(output_dir, fn2)

    t = tarfile.open(output_path, 'w:bz2')
    repack(path, t, verbose)
    write_info(t, info)
    t.close()
    if verbose:
        from pprint import pprint
        pprint(info)

    print("Wrote: %s" % output_path)
