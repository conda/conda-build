import os
import io
import sys
import json
import shutil
import locale
from os.path import basename, dirname, isdir, join

from conda_build.config import config
from conda_build.post import SHEBANG_PAT


def rewrite_script(fn):
    src = join(config.build_prefix, 'bin', fn)
    with io.open(src, encoding=locale.getpreferredencoding()) as fi:
        try:
            data = fi.read()
        except UnicodeDecodeError: # file is binary
            raise Exception("Binary: %s" % fn)
    os.unlink(src)

    m = SHEBANG_PAT.match(data)
    if not (m and 'python' in m.group()):
        raise Exception("No python shebang in: %s" % fn)
    new_data = data[data.find('\n') + 1:]

    dst_dir = join(config.build_prefix, 'python-scripts')
    if not isdir(dst_dir):
        os.makedirs(dst_dir)
    with open(join(dst_dir, fn), 'w') as fo:
        fo.write(new_data)


def handle_file(f, d):
    path = join(config.build_prefix, f)
    if f.endswith(('.egg-info', '.pyc')):
        os.unlink(path)

    elif f.endswith('.so'):
        sys.exit("[noarch] Error: Shared object file found: %s" % f)

    elif 'site-packages' in f:
        nsp = join(config.build_prefix, 'site-packages')
        if not isdir(nsp):
            os.mkdir(nsp)
        g = f[f.find('site-packages'):]
        dst = join(config.build_prefix, g)
        dst_dir = dirname(dst)
        if not isdir(dst_dir):
            os.makedirs(dst_dir)
        os.rename(path, dst)
        d['site-packages'].append(g[14:])

    elif f.startswith('bin/'):
        fn = basename(path)
        rewrite_script(fn)
        d['python-scripts'].append(fn)

    elif f.startswith('Examples/'):
        d['Examples'].append(f[9:])

    else:
        sys.exit("[noarch] Error: Don't know how to handle file: %s" % f)


def transform(m, files):
    prefix = config.build_prefix
    name = m.name()
    with open(join(prefix, 'bin/.%s-pre-link.sh' % name), 'w') as fo:
        fo.write('''\
#!/bin/bash
$PREFIX/bin/python $SOURCE_DIR/link.py
''')

    scripts_dir = join(prefix, 'Scripts')
    if not isdir(scripts_dir):
        os.mkdir(scripts_dir)

    with open(join(scripts_dir, '.%s-pre-link.bat' % name), 'w') as fo:
        fo.write('''\
@echo off
"%PREFIX%\\python.exe" "%SOURCE_DIR%\\link.py"
''')

    d = {'dist': m.dist(),
         'site-packages': [],
         'python-scripts': [],
         'Examples': []}
    for f in files:
        handle_file(f, d)

    this_dir = dirname(__file__)
    if d['python-scripts']:
        for fn in 'cli-32.exe', 'cli-64.exe':
            shutil.copyfile(join(this_dir, fn), join(prefix, fn))

    with open(join(this_dir, '_link.py')) as fi:
        link_code = fi.read()
    with open(join(prefix, 'link.py'), 'w') as fo:
        fo.write('DATA = ')
        json.dump(d, fo, indent=2, sort_keys=True)
        fo.write('\n## END DATA\n\n')
        fo.write(link_code)
