# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
try:
    from collections.abc import Hashable
except ImportError:
    from collections.abc import Hashable

import hashlib
import json
import os
import struct
import sys
import threading
from functools import partial
from subprocess import PIPE, Popen

import glob2

from .external import find_executable

# lief cannot handle files it doesn't know about gracefully
# TODO :: Remove all use of pyldd
# Currently we verify the output of each against the other
from .pyldd import codefile_type as codefile_type_pyldd
from .pyldd import inspect_linkages as inspect_linkages_pyldd

codefile_type = codefile_type_pyldd
have_lief = False
try:
    import lief

    have_lief = True
except:
    pass


def is_string(s):
    try:
        return isinstance(s, basestring)
    except NameError:
        return isinstance(s, str)


# Some functions can operate on either file names
# or an already loaded binary. Generally speaking
# these are to be avoided, or if not avoided they
# should be passed a binary when possible as that
# will prevent having to parse it multiple times.
def ensure_binary(file):
    if not is_string(file):
        return file
    else:
        try:
            if not os.path.exists(file):
                return []
            return lief.parse(file)
        except:
            print(f"WARNING: liefldd: failed to ensure_binary({file})")
    return None


def nm(filename):
    """Return symbols from *filename* binary"""
    done = False
    try:
        binary = lief.parse(filename)  # Build an abstract binary
        symbols = binary.symbols

        if len(symbols) > 0:
            for symbol in symbols:
                print(dir(symbol))
                print(symbol)
                done = True
    except:
        pass
    if not done:
        print("No symbols found")


def codefile_type_liefldd(file, skip_symlinks=True):
    binary = ensure_binary(file)
    result = None
    if binary:
        if binary.format == lief.EXE_FORMATS.PE:
            if lief.PE.DLL_CHARACTERISTICS:
                if binary.header.characteristics & lief.PE.HEADER_CHARACTERISTICS.DLL:
                    result = "DLLfile"
                else:
                    result = "EXEfile"
        elif binary.format == lief.EXE_FORMATS.MACHO:
            result = "machofile"
        elif binary.format == lief.EXE_FORMATS.ELF:
            result = "elffile"
    return result


if have_lief:
    codefile_type = codefile_type_liefldd


def _trim_sysroot(sysroot):
    while sysroot.endswith("/") or sysroot.endswith("\\"):
        sysroot = sysroot[:-1]
    return sysroot


def get_libraries(file):
    result = []
    binary = ensure_binary(file)
    if binary:
        if binary.format == lief.EXE_FORMATS.PE:
            result = binary.libraries
        else:
            result = [lib if is_string(lib) else lib.name for lib in binary.libraries]
            # LIEF returns LC_ID_DYLIB name @rpath/libbz2.dylib in binary.libraries. Strip that.
            binary_name = None
            if binary.format == lief.EXE_FORMATS.MACHO:
                binary_name = [
                    command.name
                    for command in binary.commands
                    if command.command == lief.MachO.LOAD_COMMAND_TYPES.ID_DYLIB
                ]
                binary_name = binary_name[0] if len(binary_name) else None
                result = [
                    from_os_varnames(binary.format, None, lib)
                    for lib in result
                    if not binary_name or lib != binary_name
                ]
    return result


def _get_elf_rpathy_thing(binary, attribute, dyn_tag):
    dynamic_entries = binary.dynamic_entries
    rpaths_colons = [getattr(e, attribute) for e in dynamic_entries if e.tag == dyn_tag]
    rpaths = []
    for rpath in rpaths_colons:
        rpaths.extend(rpath.split(":"))
    return rpaths


def _set_elf_rpathy_thing(binary, old_matching, new_rpath, set_rpath, set_runpath):
    dynamic_entries = binary.dynamic_entries
    changed = False
    for e in dynamic_entries:
        if (
            set_runpath
            and e.tag == lief.ELF.DYNAMIC_TAGS.RUNPATH
            and glob2.fnmatch.fnmatch(e.runpath, old_matching)
            and e.runpath != new_rpath
        ):
            e.runpath = new_rpath
            changed = True
        elif (
            set_rpath
            and e.tag == lief.ELF.DYNAMIC_TAGS.RPATH
            and glob2.fnmatch.fnmatch(e.rpath, old_matching)
            and e.rpath != new_rpath
        ):
            e.rpath = new_rpath
            changed = True
    return changed


if have_lief:

    def get_rpathy_thing_raw_partial(file, elf_attribute, elf_dyn_tag):
        """
        By raw we mean that no processing is done on them whatsoever. The values are taken directly from
        LIEF. For anything but Linux, this means an empty list.
        """

        binary_format = None
        binary_type = None
        binary = ensure_binary(file)
        rpaths = []
        if binary:
            binary_format = binary.format
            if binary_format == lief.EXE_FORMATS.ELF:
                binary_type = binary.type
                if (
                    binary_type == lief.ELF.ELF_CLASS.CLASS32
                    or binary_type == lief.ELF.ELF_CLASS.CLASS64
                ):
                    rpaths = _get_elf_rpathy_thing(binary, elf_attribute, elf_dyn_tag)
            elif (
                binary_format == lief.EXE_FORMATS.MACHO
                and binary.has_rpath
                and elf_dyn_tag == lief.ELF.DYNAMIC_TAGS.RPATH
            ):
                rpaths.extend(
                    [
                        command.path
                        for command in binary.commands
                        if command.command == lief.MachO.LOAD_COMMAND_TYPES.RPATH
                    ]
                )
        return rpaths, binary_format, binary_type

    get_runpaths_raw = partial(
        get_rpathy_thing_raw_partial,
        elf_attribute="runpath",
        elf_dyn_tag=lief.ELF.DYNAMIC_TAGS.RUNPATH,
    )
    get_rpaths_raw = partial(
        get_rpathy_thing_raw_partial,
        elf_attribute="rpath",
        elf_dyn_tag=lief.ELF.DYNAMIC_TAGS.RPATH,
    )
