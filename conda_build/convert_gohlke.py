import re
import json
import os
import shutil
import tarfile
import tempfile
import zipfile
from os.path import abspath, basename, dirname, isdir, join



def extract(src_path, dir_path):
    file_map = [
        ('PLATLIB/', 'Lib/site-packages/'),
        ('PURELIB/', 'Lib/site-packages/'),
        ('SCRIPTS/', 'Scripts/'),
        ('DATA/Lib/site-packages/', 'Lib/site-packages/'),
    ]
    z = zipfile.ZipFile(src_path)
    for src in z.namelist():
        if src.endswith(('/', '\\')):
            continue
        for a, b in file_map:
            if src.startswith(a):
                dst = abspath(join(dir_path, b + src[len(a):]))
                break
        else:
            raise RuntimeError("Don't know how to handle file %s" % src)

        dst_dir = dirname(dst)
        #print 'file %r to %r' % (src, dst_dir)
        if not isdir(dst_dir):
            os.makedirs(dst_dir)
        data = z.read(src)
        with open(dst, 'wb') as fi:
            fi.write(data)
    z.close()


def get_files(dir_path):
    res = set()
    for root, dirs, files in os.walk(dir_path):
        for fn in files:
            res.add(join(root, fn)[len(dir_path) + 1:])
    return sorted(res)


def convert(file, output_repo='.'):
    pat = re.compile(r'([\w\.-]+)-([\w\.]+)\.(win32|win-amd64)-py(\d)\.(\d)\.exe')
    fn1 = basename(file)
    m = pat.match(fn1)
    if m is None:
         print("WARNING: Invalid .exe filename '%s', skipping" % fn1)
         return
    arch_map = {'win32': 'x86', 'win-amd64': 'x86_64'}
    py_ver = '%s.%s' % (m.group(4), m.group(5))
    info = {
        "name": m.group(1).lower(),
        "version": m.group(2),
        "build": "py" + py_ver.replace('.', ''),
        "build_number": 0,
        "depends": ['python %s*' % py_ver],
        "platform": "win",
        "arch": arch_map[m.group(3)],
    }

    tmp_dir = tempfile.mkdtemp()
    extract(file, tmp_dir)
    info_dir = join(tmp_dir, 'info')
    os.mkdir(info_dir)
    files = get_files(tmp_dir)
    with open(join(info_dir, 'files'), 'w') as fo:
        for f in files:
            fo.write('%s\n' % f)
    with open(join(info_dir, 'index.json'), 'w') as fo:
        json.dump(info, fo, indent=2, sort_keys=True)
    for fn in os.listdir(info_dir):
        files.append('info/' + fn)

    subdir_map = {'x86': 'win-32', 'x86_64': 'win-64'}
    output_dir = join(output_repo, subdir_map[info['arch']])
    if not isdir(output_dir):
        os.makedirs(output_dir)
    fn2 = '%(name)s-%(version)s-%(build)s.tar.bz2' % info
    output_path = join(output_dir, fn2)

    t = tarfile.open(output_path, 'w:bz2')
    for f in files:
        t.add(join(tmp_dir, f), f)
    t.close()

    print("Wrote: %s" % output_path)
    shutil.rmtree(tmp_dir)
