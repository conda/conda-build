from __future__ import absolute_import, division, print_function

from collections import defaultdict
import fnmatch
from functools import partial
from glob2 import glob
import io
import locale
import re
import os
import stat
from subprocess import call, check_output
import sys
try:
    from os import readlink
except ImportError:
    readlink = False

from conda_build.os_utils import external
from conda_build.conda_interface import lchmod
from conda_build.conda_interface import walk_prefix
from conda_build.conda_interface import md5_file
from conda_build.conda_interface import PY3
from conda_build.conda_interface import TemporaryDirectory

from conda_build import utils
from conda_build.os_utils.pyldd import is_codefile, inspect_linkages
from conda_build.inspect_pkg import which_package

if sys.platform == 'darwin':
    from conda_build.os_utils import macho


def is_obj(path):
    return is_codefile(path)


def fix_shebang(f, prefix, build_python, osx_is_app=False):
    path = os.path.join(prefix, f)
    if is_obj(path):
        return
    elif os.path.islink(path):
        return
    elif not os.path.isfile(path):
        return

    if os.stat(path).st_size == 0:
        return

    bytes_ = False

    with io.open(path, encoding=locale.getpreferredencoding(), mode='r+') as fi:
        try:
            data = fi.read(100)
            fi.seek(0)
        except UnicodeDecodeError:  # file is binary
            return

        SHEBANG_PAT = re.compile(r'^#!.+$', re.M)

        # regexp on the memory mapped file so we only read it into
        # memory if the regexp matches.
        try:
            mm = utils.mmap_mmap(fi.fileno(), 0, tagname=None, flags=utils.mmap_MAP_PRIVATE)
        except OSError:
            mm = fi.read()
        try:
            m = SHEBANG_PAT.match(mm)
        except TypeError:
            SHEBANG_PAT = re.compile(br'^#!.+$', re.M)
            bytes_ = True
            m = SHEBANG_PAT.match(mm)

        python_str = b'python' if bytes_ else 'python'

        if not (m and python_str in m.group()):
            return

        data = mm[:]

    py_exec = '#!' + ('/bin/bash ' + prefix + '/bin/pythonw'
               if sys.platform == 'darwin' and osx_is_app else
               prefix + '/bin/' + os.path.basename(build_python))
    if bytes_ and hasattr(py_exec, 'encode'):
        py_exec = py_exec.encode()
    new_data = SHEBANG_PAT.sub(py_exec, data, count=1)
    if new_data == data:
        return
    print("updating shebang:", f)
    with io.open(path, 'w', encoding=locale.getpreferredencoding()) as fo:
        try:
            fo.write(new_data)
        except TypeError:
            fo.write(new_data.decode())
    os.chmod(path, 0o775)


def write_pth(egg_path, config):
    fn = os.path.basename(egg_path)
    py_ver = '.'.join(config.variant['python'].split('.')[:2])
    with open(os.path.join(utils.get_site_packages(config.host_prefix, py_ver),
                           '%s.pth' % (fn.split('-')[0])), 'w') as fo:
        fo.write('./%s\n' % fn)