else:

    def get_runpaths_raw(file):
        return [], None, None

    def get_rpaths_raw(file):
        return [], None, None


def get_runpaths_or_rpaths_raw(file):
    """
    Can be called on all OSes. On linux, if runpaths are present they are
    returned.
    """
    rpaths, binary_format, binary_type = get_runpaths_raw(file)
    if not len(rpaths):
        rpaths, _, _ = get_rpaths_raw(file)
        rpaths_type = "rpaths"
    else:
        rpaths_type = "runpaths"
    return rpaths, rpaths_type, binary_format, binary_type


def set_rpath(old_matching, new_rpath, file):
    binary = ensure_binary(file)
    if binary.format == lief.EXE_FORMATS.ELF and (
        binary.type == lief.ELF.ELF_CLASS.CLASS32
        or binary.type == lief.ELF.ELF_CLASS.CLASS64
    ):
        if _set_elf_rpathy_thing(
            binary, old_matching, new_rpath, set_rpath=True, set_runpath=False
        ):
            binary.write(file)


def get_rpaths(file, exe_dirname, envroot, windows_root=""):
    rpaths, rpaths_type, binary_format, binary_type = get_runpaths_or_rpaths_raw(file)
    if binary_format == lief.EXE_FORMATS.PE:
        # To allow the unix-y rpath code to work we consider
        # exes as having rpaths of env + CONDA_WINDOWS_PATHS
        # and consider DLLs as having no rpaths.
        # .. scratch that, we don't pass exes in as the root
        # entries so we just need rpaths for all files and
        # not to apply them transitively.
        # https://docs.microsoft.com/en-us/windows/desktop/dlls/dynamic-link-library-search-order
        if exe_dirname:
            rpaths.append(exe_dirname.replace("\\", "/"))
        if windows_root:
            rpaths.append("/".join((windows_root, "System32")))
            rpaths.append("/".join((windows_root, "System32", "downlevel")))
            rpaths.append(windows_root)
        if envroot:
            # and not lief.PE.HEADER_CHARACTERISTICS.DLL in binary.header.characteristics_list:
            rpaths.extend(list(_get_path_dirs(envroot)))
    elif binary_format == lief.EXE_FORMATS.MACHO:
        rpaths = [rpath.rstrip("/") for rpath in rpaths]
    return [from_os_varnames(binary_format, binary_type, rpath) for rpath in rpaths]


# TODO :: Consider memoizing instead of repeatedly scanning
# TODO :: libc.so/libSystem.dylib when inspect_linkages(recurse=True)
def _inspect_linkages_this(filename, sysroot="", arch="native"):
    """

    :param filename:
    :param sysroot:
    :param arch:
    :return:
    """

    if not os.path.exists(filename):
        return None, [], []
    sysroot = _trim_sysroot(sysroot)
    try:
        binary = lief.parse(filename)
        # Future lief has this:
        # json_data = json.loads(lief.to_json_from_abstract(binary))
        json_data = json.loads(lief.to_json(binary))
        if json_data:
            return (
                filename,
                json_data["imported_libraries"],
                json_data["imported_libraries"],
            )
    except:
        print(f"WARNING: liefldd: failed _inspect_linkages_this({filename})")

    return None, [], []


def to_os_varnames(binary, input_):
    """Don't make these functions - they are methods to match the API for elffiles."""
    if binary.format == lief.EXE_FORMATS.MACHO:
        return (
            input_.replace("$SELFDIR", "@loader_path")
            .replace("$EXEDIR", "@executable_path")
            .replace("$RPATH", "@rpath")
        )
    elif binary.format == lief.EXE_FORMATS.ELF:
        if binary.ehdr.sz_ptr == 8:
            libdir = "/lib64"
        else:
            libdir = "/lib"
        return input.replace("$SELFDIR", "$ORIGIN").replace(libdir, "$LIB")


def from_os_varnames(binary_format, binary_type, input_):
    """Don't make these functions - they are methods to match the API for elffiles."""
    if binary_format == lief.EXE_FORMATS.MACHO:
        return (
            input_.replace("@loader_path", "$SELFDIR")
            .replace("@executable_path", "$EXEDIR")
            .replace("@rpath", "$RPATH")
        )
    elif binary_format == lief.EXE_FORMATS.ELF:
        if binary_type == lief.ELF.ELF_CLASS.CLASS64:
            libdir = "/lib64"
        else:
            libdir = "/lib"
        return input_.replace("$ORIGIN", "$SELFDIR").replace("$LIB", libdir)
    elif binary_format == lief.EXE_FORMATS.PE:
        return input_


