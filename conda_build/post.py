from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import locale
import re
import os
import sys
import stat
from glob import glob
from os.path import basename, join, splitext, isdir, isfile, exists
from io import open
from subprocess import call, check_call

from conda_build.config import build_prefix, build_python, PY3K
from conda_build import external
from conda_build import environ
from conda_build import utils
from conda_build import source
from conda.compat import lchmod

if sys.platform.startswith('linux'):
    from conda_build import elf
elif sys.platform == 'darwin':
    from conda_build import macho

SHEBANG_PAT = re.compile(r'^#!.+$', re.M)


def is_obj(path):
    assert sys.platform != 'win32'
    return bool((sys.platform.startswith('linux') and elf.is_elf(path)) or
                (sys.platform == 'darwin' and macho.is_macho(path)))


def fix_shebang(f, osx_is_app=False):
    path = join(build_prefix, f)
    if is_obj(path):
        return
    elif os.path.islink(path):
        return
    with open(path, encoding=locale.getpreferredencoding()) as fi:
        try:
            data = fi.read()
        except UnicodeDecodeError: # file is binary
            return
    m = SHEBANG_PAT.match(data)
    if not (m and 'python' in m.group()):
        return

    py_exec = (build_prefix + '/python.app/Contents/MacOS/python'
               if sys.platform == 'darwin' and osx_is_app else
               build_prefix + '/bin/' + basename(build_python))
    new_data = SHEBANG_PAT.sub('#!' + py_exec, data, count=1)
    if new_data == data:
        return
    print("updating shebang:", f)
    with open(path, 'w', encoding=locale.getpreferredencoding()) as fo:
        fo.write(new_data)
    os.chmod(path, int('755', 8))


def write_pth(egg_path):
    fn = basename(egg_path)
    with open(join(environ.SP_DIR,
                   '%s.pth' % (fn.split('-')[0])), 'w', encoding='utf-8') as fo:
        fo.write('./%s\n' % fn)


def remove_easy_install_pth(preserve_egg_dir=False):
    """
    remove the need for easy-install.pth and finally remove easy-install.pth
    itself
    """
    sp_dir = environ.SP_DIR
    for egg_path in glob(join(sp_dir, '*-py*.egg')):
        if isdir(egg_path):
            if preserve_egg_dir:
                write_pth(egg_path)
                continue

            print('found egg dir:', egg_path)
            try:
                os.rename(join(egg_path, 'EGG-INFO/PKG-INFO'),
                          egg_path + '-info')
            except OSError:
                pass
            utils.rm_rf(join(egg_path, 'EGG-INFO'))
            for fn in os.listdir(egg_path):
                if fn == '__pycache__':
                    utils.rm_rf(join(egg_path, fn))
                else:
                    os.rename(join(egg_path, fn), join(sp_dir, fn))

        elif isfile(egg_path):
            print('found egg:', egg_path)
            write_pth(egg_path)

    utils.rm_rf(join(sp_dir, 'easy-install.pth'))


def rm_py_along_so():
    "remove .py (.pyc) files alongside .so or .pyd files"
    for root, dirs, files in os.walk(build_prefix):
        for fn in files:
            if fn.endswith(('.so', '.pyd')):
                name, unused_ext = splitext(fn)
                for ext in '.py', '.pyc':
                    if name + ext in files:
                        os.unlink(join(root, name + ext))


def compile_missing_pyc():
    sp_dir = environ.SP_DIR

    need_compile = False
    for root, dirs, files in os.walk(sp_dir):
        for fn in files:
            if fn.endswith('.py') and fn + 'c' not in files:
                need_compile = True
    if need_compile:
        print('compiling .pyc files...')
        utils._check_call([build_python, '-Wi', join(environ.STDLIB_DIR,
                                                     'compileall.py'),
                           '-q', '-x', 'port_v3', sp_dir])


def post_process(preserve_egg_dir=False):
    remove_easy_install_pth(preserve_egg_dir=preserve_egg_dir)
    rm_py_along_so()
    if not PY3K:
        compile_missing_pyc()


def osx_ch_link(path, link):
    assert path.startswith(build_prefix + '/')
    reldir = utils.rel_lib(path[len(build_prefix) + 1:])

    if link.startswith((build_prefix + '/lib', 'lib', '@executable_path/')):
        return '@loader_path/%s/%s' % (reldir, basename(link))

    if link == '/usr/local/lib/libgcc_s.1.dylib':
        return '/usr/lib/libgcc_s.1.dylib'

def mk_relative_osx(path):
    assert sys.platform == 'darwin' and is_obj(path)
    macho.install_name_change(path, osx_ch_link)

    if path.endswith('.dylib'):
        # note that not every MachO binaries is a "dynamically linked shared
        # library" which have an identification name, a .so C extensions
        # extensions is a "bundle".  One can verify this using the "file"
        # command.
        names = macho.otool(path)
        if names:
            args = ['install_name_tool', '-id', basename(names[0]), path]
            print(' '.join(args))
            check_call(args)

    for name in macho.otool(path):
        assert not name.startswith(build_prefix), path

def mk_relative(f, binary_relocation=True):
    assert sys.platform != 'win32'
    if f.startswith('bin/'):
        fix_shebang(f)

    if not binary_relocation:
        return

    path = join(build_prefix, f)
    if sys.platform.startswith('linux') and is_obj(path):
        rpath = '$ORIGIN/' + utils.rel_lib(f)
        patchelf = external.find_executable('patchelf')
        print('patchelf: file: %s\n    setting rpath to: %s' % (path, rpath))
        call([patchelf, '--set-rpath', rpath, path])

    if sys.platform == 'darwin' and is_obj(path):
        mk_relative_osx(path)


def fix_permissions(files):
    for root, dirs, unused_files in os.walk(build_prefix):
        for dn in dirs:
            os.chmod(join(root, dn), int('755', 8))

    for f in files:
        path = join(build_prefix, f)
        st = os.lstat(path)
        lchmod(path, stat.S_IMODE(st.st_mode) | stat.S_IWUSR) # chmod u+w


def post_build(files, binary_relocation=True):
    print('number of files:', len(files))
    fix_permissions(files)
    for f in files:
        if sys.platform != 'win32':
            mk_relative(f, binary_relocation=binary_relocation)

def get_build_metadata(m):
    if exists(join(source.WORK_DIR, '__conda_version__.txt')):
        with open(join(source.WORK_DIR, '__conda_version__.txt')) as f:
            version = f.read().strip()
            print("Setting version from __conda_version__.txt: %s" % version)
            m.meta['package']['version'] = version
