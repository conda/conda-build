import os
import io
import json
import shutil
import locale
from os.path import basename, dirname, isdir, join

from conda_build.config import config
from conda_build.post import SHEBANG_PAT



def handle_file(f, d):
    path = join(config.build_prefix, f)
    if f.endswith(('.egg-info', '.pyc')):
        os.unlink(path)

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
        with io.open(path, encoding=locale.getpreferredencoding()) as fi:
            try:
                data = fi.read()
            except UnicodeDecodeError: # file is binary
                raise Exception("No binary scripts: %s" % f)
        os.unlink(path)

        m = SHEBANG_PAT.match(data)
        if not (m and 'python' in m.group()):
            raise Exception("No python shebang in: %s" % f)
        new_data = data[data.find('\n') + 1:]

        dst_dir = join(config.build_prefix, 'python-scripts')
        if not isdir(dst_dir):
            os.makedirs(dst_dir)
        dst = join(dst_dir, basename(path))
        with open(dst, 'w') as fo:
            fo.write(new_data)
        d['python-scripts'].append(basename(path))

    elif f.startswith('Examples/'):
        d['Examples'].append(f[9:])


def transform(m, files):
    prefix = config.build_prefix
    with open(join(prefix, 'bin/.%s-pre-link.sh' % m.name()), 'w') as fo:
        fo.write('''\
#!/bin/bash
cp $SOURCE_DIR/bin/.%s-pre-unlink.sh $PREFIX/bin
$PREFIX/bin/python $SOURCE_DIR/link.py
''' % m.name())

    with open(join(prefix, 'bin/.%s-pre-unlink.sh' % m.name()), 'w') as fo:
        fo.write('''\
#!/bin/bash
$PREFIX/bin/python $SOURCE_DIR/link.py --unlink
''')

    scripts_dir = join(prefix, 'Scripts')
    if not isdir(scripts_dir):
        os.mkdir(scripts_dir)

    with open(join(scripts_dir, '.%s-pre-link.bat' % m.name()), 'w') as fo:
        fo.write('''\
@echo off
copy %%SOURCE_DIR%%\Scripts\.%s-pre-unlink.bat %%PREFIX%%\Scripts
%%PREFIX%%/bin/python $SOURCE_DIR/link.py
''' % m.name())

    with open(join(scripts_dir, '.%s-pre-unlink.bat' % m.name()), 'w') as fo:
        fo.write('''\
@echo off
%%PREFIX%%/bin/python $SOURCE_DIR/link.py --unlink
''')

    d = {'site-packages': [],
         'python-scripts': [],
         'Examples': []}
    for f in files:
        handle_file(f, d)

    with open(join(prefix, 'data.json'), 'w') as fo:
        json.dump(d, fo, indent=2, sort_keys=True)

    this_dir = dirname(__file__)
    if d['python-scripts']:
        for fn in 'cli-32.exe', 'cli-64.exe':
            shutil.copyfile(join(this_dir, fn), join(prefix, fn))

    shutil.copyfile(join(this_dir, '_link.py'), join(prefix, 'link.py'))