# TODO :: Use conda's version of this (or move the constant strings into constants.py)
def _get_path_dirs(prefix):
    yield "/".join((prefix,))
    yield "/".join((prefix, "Library", "mingw-w64", "bin"))
    yield "/".join((prefix, "Library", "usr", "bin"))
    yield "/".join((prefix, "Library", "bin"))
    yield "/".join((prefix, "Scripts"))
    yield "/".join((prefix, "bin"))


def get_uniqueness_key(file):
    binary = ensure_binary(file)
    if binary.format == lief.EXE_FORMATS.MACHO:
        return binary.name
    elif binary.format == lief.EXE_FORMATS.ELF and (  # noqa
        binary.type == lief.ELF.ELF_CLASS.CLASS32
        or binary.type == lief.ELF.ELF_CLASS.CLASS64
    ):
        dynamic_entries = binary.dynamic_entries
        result = [
            e.name for e in dynamic_entries if e.tag == lief.ELF.DYNAMIC_TAGS.SONAME
        ]
        if result:
            return result[0]
        return binary.name
    return binary.name


def _get_resolved_location(
    codefile,
    unresolved,
    exedir,
    selfdir,
    rpaths_transitive,
    LD_LIBRARY_PATH="",
    default_paths=[],
    sysroot="",
    resolved_rpath=None,
):
    """
    From `man ld.so`

    When resolving shared object dependencies, the dynamic linker first inspects each dependency
    string to see if it contains a slash (this can occur if a shared object pathname containing
    slashes was specified at link time).  If a slash is found, then the dependency string is
    interpreted as a (relative or absolute) pathname, and the shared object is loaded using that
    pathname.

    If a shared object dependency does not contain a slash, then it is searched for in the
    following order:

    o Using the directories specified in the DT_RPATH dynamic section attribute of the binary
      if present and DT_RUNPATH attribute does not exist.  Use of DT_RPATH is deprecated.

    o Using the environment variable LD_LIBRARY_PATH (unless the executable is being run in
      secure-execution mode; see below).  in which case it is ignored.

    o Using the directories specified in the DT_RUNPATH dynamic section attribute of the
      binary if present. Such directories are searched only to find those objects required
      by DT_NEEDED (direct dependencies) entries and do not apply to those objects' children,
      which must themselves have their own DT_RUNPATH entries. This is unlike DT_RPATH,
      which is applied to searches for all children in the dependency tree.

    o From the cache file /etc/ld.so.cache, which contains a compiled list of candidate
      shared objects previously found in the augmented library path. If, however, the binary
      was linked with the -z nodeflib linker option, shared objects in the default paths are
      skipped. Shared objects installed in hardware capability directories (see below) are
      preferred to other shared objects.

    o In the default path /lib, and then /usr/lib. (On some 64-bit architectures, the default
      paths for 64-bit shared objects are /lib64, and then /usr/lib64.)  If the binary was
      linked with the -z nodeflib linker option, this step is skipped.

    Returns a tuple of resolved location, rpath_used, in_sysroot
    """
    rpath_result = None
    found = False
    ld_library_paths = [] if not LD_LIBRARY_PATH else LD_LIBRARY_PATH.split(":")
    if unresolved.startswith("$RPATH"):
        these_rpaths = (
            [resolved_rpath]
            if resolved_rpath
            else rpaths_transitive
            + ld_library_paths
            + [dp.replace("$SYSROOT", sysroot) for dp in default_paths]
        )
        for rpath in these_rpaths:
            resolved = (
                unresolved.replace("$RPATH", rpath)
                .replace("$SELFDIR", selfdir)
                .replace("$EXEDIR", exedir)
            )
            exists = os.path.exists(resolved)
            exists_sysroot = exists and sysroot and resolved.startswith(sysroot)
            if resolved_rpath or exists or exists_sysroot:
                rpath_result = rpath
                found = True
                break
        if not found:
            # Return the so name so that it can be warned about as missing.
            return unresolved, None, False
    elif any(a in unresolved for a in ("$SELFDIR", "$EXEDIR")):
        resolved = unresolved.replace("$SELFDIR", selfdir).replace("$EXEDIR", exedir)
        exists = os.path.exists(resolved)
        exists_sysroot = exists and sysroot and resolved.startswith(sysroot)
    else:
        if unresolved.startswith("/"):
            return unresolved, None, False
        else:
            return os.path.join(selfdir, unresolved), None, False

    return resolved, rpath_result, exists_sysroot


