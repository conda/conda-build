# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
import re
import stat
import sys
from itertools import islice
from subprocess import PIPE, STDOUT, CalledProcessError, Popen, check_output

from conda_build import utils
from conda_build.os_utils.external import find_preferably_prefixed_executable

NO_EXT = (
    ".py",
    ".pyc",
    ".pyo",
    ".h",
    ".a",
    ".c",
    ".txt",
    ".html",
    ".xml",
    ".png",
    ".jpg",
    ".gif",
    ".class",
    ".in",
    ".sh",
    ".yaml",
    ".md",
    ".ac",
    ".m4",
    ".cc",
    ".plist",
)

MAGIC = {
    b"\xca\xfe\xba\xbe": "MachO-universal",
    b"\xce\xfa\xed\xfe": "MachO-i386",
    b"\xcf\xfa\xed\xfe": "MachO-x86_64",
    b"\xfe\xed\xfa\xce": "MachO-ppc",
    b"\xfe\xed\xfa\xcf": "MachO-ppc64",
}

FILETYPE = {
    1: "MH_OBJECT",
    2: "MH_EXECUTE",
    3: "MH_FVMLIB",
    4: "MH_CORE",
    5: "MH_PRELOAD",
    6: "MH_DYLIB",
    7: "MH_DYLINKER",
    8: "MH_BUNDLE",
    9: "MH_DYLIB_STUB",
    10: "MH_DSYM",
    11: "MH_KEXT_BUNDLE",
}


def is_macho(path):
    if path.endswith(NO_EXT) or os.path.islink(path) or not os.path.isfile(path):
        return False
    with open(path, "rb") as fi:
        head = fi.read(4)
    return bool(head in MAGIC)


def is_dylib(path, build_prefix):
    return human_filetype(path) == "DYLIB"


def human_filetype(path, build_prefix):
    otool = find_apple_cctools_executable("otool", build_prefix)
    output = check_output((otool, "-h", path)).decode("utf-8")
    lines = output.splitlines()
    if not lines[0].startswith((path, "Mach header")):
        raise ValueError(
            "Expected `otool -h` output to start with"
            " Mach header or {}, got:\n{}".format(path, output)
        )
    assert lines[0].startswith((path, "Mach header")), path

    for line in lines:
        if line.strip().startswith("0x"):
            header = line.split()
            filetype = int(header[4])
            return FILETYPE[filetype][3:]


def is_dylib_info(lines):
    dylib_info = ("LC_ID_DYLIB", "LC_LOAD_DYLIB")
    if len(lines) > 1 and lines[1].split()[1] in dylib_info:
        return True
    return False


def is_id_dylib(lines):
    if len(lines) > 1 and lines[1].split()[1] == "LC_ID_DYLIB":
        return True
    return False


def is_load_dylib(lines):
    if len(lines) > 1 and lines[1].split()[1] == "LC_LOAD_DYLIB":
        return True
    return False


def is_rpath(lines):
    if len(lines) > 1 and lines[1].split()[1] == "LC_RPATH":
        return True
    return False


def _get_load_commands(lines):
    """yields each load command from the output of otool -l"""
    a = 1  # first line is the filename.
    for ln, line in enumerate(lines):
        if line.startswith("Load command"):
            if a < ln:
                yield lines[a:ln]
            a = ln
    yield lines[a:]


