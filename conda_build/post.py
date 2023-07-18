# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import locale
import os
import re
import shutil
import stat
import sys
from collections import OrderedDict, defaultdict
from copy import copy
from fnmatch import filter as fnmatch_filter
from fnmatch import fnmatch
from fnmatch import translate as fnmatch_translate
from functools import partial
from os.path import (
    basename,
    dirname,
    exists,
    isabs,
    isdir,
    isfile,
    islink,
    join,
    normpath,
    realpath,
    relpath,
    sep,
    splitext,
)
from subprocess import CalledProcessError, call, check_output

try:
    from os import readlink
except ImportError:
    readlink = False

from conda_build import utils
from conda_build.conda_interface import (
    TemporaryDirectory,
    lchmod,
    md5_file,
    walk_prefix,
)
from conda_build.exceptions import OverDependingError, OverLinkingError, RunPathError
from conda_build.inspect_pkg import which_package
from conda_build.os_utils import external, macho
from conda_build.os_utils.ldd import get_package_files, get_package_obj_files
from conda_build.os_utils.liefldd import (
    get_exports_memoized,
    get_linkages_memoized,
    get_rpaths_raw,
    get_runpaths_raw,
    have_lief,
    set_rpath,
)
from conda_build.os_utils.pyldd import codefile_type

filetypes_for_platform = {
    "win": ("DLLfile", "EXEfile"),
    "osx": ["machofile"],
    "linux": ["elffile"],
}


def fix_shebang(f, prefix, build_python, osx_is_app=False):
    path = join(prefix, f)
    if codefile_type(path):
        return
    elif islink(path):
        return
    elif not isfile(path):
        return

    if os.stat(path).st_size == 0:
        return

    bytes_ = False

    os.chmod(path, 0o775)
    with open(path, mode="r+", encoding=locale.getpreferredencoding()) as fi:
        try:
            data = fi.read(100)
            fi.seek(0)
        except UnicodeDecodeError:  # file is binary
            return

        SHEBANG_PAT = re.compile(r"^#!.+$", re.M)

        # regexp on the memory mapped file so we only read it into
        # memory if the regexp matches.
        try:
            mm = utils.mmap_mmap(
                fi.fileno(), 0, tagname=None, flags=utils.mmap_MAP_PRIVATE
            )
        except OSError:
            mm = fi.read()
        try:
            m = SHEBANG_PAT.match(mm)
        except TypeError:
            SHEBANG_PAT = re.compile(rb"^#!.+$", re.M)
            bytes_ = True
            m = SHEBANG_PAT.match(mm)

        if m:
            python_pattern = (
                re.compile(rb"\/python[w]?(?:$|\s|\Z)", re.M)
                if bytes_
                else re.compile(r"\/python[w]?(:$|\s|\Z)", re.M)
            )
            if not re.search(python_pattern, m.group()):
                return
        else:
            return

        data = mm[:]

    py_exec = "#!" + (
        "/bin/bash " + prefix + "/bin/pythonw"
        if sys.platform == "darwin" and osx_is_app
        else prefix + "/bin/" + basename(build_python)
    )
    if bytes_ and hasattr(py_exec, "encode"):
        py_exec = py_exec.encode()
    new_data = SHEBANG_PAT.sub(py_exec, data, count=1)
    if new_data == data:
        return
    print("updating shebang:", f)
    with open(path, "w", encoding=locale.getpreferredencoding()) as fo:
        try:
            fo.write(new_data)
        except TypeError:
            fo.write(new_data.decode())


def write_pth(egg_path, config):
    fn = basename(egg_path)
    py_ver = ".".join(config.variant["python"].split(".")[:2])
    with open(
        join(
            utils.get_site_packages(config.host_prefix, py_ver),
            "%s.pth" % (fn.split("-")[0]),
        ),
        "w",
    ) as fo:
        fo.write("./%s\n" % fn)


def remove_easy_install_pth(files, prefix, config, preserve_egg_dir=False):
    """
    remove the need for easy-install.pth and finally remove easy-install.pth
    itself
    """
    absfiles = [join(prefix, f) for f in files]
    py_ver = ".".join(config.variant["python"].split(".")[:2])
    sp_dir = utils.get_site_packages(prefix, py_ver)
    for egg_path in utils.glob(join(sp_dir, "*-py*.egg")):
        if isdir(egg_path):
            if preserve_egg_dir or not any(
                join(egg_path, i) in absfiles
                for i in walk_prefix(egg_path, False, windows_forward_slashes=False)
            ):
                write_pth(egg_path, config=config)
                continue

            print("found egg dir:", egg_path)
            try:
                shutil.move(join(egg_path, "EGG-INFO"), egg_path + "-info")
            except OSError:
                pass
            utils.rm_rf(join(egg_path, "EGG-INFO"))
            for fn in os.listdir(egg_path):
                if fn == "__pycache__":
                    utils.rm_rf(join(egg_path, fn))
                else:
                    # this might be a name-space package
                    # so the package directory already exists
                    # from another installed dependency
                    if exists(join(sp_dir, fn)):
                        try:
                            utils.copy_into(
                                join(egg_path, fn),
                                join(sp_dir, fn),
                                config.timeout,
                                locking=config.locking,
                            )
                            utils.rm_rf(join(egg_path, fn))
                        except OSError as e:
                            fn = basename(str(e).split()[-1])
                            raise OSError(
                                "Tried to merge folder {egg_path} into {sp_dir}, but {fn}"
                                " exists in both locations.  Please either add "
                                "build/preserve_egg_dir: True to meta.yaml, or manually "
                                "remove the file during your install process to avoid "
                                "this conflict.".format(
                                    egg_path=egg_path, sp_dir=sp_dir, fn=fn
                                )
                            )
                    else:
                        shutil.move(join(egg_path, fn), join(sp_dir, fn))

        elif isfile(egg_path):
            if egg_path not in absfiles:
                continue
            print("found egg:", egg_path)
            write_pth(egg_path, config=config)

    installer_files = [f for f in absfiles if f.endswith(f".dist-info{sep}INSTALLER")]
    for file in installer_files:
        with open(file, "w") as f:
            f.write("conda")

    utils.rm_rf(join(sp_dir, "easy-install.pth"))


def rm_py_along_so(prefix):
    """remove .py (.pyc) files alongside .so or .pyd files"""

    files = list(os.scandir(prefix))
    for fn in files:
        if fn.is_file() and fn.name.endswith((".so", ".pyd")):
            for ext in ".py", ".pyc", ".pyo":
                name, _ = splitext(fn.path)
                name = normpath(name + ext)
                if any(name == normpath(f) for f in files):
                    os.unlink(name + ext)


def rm_pyo(files, prefix):
    """pyo considered harmful: https://www.python.org/dev/peps/pep-0488/

    The build may have proceeded with:
        [install]
        optimize = 1
    .. in setup.cfg in which case we can end up with some stdlib __pycache__
    files ending in .opt-N.pyc on Python 3, as well as .pyo files for the
    package's own python."""
    re_pyo = re.compile(r".*(?:\.pyo$|\.opt-[0-9]\.pyc)")
    for fn in files:
        if re_pyo.match(fn):
            os.unlink(join(prefix, fn))


def rm_pyc(files, prefix):
    re_pyc = re.compile(r".*(?:\.pyc$)")
    for fn in files:
        if re_pyc.match(fn):
            os.unlink(join(prefix, fn))


def rm_share_info_dir(files, prefix):
    if "share/info/dir" in files:
        fn = join(prefix, "share", "info", "dir")
        if isfile(fn):
            os.unlink(fn)