# TODO :: Consider returning a tree structure or a dict when recurse is True?
def inspect_linkages_lief(
    filename,
    resolve_filenames=True,
    recurse=True,
    sysroot="",
    envroot="",
    arch="native",
):
    # Already seen is partly about implementing single SONAME
    # rules and its appropriateness on macOS is TBD!
    already_seen = set()
    exedir = os.path.dirname(filename)
    binary = lief.parse(filename)
    todo = [[filename, binary]]
    sysroot = _trim_sysroot(sysroot)

    default_paths = []
    if binary.format == lief.EXE_FORMATS.ELF:
        if binary.type == lief.ELF.ELF_CLASS.CLASS64:
            default_paths = [
                "$SYSROOT/lib64",
                "$SYSROOT/usr/lib64",
                "$SYSROOT/lib",
                "$SYSROOT/usr/lib",
            ]
        else:
            default_paths = ["$SYSROOT/lib", "$SYSROOT/usr/lib"]
    elif binary.format == lief.EXE_FORMATS.MACHO:
        default_paths = ["$SYSROOT/usr/lib"]
    elif binary.format == lief.EXE_FORMATS.PE:
        # We do not include C:\Windows nor C:\Windows\System32 in this list. They are added in
        # get_rpaths() instead since we need to carefully control the order.
        default_paths = [
            "$SYSROOT/System32/Wbem",
            "$SYSROOT/System32/WindowsPowerShell/v1.0",
        ]
    results = {}
    rpaths_by_binary = dict()
    parents_by_filename = dict({filename: None})
    while todo:
        for element in todo:
            todo.pop(0)
            filename2 = element[0]
            binary = element[1]
            uniqueness_key = get_uniqueness_key(binary)
            if uniqueness_key not in already_seen:
                parent_exe_dirname = None
                if binary.format == lief.EXE_FORMATS.PE:
                    tmp_filename = filename2
                    while tmp_filename:
                        if (
                            not parent_exe_dirname
                            and codefile_type(tmp_filename) == "EXEfile"
                        ):
                            parent_exe_dirname = os.path.dirname(tmp_filename)
                        tmp_filename = parents_by_filename[tmp_filename]
                else:
                    parent_exe_dirname = exedir
                # This is a hack for Python on Windows. Sorry.
                if ".pyd" in filename2 or (os.sep + "DLLs" + os.sep) in filename2:
                    parent_exe_dirname = envroot.replace(os.sep, "/") + "/DLLs"
                rpaths_by_binary[filename2] = get_rpaths(
                    binary, parent_exe_dirname, envroot.replace(os.sep, "/"), sysroot
                )
                tmp_filename = filename2
                rpaths_transitive = []
                if binary.format == lief.EXE_FORMATS.PE:
                    rpaths_transitive = rpaths_by_binary[tmp_filename]
                else:
                    while tmp_filename:
                        rpaths_transitive[:0] = rpaths_by_binary[tmp_filename]
                        tmp_filename = parents_by_filename[tmp_filename]
                libraries = get_libraries(binary)
                if filename2 in libraries:  # Happens on macOS, leading to cycles.
                    libraries.remove(filename2)
                # RPATH is implicit everywhere except macOS, make it explicit to simplify things.
                these_orig = [
                    (
                        "$RPATH/" + lib
                        if not lib.startswith("/")
                        and not lib.startswith("$")
                        and binary.format != lief.EXE_FORMATS.MACHO  # noqa
                        else lib
                    )
                    for lib in libraries
                ]
                for lib, orig in zip(libraries, these_orig):
                    resolved = _get_resolved_location(
                        binary,
                        orig,
                        exedir,
                        exedir,
                        rpaths_transitive=rpaths_transitive,
                        default_paths=default_paths,
                        sysroot=sysroot,
                    )
                    path_fixed = os.path.normpath(resolved[0])
                    # Test, randomise case. We only allow for the filename part to be random, and we allow that
                    # only for Windows DLLs. We may need a special case for Lib (from Python) vs lib (from R)
                    # too, but in general we want to enforce case checking as much as we can since even Windows
                    # can be run case-sensitively if the user wishes.
                    #
                    """
                    if binary.format == lief.EXE_FORMATS.PE:
                        import random
                        path_fixed = os.path.dirname(path_fixed) + os.sep +  \
                                     ''.join(random.choice((str.upper, str.lower))(c) for c in os.path.basename(path_fixed))
                        if random.getrandbits(1):
                            path_fixed = path_fixed.replace(os.sep + 'lib' + os.sep, os.sep + 'Lib' + os.sep)
                        else:
                            path_fixed = path_fixed.replace(os.sep + 'Lib' + os.sep, os.sep + 'lib' + os.sep)
                    """
                    if resolve_filenames:
                        rec = {
                            "orig": orig,
                            "resolved": path_fixed,
                            "rpaths": rpaths_transitive,
                        }
                    else:
                        rec = {"orig": orig, "rpaths": rpaths_transitive}
                    results[lib] = rec
                    parents_by_filename[resolved[0]] = filename2
                    if recurse:
                        if os.path.exists(resolved[0]):
                            todo.append([resolved[0], lief.parse(resolved[0])])
                already_seen.add(get_uniqueness_key(binary))
    return results


def get_linkages(
    filename,
    resolve_filenames=True,
    recurse=True,
    sysroot="",
    envroot="",
    arch="native",
):
    # When we switch to lief, want to ensure these results do not change.
    # We do not support Windows yet with pyldd.
    result_pyldd = []
    debug = False
    if not have_lief or debug:
        if codefile_type(filename) not in ("DLLfile", "EXEfile"):
            result_pyldd = inspect_linkages_pyldd(
                filename,
                resolve_filenames=resolve_filenames,
                recurse=recurse,
                sysroot=sysroot,
                arch=arch,
            )
            if not have_lief:
                return result_pyldd
        else:
            print(
                f"WARNING: failed to get_linkages, codefile_type('{filename}')={codefile_type(filename)}"
            )
            return {}
    result_lief = inspect_linkages_lief(
        filename,
        resolve_filenames=resolve_filenames,
        recurse=recurse,
        sysroot=sysroot,
        envroot=envroot,
        arch=arch,
    )
    if debug and result_pyldd and set(result_lief) != set(result_pyldd):
        print(
            "WARNING: Disagreement in get_linkages(filename={}, resolve_filenames={}, recurse={}, sysroot={}, envroot={}, arch={}):\n lief: {}\npyldd: {}\n  (using lief)".format(
                filename,
                resolve_filenames,
                recurse,
                sysroot,
                envroot,
                arch,
                result_lief,
                result_pyldd,
            )
        )
    return result_lief