def remove_easy_install_pth(files, prefix, config, preserve_egg_dir=False):
    """
    remove the need for easy-install.pth and finally remove easy-install.pth
    itself
    """
    absfiles = [os.path.join(prefix, f) for f in files]
    py_ver = '.'.join(config.variant['python'].split('.')[:2])
    sp_dir = utils.get_site_packages(prefix, py_ver)
    for egg_path in glob(os.path.join(sp_dir, '*-py*.egg')):
        if os.path.isdir(egg_path):
            if preserve_egg_dir or not any(os.path.join(egg_path, i) in absfiles for i
                    in walk_prefix(egg_path, False, windows_forward_slashes=False)):
                write_pth(egg_path, config=config)
                continue

            print('found egg dir:', egg_path)
            try:
                os.rename(os.path.join(egg_path, 'EGG-INFO'),
                          egg_path + '-info')
            except OSError:
                pass
            utils.rm_rf(os.path.join(egg_path, 'EGG-INFO'))
            for fn in os.listdir(egg_path):
                if fn == '__pycache__':
                    utils.rm_rf(os.path.join(egg_path, fn))
                else:
                    # this might be a name-space package
                    # so the package directory already exists
                    # from another installed dependency
                    if os.path.exists(os.path.join(sp_dir, fn)):
                        try:
                            utils.copy_into(os.path.join(egg_path, fn),
                                            os.path.join(sp_dir, fn), config.timeout,
                                            locking=config.locking)
                            utils.rm_rf(os.path.join(egg_path, fn))
                        except IOError as e:
                            fn = os.path.basename(str(e).split()[-1])
                            raise IOError("Tried to merge folder {egg_path} into {sp_dir}, but {fn}"
                                          " exists in both locations.  Please either add "
                                          "build/preserve_egg_dir: True to meta.yaml, or manually "
                                          "remove the file during your install process to avoid "
                                          "this conflict."
                                          .format(egg_path=egg_path, sp_dir=sp_dir, fn=fn))
                    else:
                        os.rename(os.path.join(egg_path, fn), os.path.join(sp_dir, fn))

        elif os.path.isfile(egg_path):
            if egg_path not in absfiles:
                continue
            print('found egg:', egg_path)
            write_pth(egg_path, config=config)

    utils.rm_rf(os.path.join(sp_dir, 'easy-install.pth'))


def rm_py_along_so(prefix):
    """remove .py (.pyc) files alongside .so or .pyd files"""
    for root, _, files in os.walk(prefix):
        for fn in files:
            if fn.endswith(('.so', '.pyd')):
                name, _ = os.path.splitext(fn)
                for ext in '.py', '.pyc', '.pyo':
                    if name + ext in files:
                        os.unlink(os.path.join(root, name + ext))


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
    if not os.path.isfile(python_exe):
        return
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
        python_exe = (config.build_python if os.path.isfile(config.build_python) else
                      config.host_python)
        compile_missing_pyc(files, cwd=prefix, python_exe=python_exe,
                            skip_compile_pyc=skip_compile_pyc)
    remove_easy_install_pth(files, prefix, config, preserve_egg_dir=preserve_egg_dir)
    rm_py_along_so(prefix)


def find_lib(link, prefix, files, path=None):
    if link.startswith(prefix):
        link = os.path.normpath(link[len(prefix) + 1:])
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
        link = os.path.basename(link)
        file_names = defaultdict(list)
        for f in files:
            file_names[os.path.basename(f)].append(f)
        if link not in file_names:
            sys.exit("Error: Could not find %s" % link)
        if len(file_names[link]) > 1:
            if path and os.path.basename(path) == link:
                # The link is for the file itself, just use it
                return path
            # Allow for the possibility of the same library appearing in
            # multiple places.
            md5s = set()
            for f in file_names[link]:
                md5s.add(md5_file(os.path.join(prefix, f)))
            if len(md5s) > 1:
                sys.exit("Error: Found multiple instances of %s: %s" % (link, file_names[link]))
            else:
                file_names[link].sort()
                print("Found multiple instances of %s (%s).  "
                    "Choosing the first one." % (link, file_names[link]))
        return file_names[link][0]
    print("Don't know how to find %s, skipping" % link)


def osx_ch_link(path, link_dict, host_prefix, build_prefix, files):
    link = link_dict['name']
    print("Fixing linking of %s in %s" % (link, path))
    if build_prefix != host_prefix and link.startswith(build_prefix):
        link = link.replace(build_prefix, host_prefix)
        print(".. seems to be linking to a compiler runtime, replacing build prefix with "
              "host prefix and")
        if not is_obj(link):
            sys.exit("Error: Compiler runtime library in build prefix not found in host prefix %s"
                     % link)
        else:
            print(".. fixing linking of %s in %s instead" % (link, path))

    link_loc = find_lib(link, host_prefix, files, path)
    print("New link location is %s" % (link_loc))

    if not link_loc:
        return

    lib_to_link = os.path.relpath(os.path.dirname(link_loc), 'lib')
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

    ret = '@rpath/%s/%s' % (lib_to_link, os.path.basename(link))

    # XXX: IF the above fails for whatever reason, the below can be used
    # TODO: This might contain redundant ..'s if link and path are both in
    # some subdirectory of lib.
    # ret = '@loader_path/%s/%s/%s' % (path_to_lib, lib_to_link, basename(link))

    ret = ret.replace('/./', '/')

    return ret


