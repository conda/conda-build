from __future__ import absolute_import, division, print_function

import locale
import re
import os
import sys
import stat
from glob import glob
from os.path import (basename, dirname, join, splitext, isdir, isfile, exists,
                     islink, realpath, relpath)
try:
    from os import readlink
except ImportError:
    readlink = False
import io
from subprocess import call, Popen, PIPE
from collections import defaultdict

from conda_build.config import config
from conda_build import external
from conda_build import environ
from conda_build import utils
from conda_build import source
from conda.compat import lchmod
from conda.misc import walk_prefix

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


def remove_easy_install_pth(files, preserve_egg_dir=False):
    """
    remove the need for easy-install.pth and finally remove easy-install.pth
    itself
    """
    absfiles = [join(config.build_prefix, f) for f in files]
    sp_dir = environ.get_sp_dir()
    for egg_path in glob(join(sp_dir, '*-py*.egg')):
        if isdir(egg_path):
            if preserve_egg_dir or not any(i in absfiles for i in walk_prefix(egg_path, False)):
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
            if not egg_path in absfiles:
                continue
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


def post_process(files, preserve_egg_dir=False):
    remove_easy_install_pth(files, preserve_egg_dir=preserve_egg_dir)
    rm_py_along_so()
    if not config.PY3K:
        compile_missing_pyc()


def find_lib(link):
    from conda_build.build import prefix_files
    files = prefix_files()
    if link.startswith(config.build_prefix):
        link = link[len(config.build_prefix) + 1:]
        if link not in files:
            sys.exit("Error: Could not find %s" % link)
        return link
    if link.startswith('/'): # but doesn't start with the build prefix
        return
    if link.startswith('@rpath/'):
        # Assume the rpath already points to lib, so there is no need to
        # change it.
        return
    if '/' not in link or link.startswith('@executable_path/'):
        link = basename(link)
        file_names = defaultdict(list)
        for f in files:
            file_names[basename(f)].append(f)
        if link not in file_names:
            sys.exit("Error: Could not find %s" % link)
        if len(file_names[link]) > 1:
            sys.exit("Error: Found multiple instances of %s: %s" % (link, file_names[link]))
        return file_names[link][0]
    print("Don't know how to find %s, skipping" % link)

def osx_ch_link(path, link):
    assert path.startswith(config.build_prefix + '/')
    link_loc = find_lib(link)
    if not link_loc:
        return

    lib_to_link = relpath(dirname(link_loc), 'lib')
    path_to_lib = utils.relative(path[len(config.build_prefix) + 1:])
    # e.g., if
    # path = '/build_prefix/lib/some/stuff/libstuff.dylib'
    # link_loc = 'lib/things/libthings.dylib'

    # then

    # lib_to_link = 'things'
    # path_to_lib = '../..'

    # @rpath always means 'lib', link will be at
    # @rpath/lib_to_link/basename(link), like @rpath/things/libthings.dylib.

    # For when we can't use @rpath, @loader_path means the path to the library
    # ('path'), so from path to link is
    # @loader_path/path_to_lib/lib_to_link/basename(link), like
    # @loader_path/../../things/libthings.dylib.

    if True or macho.is_dylib(path):
        ret =  '@rpath/%s/%s' % (lib_to_link, basename(link))
    else:
        # TODO: This might contain redundant ..'s if link and path are both in
        # some subdirectory of lib.
        ret = '@loader_path/%s/%s/%s' % (path_to_lib, lib_to_link, basename(link))

    ret = ret.replace('/./', '/')
    return ret

def mk_relative_osx(path):
    assert sys.platform == 'darwin' and is_obj(path)
    s = macho.install_name_change(path, osx_ch_link)

    names = macho.otool(path)
    if names:
        # Strictly speaking, not all object files have install names (e.g.,
        # bundles and executables do not). In that case, the first name here
        # will not be the install name (i.e., the id), but it isn't a problem,
        # because in that case it will be a no-op (with the exception of stub
        # files, which give an error, which is handled below).
        args = [
            'install_name_tool',
            '-id',
            join('@rpath', relpath(dirname(path),
                join(config.build_prefix, 'lib')), basename(names[0])),
            path,
        ]
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

        # Add an rpath to every executable to increase the chances of it
        # being found.
        args = [
            'install_name_tool',
            '-add_rpath',
            join('@loader_path', relpath(join(config.build_prefix, 'lib'),
                dirname(path)), ''),
            path,
            ]
        print(' '.join(args))
        p = Popen(args, stderr=PIPE)
        stdout, stderr = p.communicate()
        stderr = stderr.decode('utf-8')
        if "Mach-O dynamic shared library stub file" in stderr:
            print("Skipping Mach-O dynamic shared library stub file %s\n" % path)
            return
        elif "would duplicate path, file already has LC_RPATH for:" in stderr:
            print("Skipping -add_rpath, file already has LC_RPATH set")
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

def mk_relative_linux(f, rpaths=('lib',)):
    path = join(config.build_prefix, f)
    rpath = ':'.join('$ORIGIN/' + utils.relative(f, d) for d in rpaths)
    patchelf = external.find_executable('patchelf')
    print('patchelf: file: %s\n    setting rpath to: %s' % (path, rpath))
    call([patchelf, '--set-rpath', rpath, path])

def assert_relative_osx(path):
    for name in macho.otool(path):
        assert not name.startswith(config.build_prefix), path

def mk_relative(m, f):
    assert sys.platform != 'win32'
    path = join(config.build_prefix, f)
    if not is_obj(path):
        return

    if sys.platform.startswith('linux'):
        mk_relative_linux(f, rpaths=m.get_value('build/rpaths', ['lib']))
    elif sys.platform == 'darwin':
        mk_relative_osx(path)


def fix_permissions(files):
    for root, dirs, unused_files in os.walk(config.build_prefix):
        for dn in dirs:
            lchmod(join(root, dn), int('755', 8))

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
        if binary_relocation:
            mk_relative(m, f)

    check_symlinks(files)


def check_symlinks(files):
    if readlink is False:
        return  # Not on Unix system
    msgs = []
    for f in files:
        path = join(config.build_prefix, f)
        if islink(path):
            link_path = readlink(path)
            real_link_path = realpath(path)
            if real_link_path.startswith(config.build_prefix):
                # If the path is in the build prefix, this is fine, but
                # the link needs to be relative
                if not link_path.startswith('.'):
                    # Don't change the link structure if it is already a
                    # relative link. It's possible that ..'s later in the path
                    # can result in a broken link still, but we'll assume that
                    # such crazy things don't happen.
                    print("Making absolute symlink %s -> %s relative" % (f, link_path))
                    os.unlink(path)
                    os.symlink(relpath(real_link_path, dirname(path)), path)
            else:
                # Symlinks to absolute paths on the system (like /usr) are fine.
                if real_link_path.startswith(config.croot):
                    msgs.append("%s is a symlink to a path that may not "
                        "exist after the build is completed (%s)" % (f, link_path))

    if msgs:
        for msg in msgs:
            print("Error: %s" % msg, file=sys.stderr)
        sys.exit(1)

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