def get_imports(file, arch="native"):
    binary = ensure_binary(file)
    return [str(i) for i in binary.imported_functions]


def _get_archive_signature(file):
    try:
        with open(file, "rb") as f:
            index = 0
            content = f.read(8)
            (signature,) = struct.unpack("<8s", content[index:8])
            return signature, 8
    except:
        return "", 0


debug_static_archives = 0


def is_archive(file):
    signature, _ = _get_archive_signature(file)
    return True if signature == b"!<arch>\n" else False


def get_static_lib_exports(file):
    # file = '/Users/rdonnelly/conda/main-augmented-tmp/osx-64_14354bd0cd1882bc620336d9a69ae5b9/lib/python2.7/config/libpython2.7.a'
    # References:
    # https://github.com/bminor/binutils-gdb/tree/master/bfd/archive.c
    # https://en.wikipedia.org/wiki/Ar_(Unix)
    # https://web.archive.org/web/20100314154747/http://www.microsoft.com/whdc/system/platform/firmware/PECOFF.mspx
    def _parse_ar_hdr(content, index):
        """
        0   16  File identifier                 ASCII
        16  12 	File modification timestamp     Decimal
        28  6   Owner ID                        Decimal
        34  6   Group ID                        Decimal
        40  8   File mode                       Octal
        48  10  File size in bytes              Decimal
        58  2   Ending characters               0x60 0x0A
        """
        header_fmt = "<16s 12s 6s 6s 8s 10s 2s"
        header_sz = struct.calcsize(header_fmt)

        name, modified, owner, group, mode, size, ending = struct.unpack(
            header_fmt, content[index : index + header_sz]
        )
        try:
            size = int(size)
        except:
            print(f"ERROR: {name} has non-integral size of {size}")
            return index, "", 0, 0, "INVALID"
        name_len = (
            0  # File data in BSD format archives begin with a name of this length.
        )
        if name.startswith(b"#1/"):
            typ = "BSD"
            name_len = int(name[3:])
            (name,) = struct.unpack(
                "<" + str(name_len) + "s",
                content[index + header_sz : index + header_sz + name_len],
            )
            if b"\x00" in name:
                name = name[: name.find(b"\x00")]
        elif name.startswith(b"//"):
            typ = "GNU_TABLE"
        elif name.strip() == b"/":
            typ = "GNU_SYMBOLS"
        elif name.startswith(b"/"):
            typ = "GNU"
        else:
            typ = "NORMAL"
        if b"/" in name:
            name = name[: name.find(b"/")]
        # if debug_static_archives: print("index={}, name={}, ending={}, size={}, type={}".format(index, name, ending, size, typ))
        index += header_sz + name_len
        return index, name, name_len, size, typ

    results = []
    signature, len_signature = _get_archive_signature(file)
    if signature != b"!<arch>\n":
        print(f"ERROR: {file} is not an archive")
        return results
    with open(file, "rb") as f:
        if debug_static_archives:
            print(f"Archive file {file}")
        index = 0
        content = f.read()
        index += len_signature
        obj_starts = set()
        obj_ends = set()
        functions = []
        if index & 1:
            index += 1
        if debug_static_archives:
            print(f"ar_hdr index = {hex(index)}")
        index, name, name_len, size, typ = _parse_ar_hdr(content, index)
        if typ == "GNU_SYMBOLS":
            # Reference:
            # https://web.archive.org/web/20070924090618/http://www.microsoft.com/msj/0498/hood0498.aspx
            (nsymbols,) = struct.unpack(">I", content[index : index + 4])
            # Reference:
            # https://docs.microsoft.com/en-us/windows/desktop/api/winnt/ns-winnt-_image_file_header
            offsets = []
            for i in range(nsymbols):
                (offset,) = struct.unpack(
                    ">I", content[index + 4 + i * 4 : index + 4 + (i + 1) * 4]
                )
                offsets.append(offset)
            syms = [
                symname.decode("utf-8")
                for symname in content[index + 4 + (nsymbols * 4) : index + size].split(
                    b"\x00"
                )[:nsymbols]
            ]
            for i in range(nsymbols):
                index2, name, name_len, size, typ = _parse_ar_hdr(content, offsets[i])
                obj_starts.add(index2)
                obj_ends.add(offsets[i])
                if debug_static_archives:
                    print(
                        f"symname {syms[i]}, offset {offsets[i]}, name {name}, elf? {content[index2:index2 + 4]}"
                    )
        elif name.startswith(b"__.SYMDEF"):
            # Reference:
            # http://www.manpagez.com/man/5/ranlib/
            # https://opensource.apple.com/source/cctools/cctools-921/misc/libtool.c.auto.html
            # https://opensource.apple.com/source/cctools/cctools-921/misc/nm.c.auto.html
            # https://opensource.apple.com/source/cctools/cctools-921/libstuff/writeout.c
            # https://developer.apple.com/documentation/kernel/nlist_64/1583944-n_type?language=objc
            if b"64" in name:
                # 2 uint64_t, a string table index and an offset
                ranlib_struct_field_fmt = "Q"
                toc_integers_fmt = "Q"
            else:
                # 2 uint32_t, a string table index and an offset
                ranlib_struct_field_fmt = "I"
                toc_integers_fmt = "I"
            ranlib_struct_sz = struct.calcsize(ranlib_struct_field_fmt) * 2
            toc_integers_sz = struct.calcsize(toc_integers_fmt)
            (size_ranlib_structs,) = struct.unpack(
                "<" + toc_integers_fmt, content[index : index + toc_integers_sz]
            )
            # Each of the ranlib structures consists of a zero based offset into the next
            # section (a string table of symbols) and an offset from the beginning of
            # the archive to the start of the archive file which defines the symbol
            nsymbols = size_ranlib_structs // 8
            (size_string_table,) = struct.unpack(
                "<" + toc_integers_fmt,
                content[
                    index
                    + toc_integers_sz
                    + (nsymbols * ranlib_struct_sz) : index
                    + 4
                    + 4
                    + (nsymbols * ranlib_struct_sz)
                ],
            )
            ranlib_structs = []
            ranlib_index = index + (toc_integers_sz * 2)
            for i in range(nsymbols):
                ran_off, ran_strx = struct.unpack(
                    "<" + ranlib_struct_field_fmt + ranlib_struct_field_fmt,
                    content[
                        ranlib_index
                        + (i * ranlib_struct_sz) : ranlib_index
                        + ((i + 1) * ranlib_struct_sz)
                    ],
                )
                ranlib_structs.append((ran_strx, ran_off))
            if debug_static_archives > 1:
                print(
                    "string_table: start: {} end: {}".format(
                        hex(ranlib_index + (nsymbols * ranlib_struct_sz)),
                        hex(
                            ranlib_index
                            + (nsymbols * ranlib_struct_sz)
                            + size_string_table
                        ),
                    )
                )
            string_table = content[
                ranlib_index
                + (nsymbols * ranlib_struct_sz) : ranlib_index
                + (nsymbols * ranlib_struct_sz)
                + size_string_table
            ]
            string_table = string_table.decode("utf-8", errors="ignore")
            syms = []
            for i in range(nsymbols):
                ranlib_struct = ranlib_structs[i]
                strx, off = ranlib_struct
                sym = string_table[strx : strx + string_table[strx:].find("\x00")]
                syms.append(sym)
                if debug_static_archives > 1:
                    print(f"{syms[i]} :: strx={hex(strx)}, off={hex(off)}")
                # This is probably a different structure altogether! Something symobol-y not file-y.
                off2, name, name_len, size, typ = _parse_ar_hdr(content, off)
                obj_starts.add(off2)
                obj_ends.add(off)
        obj_ends.add(len(content))
        obj_starts = sorted(list(obj_starts))
        obj_ends = sorted(list(obj_ends))[1:]
        if debug_static_archives > 1:
            print("obj_starts: {}".format(" ".join(f"0x{o:05x}" for o in obj_starts)))
        if debug_static_archives > 1:
            print("  obj_ends: {}".format(" ".join(f"0x{o:05x}" for o in obj_ends)))
        for obj_start, obj_end in zip(obj_starts, obj_ends):
            IMAGE_FILE_MACHINE_I386 = 0x014C
            IMAGE_FILE_MACHINE_AMD64 = 0x8664
            (MACHINE_TYPE,) = struct.unpack("<H", content[obj_start : obj_start + 2])
            if debug_static_archives > 0:
                print(hex(obj_start), hex(obj_end), obj_end - obj_start)
            if MACHINE_TYPE in (IMAGE_FILE_MACHINE_I386, IMAGE_FILE_MACHINE_AMD64):
                # 'This file is not a PE binary' (yeah, fair enough, it's a COFF file).
                # Reported at https://github.com/lief-project/LIEF/issues/233#issuecomment-452580391
                try:
                    obj = lief.PE.parse(raw=content[obj_start : obj_end - 1])
                except:
                    if debug_static_archives > 0:
                        print(
                            "get_static_lib_exports failed, PECOFF not supported by LIEF nor pyldd."
                        )
                    pass
                    obj = None
            elif MACHINE_TYPE == 0xFACF:
                obj = lief.parse(raw=content[obj_start:obj_end])

                # filename = '/Users/rdonnelly/conda/conda-build/macOS-libpython2.7.a/getbuildinfo.o'
                # obj = lief.parse(filename)
                # syms_a = get_symbols(obj, defined=True, undefined=False)
                # obj = lief.parse(filename)
                # syms_b = get_symbols(obj, defined=True, undefined=False)
                # print(syms_b)
            else:
                obj = lief.ELF.parse(raw=content[obj_start:obj_end])
            if not obj:
                # Cannot do much here except return the index.
                return syms, [[0, 0] for sym in syms], syms, [[0, 0] for sym in syms]
            # You can unpack an archive via:
            # /mingw64/bin/ar.exe xv /mingw64/lib/libz.dll.a
            # obj = lief.PE.parse('C:\\Users\\rdonnelly\\conda\\conda-build\\mingw-w64-libz.dll.a\\d000103.o')
            # for sym in obj.symbols:
            #     # Irrespective of whether you pass -g or not to nm, it still
            #     # lists symbols that are either exported or is_static.
            #     if sym.is_function and (sym.exported or sym.is_static):
            #         functions.append(sym.name)
            functions.extend(get_symbols(obj, defined=True, undefined=False))
        return (
            functions,
            [[0, 0] for sym in functions],
            functions,
            [[0, 0] for sym in functions],
        )