def compile_missing_pyc(files, cwd, python_exe, skip_compile_pyc=()):
    if not isfile(python_exe):
        return
    compile_files = []
    skip_compile_pyc_n = [normpath(skip) for skip in skip_compile_pyc]
    skipped_files = set()
    for skip in skip_compile_pyc_n:
        skipped_files.update(set(fnmatch_filter(files, skip)))
    unskipped_files = set(files) - skipped_files
    for fn in unskipped_files:
        # omit files in Library/bin, Scripts, and the root prefix - they are not generally imported
        if sys.platform == "win32":
            if any(
                [
                    fn.lower().startswith(start)
                    for start in ["library/bin", "library\\bin", "scripts"]
                ]
            ):
                continue
        else:
            if fn.startswith("bin"):
                continue
        cache_prefix = "__pycache__" + os.sep
        if (
            fn.endswith(".py")
            and dirname(fn) + cache_prefix + basename(fn) + "c" not in files
        ):
            compile_files.append(fn)

    if compile_files:
        if not isfile(python_exe):
            print("compiling .pyc files... failed as no python interpreter was found")
        else:
            print("compiling .pyc files...")
            # We avoid command lines longer than 8190
            if sys.platform == "win32":
                limit = 8190
            else:
                limit = 32760
            limit -= len(compile_files) * 2
            lower_limit = len(max(compile_files, key=len)) + 1
            if limit < lower_limit:
                limit = lower_limit
            groups = [[]]
            args = [python_exe, "-Wi", "-m", "py_compile"]
            args_len = length = len(" ".join(args)) + 1
            for f in compile_files:
                length_this = len(f) + 1
                if length_this + length > limit:
                    groups.append([])
                    length = args_len
                else:
                    length += length_this
                groups[len(groups) - 1].append(f)
            for group in groups:
                call(args + group, cwd=cwd)


def check_dist_info_version(name, version, files):
    for f in files:
        if f.endswith(".dist-info" + os.sep + "METADATA"):
            f_lower = basename(dirname(f).lower())
            if f_lower.startswith(name + "-"):
                f_lower, _, _ = f_lower.rpartition(".dist-info")
                _, distname, f_lower = f_lower.rpartition(name + "-")
                if distname == name and version != f_lower:
                    print(
                        f"ERROR: Top level dist-info version incorrect (is {f_lower}, should be {version})"
                    )
                    sys.exit(1)
                else:
                    return


def post_process(
    name,
    version,
    files,
    prefix,
    config,
    preserve_egg_dir=False,
    noarch=False,
    skip_compile_pyc=(),
):
    rm_pyo(files, prefix)
    if noarch:
        rm_pyc(files, prefix)
    else:
        python_exe = (
            config.build_python if isfile(config.build_python) else config.host_python
        )
        compile_missing_pyc(
            files, cwd=prefix, python_exe=python_exe, skip_compile_pyc=skip_compile_pyc
        )
    remove_easy_install_pth(files, prefix, config, preserve_egg_dir=preserve_egg_dir)
    rm_py_along_so(prefix)
    rm_share_info_dir(files, prefix)
    check_dist_info_version(name, version, files)


def find_lib(link, prefix, files, path=None):
    if link.startswith(prefix):
        link = normpath(link[len(prefix) + 1 :])
        if not any(link == normpath(w) for w in files):
            sys.exit("Error: Could not find %s" % link)
        return link
    if link.startswith("/"):  # but doesn't start with the build prefix
        return
    if link.startswith("@rpath/"):
        # Assume the rpath already points to lib, so there is no need to
        # change it.
        return
    if "/" not in link or link.startswith("@executable_path/"):
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
                sys.exit(
                    f"Error: Found multiple instances of {link}: {file_names[link]}"
                )
            else:
                file_names[link].sort()
                print(
                    "Found multiple instances of %s (%s).  "
                    "Choosing the first one." % (link, file_names[link])
                )
        return file_names[link][0]
    print("Don't know how to find %s, skipping" % link)


def osx_ch_link(path, link_dict, host_prefix, build_prefix, files):
    link = link_dict["name"]
    if build_prefix != host_prefix and link.startswith(build_prefix):
        link = link.replace(build_prefix, host_prefix)
        print(f"Fixing linking of {link} in {path}")
        print(
            ".. seems to be linking to a compiler runtime, replacing build prefix with "
            "host prefix and"
        )
        if not codefile_type(link):
            sys.exit(
                "Error: Compiler runtime library in build prefix not found in host prefix %s"
                % link
            )
        else:
            print(f".. fixing linking of {link} in {path} instead")

    link_loc = find_lib(link, host_prefix, files, path)

    if not link_loc:
        return

    print(f"Fixing linking of {link} in {path}")
    print("New link location is %s" % (link_loc))

    lib_to_link = relpath(dirname(link_loc), "lib")
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

    ret = f"@rpath/{lib_to_link}/{basename(link)}"

    # XXX: IF the above fails for whatever reason, the below can be used
    # TODO: This might contain redundant ..'s if link and path are both in
    # some subdirectory of lib.
    # ret = '@loader_path/%s/%s/%s' % (path_to_lib, lib_to_link, basename(link))

    ret = ret.replace("/./", "/")

    return ret


def mk_relative_osx(path, host_prefix, m, files, rpaths=("lib",)):
    base_prefix = m.config.build_folder
    assert base_prefix == dirname(host_prefix)
    build_prefix = m.config.build_prefix
    prefix = build_prefix if exists(build_prefix) else host_prefix
    names = macho.otool(path, prefix)
    s = macho.install_name_change(
        path,
        prefix,
        partial(
            osx_ch_link, host_prefix=host_prefix, build_prefix=build_prefix, files=files
        ),
        dylibs=names,
    )

    if names:
        existing_rpaths = macho.get_rpaths(path, build_prefix=prefix)
        # Add an rpath to every executable to increase the chances of it
        # being found.
        for rpath in rpaths:
            # Escape hatch for when you really don't want any rpaths added.
            if rpath == "":
                continue
            rpath_new = join(
                "@loader_path", relpath(join(host_prefix, rpath), dirname(path)), ""
            ).replace("/./", "/")
            macho.add_rpath(path, rpath_new, build_prefix=prefix, verbose=True)
            full_rpath = join(host_prefix, rpath)
            for existing_rpath in existing_rpaths:
                if normpath(existing_rpath) == normpath(full_rpath):
                    macho.delete_rpath(
                        path, existing_rpath, build_prefix=prefix, verbose=True
                    )

        for rpath in existing_rpaths:
            if rpath.startswith(base_prefix) and not rpath.startswith(host_prefix):
                macho.delete_rpath(path, rpath, build_prefix=prefix, verbose=True)
    if s:
        # Skip for stub files, which have to use binary_has_prefix_files to be
        # made relocatable.
        assert_relative_osx(path, host_prefix, build_prefix)


