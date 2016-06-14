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
from subprocess import call
from collections import defaultdict
import mmap

from conda_build.config import config
from conda_build import external
from conda_build import environ
from conda_build import utils
from conda_build import source
from conda.compat import lchmod
from conda.misc import walk_prefix
from conda.utils import md5_file

if sys.platform.startswith('linux'):
    from conda_build import elf
elif sys.platform == 'darwin':
    from conda_build import macho

SHEBANG_PAT = re.compile(br'^#!.+$', re.M)


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

    if os.stat(path).st_size == 0:
        return

    with io.open(path, encoding=locale.getpreferredencoding(), mode='r+') as fi:
        try:
            data = fi.read(100)
        except UnicodeDecodeError:  # file is binary
            return

        # regexp on the memory mapped file so we only read it into
        # memory if the regexp matches.
        mm = mmap.mmap(fi.fileno(), 0)
        m = SHEBANG_PAT.match(mm)

        if not (m and b'python' in m.group()):
            return

        data = mm[:]

    encoding = sys.stdout.encoding or 'utf8'

    py_exec = ('/bin/bash ' + config.build_prefix + '/bin/python.app'
               if sys.platform == 'darwin' and osx_is_app else
               config.build_prefix + '/bin/' + basename(config.build_python))
    lib = "{0}_LIBRARY_PATH={1}/lib".format('DYLD' if sys.platform == 'darwin' else 'LD',
                                            config.build_prefix)
    new_shebang = '#!/usr/bin/env {0} {1}'.format(lib, py_exec).encode(encoding)
    new_data = SHEBANG_PAT.sub(new_shebang, data, count=1)
    if new_data == data:
        return
    print("updating shebang of {0} with {1}".format(f, new_data.split('\n')[0]))
    with io.open(path, 'w', encoding=locale.getpreferredencoding()) as fo:
        fo.write(new_data.decode(encoding))
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
            if preserve_egg_dir or not any(join(egg_path, i) in absfiles for i
                    in walk_prefix(egg_path, False, windows_forward_slashes=False)):
                write_pth(egg_path)
                continue

            print('found egg dir:', egg_path)
            try:
                os.rename(join(egg_path, 'EGG-INFO'),
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
            if egg_path not in absfiles:
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
    if config.CONDA_PY < 30:
        compile_missing_pyc()


def find_lib(link, path=None):
    from conda_build.build import prefix_files
    files = prefix_files()
    if link.startswith(config.build_prefix):
        link = link[len(config.build_prefix) + 1:]
        if link not in files:
            sys.exit("Error: Could not find %s" % link)
        return link
    if link.startswith('/'):  # but doesn't start with the build prefix
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
            if path and basename(path) == link:
                # The link is for the file itself, just use it
                return path
            # Allow for the possibility of the same library appearing in
            # multiple places.
            md5s = set()
            for f in file_names[link]:
                md5s.add(md5_file(join(config.build_prefix, f)))
            if len(md5s) > 1:
                sys.exit("Error: Found multiple instances of %s: %s" % (link, file_names[link]))
            else:
                file_names[link].sort()
                print("Found multiple instances of %s (%s).  "
                    "Choosing the first one." % (link, file_names[link]))
        return file_names[link][0]
    print("Don't know how to find %s, skipping" % link)


def osx_ch_link(path, link_dict):
    link = link_dict['name']
    print("Fixing linking of %s in %s" % (link, path))
    link_loc = find_lib(link, path)
    if not link_loc:
        return

    lib_to_link = relpath(dirname(link_loc), 'lib')
    # path_to_lib = utils.relative(path[len(config.build_prefix) + 1:])

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

    ret = '@rpath/%s/%s' % (lib_to_link, basename(link))

    # XXX: IF the above fails for whatever reason, the below can be used
    # TODO: This might contain redundant ..'s if link and path are both in
    # some subdirectory of lib.
    # ret = '@loader_path/%s/%s/%s' % (path_to_lib, lib_to_link, basename(link))

    ret = ret.replace('/./', '/')

    return ret


def mk_relative_osx(path, build_prefix=None):
    '''
    if build_prefix is None, then this is a standard conda build. The path
    and all dependencies are in the build_prefix.

    if package is built in develop mode, build_prefix is specified. Object
    specified by 'path' needs to relink runtime dependences to libs found in
    build_prefix/lib/. Also, in develop mode, 'path' is not in 'build_prefix'
    '''
    if build_prefix is None:
        assert path.startswith(config.build_prefix + '/')
    else:
        config.short_build_prefix = build_prefix

    assert sys.platform == 'darwin' and is_obj(path)
    s = macho.install_name_change(path, osx_ch_link)

    names = macho.otool(path)
    if names:
        # Add an rpath to every executable to increase the chances of it
        # being found.
        rpath = join('@loader_path',
                     relpath(join(config.build_prefix, 'lib'),
                             dirname(path)), '').replace('/./', '/')
        macho.add_rpath(path, rpath, verbose=True)

        # 10.7 install_name_tool -delete_rpath causes broken dylibs, I will revisit this ASAP.
        # .. and remove config.build_prefix/lib which was added in-place of
        # DYLD_FALLBACK_LIBRARY_PATH since El Capitan's SIP.
        # macho.delete_rpath(path, config.build_prefix + '/lib', verbose = True)

    if s:
        # Skip for stub files, which have to use binary_has_prefix_files to be
        # made relocatable.
        assert_relative_osx(path)


def mk_relative_linux(f, rpaths=('lib',)):
    path = join(config.build_prefix, f)
    rpath = ':'.join('$ORIGIN/' + utils.relative(f, d) if not
        d.startswith('/') else d for d in rpaths)
    patchelf = external.find_executable('patchelf')
    print('patchelf: file: %s\n    setting rpath to: %s' % (path, rpath))
    call([patchelf, '--force-rpath', '--set-rpath', rpath, path])


def assert_relative_osx(path):
    for name in macho.get_dylibs(path):
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
    print("Fixing permissions")
    for root, dirs, unused_files in os.walk(config.build_prefix):
        for dn in dirs:
            lchmod(join(root, dn), int('755', 8))

    for f in files:
        path = join(config.build_prefix, f)
        st = os.lstat(path)
        lchmod(path, stat.S_IMODE(st.st_mode) | stat.S_IWUSR)  # chmod u+w


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
    real_build_prefix = realpath(config.build_prefix)
    for f in files:
        path = join(real_build_prefix, f)
        if islink(path):
            link_path = readlink(path)
            real_link_path = realpath(path)
            if real_link_path.startswith(real_build_prefix):
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
    src_dir = source.get_dir()
    if "build" not in m.meta:
        m.meta["build"] = {}
    if exists(join(src_dir, '__conda_version__.txt')):
        print("Deprecation warning: support for __conda_version__ will be removed in Conda build 2.0."  # noqa
              "Try Jinja templates instead: "
              "http://conda.pydata.org/docs/building/environment-vars.html#git-environment-variables")  # noqa
        with open(join(src_dir, '__conda_version__.txt')) as f:
            version = f.read().strip()
            print("Setting version from __conda_version__.txt: %s" % version)
            m.meta['package']['version'] = version
    if exists(join(src_dir, '__conda_buildnum__.txt')):
        print("Deprecation warning: support for __conda_buildnum__ will be removed in Conda build 2.0."  # noqa
              "Try Jinja templates instead: "
              "http://conda.pydata.org/docs/building/environment-vars.html#git-environment-variables")  # noqa
        with open(join(src_dir, '__conda_buildnum__.txt')) as f:
            build_number = f.read().strip()
            print("Setting build number from __conda_buildnum__.txt: %s" %
                  build_number)
            m.meta['build']['number'] = build_number
    if exists(join(src_dir, '__conda_buildstr__.txt')):
        print("Deprecation warning: support for __conda_buildstr__ will be removed in Conda build 2.0."  # noqa
              "Try Jinja templates instead: "
              "http://conda.pydata.org/docs/building/environment-vars.html#git-environment-variables")  # noqa
        with open(join(src_dir, '__conda_buildstr__.txt')) as f:
            buildstr = f.read().strip()
            print("Setting version from __conda_buildstr__.txt: %s" % buildstr)
            m.meta['build']['string'] = buildstr