def _get_matching_load_commands(lines, cb_filter):
    """Workhorse function for otool

    Does the work of filtering load commands and making a list
    of dicts. The logic for splitting the free-form lines into
    keys and values in entirely encoded here. Values that can
    be converted to ints are converted to ints.
    """
    result = []
    for lcmds in _get_load_commands(lines):
        if cb_filter(lcmds):
            lcdict = {}
            for line in islice(lcmds, 1, len(lcmds)):
                listy = line.split()
                # This could be prettier, but what we need it to handle
                # is fairly simple so let's just hardcode it for speed.
                if len(listy) == 2:
                    key, value = listy
                elif listy[0] == "name" or listy[0] == "path":
                    # Create an entry for 'name offset' if there is one
                    # as that can be useful if we need to know if there
                    # is space to patch it for relocation purposes.
                    if listy[2] == "(offset":
                        key = listy[0] + " offset"
                        value = int(listy[3][:-1])
                        lcdict[key] = value
                    key, value = listy[0:2]
                elif listy[0] == "time":
                    key = " ".join(listy[0:3])
                    value = " ".join(listy[3:])
                elif listy[0] in ("current", "compatibility"):
                    key = " ".join(listy[0:2])
                    value = listy[2]
                try:
                    value = int(value)
                except ValueError:
                    pass
                lcdict[key] = value
            result.append(lcdict)
    return result


def find_apple_cctools_executable(name, build_prefix, nofail=False):
    tools = find_preferably_prefixed_executable(name, build_prefix, all_matches=True)
    for tool in tools:
        try:
            if "/usr/bin" in tool:
                with open(tool, "rb") as f:
                    s = f.read()
                if s.find(b"usr/lib/libxcselect.dylib") != -1:
                    # We ask xcrun.
                    try:
                        tool_xcr = (
                            check_output(["xcrun", "-find", name], stderr=STDOUT)
                            .decode("utf-8")
                            .splitlines()[0]
                        )
                    except Exception as e:
                        log = utils.get_logger(__name__)
                        log.error(
                            "ERROR :: Found `{}` but is is an Apple Xcode stub executable\n"
                            "and it returned an error:\n{}".format(tool, e.output)
                        )
                        raise e
                    tool = tool_xcr
                    if os.path.exists(tool):
                        return tool
        except Exception as _:  # noqa
            print(
                "ERROR :: Failed to run `{}`.  Please use `conda` to install `cctools` into your base environment.\n"
                "         An option on macOS is to install `Xcode` or `Command Line Tools for Xcode`.".format(
                    tool
                )
            )
            sys.exit(1)
        return tool


def otool(path, build_prefix=None, cb_filter=is_dylib_info):
    """A wrapper around otool -l

    Parse the output of the otool -l 'load commands', filtered by
    cb_filter, returning a list of dictionairies for the records.

    cb_filter receives the whole load command record, including the
    first line, the 'Load Command N' one. All the records have been
    pre-stripped of white space.

    The output of otool -l is entirely freeform; delineation between
    key and value doesn't formally exist, so that is hard coded. I
    didn't want to use regexes to parse it for speed purposes.

    Any key values that can be converted to integers are converted
    to integers, the rest are strings.
    """
    otool = find_apple_cctools_executable("otool", build_prefix)
    lines = check_output([otool, "-l", path], stderr=STDOUT).decode("utf-8")
    # llvm-objdump returns 0 for some things that are anything but successful completion.
    lines_split = lines.splitlines()
    # 'invalid', 'expected' and 'unexpected' are too generic
    # here so also check that we do not get 'useful' output.
    if len(lines_split) < 10 and (
        re.match(
            ".*(is not a Mach-O|invalid|expected|unexpected).*", lines, re.MULTILINE
        )
    ):
        raise CalledProcessError(-1, otool)
    return _get_matching_load_commands(lines_split, cb_filter)


def get_dylibs(path, build_prefix=None):
    """Return a list of the loaded dylib pathnames"""
    dylib_loads = otool(path, build_prefix, is_load_dylib)
    return [dylib_load["name"] for dylib_load in dylib_loads]


def get_id(path, build_prefix=None):
    """Returns the id name of the Mach-O file `path` or an empty string"""
    dylib_loads = otool(path, build_prefix, is_id_dylib)
    try:
        return [dylib_load["name"] for dylib_load in dylib_loads][0]
    except:
        return ""


def get_rpaths(path, build_prefix=None):
    """Return a list of the dylib rpaths"""
    dylib_loads = otool(path, build_prefix, is_rpath)
    return [dylib_load["path"] for dylib_load in dylib_loads]


