from __future__ import absolute_import, division, print_function

import locale
import re
import os
import sys
import stat
from glob import glob
from os.path import basename, join, splitext, isdir, isfile, exists
import io
from subprocess import call, Popen, PIPE

from conda_build.config import config
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
    path = join(config.build_prefix, f)
    if is_obj(path):
        return
    elif os.path.islink(path):
        return
    with io.open(path, encoding=locale.getpreferredencoding()) as fi:
        try:
            data = fi.read()
        except UnicodeDecodeError: # file is binary
            return
    m = SHEBANG_PAT.match(data)
    if not (m and 'python' in m.group()):
        return

    py_exec = ('/bin/bash ' + config.build_prefix + '/bin/python.app'
               if sys.platform == 'darwin' and osx_is_app else
               config.build_prefix + '/bin/' + basename(config.build_python))
    new_data = SHEBANG_PAT.sub('#!' + py_exec, data, count=1)
    if new_data == data:
        return
    print("updating shebang:", f)
    with io.open(path, 'w', encoding=locale.getpreferredencoding()) as fo:
        fo.write(new_data)
    os.chmod(path, int('755', 8))


def write_pth(egg_path):
    fn = basename(egg_path)
    with open(join(environ.get_sp_dir(),
                   '%s.pth' % (fn.split('-')[0])), 'w') as fo:
        fo.write('./%s\n' % fn)


def remove_easy_install_pth(preserve_egg_dir=False):
    """
    remove the need for easy-install.pth and finally remove easy-install.pth
    itself
    """
    sp_dir = environ.get_sp_dir()
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
                    # this might be a name-space package
                    # so the package directory already exists
                    # from another installed dependency
                    if os.path.exists(join(sp_dir, fn)):
                        utils.copy_into(join(egg_path, fn), join(sp_dir, fn))
                        utils.rm_rf(join(egg_path, fn))
                    else:
                        os.rename(join(egg_path, fn), join(sp_dir, fn))

        elif isfile(egg_path):
            print('found egg:', egg_path)
            write_pth(egg_path)

    utils.rm_rf(join(sp_dir, 'easy-install.pth'))


def rm_py_along_so():
    "remove .py (.pyc) files alongside .so or .pyd files"
    for root, dirs, files in os.walk(config.build_prefix):
        for fn in files:
            if fn.endswith(('.so', '.pyd')):
                name, unused_ext = splitext(fn)
                for ext in '.py', '.pyc':
                    if name + ext in files:
                        os.unlink(join(root, name + ext))


def compile_missing_pyc():
    sp_dir = environ.get_sp_dir()
    stdlib_dir = environ.get_stdlib_dir()

    need_compile = False
    for root, dirs, files in os.walk(sp_dir):
        for fn in files:
            if fn.endswith('.py') and fn + 'c' not in files:
                need_compile = True
                break
    if need_compile:
        print('compiling .pyc files...')
        utils._check_call([config.build_python, '-Wi',
                           join(stdlib_dir, 'compileall.py'),
                           '-q', '-x', 'port_v3', sp_dir])


def post_process(preserve_egg_dir=False):
    remove_easy_install_pth(preserve_egg_dir=preserve_egg_dir)
    rm_py_along_so()
    if not config.PY3K:
        compile_missing_pyc()


def osx_ch_link(path, link):
    assert path.startswith(config.build_prefix + '/')
    reldir = utils.relative(path[len(config.build_prefix) + 1:])

    if link.startswith((config.build_prefix + '/lib', 'lib',
                        '@executable_path/')):
        return '@loader_path/%s/%s' % (reldir, basename(link))

    if link == '/usr/local/lib/libgcc_s.1.dylib':
        return '/usr/lib/libgcc_s.1.dylib'

def mk_relative_osx(path):
    assert sys.platform == 'darwin' and is_obj(path)
    s = macho.install_name_change(path, osx_ch_link)

    if macho.is_dylib(path):
        names = macho.otool(path)
        if names:
            args = ['install_name_tool', '-id', basename(names[0]), path]
            print(' '.join(args))
            p = Popen(args, stderr=PIPE)
            stdout, stderr = p.communicate()
            stderr = stderr.decode('utf-8')
            if "Mach-O dynamic shared library stub file" in stderr:
                print("Skipping Mach-O dynamic shared library stub file %s" % path)
                return
            else:
                print(stderr, file=sys.stderr)
                if p.returncode:
                    raise RuntimeError("install_name_tool failed with exit status %d"
                % p.returncode)

    if s:
        # Skip for stub files, which have to use binary_has_prefix_files to be
        # made relocatable.
        assert_relative_osx(path)

def assert_relative_osx(path):
    for name in macho.otool(path):
        assert not name.startswith(config.build_prefix), path

def mk_relative(f, binary_relocation=True, m=None):
    assert sys.platform != 'win32'

    if not binary_relocation:
        return

    path = join(config.build_prefix, f)
    if sys.platform.startswith('linux') and is_obj(path):
        if m and m.get_value('build/rpaths'):
            rpath = ':'.join('$ORIGIN/' + utils.relative(f, d)
                             for d in m.get_value('build/rpaths'))
        else:
            rpath = '$ORIGIN/' + utils.relative(f)
        patchelf = external.find_executable('patchelf')
        print('patchelf: file: %s\n    setting rpath to: %s' % (path, rpath))
        call([patchelf, '--set-rpath', rpath, path])

    if sys.platform == 'darwin' and is_obj(path):
        mk_relative_osx(path)


def fix_permissions(files):
    for root, dirs, unused_files in os.walk(config.build_prefix):
        for dn in dirs:
            os.chmod(join(root, dn), int('755', 8))

    for f in files:
        path = join(config.build_prefix, f)
        st = os.lstat(path)
        lchmod(path, stat.S_IMODE(st.st_mode) | stat.S_IWUSR) # chmod u+w


def post_build(m, files):
    print('number of files:', len(files))
    fix_permissions(files)

    if sys.platform == 'win32':
        return

    binary_relocation = bool(m.get_value('build/binary_relocation', True))
    if not binary_relocation:
        print("Skipping binary relocation logic")
    osx_is_app = bool(m.get_value('build/osx_is_app', False))
    for f in files:
        if f.startswith('bin/'):
            fix_shebang(f, osx_is_app=osx_is_app)
        mk_relative(f, binary_relocation=binary_relocation, m)

def get_build_metadata(m):
    if exists(join(source.WORK_DIR, '__conda_version__.txt')):
        with open(join(source.WORK_DIR, '__conda_version__.txt')) as f:
            version = f.read().strip()
            print("Setting version from __conda_version__.txt: %s" % version)
            m.meta['package']['version'] = version
    if exists(join(source.WORK_DIR, '__conda_buildnum__.txt')):
        with open(join(source.WORK_DIR, '__conda_buildnum__.txt')) as f:
            build_number = f.read().strip()
            print("Setting build number from __conda_buildnum__.txt: %s" %
                  build_number)
            m.meta['build']['number'] = build_number
    if exists(join(source.WORK_DIR, '__conda_buildstr__.txt')):
        with open(join(source.WORK_DIR, '__conda_buildstr__.txt')) as f:
            buildstr = f.read().strip()
            print("Setting version from __conda_buildstr__.txt: %s" % buildstr)
            m.meta['build']['string'] = buildstr