def mk_relative_osx(path, host_prefix, build_prefix, files):
    assert sys.platform == 'darwin' and is_obj(path)

    names = macho.otool(path)
    s = macho.install_name_change(path,
                                  partial(osx_ch_link,
                                          host_prefix=host_prefix,
                                          build_prefix=build_prefix,
                                          files=files),
                                  dylibs=names)

    if names:
        # Add an rpath to every executable to increase the chances of it
        # being found.
        rpath = os.path.join('@loader_path',
                     os.path.relpath(os.path.join(host_prefix, 'lib'),
                             os.path.dirname(path)), '').replace('/./', '/')
        macho.add_rpath(path, rpath, verbose=True)

        # 10.7 install_name_tool -delete_rpath causes broken dylibs, I will revisit this ASAP.
        # .. and remove config.build_prefix/lib which was added in-place of
        # DYLD_FALLBACK_LIBRARY_PATH since El Capitan's SIP.
        # macho.delete_rpath(path, config.build_prefix + '/lib', verbose = True)

    if s:
        # Skip for stub files, which have to use binary_has_prefix_files to be
        # made relocatable.
        assert_relative_osx(path, host_prefix)


def mk_relative_linux(f, prefix, rpaths=('lib',)):
    'Respects the original values and converts abs to $ORIGIN-relative'

    elf = os.path.join(prefix, f)
    origin = os.path.dirname(elf)

    patchelf = external.find_executable('patchelf', prefix)
    try:
        existing = check_output([patchelf, '--print-rpath', elf]).decode('utf-8').splitlines()[0]
    except:
        print('patchelf: --print-rpath failed for %s\n' % (elf))
        return
    existing = existing.split(os.pathsep)
    new = []
    for old in existing:
        if old.startswith('$ORIGIN'):
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


def print_msg(errors, text):
    if text.startswith("  ERROR"):
        errors.append(text)
    print(text)


def _find_needed_dso_in_prefix(m, needed_dso, f, files, errors, run_reqs, host_reqs,
                               msg_prelude, info_prelude):
    in_prefix_dso = os.path.normpath(needed_dso.replace(m.config.host_prefix + '/', ''))
    n_dso_p = "Needed DSO {} in {}".format(in_prefix_dso, f)
    and_also = " (and also in this package)" if in_prefix_dso in files else ""
    pkgs = list(which_package(in_prefix_dso, m.config.host_prefix))
    if len(pkgs) == 1:
        if pkgs[0].quad[0] not in run_reqs:
            print_msg(errors, '{}: {} found in {}{}'.format(msg_prelude,
                                                            n_dso_p,
                                                            pkgs[0],
                                                            and_also))
            print_msg(errors, '{}: .. but {} not in reqs/run, i.e. it is overlinked'
                                ' (likely) or a missing dependency (less likely)'.
                                format(msg_prelude, pkgs[0].quad[0]))
        elif m.config.verbose:
            print_msg(errors, '{}: {} found in {}{}'.format(info_prelude,
                                                            n_dso_p,
                                                            pkgs[0],
                                                            and_also))
    elif len(pkgs) > 1:
        print_msg(errors, '{}: {} found in multiple packages:{}'.format(msg_prelude,
                                                                        in_prefix_dso,
                                                                        and_also))
        for pkg in pkgs:
            print_msg(errors, '{}: {}'.format(msg_prelude, pkg))
            if pkg.dist_name not in host_reqs:
                print_msg(errors, '{}: .. but {} not in reqs/host (is transitive)'.
                format(msg_prelude, pkg.dist_name))
    else:
        if in_prefix_dso not in files:
            print_msg(errors, '{}: {} not found in any packages'.format(msg_prelude,
                                                                        in_prefix_dso))
        elif m.config.verbose:
            print_msg(errors, '{}: {} found in this package'.format(info_prelude,
                                                                    in_prefix_dso))


