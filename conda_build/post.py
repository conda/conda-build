from __future__ import absolute_import, division, print_function

from collections import defaultdict
from functools import partial
from glob import glob
import io
import locale
import mmap
import re
import os
import fnmatch
from os.path import (basename, dirname, join, splitext, isdir, isfile, exists,
                     islink, realpath, relpath, normpath)
import stat
from subprocess import call, check_output
import sys
try:
    from os import readlink
except ImportError:
    readlink = False

from conda_build.os_utils import external
from .conda_interface import lchmod
from .conda_interface import walk_prefix
from .conda_interface import md5_file
from .conda_interface import PY3

from conda_build import utils

if sys.platform.startswith('linux'):
    from conda_build.os_utils import elf
elif sys.platform == 'darwin':
    from conda_build.os_utils import macho

SHEBANG_PAT = re.compile(br'^#!.+$', re.M)


def is_obj(path):
    assert sys.platform != 'win32'
    return bool((sys.platform.startswith('linux') and elf.is_elf(path)) or
                (sys.platform == 'darwin' and macho.is_macho(path)))


def fix_shebang(f, prefix, build_python, osx_is_app=False):
    path = join(prefix, f)
    if is_obj(path):
        return
    elif os.path.islink(path):
        return
    elif not os.path.isfile(path):
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

    py_exec = ('/bin/bash ' + prefix + '/bin/python.app'
               if sys.platform == 'darwin' and osx_is_app else
               prefix + '/bin/' + basename(build_python))
    new_data = SHEBANG_PAT.sub(b'#!' + py_exec.encode(encoding), data, count=1)
    if new_data == data:
        return
    print("updating shebang:", f)
    with io.open(path, 'w', encoding=locale.getpreferredencoding()) as fo:
        fo.write(new_data.decode(encoding))
    os.chmod(path, 0o775)


def write_pth(egg_path, config):
    fn = basename(egg_path)
    with open(join(utils.get_site_packages(config.build_prefix),
                   '%s.pth' % (fn.split('-')[0])), 'w') as fo:
        fo.write('./%s\n' % fn)


def remove_easy_install_pth(files, prefix, config, preserve_egg_dir=False):
    """
    remove the need for easy-install.pth and finally remove easy-install.pth
    itself
    """
    absfiles = [join(prefix, f) for f in files]
    sp_dir = utils.get_site_packages(prefix)
    for egg_path in glob(join(sp_dir, '*-py*.egg')):
        if isdir(egg_path):
            if preserve_egg_dir or not any(join(egg_path, i) in absfiles for i
                    in walk_prefix(egg_path, False, windows_forward_slashes=False)):
                write_pth(egg_path, config=config)
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
                        try:
                            utils.copy_into(join(egg_path, fn), join(sp_dir, fn), config.timeout)
                            utils.rm_rf(join(egg_path, fn))
                        except IOError as e:
                            fn = os.path.basename(str(e).split()[-1])
                            raise IOError("Tried to merge folder {egg_path} into {sp_dir}, but {fn}"
                                          " exists in both locations.  Please either add "
                                          "build/preserve_egg_dir: True to meta.yaml, or manually "
                                          "remove the file during your install process to avoid "
                                          "this conflict."
                                          .format(egg_path=egg_path, sp_dir=sp_dir, fn=fn))
                    else:
                        os.rename(join(egg_path, fn), join(sp_dir, fn))

        elif isfile(egg_path):
            if egg_path not in absfiles:
                continue
            print('found egg:', egg_path)
            write_pth(egg_path, config=config)

    utils.rm_rf(join(sp_dir, 'easy-install.pth'))


def rm_py_along_so(prefix):
    """remove .py (.pyc) files alongside .so or .pyd files"""
    for root, _, files in os.walk(prefix):
        for fn in files:
            if fn.endswith(('.so', '.pyd')):
                name, _ = splitext(fn)
                for ext in '.py', '.pyc', '.pyo':
                    if name + ext in files:
                        os.unlink(join(root, name + ext))