def _chmod(filename, mode):
    try:
        os.chmod(filename, mode)
    except (OSError, utils.PermissionError) as e:
        log = utils.get_logger(__name__)
        log.warn(str(e))


def install_name_tool(args, build_prefix=None, verbose=False):
    args_full = [find_apple_cctools_executable("install_name_tool", build_prefix)]
    args_full.extend(args)
    if verbose:
        print(" ".join(args_full))
    old_mode = stat.S_IMODE(os.stat(args[-1]).st_mode)
    new_mode = old_mode | stat.S_IWUSR
    if old_mode != new_mode:
        _chmod(args[-1], new_mode)
    subproc = Popen(args_full, stdout=PIPE, stderr=PIPE)
    out, err = subproc.communicate()
    out = out.decode("utf-8")
    err = err.decode("utf-8")
    if old_mode != new_mode:
        _chmod(args[-1], old_mode)
    return subproc.returncode, out, err


def add_rpath(path, rpath, build_prefix=None, verbose=False):
    """Add an `rpath` to the Mach-O file at `path`"""
    if not is_macho(path):
        return
    args = ["-add_rpath", rpath, path]
    code, _, stderr = install_name_tool(args, build_prefix)
    if "Mach-O dynamic shared library stub file" in stderr:
        print("Skipping Mach-O dynamic shared library stub file %s\n" % path)
        return
    elif "would duplicate path, file already has LC_RPATH for:" in stderr:
        print("Skipping -add_rpath, file already has LC_RPATH set")
        return
    else:
        print(stderr, file=sys.stderr)
        if code:
            raise RuntimeError("install_name_tool failed with exit status %d" % code)


def delete_rpath(path, rpath, build_prefix=None, verbose=False):
    """Delete an `rpath` from the Mach-O file at `path`"""
    if not is_macho(path):
        return
    args = ["-delete_rpath", rpath, path]
    code, _, stderr = install_name_tool(args, build_prefix)
    if "Mach-O dynamic shared library stub file" in stderr:
        print("Skipping Mach-O dynamic shared library stub file %s\n" % path)
        return
    elif "no LC_RPATH load command with path:" in stderr:
        print("Skipping -delete_rpath, file doesn't contain that LC_RPATH")
        return
    else:
        print(stderr, file=sys.stderr)
        if code:
            raise RuntimeError("install_name_tool failed with exit status %d" % code)


def install_name_change(path, build_prefix, cb_func, dylibs, verbose=False):
    """Change dynamic shared library load name or id name of Mach-O Binary `path`.

    `cb_func` is called for each shared library load command. The dictionary of
    the load command is passed in and the callback returns the new name or None
    if the name should be unchanged.

    When dealing with id load commands, `install_name_tool -id` is used.
    When dealing with dylib load commands `install_name_tool -change` is used.
    """

    changes = []
    for index, dylib in enumerate(dylibs):
        new_name = cb_func(path, dylib)
        if new_name:
            changes.append((index, new_name))

    ret = True
    for index, new_name in changes:
        args = []
        if dylibs[index]["cmd"] == "LC_ID_DYLIB":
            args.extend(("-id", new_name, path))
        else:
            args.extend(("-change", dylibs[index]["name"], new_name, path))
        code, _, stderr = install_name_tool(args, build_prefix)
        if "Mach-O dynamic shared library stub file" in stderr:
            print("Skipping Mach-O dynamic shared library stub file %s" % path)
            ret = False
            continue
        else:
            print(stderr, file=sys.stderr)
        if code:
            raise RuntimeError(
                "install_name_tool failed with exit status %d, stderr of:\n%s"
                % (code, stderr)
            )
    return ret


if __name__ == "__main__":
    if sys.platform == "darwin":
        for path in "/bin/ls", "/etc/locate.rc":
            print(path, is_macho(path))
