import re
import json
import os
import shutil
import tarfile
import tempfile
import zipfile
from os.path import abspath, basename, dirname, isdir, join


fn_pat = re.compile(
    r'([\w\.-]+)-([\w\.]+)\.(win32|win-amd64)-py(\d)\.(\d)\.exe$')

arch_map = {'win32': 'x86', 'win-amd64': 'x86_64'}

subdir_map = {'x86': 'win-32', 'x86_64': 'win-64'}

file_map = [
    ('PLATLIB/', 'Lib/site-packages/'),
    ('PURELIB/', 'Lib/site-packages/'),
    ('SCRIPTS/', 'Scripts/'),
    ('DATA/Lib/site-packages/', 'Lib/site-packages/'),
]


def info_from_fn(fn):
    m = fn_pat.match(fn)
    if m is None:
         return
    py_ver = '%s.%s' % (m.group(4), m.group(5))
    return {
        "name": m.group(1).lower(),
        "version": m.group(2),
        "build": "py" + py_ver.replace('.', ''),
        "build_number": 0,
        "depends": ['python %s*' % py_ver],
        "platform": "win",
        "arch": arch_map[m.group(3)],
    }


def extract(src_path, dir_path):
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


def write_info(dir_path, files, info):
    info_dir = join(dir_path, 'info')
    os.mkdir(info_dir)
    with open(join(info_dir, 'files'), 'w') as fo:
        for f in files:
            fo.write('%s\n' % f)
    with open(join(info_dir, 'index.json'), 'w') as fo:
        json.dump(info, fo, indent=2, sort_keys=True)
    for fn in os.listdir(info_dir):
        files.append('info/' + fn)


def convert(path, repo_dir='.'):
    fn = basename(path)
    info = info_from_fn(fn)
    if info is None:
         print("WARNING: Invalid .exe filename '%s', skipping" % fn)
         return

    tmp_dir = tempfile.mkdtemp()
    extract(path, tmp_dir)
    files = get_files(tmp_dir)
    write_info(tmp_dir, files, info)

    output_dir = join(repo_dir, subdir_map[info['arch']])
    if not isdir(output_dir):
        os.makedirs(output_dir)
    output_path = join(output_dir,
                       '%(name)s-%(version)s-%(build)s.tar.bz2' % info)

    t = tarfile.open(output_path, 'w:bz2')
    for f in files:
        t.add(join(tmp_dir, f), f)
    t.close()

    print("Wrote: %s" % output_path)
    shutil.rmtree(tmp_dir)