"""
# Both patchelf and LIEF have bugs in them. Neither can be used on all binaries we have seen.
# This code tries each and tries to keep count of which worked between the original binary and
# patchelf-patched, LIEF-patched versions.
#
# Please do not delete it until you are sure the bugs in both projects have been fixed.
#

from subprocess import STDOUT

def check_binary(binary, expected=None):
    from ctypes import cdll
    print("trying {}".format(binary))
    # import pdb; pdb.set_trace()
    try:
        txt = check_output([sys.executable, '-c', 'from ctypes import cdll; cdll.LoadLibrary("' + binary + '")'], timeout=2)
        # mydll = cdll.LoadLibrary(binary)
    except Exception as e:
        print(e)
        return None, None
    try:
        txt = check_output(binary, stderr=STDOUT, timeout=0.1)
    except Exception as e:
        print(e)
        txt = e.output
    if expected is not None:
        return txt == expected, txt
    return True, txt


worksd = {'original': 0,
          'LIEF': 0,
          'patchelf': 0}


def check_binary_patchers(elf, prefix, rpath):
    patchelf = external.find_executable('patchelf', prefix)
    tmpname_pe = elf+'.patchelf'
    tmpname_le = elf+'.lief'
    shutil.copy(elf, tmpname_pe)
    shutil.copy(elf, tmpname_le)
    import pdb; pdb.set_trace()
    works, original = check_binary(elf)
    if works:
        worksd['original'] += 1
        set_rpath(old_matching='*', new_rpath=rpath, file=tmpname_le)
        works, LIEF = check_binary(tmpname_le, original)
        call([patchelf, '--force-rpath', '--set-rpath', rpath, tmpname_pe])
        works, pelf = check_binary(tmpname_pe, original)
        if original == LIEF and works:
            worksd['LIEF'] += 1
        if original == pelf and works:
            worksd['patchelf'] += 1
    print('\n' + str(worksd) + '\n')
"""


def mk_relative_linux(f, prefix, rpaths=("lib",), method=None):
    "Respects the original values and converts abs to $ORIGIN-relative"

    elf = join(prefix, f)
    origin = dirname(elf)

    existing_pe = None
    patchelf = external.find_executable("patchelf", prefix)
    if not patchelf:
        print(
            f"ERROR :: You should install patchelf, will proceed with LIEF for {elf} (was {method})"
        )
        method = "LIEF"
    else:
        try:
            existing_pe = (
                check_output([patchelf, "--print-rpath", elf])
                .decode("utf-8")
                .splitlines()[0]
            )
        except CalledProcessError:
            if method == "patchelf":
                print(
                    "ERROR :: `patchelf --print-rpath` failed for {}, but patchelf was specified".format(
                        elf
                    )
                )
            elif method != "LIEF":
                print(
                    "WARNING :: `patchelf --print-rpath` failed for {}, will proceed with LIEF (was {})".format(
                        elf, method
                    )
                )
            method = "LIEF"
        else:
            existing_pe = existing_pe.split(os.pathsep)
    existing = existing_pe
    if have_lief:
        existing2, _, _ = get_rpaths_raw(elf)
        if existing_pe and existing_pe != existing2:
            print(
                "WARNING :: get_rpaths_raw()={} and patchelf={} disagree for {} :: ".format(
                    existing2, existing_pe, elf
                )
            )
        # Use LIEF if method is LIEF to get the initial value?
        if method == "LIEF":
            existing = existing2
    new = []
    for old in existing:
        if old.startswith("$ORIGIN"):
            new.append(old)
        elif old.startswith("/"):
            # Test if this absolute path is outside of prefix. That is fatal.
            rp = relpath(old, prefix)
            if rp.startswith(".." + os.sep):
                print(f"Warning: rpath {old} is outside prefix {prefix} (removing it)")
            else:
                rp = "$ORIGIN/" + relpath(old, origin)
                if rp not in new:
                    new.append(rp)
    # Ensure that the asked-for paths are also in new.
    for rpath in rpaths:
        if rpath != "":
            if not rpath.startswith("/"):
                # IMHO utils.relative shouldn't exist, but I am too paranoid to remove
                # it, so instead, make sure that what I think it should be replaced by
                # gives the same result and assert if not. Yeah, I am a chicken.
                rel_ours = normpath(utils.relative(f, rpath))
                rel_stdlib = normpath(relpath(rpath, dirname(f)))
                if not rel_ours == rel_stdlib:
                    raise ValueError(
                        "utils.relative {} and relpath {} disagree for {}, {}".format(
                            rel_ours, rel_stdlib, f, rpath
                        )
                    )
                rpath = "$ORIGIN/" + rel_stdlib
            if rpath not in new:
                new.append(rpath)
    rpath = ":".join(new)

    # check_binary_patchers(elf, prefix, rpath)
    if not patchelf or (method and method.upper() == "LIEF"):
        set_rpath(old_matching="*", new_rpath=rpath, file=elf)
    else:
        call([patchelf, "--force-rpath", "--set-rpath", rpath, elf])


def assert_relative_osx(path, host_prefix, build_prefix):
    tools_prefix = build_prefix if exists(build_prefix) else host_prefix
    for name in macho.get_dylibs(path, tools_prefix):
        for prefix in (host_prefix, build_prefix):
            if prefix and name.startswith(prefix):
                raise RuntimeError(
                    "library at %s appears to have an absolute path embedded" % path
                )


def determine_package_nature(
    pkg, prefix, subdir, bldpkgs_dir, output_folder, channel_urls
):
    run_exports = None
    lib_prefix = pkg.name.startswith("lib")
    codefiles = get_package_obj_files(pkg, prefix)
    # get_package_obj_files already filters by extension and I'm not sure we need two.
    dsos = [
        f for f in codefiles for ext in (".dylib", ".so", ".dll", ".pyd") if ext in f
    ]
    # TODO :: Is this package not in a channel somewhere at this point? It would be good not to be special
    #         casing like this. Clearly we aren't able to get run_exports for starters and that's not good
    if not isinstance(pkg, FakeDist):
        # we don't care about the actual run_exports value, just whether or not run_exports are present.
        json_file = os.path.join(prefix, "conda-meta", pkg.dist_name + ".json")
        import json

        assert os.path.isfile(json_file), f"conda-meta :: Not a file: {json_file}"
        json_info = json.loads(open(json_file).read())
        epd = json_info["extracted_package_dir"]
        run_exports_json = os.path.join(epd, "info", "run_exports.json")
        if os.path.isfile(run_exports_json):
            run_exports = json.loads(open(run_exports_json).read())
    return (dsos, run_exports, lib_prefix)


def library_nature(pkg, prefix, subdir, bldpkgs_dirs, output_folder, channel_urls):
    """
    Result :: "non-library",
              "interpreted library (Python|R|Python,R)",
              "plugin library (Python|R|Python,R)",
              "dso library",
              "run-exports library",
              "interpreter (R)"
              "interpreter (Python)"
    .. in that order, i.e. if have both dsos and run_exports, it's a run_exports_library.
    """
    dsos, run_exports, _ = determine_package_nature(
        pkg, prefix, subdir, bldpkgs_dirs, output_folder, channel_urls
    )
    if pkg.name == "python":
        return "interpreter (Python)"
    elif pkg.name == "r-base":
        return "interpreter (R)"
    if run_exports:
        return "run-exports library"
    elif len(dsos):
        # If all DSOs are under site-packages or R/lib/
        python_dsos = [dso for dso in dsos if "site-packages" in dso]
        r_dsos = [dso for dso in dsos if "lib/R/library" in dso]
        dsos_without_plugins = [dso for dso in dsos if dso not in r_dsos + python_dsos]
        if len(dsos_without_plugins):
            return "dso library"
        else:
            if python_dsos and r_dsos:
                return "plugin library (Python,R)"
            elif python_dsos:
                return "plugin library (Python)"
            elif r_dsos:
                return "plugin library (R)"
    else:
        files = get_package_files(pkg, prefix)
        python_files = [f for f in files if "site-packages" in f]
        r_files = [f for f in files if "lib/R/library" in f]
        if python_files and r_files:
            return "interpreted library (Python,R)"
        elif python_files:
            return "interpreted library (Python)"
        elif r_files:
            return "interpreted library (R)"

    return "non-library"


def dists_from_names(names, prefix):
    results = []
    from conda_build.utils import linked_data_no_multichannels

    pkgs = linked_data_no_multichannels(prefix)
    for name in names:
        for pkg in pkgs:
            if pkg.quad[0] == name:
                results.append(pkg)
    return results