def rm_pyo(files, prefix):
    """pyo considered harmful: https://www.python.org/dev/peps/pep-0488/

    The build may have proceeded with:
        [install]
        optimize = 1
    .. in setup.cfg in which case we can end up with some stdlib __pycache__
    files ending in .opt-N.pyc on Python 3, as well as .pyo files for the
    package's own python. """
    re_pyo = re.compile(r'.*(?:\.pyo$|\.opt-[0-9]\.pyc)')
    for fn in files:
        if re_pyo.match(fn):
            os.unlink(os.path.join(prefix, fn))


def rm_pyc(files, prefix):
    re_pyc = re.compile(r'.*(?:\.pyc$)')
    for fn in files:
        if re_pyc.match(fn):
            os.unlink(os.path.join(prefix, fn))


def compile_missing_pyc(files, cwd, python_exe, skip_compile_pyc=()):
    compile_files = []
    skip_compile_pyc_n = [os.path.normpath(skip) for skip in skip_compile_pyc]
    skipped_files = set()
    for skip in skip_compile_pyc_n:
        skipped_files.update(set(fnmatch.filter(files, skip)))
    unskipped_files = set(files) - skipped_files
    for fn in unskipped_files:
        # omit files in Library/bin, Scripts, and the root prefix - they are not generally imported
        if sys.platform == 'win32':
            if any([fn.lower().startswith(start) for start in ['library/bin', 'library\\bin',
                                                               'scripts']]):
                continue
        else:
            if fn.startswith('bin'):
                continue
        cache_prefix = ("__pycache__" + os.sep) if PY3 else ""
        if (fn.endswith(".py") and
                os.path.dirname(fn) + cache_prefix + os.path.basename(fn) + 'c' not in files):
            compile_files.append(fn)

    if compile_files:
        if not os.path.isfile(python_exe):
            print('compiling .pyc files... failed as no python interpreter was found')
        else:
            print('compiling .pyc files...')
            for f in compile_files:
                call([python_exe, '-Wi', '-m', 'py_compile', f], cwd=cwd)


def post_process(files, prefix, config, preserve_egg_dir=False, noarch=False, skip_compile_pyc=()):
    rm_pyo(files, prefix)
    if noarch:
        rm_pyc(files, prefix)
    else:
        compile_missing_pyc(files, cwd=prefix, python_exe=config.build_python,
                            skip_compile_pyc=skip_compile_pyc)
    remove_easy_install_pth(files, prefix, config, preserve_egg_dir=preserve_egg_dir)
    rm_py_along_so(prefix)


def find_lib(link, prefix, path=None):
    from conda_build.build import prefix_files
    files = prefix_files(prefix)
    if link.startswith(prefix):
        link = normpath(link[len(prefix) + 1:])
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
                md5s.add(md5_file(join(prefix, f)))
            if len(md5s) > 1:
                sys.exit("Error: Found multiple instances of %s: %s" % (link, file_names[link]))
            else:
                file_names[link].sort()
                print("Found multiple instances of %s (%s).  "
                    "Choosing the first one." % (link, file_names[link]))
        return file_names[link][0]
    print("Don't know how to find %s, skipping" % link)


def osx_ch_link(path, link_dict, prefix):
    link = link_dict['name']
    print("Fixing linking of %s in %s" % (link, path))
    link_loc = find_lib(link, prefix, path)
    if not link_loc:
        return

    lib_to_link = relpath(dirname(link_loc), 'lib')
    # path_to_lib = utils.relative(path[len(prefix) + 1:])

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


