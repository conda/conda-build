import os
import json
import shutil
from os.path import dirname, isdir, join

from conda_build.config import config



def handle_file(f):
    path = join(config.build_prefix, f)
    if f.endswith(('.egg-info', '.pyc')):
        os.unlink(path)
        return None

    if 'site-packages' in f:
        nsp = join(config.build_prefix, 'site-packages')
        if not isdir(nsp):
            os.mkdir(nsp)
        g = f[f.find('site-packages'):]
        dst = join(config.build_prefix, g)
        dst_dir = dirname(dst)
        if not isdir(dst_dir):
            os.makedirs(dst_dir)
        os.rename(path, dst)
        return g

    if f.startswith('bin/'):
        with open(path, 'rb') as fi:
            data = fi.read()
        if not data[:2] == b'#!':
            raise Exception("No shebang in: %s" % f)
        new_data = data[data.find('\n') + 1:]
        with open(path, 'wb') as fo:
            fo.write(new_data)
        return f

    if f.startswith('Examples/'):
        return f

    return None


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

    d = {'Examples': [],
         'site-packages': [],
         'bin': []}
    for f in files:
        g = handle_file(f)
        if g is None:
            continue
        if g.startswith('site-packages/'):
            d['site-packages'].append(g[14:])
        elif g.startswith('bin/'):
            d['bin'].append(g[4:])
        elif g.startswith('Examples/'):
            d['Examples'].append(g[9:])
        else:
            raise Exception("Did not expect: %r" % g)

    with open(join(prefix, 'data.json'), 'w') as fo:
        json.dump(d, fo, indent=2, sort_keys=True)

    this_dir = dirname(__file__)
    if d['bin']:
        for fn in 'cli-32.exe', 'cli-64.exe':
            shutil.copyfile(join(this_dir, fn), join(prefix, fn))

    shutil.copyfile(join(this_dir, '_link.py'), join(prefix, 'link.py'))