class FakeDist:
    def __init__(self, name, version, build_number, build_str, channel, files):
        self.name = name
        self.quad = [name]
        self.version = version
        self.build_number = build_number
        self.build_string = build_str
        self.channel = channel
        self.files = files

    def get(self, name):
        if name == "files":
            return self.files


# This is really just a small, fixed sysroot and it is rooted at ''. `libcrypto.0.9.8.dylib` should not be in it IMHO.
DEFAULT_MAC_WHITELIST = [
    "/opt/X11/",
    "/usr/lib/libSystem.B.dylib",
    "/usr/lib/libcrypto.0.9.8.dylib",
    "/usr/lib/libobjc.A.dylib",
    """
                         '/System/Library/Frameworks/Accelerate.framework/*',
                         '/System/Library/Frameworks/AGL.framework/*',
                         '/System/Library/Frameworks/AppKit.framework/*',
                         '/System/Library/Frameworks/ApplicationServices.framework/*',
                         '/System/Library/Frameworks/AudioToolbox.framework/*',
                         '/System/Library/Frameworks/AudioUnit.framework/*',
                         '/System/Library/Frameworks/AVFoundation.framework/*',
                         '/System/Library/Frameworks/CFNetwork.framework/*',
                         '/System/Library/Frameworks/Carbon.framework/*',
                         '/System/Library/Frameworks/Cocoa.framework/*',
                         '/System/Library/Frameworks/CoreAudio.framework/*',
                         '/System/Library/Frameworks/CoreFoundation.framework/*',
                         '/System/Library/Frameworks/CoreGraphics.framework/*',
                         '/System/Library/Frameworks/CoreMedia.framework/*',
                         '/System/Library/Frameworks/CoreBluetooth.framework/*',
                         '/System/Library/Frameworks/CoreMIDI.framework/*',
                         '/System/Library/Frameworks/CoreMedia.framework/*',
                         '/System/Library/Frameworks/CoreServices.framework/*',
                         '/System/Library/Frameworks/CoreText.framework/*',
                         '/System/Library/Frameworks/CoreVideo.framework/*',
                         '/System/Library/Frameworks/CoreWLAN.framework/*',
                         '/System/Library/Frameworks/DiskArbitration.framework/*',
                         '/System/Library/Frameworks/Foundation.framework/*',
                         '/System/Library/Frameworks/GameController.framework/*',
                         '/System/Library/Frameworks/GLKit.framework/*',
                         '/System/Library/Frameworks/ImageIO.framework/*',
                         '/System/Library/Frameworks/IOBluetooth.framework/*',
                         '/System/Library/Frameworks/IOKit.framework/*',
                         '/System/Library/Frameworks/IOSurface.framework/*',
                         '/System/Library/Frameworks/OpenAL.framework/*',
                         '/System/Library/Frameworks/OpenGL.framework/*',
                         '/System/Library/Frameworks/Quartz.framework/*',
                         '/System/Library/Frameworks/QuartzCore.framework/*',
                         '/System/Library/Frameworks/Security.framework/*',
                         '/System/Library/Frameworks/StoreKit.framework/*',
                         '/System/Library/Frameworks/SystemConfiguration.framework/*',
                         '/System/Library/Frameworks/WebKit.framework/*'
""",
]

# Should contain the System32/SysWOW64 DLLs present on a clean installation of the
# oldest version of Windows that we support (or are currently) building packages for.
DEFAULT_WIN_WHITELIST = [
    "**/ADVAPI32.dll",
    "**/bcrypt.dll",
    "**/COMCTL32.dll",
    "**/COMDLG32.dll",
    "**/CRYPT32.dll",
    "**/dbghelp.dll",
    "**/GDI32.dll",
    "**/IMM32.dll",
    "**/KERNEL32.dll",
    "**/NETAPI32.dll",
    "**/ole32.dll",
    "**/OLEAUT32.dll",
    "**/PSAPI.DLL",
    "**/RPCRT4.dll",
    "**/SHELL32.dll",
    "**/USER32.dll",
    "**/USERENV.dll",
    "**/WINHTTP.dll",
    "**/WS2_32.dll",
    "**/ntdll.dll",
    "**/msvcrt.dll",
]


def _collect_needed_dsos(
    sysroots_files,
    files,
    run_prefix,
    sysroot_substitution,
    build_prefix,
    build_prefix_substitution,
):
    all_needed_dsos = set()
    needed_dsos_for_file = dict()
    sysroots = ""
    if sysroots_files:
        sysroots = list(sysroots_files.keys())[0]
    for f in files:
        path = join(run_prefix, f)
        if not codefile_type(path):
            continue
        build_prefix = build_prefix.replace(os.sep, "/")
        run_prefix = run_prefix.replace(os.sep, "/")
        needed = get_linkages_memoized(
            path,
            resolve_filenames=True,
            recurse=False,
            sysroot=sysroots,
            envroot=run_prefix,
        )
        for lib, res in needed.items():
            resolved = res["resolved"].replace(os.sep, "/")
            for sysroot, sysroot_files in sysroots_files.items():
                if resolved.startswith(sysroot):
                    resolved = resolved.replace(sysroot, sysroot_substitution)
                elif resolved[1:] in sysroot_files:
                    resolved = sysroot_substitution + resolved[1:]

            # We do not want to do this substitution when merging build and host prefixes.
            if build_prefix != run_prefix and resolved.startswith(build_prefix):
                resolved = resolved.replace(build_prefix, build_prefix_substitution)
            if resolved.startswith(run_prefix):
                resolved = relpath(resolved, run_prefix).replace(os.sep, "/")
            # If resolved still starts with '$RPATH' then that means we will either find it in
            # the whitelist or it will present as an error later.
            res["resolved"] = resolved
        needed_dsos_for_file[f] = needed
        all_needed_dsos = all_needed_dsos.union(
            {info["resolved"] for f, info in needed.items()}
        )
    return all_needed_dsos, needed_dsos_for_file