def _find_needed_dso_in_system(m, needed_dso, errors, sysroots, msg_prelude,
                               info_prelude, warn_prelude):
    # A system dependency then. We should be able to find it in one of the CDT o
    # compiler packages on linux or at in a sysroot folder on other OSes.
    #
    if m.config.verbose and len(sysroots):
        # Check id we have a CDT package.
        dso_fname = os.path.basename(needed_dso)
        sysroot_files = []
        for sysroot in sysroots:
            sysroot_files.extend(glob(os.path.join(sysroot, '**', dso_fname)))
        if len(sysroot_files):
            # Removing config.build_prefix is only *really* for Linux, though we could
            # use CONDA_BUILD_SYSROOT for macOS. We should figure out what to do about
            # /opt/X11 too.
            in_prefix_dso = os.path.normpath(sysroot_files[0].replace(
                m.config.build_prefix + '/', ''))
            n_dso_p = "Needed DSO {}".format(in_prefix_dso)
            pkgs = list(which_package(in_prefix_dso, m.config.build_prefix))
            if len(pkgs):
                print_msg(errors, '{}: {} found in CDT/compiler package {}'.
                                    format(info_prelude, n_dso_p, pkgs[0]))
            else:
                print_msg(errors, '{}: {} not found in any CDT/compiler package?!'.
                                    format(info_prelude, n_dso_p))
        else:
            prelude = warn_prelude if needed_dso.startswith('$RPATH') else msg_prelude
            print_msg(errors, "{}: {} not found in sysroot, is this binary repackaging?"
                                " .. do you need to use install_name_tool/patchelf?".
                                format(prelude, needed_dso))
    else:
        # When a needed_dso begins with $RPATH it means we are making a CDT package
        # (in any other case this would be a problem), but I should verify it is ok
        # for CDT packages too.
        if needed_dso.startswith('$RPATH'):
            print_msg(errors, "{}: {} returned by pyldd. A CDT package?".
                                format(warn_prelude, needed_dso))
        else:
            print_msg(errors, "{}: did not find - or even know where to look for: {}".
                                format(msg_prelude, needed_dso))


def _inspect_file_linking(m, path, files, errors, pkg_name, run_reqs, host_reqs, sysroots):
    f = os.path.basename(path)
    warn_prelude = "WARNING ({},{})".format(pkg_name, f)
    err_prelude = "  ERROR ({},{})".format(pkg_name, f)
    info_prelude = "   INFO ({},{})".format(pkg_name, f)
    msg_prelude = err_prelude if m.config.error_overlinking else warn_prelude

    needed = inspect_linkages(path, resolve_filenames=True, recurse=False)
    for needed_dso in needed:
        if needed_dso.startswith(m.config.host_prefix):
            _find_needed_dso_in_prefix(m, needed_dso, f, files, errors, run_reqs, host_reqs,
                                       msg_prelude, info_prelude)
        elif needed_dso.startswith(m.config.build_prefix):
            print_msg(errors, "ERROR: {} found in build prefix; should never happen".format(
                needed_dso))
        else:
            _find_needed_dso_in_system(m, needed_dso, errors, sysroots, msg_prelude, info_prelude,
                                       warn_prelude)


def check_overlinking(m, files):
    errors = []
    pkg_name = m.get_value('package/name')

    run_reqs = [req.split(' ')[0] for req in m.meta.get('requirements', {}).get('run', [])]
    host_reqs = [req.split(' ')[0] for req in m.meta.get('requirements', {}).get('host', [])]
    sysroots = glob(os.path.join(m.config.build_prefix, '**', 'sysroot'))
    if not len(sysroots):
        if m.config.variant.get('target_platform') == 'osx-64':
            sysroots = ['/usr/lib', '/opt/X11', '/System/Library/Frameworks']

    for f in files:
        path = os.path.join(m.config.host_prefix, f)
        if not is_obj(path):
            continue
        _inspect_file_linking(m, path, files, errors, pkg_name, run_reqs, host_reqs, sysroots)
        if len(errors):
            sys.exit(1)