def get_static_lib_exports_nope(file):
    return [], [], [], []


def get_static_lib_exports_nm(filename):
    nm_exe = find_executable("nm")
    if sys.platform == "win32" and not nm_exe:
        nm_exe = "C:\\msys64\\mingw64\\bin\\nm.exe"
    if not nm_exe or not os.path.exists(nm_exe):
        return None
    flags = "-Pg"
    if sys.platform == "darwin":
        flags = "-PgUj"
    try:
        out, _ = Popen(
            [nm_exe, flags, filename], shell=False, stdout=PIPE
        ).communicate()
        results = out.decode("utf-8").replace("\r\n", "\n").splitlines()
        results = [
            r.split(" ")[0]
            for r in results
            if " T " in r and not r.startswith(".text ")
        ]
        results.sort()
    except OSError:
        # nm may not be available or have the correct permissions, this
        # should not cause a failure, see gh-3287
        print(f"WARNING: nm: failed to get_exports({filename})")
        results = None
    return results


def get_static_lib_exports_dumpbin(filename):
    r"""
    > dumpbin /SYMBOLS /NOLOGO C:\msys64\mingw64\lib\libasprintf.a
    > C:\Program Files (x86)\Microsoft Visual Studio\2019\Community\VC\Tools\MSVC\14.20.27508\bin\Hostx64\x64\dumpbin.exe
    > 020 00000000 UNDEF  notype ()    External     | malloc
    > vs
    > 004 00000010 SECT1  notype ()    External     | _ZN3gnu11autosprintfC1EPKcz
    """
    dumpbin_exe = find_executable("dumpbin")
    if not dumpbin_exe:
        """
        Oh the fun:
        https://stackoverflow.com/questions/41106407/programmatically-finding-the-vs2017-installation-directory
        Nice to see MS avoiding the Windows Registry though, took them a while! Still, let's ignore that, we just
        want a good dumpbin!
        """
        pfx86 = os.environ["PROGRAMFILES(X86)"]
        programs = [
            p for p in os.listdir(pfx86) if p.startswith("Microsoft Visual Studio")
        ]
        results = []
        for p in programs:
            from conda_build.utils import rec_glob

            dumpbin = rec_glob(os.path.join(pfx86, p), ("dumpbin.exe",))
            for result in dumpbin:
                try:
                    out, _ = Popen(
                        [result, filename], shell=False, stdout=PIPE
                    ).communicate()
                    lines = out.decode("utf-8").splitlines()
                    version = lines[0].split(" ")[-1]
                    results.append((result, version))
                except:
                    pass
        from conda_build.conda_interface import VersionOrder

        results = sorted(results, key=lambda x: VersionOrder(x[1]))
        dumpbin_exe = results[-1][0]
    if not dumpbin_exe:
        return None
    flags = ["/NOLOGO"]
    exports = []
    for flag in ("/SYMBOLS", "/EXPORTS"):
        try:
            out, _ = Popen(
                [dumpbin_exe] + flags + [flag] + [filename], shell=False, stdout=PIPE
            ).communicate()
            results = out.decode("utf-8").splitlines()
            if flag == "/EXPORTS":
                exports.extend(
                    [
                        r.split(" ")[-1]
                        for r in results
                        if r.startswith("                  ")
                    ]
                )
            else:
                exports.extend(
                    [
                        r.split(" ")[-1]
                        for r in results
                        if ("External " in r and "UNDEF " not in r)
                    ]
                )
        except OSError:
            # nm may not be available or have the correct permissions, this
            # should not cause a failure, see gh-3287
            print(f"WARNING: nm: failed to get_exports({filename})")
            exports = None
    exports.sort()
    return exports