def _map_file_to_package(
    files,
    run_prefix,
    build_prefix,
    all_needed_dsos,
    pkg_vendored_dist,
    ignore_list_syms,
    sysroot_substitution,
    enable_static,
):
    # Form a mapping of file => package

    prefix_owners = {}
    contains_dsos = {}
    contains_static_libs = {}
    # Used for both dsos and static_libs
    all_lib_exports = {}
    all_needed_dsos_lower = [w.lower() for w in all_needed_dsos]

    if all_needed_dsos:
        for prefix in (run_prefix, build_prefix):
            all_lib_exports[prefix] = {}
            prefix_owners[prefix] = {}
            for subdir2, _, filez in os.walk(prefix):
                for file in filez:
                    fp = join(subdir2, file)
                    dynamic_lib = (
                        any(fnmatch(fp, ext) for ext in ("*.so*", "*.dylib*", "*.dll"))
                        and codefile_type(fp, skip_symlinks=False) is not None
                    )
                    static_lib = any(fnmatch(fp, ext) for ext in ("*.a", "*.lib"))
                    # Looking at all the files is very slow.
                    if not dynamic_lib and not static_lib:
                        continue
                    rp = normpath(relpath(fp, prefix)).replace("\\", "/")
                    if dynamic_lib and not any(
                        rp.lower() == w for w in all_needed_dsos_lower
                    ):
                        continue
                    if any(rp == normpath(w) for w in all_lib_exports[prefix]):
                        continue
                    rp_po = rp.replace("\\", "/")
                    owners = (
                        prefix_owners[prefix][rp_po]
                        if rp_po in prefix_owners[prefix]
                        else []
                    )
                    # Self-vendoring, not such a big deal but may as well report it?
                    if not len(owners):
                        if any(rp == normpath(w) for w in files):
                            owners.append(pkg_vendored_dist)
                    new_pkgs = list(
                        which_package(rp, prefix, avoid_canonical_channel_name=True)
                    )
                    # Cannot filter here as this means the DSO (eg libomp.dylib) will not be found in any package
                    # [owners.append(new_pkg) for new_pkg in new_pkgs if new_pkg not in owners
                    #  and not any([fnmatch(new_pkg.name, i) for i in ignore_for_statics])]
                    for new_pkg in new_pkgs:
                        if new_pkg not in owners:
                            owners.append(new_pkg)
                    prefix_owners[prefix][rp_po] = owners
                    if len(prefix_owners[prefix][rp_po]):
                        exports = {
                            e
                            for e in get_exports_memoized(
                                fp, enable_static=enable_static
                            )
                            if not any(
                                fnmatch(e, pattern) for pattern in ignore_list_syms
                            )
                        }
                        all_lib_exports[prefix][rp_po] = exports
                        # Check codefile_type to filter out linker scripts.
                        if dynamic_lib:
                            contains_dsos[prefix_owners[prefix][rp_po][0]] = True
                        elif static_lib:
                            if sysroot_substitution in fp:
                                if (
                                    prefix_owners[prefix][rp_po][0].name.startswith(
                                        "gcc_impl_linux"
                                    )
                                    or prefix_owners[prefix][rp_po][0].name == "llvm"
                                ):
                                    continue
                                print(
                                    f"sysroot in {fp}, owner is {prefix_owners[prefix][rp_po][0]}"
                                )
                            # Hmm, not right, muddies the prefixes again.
                            contains_static_libs[prefix_owners[prefix][rp_po][0]] = True

    return prefix_owners, contains_dsos, contains_static_libs, all_lib_exports


def _get_fake_pkg_dist(pkg_name, pkg_version, build_str, build_number, channel, files):
    pkg_vendoring_name = pkg_name
    pkg_vendoring_version = str(pkg_version)
    pkg_vendoring_build_str = build_str
    pkg_vendoring_build_number = build_number
    pkg_vendoring_key = "-".join(
        [pkg_vendoring_name, pkg_vendoring_version, pkg_vendoring_build_str]
    )

    return (
        FakeDist(
            pkg_vendoring_name,
            pkg_vendoring_version,
            pkg_vendoring_build_number,
            pkg_vendoring_build_str,
            channel,
            files,
        ),
        pkg_vendoring_key,
    )


def _print_msg(errors, text, verbose):
    if text.startswith("  ERROR"):
        errors.append(text)
    if verbose:
        print(text)


def caseless_sepless_fnmatch(paths, pat):
    pat = pat.replace("\\", "/")
    match = re.compile("(?i)" + fnmatch_translate(pat)).match
    matches = [
        path
        for path in paths
        if (path.replace("\\", "/") == pat) or match(path.replace("\\", "/"))
    ]
    return matches


def _lookup_in_sysroots_and_whitelist(
    errors,
    whitelist,
    needed_dso,
    sysroots_files,
    msg_prelude,
    info_prelude,
    sysroot_prefix,
    sysroot_substitution,
    subdir,
    verbose,
):
    # A system or ignored dependency. We should be able to find it in one of the CDT or
    # compiler packages on linux or in a sysroot folder on other OSes. These usually
    # start with '$RPATH/' which indicates pyldd did not find them, so remove that now.
    if needed_dso.startswith(sysroot_substitution):
        replacements = [sysroot_substitution] + [
            sysroot for sysroot, _ in sysroots_files.items()
        ]
    else:
        replacements = [needed_dso]
    in_whitelist = False
    in_sysroots = False
    if len(sysroots_files):
        # Check if we have a CDT package or a file in a sysroot.
        sysroot_files = []
        for sysroot, files in sysroots_files.items():
            sysroot_os = sysroot.replace("\\", os.sep)
            if needed_dso.startswith(sysroot_substitution):
                # Do we want to do this replace?
                sysroot_files.append(
                    needed_dso.replace(sysroot_substitution, sysroot_os)
                )
            else:
                found = caseless_sepless_fnmatch(files, needed_dso[1:])
                sysroot_files.extend(found)
        if len(sysroot_files):
            in_sysroots = True
            if subdir.startswith("osx-") or "win" in subdir:
                in_prefix_dso = sysroot_files[0]
                n_dso_p = f"Needed DSO {in_prefix_dso}"
                _print_msg(
                    errors,
                    f"{info_prelude}: {n_dso_p} found in $SYSROOT",
                    verbose=verbose,
                )
            else:
                # Removing sysroot_prefix is only for Linux, though we could
                # use CONDA_BUILD_SYSROOT for macOS. We should figure out what to do about
                # /opt/X11 too.
                pkgs = []
                for idx in range(len(sysroot_files)):
                    # in_prefix_dso = normpath(sysroot_files[idx].replace(
                    #     sysroot_prefix + os.sep, ''))
                    in_prefix_dso = sysroot_files[idx][len(sysroot_prefix) + 1 :]
                    n_dso_p = f"Needed DSO {in_prefix_dso}"
                    _pkgs = list(which_package(in_prefix_dso, sysroot_prefix))
                    if len(_pkgs) > 0:
                        pkgs.extend(_pkgs)
                        break
                if len(pkgs):
                    _print_msg(
                        errors,
                        "{}: {} found in CDT/compiler package {}".format(
                            info_prelude, n_dso_p, pkgs[0]
                        ),
                        verbose=verbose,
                    )
                else:
                    _print_msg(
                        errors,
                        "{}: {} not found in any CDT/compiler package,"
                        " nor the whitelist?!".format(msg_prelude, n_dso_p),
                        verbose=verbose,
                    )
    if not in_sysroots:
        # It takes a very long time to glob in C:/Windows so we do not do that.
        for replacement in replacements:
            needed_dso_w = needed_dso.replace(sysroot_substitution, replacement + "/")
            # We should pass in multiple paths at once to this, but the code isn't structured for that.
            in_whitelist = any(
                [caseless_sepless_fnmatch([needed_dso_w], w) for w in whitelist]
            )
            if in_whitelist:
                n_dso_p = f"Needed DSO {needed_dso_w}"
                _print_msg(
                    errors,
                    f"{info_prelude}: {n_dso_p} found in the whitelist",
                    verbose=verbose,
                )
                break
    if not in_whitelist and not in_sysroots:
        _print_msg(
            errors,
            "{}: {} not found in packages, sysroot(s) nor the missing_dso_whitelist.\n"
            ".. is this binary repackaging?".format(msg_prelude, needed_dso),
            verbose=verbose,
        )