def mk_relative_osx(path, prefix, build_prefix=None):
    '''
    if build_prefix is None, the_n this is a standard conda build. The path
    and all dependencies are in the build_prefix.

    if package is built in develop mode, build_prefix is specified. Object
    specified by 'path' needs to relink runtime dependences to libs found in
    build_prefix/lib/. Also, in develop mode, 'path' is not in 'build_prefix'
    '''
    if build_prefix is None:
        assert path.startswith(prefix + '/')
    else:
        prefix = build_prefix

    assert sys.platform == 'darwin' and is_obj(path)
    s = macho.install_name_change(path, partial(osx_ch_link, prefix=prefix))

    names = macho.otool(path)
    if names:
        # Add an rpath to every executable to increase the chances of it
        # being found.
        rpath = join('@loader_path',
                     relpath(join(prefix, 'lib'),
                             dirname(path)), '').replace('/./', '/')
        macho.add_rpath(path, rpath, verbose=True)

        # 10.7 install_name_tool -delete_rpath causes broken dylibs, I will revisit this ASAP.
        # .. and remove config.build_prefix/lib which was added in-place of
        # DYLD_FALLBACK_LIBRARY_PATH since El Capitan's SIP.
        # macho.delete_rpath(path, config.build_prefix + '/lib', verbose = True)

    if s:
        # Skip for stub files, which have to use binary_has_prefix_files to be
        # made relocatable.
        assert_relative_osx(path, prefix)


def mk_relative_linux(f, prefix, rpaths=('lib',)):
    'Respects the original values and converts abs to $ORIGIN-relative'

    elf = join(prefix, f)
    origin = dirname(elf)

    patchelf = external.find_executable('patchelf', prefix)
    try:
        existing = check_output([patchelf, '--print-rpath', elf]).decode('utf-8').splitlines()[0]
    except:
        print('patchelf: --print-rpath failed for %s\n' % (elf))
        return
    existing = existing.split(os.pathsep)
    new = []
    for old in existing:
        if old.startswith('$ORIGIN/'):
            new.append(old)
        elif old.startswith('/'):
            # Test if this absolute path is outside of prefix. That is fatal.
            relpath = os.path.relpath(old, prefix)
            if relpath.startswith('..' + os.sep):
                print('Warning: rpath {0} is outside prefix {1} (removing it)'.format(old, prefix))
            else:
                relpath = '$ORIGIN/' + os.path.relpath(old, origin)
                if relpath not in new:
                    new.append(relpath)
    # Ensure that the asked-for paths are also in new.
    for rpath in rpaths:
        if not rpath.startswith('/'):
            # IMHO utils.relative shouldn't exist, but I am too paranoid to remove
            # it, so instead, make sure that what I think it should be replaced by
            # gives the same result and assert if not. Yeah, I am a chicken.
            rel_ours = os.path.normpath(utils.relative(f, rpath))
            rel_stdlib = os.path.normpath(os.path.relpath(rpath, os.path.dirname(f)))
            assert rel_ours == rel_stdlib, \
                'utils.relative {0} and relpath {1} disagree for {2}, {3}'.format(
                rel_ours, rel_stdlib, f, rpath)
            rpath = '$ORIGIN/' + rel_stdlib
        if rpath not in new:
            new.append(rpath)
    rpath = ':'.join(new)
    print('patchelf: file: %s\n    setting rpath to: %s' % (elf, rpath))
    call([patchelf, '--force-rpath', '--set-rpath', rpath, elf])


def assert_relative_osx(path, prefix):
    for name in macho.get_dylibs(path):
        assert not name.startswith(prefix), path


def mk_relative(m, f, prefix):
    assert sys.platform != 'win32'
    path = join(prefix, f)
    if not is_obj(path):
        return

    if sys.platform.startswith('linux'):
        mk_relative_linux(f, prefix=prefix, rpaths=m.get_value('build/rpaths', ['lib']))
    elif sys.platform == 'darwin':
        mk_relative_osx(path, prefix=prefix)


def fix_permissions(files, prefix):
    print("Fixing permissions")
    for root, dirs, _ in os.walk(prefix):
        for dn in dirs:
            lchmod(join(root, dn), 0o775)

    for f in files:
        path = join(prefix, f)
        st = os.lstat(path)
        old_mode = stat.S_IMODE(st.st_mode)
        new_mode = old_mode
        # broadcast execute
        if old_mode & stat.S_IXUSR:
            new_mode = new_mode | stat.S_IXGRP | stat.S_IXOTH
        # ensure user and group can write and all can read
        new_mode = new_mode | stat.S_IWUSR | stat.S_IWGRP | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH  # noqa
        if old_mode != new_mode:
            lchmod(path, new_mode)