def get_static_lib_exports_externally(filename):
    res_nm = get_static_lib_exports_nm(filename)
    res_dumpbin = get_static_lib_exports_dumpbin(filename)
    if res_nm is None:
        return res_dumpbin
    if res_dumpbin is None:
        return res_dumpbin
    if res_nm != res_dumpbin:
        print(f"ERROR :: res_nm != res_dumpbin\n{res_nm}\n != \n{res_dumpbin}\n")
    return res_nm


def get_exports(filename, arch="native", enable_static=False):
    result = []
    if enable_static and isinstance(filename, str):
        if (
            os.path.exists(filename)
            and (filename.endswith(".a") or filename.endswith(".lib"))
            and is_archive(filename)
        ) and sys.platform != "win32":
            # syms = os.system('nm -g {}'.filename)
            # on macOS at least:
            # -PgUj is:
            # P: posix format
            # g: global (exported) only
            # U: not undefined
            # j: name only
            if debug_static_archives or sys.platform == "win32":
                exports = get_static_lib_exports_externally(filename)
            # Now, our own implementation which does not require nm and can
            # handle .lib files.
            if sys.platform == "win32":
                # Sorry, LIEF does not handle COFF (only PECOFF) and object files are COFF.
                exports2 = exports
            else:
                try:
                    exports2, flags2, exports2_all, flags2_all = get_static_lib_exports(
                        filename
                    )
                except:
                    print(f"WARNING :: Failed to get_static_lib_exports({filename})")
                    exports2 = []
            result = exports2
            if debug_static_archives:
                if exports and set(exports) != set(exports2):
                    diff1 = set(exports).difference(set(exports2))
                    diff2 = set(exports2).difference(set(exports))
                    error_count = len(diff1) + len(diff2)
                    if debug_static_archives:
                        print(f"errors: {error_count} (-{len(diff1)}, +{len(diff2)})")
                    if debug_static_archives:
                        print(
                            "WARNING :: Disagreement regarding static lib exports in {} between nm (nsyms={}) and lielfldd (nsyms={}):".format(
                                filename, len(exports), len(exports2)
                            )
                        )
                    print(
                        "** nm.diff(liefldd) [MISSING SYMBOLS] **\n{}".format(
                            "\n".join(diff1)
                        )
                    )
                    print(
                        "** liefldd.diff(nm) [  EXTRA SYMBOLS] **\n{}".format(
                            "\n".join(diff2)
                        )
                    )

    if not result:
        binary = ensure_binary(filename)
        if binary:
            result = [str(e) for e in binary.exported_functions]
    return result