def _lookup_in_prefix_packages(
    errors,
    needed_dso,
    files,
    run_prefix,
    whitelist,
    info_prelude,
    msg_prelude,
    warn_prelude,
    verbose,
    requirements_run,
    lib_packages,
    lib_packages_used,
):
    in_prefix_dso = normpath(needed_dso)
    n_dso_p = "Needed DSO {}".format(in_prefix_dso.replace("\\", "/"))
    and_also = " (and also in this package)" if in_prefix_dso in files else ""
    pkgs = list(
        which_package(in_prefix_dso, run_prefix, avoid_canonical_channel_name=True)
    )
    in_pkgs_in_run_reqs = [pkg for pkg in pkgs if pkg.quad[0] in requirements_run]
    # TODO :: metadata build/inherit_child_run_exports (for vc, mro-base-impl).
    for pkg in in_pkgs_in_run_reqs:
        if pkg in lib_packages:
            lib_packages_used.add(pkg)
    in_whitelist = any([fnmatch(in_prefix_dso, w) for w in whitelist])
    if len(in_pkgs_in_run_reqs) == 1:
        _print_msg(
            errors,
            "{}: {} found in {}{}".format(
                info_prelude, n_dso_p, in_pkgs_in_run_reqs[0], and_also
            ),
            verbose=verbose,
        )
    elif in_whitelist:
        _print_msg(
            errors,
            f"{info_prelude}: {n_dso_p} found in the whitelist",
            verbose=verbose,
        )
    elif len(in_pkgs_in_run_reqs) == 0 and len(pkgs) > 0:
        _print_msg(
            errors,
            "{}: {} found in {}{}".format(
                msg_prelude, n_dso_p, [p.quad[0] for p in pkgs], and_also
            ),
            verbose=verbose,
        )
        _print_msg(
            errors,
            "{}: .. but {} not in reqs/run, (i.e. it is overlinking)"
            " (likely) or a missing dependency (less likely)".format(
                msg_prelude, [p.quad[0] for p in pkgs]
            ),
            verbose=verbose,
        )
    elif len(in_pkgs_in_run_reqs) > 1:
        _print_msg(
            errors,
            "{}: {} found in multiple packages in run/reqs: {}{}".format(
                warn_prelude, in_prefix_dso, in_pkgs_in_run_reqs, and_also
            ),
            verbose=verbose,
        )
    else:
        if not any(in_prefix_dso == normpath(w) for w in files):
            _print_msg(
                errors,
                f"{msg_prelude}: {in_prefix_dso} not found in any packages",
                verbose=verbose,
            )
        elif verbose:
            _print_msg(
                errors,
                f"{info_prelude}: {in_prefix_dso} found in this package",
                verbose=verbose,
            )


def _show_linking_messages(
    files,
    errors,
    needed_dsos_for_file,
    build_prefix,
    run_prefix,
    pkg_name,
    error_overlinking,
    runpath_whitelist,
    verbose,
    requirements_run,
    lib_packages,
    lib_packages_used,
    whitelist,
    sysroots,
    sysroot_prefix,
    sysroot_substitution,
    subdir,
):
    if len(sysroots):
        for sysroot, sr_files in sysroots.items():
            _print_msg(
                errors,
                "   INFO: sysroot: '{}' files: '{}'".format(
                    sysroot, sorted(list(sr_files), reverse=True)[1:5]
                ),
                verbose=verbose,
            )
    for f in files:
        path = join(run_prefix, f)
        filetype = codefile_type(path)
        if not filetype or filetype not in filetypes_for_platform[subdir.split("-")[0]]:
            continue
        warn_prelude = "WARNING ({},{})".format(pkg_name, f.replace(os.sep, "/"))
        err_prelude = "  ERROR ({},{})".format(pkg_name, f.replace(os.sep, "/"))
        info_prelude = "   INFO ({},{})".format(pkg_name, f.replace(os.sep, "/"))
        msg_prelude = err_prelude if error_overlinking else warn_prelude

        # TODO :: Determine this much earlier, storing in needed_dsos_for_file in _collect_needed_dsos()
        try:
            runpaths, _, _ = get_runpaths_raw(path)
        except:
            _print_msg(
                errors, f"{warn_prelude}: pyldd.py failed to process", verbose=verbose
            )
            continue
        if runpaths and not (
            runpath_whitelist or any(fnmatch(f, w) for w in runpath_whitelist)
        ):
            _print_msg(
                errors,
                f"{msg_prelude}: runpaths {runpaths} found in {path}",
                verbose=verbose,
            )
        needed = needed_dsos_for_file[f]
        for needed_dso, needed_dso_info in needed.items():
            needed_dso = needed_dso.replace("/", os.sep)
            # Should always be the case, even when we fail to resolve the original value is stored here
            # as it is still a best attempt and informative.
            if "resolved" in needed_dso_info:
                needed_dso = needed_dso_info["resolved"]
            if not needed_dso.startswith(os.sep) and not needed_dso.startswith("$"):
                _lookup_in_prefix_packages(
                    errors,
                    needed_dso,
                    files,
                    run_prefix,
                    whitelist,
                    info_prelude,
                    msg_prelude,
                    warn_prelude,
                    verbose,
                    requirements_run,
                    lib_packages,
                    lib_packages_used,
                )
            elif needed_dso.startswith("$PATH"):
                _print_msg(
                    errors,
                    "{}: {} found in build prefix; should never happen".format(
                        err_prelude, needed_dso
                    ),
                    verbose=verbose,
                )
            else:
                _lookup_in_sysroots_and_whitelist(
                    errors,
                    whitelist,
                    needed_dso,
                    sysroots,
                    msg_prelude,
                    info_prelude,
                    sysroot_prefix,
                    sysroot_substitution,
                    subdir,
                    verbose,
                )