def post_process_shared_lib(m, f, files):
    path = os.path.join(m.config.host_prefix, f)
    if not is_obj(path):
        return
    if sys.platform.startswith('linux'):
        mk_relative_linux(f, m.config.host_prefix, rpaths=m.get_value('build/rpaths', ['lib']))
    elif sys.platform == 'darwin':
        mk_relative_osx(path, m.config.host_prefix, m.config.build_prefix, files=files)


def fix_permissions(files, prefix):
    print("Fixing permissions")
    for root, dirs, _ in os.walk(prefix):
        for dn in dirs:
            lchmod(os.path.join(root, dn), 0o775)

    for f in files:
        path = os.path.join(prefix, f)
        st = os.lstat(path)
        old_mode = stat.S_IMODE(st.st_mode)
        new_mode = old_mode
        # broadcast execute
        if old_mode & stat.S_IXUSR:
            new_mode = new_mode | stat.S_IXGRP | stat.S_IXOTH
        # ensure user and group can write and all can read
        new_mode = new_mode | stat.S_IWUSR | stat.S_IWGRP | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH  # noqa
        if old_mode != new_mode:
            try:
                lchmod(path, new_mode)
            except (OSError, utils.PermissionError) as e:
                log = utils.get_logger(__name__)
                log.warn(str(e))


def post_build(m, files, build_python):
    print('number of files:', len(files))
    fix_permissions(files, m.config.host_prefix)

    for f in files:
        make_hardlink_copy(f, m.config.host_prefix)

    if sys.platform == 'win32':
        return

    binary_relocation = m.binary_relocation()
    if not binary_relocation:
        print("Skipping binary relocation logic")
    osx_is_app = bool(m.get_value('build/osx_is_app', False)) and sys.platform == 'darwin'

    check_symlinks(files, m.config.host_prefix, m.config.croot)
    prefix_files = utils.prefix_files(m.config.host_prefix)

    for f in files:
        if f.startswith('bin/'):
            fix_shebang(f, prefix=m.config.host_prefix, build_python=build_python,
                        osx_is_app=osx_is_app)
        if binary_relocation is True or (isinstance(binary_relocation, list) and
                                         f in binary_relocation):
            post_process_shared_lib(m, f, prefix_files)
    check_overlinking(m, files)


def check_symlinks(files, prefix, croot):
    if readlink is False:
        return  # Not on Unix system
    msgs = []
    real_build_prefix = os.path.realpath(prefix)
    for f in files:
        path = os.path.join(real_build_prefix, f)
        if os.path.islink(path):
            link_path = readlink(path)
            real_link_path = os.path.realpath(path)
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
                    os.symlink(os.path.relpath(real_link_path, os.path.dirname(path)), path)
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
    if not os.path.isabs(path):
        path = os.path.normpath(os.path.join(prefix, path))
    fn = os.path.basename(path)
    if os.lstat(path).st_nlink > 1:
        with TemporaryDirectory() as dest:
            # copy file to new name
            utils.copy_into(path, dest)
            # remove old file
            utils.rm_rf(path)
            # rename copy to original filename
            #   It is essential here to use copying (as opposed to os.rename), so that
            #        crossing volume boundaries works
            utils.copy_into(os.path.join(dest, fn), path)


def get_build_metadata(m):
    src_dir = m.config.work_dir
    if os.path.exists(os.path.join(src_dir, '__conda_version__.txt')):
        raise ValueError("support for __conda_version__ has been removed as of Conda-build 3.0."
              "Try Jinja templates instead: "
              "http://conda.pydata.org/docs/building/meta-yaml.html#templating-with-jinja")
    if os.path.exists(os.path.join(src_dir, '__conda_buildnum__.txt')):
        raise ValueError("support for __conda_buildnum__ has been removed as of Conda-build 3.0."
              "Try Jinja templates instead: "
              "http://conda.pydata.org/docs/building/meta-yaml.html#templating-with-jinja")
    if os.path.exists(os.path.join(src_dir, '__conda_buildstr__.txt')):
        raise ValueError("support for __conda_buildstr__ has been removed as of Conda-build 3.0."
              "Try Jinja templates instead: "
              "http://conda.pydata.org/docs/building/meta-yaml.html#templating-with-jinja")