def get_relocations(filename, arch="native"):
    if not os.path.exists(filename):
        return []
    try:
        binary = lief.parse(filename)
        res = []
        if len(binary.relocations):
            for r in binary.relocations:
                if r.has_symbol:
                    if r.symbol and r.symbol.name:
                        res.append(r.symbol.name)
            return res
    except:
        print(f"WARNING: liefldd: failed get_relocations({filename})")

    return []


def get_symbols(file, defined=True, undefined=True, notexported=False, arch="native"):
    binary = ensure_binary(file)

    first_undefined_symbol = 0
    last_undefined_symbol = -1
    if isinstance(binary, lief.MachO.Binary) and binary.has_dynamic_symbol_command:
        try:
            dyscmd = binary.dynamic_symbol_command
            first_undefined_symbol = dyscmd.idx_undefined_symbol
            last_undefined_symbol = (
                first_undefined_symbol + dyscmd.nb_undefined_symbols - 1
            )
        except:
            pass
    res = []
    if len(binary.exported_functions):
        syms = binary.exported_functions
    elif len(binary.symbols):
        syms = binary.symbols
    elif len(binary.static_symbols):
        syms = binary.static_symbols
    else:
        syms = []
    for index, s in enumerate(syms):
        if debug_static_archives > 1:
            print(s)
        #        if s.type&16:
        #            continue
        is_notexported = True
        is_undefined = (
            index >= first_undefined_symbol and index <= last_undefined_symbol
        )
        if binary.__class__ != lief.MachO.Binary:
            if isinstance(s, str):
                s_name = "%s" % s
            else:
                s_name = "%s" % s.name
                if s.exported and s.imported:
                    print(f"Weird, symbol {s.name} is both imported and exported")
                if s.exported:
                    is_undefined = True
                    is_notexported = False
                elif s.imported:
                    is_undefined = False
        else:
            s_name = "%s" % s.name
            is_notexported = False if s.type & 1 else True

        # print("{:32s} : s.type 0b{:020b}, s.value 0b{:020b}".format(s.name, s.type, s.value))
        # print("s.value 0b{:020b} :: s.type 0b{:020b}, {:32s}".format(s.value, s.type, s.name))
        if notexported is True or is_notexported is False:
            if is_undefined and undefined:
                res.append("%s" % s_name)
            elif not is_undefined and defined:
                res.append("%s" % s_name)
    return res


class memoized_by_arg0_filehash:
    """Decorator. Caches a function's return value each time it is called.
    If called later with the same arguments, the cached value is returned
    (not reevaluated).

    The first argument is required to be an existing filename and it is
    always converted to an inode number.
    """

    def __init__(self, func):
        self.func = func
        self.cache = {}
        self.lock = threading.Lock()

    def __call__(self, *args, **kw):
        newargs = []
        for arg in args:
            if arg is args[0]:
                sha1 = hashlib.sha1()
                with open(arg, "rb") as f:
                    while True:
                        data = f.read(65536)
                        if not data:
                            break
                        sha1.update(data)
                arg = sha1.hexdigest()
            if isinstance(arg, list):
                newargs.append(tuple(arg))
            elif not isinstance(arg, Hashable):
                # uncacheable. a list, for instance.
                # better to not cache than blow up.
                return self.func(*args, **kw)
            else:
                newargs.append(arg)
        newargs = tuple(newargs)
        key = (newargs, frozenset(sorted(kw.items())))
        with self.lock:
            if key in self.cache:
                return self.cache[key]
            else:
                value = self.func(*args, **kw)
                self.cache[key] = value
                return value


@memoized_by_arg0_filehash
def get_exports_memoized(filename, arch="native", enable_static=False):
    return get_exports(filename, arch=arch, enable_static=enable_static)


@memoized_by_arg0_filehash
def get_imports_memoized(filename, arch="native"):
    return get_imports(filename, arch=arch)


@memoized_by_arg0_filehash
def get_relocations_memoized(filename, arch="native"):
    return get_relocations(filename, arch=arch)


@memoized_by_arg0_filehash
def get_symbols_memoized(filename, defined, undefined, arch):
    return get_symbols(filename, defined=defined, undefined=undefined, arch=arch)


@memoized_by_arg0_filehash
def get_linkages_memoized(
    filename, resolve_filenames, recurse, sysroot="", envroot="", arch="native"
):
    return get_linkages(
        filename,
        resolve_filenames=resolve_filenames,
        recurse=recurse,
        sysroot=sysroot,
        envroot=envroot,
        arch=arch,
    )