def check_overlinking_impl(
    pkg_name,
    pkg_version,
    build_str,
    build_number,
    subdir,
    ignore_run_exports,
    requirements_run,
    requirements_build,
    requirements_host,
    run_prefix,
    build_prefix,
    missing_dso_whitelist,
    runpath_whitelist,
    error_overlinking,
    error_overdepending,
    verbose,
    exception_on_error,
    files,
    bldpkgs_dirs,
    output_folder,
    channel_urls,
    enable_static=False,
    variants={},
):
    verbose = True
    errors = []

    files_to_inspect = []
    filesu = []
    for f in files:
        path = join(run_prefix, f)
        filetype = codefile_type(path)
        if filetype and filetype in filetypes_for_platform[subdir.split("-")[0]]:
            files_to_inspect.append(f)
        filesu.append(f.replace("\\", "/"))

    if not files_to_inspect:
        return dict()

    sysroot_substitution = "$SYSROOT"
    build_prefix_substitution = "$PATH"
    # Used to detect overlinking (finally)
    requirements_run = [req.split(" ")[0] for req in requirements_run]
    packages = dists_from_names(requirements_run, run_prefix)
    local_channel = (
        dirname(bldpkgs_dirs).replace("\\", "/")
        if utils.on_win
        else dirname(bldpkgs_dirs)[1:]
    )
    pkg_vendored_dist, pkg_vendoring_key = _get_fake_pkg_dist(
        pkg_name, pkg_version, build_str, build_number, local_channel, files
    )
    packages.append(pkg_vendored_dist)
    ignore_list = utils.ensure_list(ignore_run_exports)
    if subdir.startswith("linux"):
        ignore_list.append("libgcc-ng")

    package_nature = {
        package: library_nature(
            package, run_prefix, subdir, bldpkgs_dirs, output_folder, channel_urls
        )
        for package in packages
    }
    lib_packages = {
        package
        for package in packages
        if package.quad[0] not in ignore_list and [package] != "non-library"
    }
    lib_packages_used = {pkg_vendored_dist}

    ignore_list_syms = [
        "main",
        "_main",
        "*get_pc_thunk*",
        "___clang_call_terminate",
        "_timeout",
    ]
    # ignore_for_statics = ['gcc_impl_linux*', 'compiler-rt*', 'llvm-openmp*', 'gfortran_osx*']
    # sysroots and whitelists are similar, but the subtle distinctions are important.
    CONDA_BUILD_SYSROOT = variants.get("CONDA_BUILD_SYSROOT", None)
    if CONDA_BUILD_SYSROOT and os.path.exists(CONDA_BUILD_SYSROOT):
        # When on macOS and CBS not set, sysroots should probably be '/'
        # is everything in the sysroot allowed? I suppose so!
        sysroot_prefix = ""
        sysroots = [CONDA_BUILD_SYSROOT]
    else:
        # The linux case.
        sysroot_prefix = build_prefix
        sysroots = [
            sysroot + os.sep
            for sysroot in utils.glob(join(sysroot_prefix, "**", "sysroot"))
        ]
    whitelist = []
    vendoring_record = dict()
    # When build_is_host is True we perform file existence checks for files in the sysroot (e.g. C:\Windows)
    # When build_is_host is False we must skip things that match the whitelist from the prefix_owners (we could
    #   create some packages for the Windows System DLLs as an alternative?)
    build_is_host = False
    if not len(sysroots):
        if subdir.startswith("osx-"):
            # This is a bit confused! A sysroot shouldn't contain /usr/lib (it's the bit before that)
            # what we are really specifying here are subtrees of sysroots to search in and it may be
            # better to store each element of this as a tuple with a string and a nested tuple, e.g.
            # [('/', ('/usr/lib', '/opt/X11', '/System/Library/Frameworks'))]
            # Here we mean that we have a sysroot at '/' (could be a tokenized value like '$SYSROOT'?)
            # .. and in that sysroot there are 3 suddirs in which we may search for DSOs.
            sysroots = ["/usr/lib", "/opt/X11", "/System/Library/Frameworks"]
            whitelist = DEFAULT_MAC_WHITELIST
            build_is_host = True if sys.platform == "darwin" else False
        elif subdir.startswith("win"):
            sysroots = ["C:/Windows"]
            whitelist = DEFAULT_WIN_WHITELIST
            build_is_host = True if sys.platform == "win-32" else False

    whitelist += missing_dso_whitelist or []

    # Sort the sysroots by the number of files in them so things can assume that
    # the first sysroot is more important than others.
    sysroots_files = dict()
    for sysroot in sysroots:
        from conda_build.utils import prefix_files

        srs = sysroot if sysroot.endswith("/") else sysroot + "/"
        sysroot_files = prefix_files(sysroot)
        sysroot_files = [p.replace("\\", "/") for p in sysroot_files]
        sysroots_files[srs] = sysroot_files
        if subdir.startswith("osx-"):
            orig_sysroot_files = copy(sysroot_files)
            sysroot_files = []
            for f in orig_sysroot_files:
                replaced = f
                if f.endswith(".tbd"):
                    # For now, look up the line containing:
                    # install-name:    /System/Library/Frameworks/CoreFoundation.framework/Versions/A/CoreFoundation
                    with open(os.path.join(sysroot, f), "rb") as tbd_fh:
                        lines = [
                            line
                            for line in tbd_fh.read().decode("utf-8").splitlines()
                            if line.startswith("install-name:")
                        ]
                    if lines:
                        install_names = [
                            re.match(r"^install-name:\s+(.*)$", line) for line in lines
                        ]
                        install_names = [
                            insname.groups(1)[0] for insname in install_names
                        ]
                        replaced = install_names[0][1:]
                        if replaced.endswith("'"):
                            # Some SDKs have install name surrounded by single qoutes
                            replaced = replaced[1:-1]
                sysroot_files.append(replaced)
            diffs = set(orig_sysroot_files) - set(sysroot_files)
            if diffs:
                log = utils.get_logger(__name__)
                log.warning(
                    "Partially parsed some '.tbd' files in sysroot {}, pretending .tbds are their install-names\n"
                    "Adding support to 'conda-build' for parsing these in 'liefldd.py' would be easy and useful:\n"
                    "{} ...".format(sysroot, list(diffs)[1:3])
                )
                sysroots_files[srs] = sysroot_files
    sysroots_files = OrderedDict(
        sorted(sysroots_files.items(), key=lambda x: -len(x[1]))
    )

    all_needed_dsos, needed_dsos_for_file = _collect_needed_dsos(
        sysroots_files,
        files,
        run_prefix,
        sysroot_substitution,
        build_prefix,
        build_prefix_substitution,
    )

    prefix_owners, _, _, all_lib_exports = _map_file_to_package(
        files,
        run_prefix,
        build_prefix,
        all_needed_dsos,
        pkg_vendored_dist,
        ignore_list_syms,
        sysroot_substitution,
        enable_static,
    )

    for f in files_to_inspect:
        needed = needed_dsos_for_file[f]
        for needed_dso, needed_dso_info in needed.items():
            orig = needed_dso
            resolved = needed_dso_info["resolved"]
            if (
                not resolved.startswith("/")
                and not resolved.startswith(sysroot_substitution)
                and not resolved.startswith(build_prefix_substitution)
                and resolved.lower()
                not in [o.lower() for o in prefix_owners[run_prefix]]
                and resolved not in filesu
            ):
                in_whitelist = False
                if not build_is_host:
                    in_whitelist = any(
                        [caseless_sepless_fnmatch([orig], w) for w in whitelist]
                    )
                if not in_whitelist:
                    if resolved in prefix_owners[build_prefix]:
                        print(f"  ERROR :: {needed_dso} in prefix_owners[build_prefix]")
                    elif not needed_dso.startswith("$PATH"):
                        # DSOs with '$RPATH' in them at this stage are 'unresolved'. Though instead of
                        # letting them through through like this, I should detect that they were not
                        # resolved and change them back to how they were stored in the consumer DSO/elf
                        # e.g. an elf will have a DT_NEEDED of just 'zlib.so.1' and to standardize
                        # processing across platforms I prefixed them all with $RPATH. That should be
                        # un-done so that this error message is more clearly related to the consumer..
                        # print("WARNING :: For consumer: '{}' with rpaths: '{}'\n"
                        #       "WARNING :: .. the package containing '{}' could not be found in the run prefix".format(
                        #     f, rpaths, needed_dso))
                        pass

    _show_linking_messages(
        files,
        errors,
        needed_dsos_for_file,
        build_prefix,
        run_prefix,
        pkg_name,
        error_overlinking,
        runpath_whitelist,
        verbose,
        requirements_run,
        lib_packages,
        lib_packages_used,
        whitelist,
        sysroots_files,
        sysroot_prefix,
        sysroot_substitution,
        subdir,
    )

    if lib_packages_used != lib_packages:
        info_prelude = f"   INFO ({pkg_name})"
        warn_prelude = f"WARNING ({pkg_name})"
        err_prelude = f"  ERROR ({pkg_name})"
        for lib in lib_packages - lib_packages_used:
            if package_nature[lib] in ("run-exports library", "dso library"):
                msg_prelude = err_prelude if error_overdepending else warn_prelude
            elif package_nature[lib] == "plugin library":
                msg_prelude = info_prelude
            else:
                msg_prelude = warn_prelude
            found_interpreted_and_interpreter = False
            if (
                "interpreter" in package_nature[lib]
                and "interpreted" in package_nature[pkg_vendored_dist]
            ):
                found_interpreted_and_interpreter = True
            if found_interpreted_and_interpreter:
                _print_msg(
                    errors,
                    "{}: Interpreted package '{}' is interpreted by '{}'".format(
                        info_prelude, pkg_vendored_dist.name, lib.name
                    ),
                    verbose=verbose,
                )
            elif package_nature[lib] != "non-library":
                _print_msg(
                    errors,
                    "{}: {} package {} in requirements/run but it is not used "
                    "(i.e. it is overdepending or perhaps statically linked? "
                    "If that is what you want then add it to `build/ignore_run_exports`)".format(
                        msg_prelude, package_nature[lib], lib
                    ),
                    verbose=verbose,
                )
    if len(errors):
        if exception_on_error:
            runpaths_errors = [
                error for error in errors if re.match(r".*runpaths.*found in.*", error)
            ]
            if len(runpaths_errors):
                raise RunPathError(runpaths_errors)
            overlinking_errors = [
                error
                for error in errors
                if re.match(r".*(overlinking|not found in|did not find).*", error)
            ]
            if len(overlinking_errors):
                raise OverLinkingError(overlinking_errors)
            overdepending_errors = [
                error for error in errors if "overdepending" in error
            ]
            if len(overdepending_errors):
                raise OverDependingError(overdepending_errors)
        else:
            sys.exit(1)

    if pkg_vendoring_key in vendoring_record:
        imports = vendoring_record[pkg_vendoring_key]
        return imports
    else:
        return dict()


