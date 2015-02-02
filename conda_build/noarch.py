import os
from os.path import dirname, isdir, join

from conda_build.config import config


BASH_HEAD = '''\
#!/bin/bash
SP_DIR=$($PREFIX/bin/python -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())")
#echo "SP_DIR='$SP_DIR'"
'''

BAT_HEAD = '''\
@echo off
for /f %%i in ('%PREFIX%/python.exe -c "from distutils.sysconfig import get_python_lib; print(get_python_lib())"') do set SP_DIR=%%i
if errorlevel 1 exit 1
REM echo "SP_DIR='$SP_DIR'"
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
            os.makedirs(dst_dir)
        os.rename(path, dst)
        return g

def transform(m, files):
    f1 = open(join(config.install_prefix,
                   'bin/.%s-pre-link.sh' % m.name()), 'w')
    f1.write(BASH_HEAD)
    f1.write('''
cp $SOURCE_DIR/bin/.%s-pre-unlink.sh $PREFIX/bin
''' % m.name())
    f2 = open(join(config.install_prefix,
                   'bin/.%s-pre-unlink.sh' % m.name()), 'w')
    f2.write(BASH_HEAD)

    scripts_dir = join(config.install_prefix, 'Scripts')
    if not isdir(scripts_dir):
        os.mkdir(scripts_dir)

    f3 = open(join(scripts_dir, '.%s-pre-link.bat' % m.name()), 'w')
    f3.write(BAT_HEAD)
    f3.write(r'''
copy %%SOURCE_DIR%%\Scripts\.%s-pre-unlink.bat %%PREFIX%%\Scripts
''' % m.name())
    f4 = open(join(scripts_dir, '.%s-pre-unlink.bat' % m.name()), 'w')
    f4.write(BAT_HEAD)

    dirs = set()
    for f in files:
        g = handle_file(f)
        if g is None:
            continue
        if g.startswith('site-packages/'):
            g = g[14:]
            dirs.add(dirname(g))
            f1.write('''
mkdir -p $SP_DIR/%s
rm -f $SP_DIR/%s
ln $SOURCE_DIR/site-packages/%s $SP_DIR/%s
''' % (dirname(g), g, g, g))
            f2.write('rm -f $SP_DIR/%s*\n' % g)

            gw = g.replace('/', '\\')
            f3.write(r'''
md %%SP_DIR%%\%s
del %%SP_DIR%%\%s
fsutil hardlink create %%SP_DIR%%\%s %%SOURCE_DIR%%\site-packages\%s
''' % (dirname(g).replace('/', '\\'), gw, gw, gw))
            f4.write('del %%SP_DIR%%\\%s*\n' % gw)

    for d in sorted(dirs, key=len, reverse=True):
        f2.write('rmdir $SP_DIR/%s\n' % d)
        f4.write('rd /S /Q %%SP_DIR%%\\%s\n' % d.replace('/', '\\'))

    f1.close()
    f2.close()
    f3.close()
    f4.close()
