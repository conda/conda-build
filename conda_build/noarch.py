import os
from os.path import dirname, isdir, join

from conda_build.config import config


BASH_HEAD = '''\
#!/bin/bash
SP_DIR=$($PREFIX/bin/python -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())")
#echo "SP_DIR='$SP_DIR'"
'''

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
            os.mkdir(dst_dir)
        os.rename(path, dst)
        return g

def transform(m, files):
    f1 = open(join(config.build_prefix,
                   'bin/.%s-pre-link.sh' % m.name()), 'w')
    f1.write('''
cp $SOURCE_DIR/bin/.%s-pre-unlink.sh $PREFIX/bin
''' % m.name())
    f1.write(BASH_HEAD)
    f2 = open(join(config.build_prefix,
                   'bin/.%s-pre-unlink.sh' % m.name()), 'w')
    f2.write(BASH_HEAD)
    for f in files:
        print f
        g = handle_file(f)
        if g is None:
            continue
        if g.startswith('site-packages/'):
            g = g[14:]
            f1.write('''
mkdir -p $SP_DIR/%s
rm -f $SP_DIR/%s
ln $SOURCE_DIR/site-packages/%s $SP_DIR/%s
''' % (dirname(g), g, g, g))
            f2.write('''\
rm -f $SP_DIR/%s*
''' % g)
    f1.close()
    f2.close()