def check_overlinking(m, files, host_prefix=None):
    if not host_prefix:
        host_prefix = m.config.host_prefix

    overlinking_ignore_patterns = m.meta.get("build", {}).get(
        "overlinking_ignore_patterns"
    )
    if overlinking_ignore_patterns:
        files = [
            f
            for f in files
            if not any([fnmatch(f, p) for p in overlinking_ignore_patterns])
        ]
    return check_overlinking_impl(
        m.get_value("package/name"),
        m.get_value("package/version"),
        m.get_value("build/string"),
        m.get_value("build/number"),
        m.config.target_subdir,
        m.get_value("build/ignore_run_exports"),
        [req.split(" ")[0] for req in m.meta.get("requirements", {}).get("run", [])],
        [req.split(" ")[0] for req in m.meta.get("requirements", {}).get("build", [])],
        [req.split(" ")[0] for req in m.meta.get("requirements", {}).get("host", [])],
        host_prefix,
        m.config.build_prefix,
        m.meta.get("build", {}).get("missing_dso_whitelist", []),
        m.meta.get("build", {}).get("runpath_whitelist", []),
        m.config.error_overlinking,
        m.config.error_overdepending,
        m.config.verbose,
        True,
        files,
        m.config.bldpkgs_dir,
        m.config.output_folder,
        list(m.config.channel_urls) + ["local"],
        m.config.enable_static,
        m.config.variant,
    )


def post_process_shared_lib(m, f, files, host_prefix=None):
    if not host_prefix:
        host_prefix = m.config.host_prefix
    path = join(host_prefix, f)
    codefile_t = codefile_type(path)
    if not codefile_t or path.endswith(".debug"):
        return
    rpaths = m.get_value("build/rpaths", ["lib"])
    if codefile_t == "elffile":
        mk_relative_linux(
            f,
            host_prefix,
            rpaths=rpaths,
            method=m.get_value("build/rpaths_patcher", None),
        )
    elif codefile_t == "machofile":
        if m.config.host_platform != "osx":
            log = utils.get_logger(__name__)
            log.warn(
                "Found Mach-O file but patching is only supported on macOS, skipping: %s",
                path,
            )
            return
        mk_relative_osx(path, host_prefix, m, files=files, rpaths=rpaths)


def fix_permissions(files, prefix):
    print("Fixing permissions")
    for path in os.scandir(prefix):
        if path.is_dir():
            lchmod(path.path, 0o775)

    for f in files:
        path = join(prefix, f)
        st = os.lstat(path)
        old_mode = stat.S_IMODE(st.st_mode)
        new_mode = old_mode
        # broadcast execute
        if old_mode & stat.S_IXUSR:
            new_mode = new_mode | stat.S_IXGRP | stat.S_IXOTH
        # ensure user and group can write and all can read
        new_mode = (
            new_mode
            | stat.S_IWUSR
            | stat.S_IWGRP
            | stat.S_IRUSR
            | stat.S_IRGRP
            | stat.S_IROTH
        )  # noqa
        if old_mode != new_mode:
            try:
                lchmod(path, new_mode)
            except (OSError, utils.PermissionError) as e:
                log = utils.get_logger(__name__)
                log.warn(str(e))


def post_build(m, files, build_python, host_prefix=None, is_already_linked=False):
    print("number of files:", len(files))

    if not host_prefix:
        host_prefix = m.config.host_prefix

    if not is_already_linked:
        for f in files:
            make_hardlink_copy(f, host_prefix)

    if not m.config.target_subdir.startswith("win"):
        binary_relocation = m.binary_relocation()
        if not binary_relocation:
            print("Skipping binary relocation logic")
        osx_is_app = m.config.target_subdir.startswith("osx-") and bool(
            m.get_value("build/osx_is_app", False)
        )
        check_symlinks(files, host_prefix, m.config.croot)
        prefix_files = utils.prefix_files(host_prefix)

        for f in files:
            if f.startswith("bin/"):
                fix_shebang(
                    f,
                    prefix=host_prefix,
                    build_python=build_python,
                    osx_is_app=osx_is_app,
                )
            if binary_relocation is True or (
                isinstance(binary_relocation, list) and f in binary_relocation
            ):
                post_process_shared_lib(m, f, prefix_files, host_prefix)
    check_overlinking(m, files, host_prefix)


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
            if not dirname(link_path) == dirname(real_link_path) and codefile_type(f):
                os.remove(path)
                utils.copy_into(real_link_path, path)
            elif real_link_path.startswith(real_build_prefix):
                # If the path is in the build prefix, this is fine, but
                # the link needs to be relative
                relative_path = relpath(real_link_path, dirname(path))
                if not link_path.startswith(".") and link_path != relative_path:
                    # Don't change the link structure if it is already a
                    # relative link. It's possible that ..'s later in the path
                    # can result in a broken link still, but we'll assume that
                    # such crazy things don't happen.
                    print(
                        f"Making absolute symlink relative ({f} -> {link_path} :-> {relative_path})"
                    )
                    os.unlink(path)
                    os.symlink(relative_path, path)
            else:
                # Symlinks to absolute paths on the system (like /usr) are fine.
                if real_link_path.startswith(croot):
                    msgs.append(
                        "%s is a symlink to a path that may not "
                        "exist after the build is completed (%s)" % (f, link_path)
                    )

    if msgs:
        for msg in msgs:
            print("Error: %s" % msg, file=sys.stderr)
        sys.exit(1)


def make_hardlink_copy(path, prefix):
    """Hardlinks create invalid packages.  Copy files to break the link.
    Symlinks are OK, and unaffected here."""
    if not isabs(path):
        path = normpath(join(prefix, path))
    fn = basename(path)
    if os.lstat(path).st_nlink > 1:
        with TemporaryDirectory() as dest:
            # copy file to new name
            utils.copy_into(path, dest)
            # remove old file
            utils.rm_rf(path)
            # rename copy to original filename
            #   It is essential here to use copying (as opposed to os.rename), so that
            #        crossing volume boundaries works
            utils.copy_into(join(dest, fn), path)


def get_build_metadata(m):
    src_dir = m.config.work_dir
    if exists(join(src_dir, "__conda_version__.txt")):
        raise ValueError(
            "support for __conda_version__ has been removed as of Conda-build 3.0."
            "Try Jinja templates instead: "
            "http://conda.pydata.org/docs/building/meta-yaml.html#templating-with-jinja"
        )
    if exists(join(src_dir, "__conda_buildnum__.txt")):
        raise ValueError(
            "support for __conda_buildnum__ has been removed as of Conda-build 3.0."
            "Try Jinja templates instead: "
            "http://conda.pydata.org/docs/building/meta-yaml.html#templating-with-jinja"
        )
    if exists(join(src_dir, "__conda_buildstr__.txt")):
        raise ValueError(
            "support for __conda_buildstr__ has been removed as of Conda-build 3.0."
            "Try Jinja templates instead: "
            "http://conda.pydata.org/docs/building/meta-yaml.html#templating-with-jinja"
        )