def post_build(m, files, prefix, build_python, croot):
    print('number of files:', len(files))
    fix_permissions(files, prefix)

    if sys.platform == 'win32':
        return

    binary_relocation = m.binary_relocation()
    if not binary_relocation:
        print("Skipping binary relocation logic")
    osx_is_app = bool(m.get_value('build/osx_is_app', False))

    check_symlinks(files, prefix, croot)

    for f in files:
        if f.startswith('bin/'):
            fix_shebang(f, prefix=prefix, build_python=build_python, osx_is_app=osx_is_app)
        if binary_relocation is True or (isinstance(f, list) and f in binary_relocation):
            mk_relative(m, f, prefix)
        make_hardlink_copy(f, prefix)


def check_symlinks(files, prefix, croot):
    if readlink is False:
        return  # Not on Unix system
    msgs = []
    real_build_prefix = realpath(prefix)
    for f in files:
        path = join(real_build_prefix, f)
        if islink(path):
            link_path = readlink(path)
            real_link_path = realpath(path)
            # symlinks to binaries outside of the same dir don't work.  RPATH stuff gets confused
            #    because ld.so follows symlinks in RPATHS
            #    If condition exists, then copy the file rather than symlink it.
            if (not os.path.dirname(link_path) == os.path.dirname(real_link_path) and
                    is_obj(f)):
                os.remove(path)
                utils.copy_into(real_link_path, path)
            elif real_link_path.startswith(real_build_prefix):
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
                if real_link_path.startswith(croot):
                    msgs.append("%s is a symlink to a path that may not "
                        "exist after the build is completed (%s)" % (f, link_path))

    if msgs:
        for msg in msgs:
            print("Error: %s" % msg, file=sys.stderr)
        sys.exit(1)


def make_hardlink_copy(path, prefix):
    """Hardlinks create invalid packages.  Copy files to break the link.
    Symlinks are OK, and unaffected here."""
    if not os.path.isabs(path) and not os.path.exists(path):
        path = os.path.normpath(os.path.join(prefix, path))
    nlinks = os.lstat(path).st_nlink
    dest = 'tmpfile'
    if os.path.isabs(path):
        dest = os.path.join(os.getcwd(), dest)
    if nlinks > 1:
        # copy file to new name
        utils.copy_into(path, dest)
        # remove old file
        utils.rm_rf(path)
        # rename copy to original filename
        utils.copy_into(dest, path)
        utils.rm_rf(dest)


def get_build_metadata(m, config):
    src_dir = config.work_dir

    if "build" not in m.meta:
        m.meta["build"] = {}
    if exists(join(src_dir, '__conda_version__.txt')):
        print("Deprecation warning: support for __conda_version__ will be removed in Conda build 3.0."  # noqa
              "Try Jinja templates instead: "
              "http://conda.pydata.org/docs/building/meta-yaml.html#templating-with-jinja")
        with open(join(src_dir, '__conda_version__.txt')) as f:
            version = f.read().strip()
            print("Setting version from __conda_version__.txt: %s" % version)
            m.meta['package']['version'] = version
    if exists(join(src_dir, '__conda_buildnum__.txt')):
        print("Deprecation warning: support for __conda_buildnum__ will be removed in Conda build 3.0."  # noqa
              "Try Jinja templates instead: "
              "http://conda.pydata.org/docs/building/meta-yaml.html#templating-with-jinja")
        with open(join(src_dir, '__conda_buildnum__.txt')) as f:
            build_number = f.read().strip()
            print("Setting build number from __conda_buildnum__.txt: %s" %
                  build_number)
            m.meta['build']['number'] = build_number
    if exists(join(src_dir, '__conda_buildstr__.txt')):
        print("Deprecation warning: support for __conda_buildstr__ will be removed in Conda build 3.0."  # noqa
              "Try Jinja templates instead: "
              "http://conda.pydata.org/docs/building/meta-yaml.html#templating-with-jinja")
        with open(join(src_dir, '__conda_buildstr__.txt')) as f:
            buildstr = f.read().strip()
            print("Setting version from __conda_buildstr__.txt: %s" % buildstr)
            m.meta['build']['string'] = buildstr
