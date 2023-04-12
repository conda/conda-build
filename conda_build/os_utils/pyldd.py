# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import argparse
import glob
import logging
import os
import re
import struct
import sys

from conda_build.utils import ensure_list, get_logger

logging.basicConfig(level=logging.INFO)


'''
# Detect security flags via readelf (from https://github.com/hugsy/gef)
# .. spawning out to readelf is not something we intend to do though ..
@lru_cache(32)
def checksec(filename):
    """Check the security property of the ELF binary. The following properties are:
    - Canary
    - NX
    - PIE
    - Fortify
    - Partial/Full RelRO.
    Return a Python dict() with the different keys mentioned above, and the boolean
    associated whether the protection was found."""

    try:
        readelf = which("readelf")
    except IOError:
        err("Missing `readelf`")
        return

    def __check_security_property(opt, filename, pattern):
        cmd   = [readelf,]
        cmd  += opt.split()
        cmd  += [filename,]
        lines = gef_execute_external(cmd, as_list=True)
        for line in lines:
            if re.search(pattern, line):
                return True
        return False

    results = collections.OrderedDict()
    results["Canary"] = __check_security_property("-s", filename, r"__stack_chk_fail") is True
    has_gnu_stack = __check_security_property("-W -l", filename, r"GNU_STACK") is True
    if has_gnu_stack:
        results["NX"] = __check_security_property("-W -l", filename, r"GNU_STACK.*RWE") is False
    else:
        results["NX"] = False
    results["PIE"] = __check_security_property("-h", filename, r"Type:.*EXEC") is False
    results["Fortify"] = __check_security_property("-s", filename, r"_chk@GLIBC") is True
    results["Partial RelRO"] = __check_security_property("-l", filename, r"GNU_RELRO") is True
    results["Full RelRO"] = __check_security_property("-d", filename, r"BIND_NOW") is True
    return results
'''

"""
Eventual goal is to become a full replacement for `ldd` `otool -L` and `ntldd'
For now only works with ELF and Mach-O files and command-line execution is not
supported. To get the list of shared libs use `inspect_linkages(filename)`.
"""

LDD_USAGE = """
Usage: ldd [OPTION]... FILE...
      --help              print this help and exit
      --version           print version information and exit
  -d, --data-relocs       process data relocations
  -r, --function-relocs   process data and function relocations
  -u, --unused            print unused direct dependencies
  -v, --verbose           print all information

For bug reporting instructions, please see:
<https://bugs.archlinux.org/>.
"""  # noqa

OTOOL_USAGE = """
Usage: /Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/otool [-arch arch_type] [-fahlLDtdorSTMRIHGvVcXmqQjCP] [-mcpu=arg] [--version] <object file> ...
    -f print the fat headers
    -a print the archive header
    -h print the mach header
    -l print the load commands
    -L print shared libraries used
    -D print shared library id name
    -t print the text section (disassemble with -v)
    -p <routine name>  start dissassemble from routine name
    -s <segname> <sectname> print contents of section
    -d print the data section
    -o print the Objective-C segment
    -r print the relocation entries
    -S print the table of contents of a library
    -T print the table of contents of a dynamic shared library
    -M print the module table of a dynamic shared library
    -R print the reference table of a dynamic shared library
    -I print the indirect symbol table
    -H print the two-level hints table
    -G print the data in code table
    -v print verbosely (symbolically) when possible
    -V print disassembled operands symbolically
    -c print argument strings of a core file
    -X print no leading addresses or headers
    -m don't use archive(member) syntax
    -B force Thumb disassembly (ARM objects only)
    -q use llvm's disassembler (the default)
    -Q use otool(1)'s disassembler
    -mcpu=arg use `arg' as the cpu for disassembly
    -j print opcode bytes
    -P print the info plist section as strings
    -C print linker optimization hints
    --version print the version of /Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/otool
"""  # noqa


##############################################
# Constants used in the Mach-O specification #
##############################################

MH_MAGIC = 0xFEEDFACE
MH_CIGAM = 0xCEFAEDFE
MH_MAGIC_64 = 0xFEEDFACF
MH_CIGAM_64 = 0xCFFAEDFE
FAT_MAGIC = 0xCAFEBABE
BIG_ENDIAN = ">"
LITTLE_ENDIAN = "<"
LC_ID_DYLIB = 0xD
LC_LOAD_DYLIB = 0xC
LC_LOAD_WEAK_DYLIB = 0x18
LC_LOAD_UPWARD_DYLIB = 0x23
LC_REEXPORT_DYLIB = 0x1F
LC_LAZY_LOAD_DYLIB = 0x20
LC_LOAD_DYLIBS = (
    LC_LOAD_DYLIB,
    LC_LOAD_WEAK_DYLIB,
    LC_LOAD_UPWARD_DYLIB,
    LC_LAZY_LOAD_DYLIB,
    LC_REEXPORT_DYLIB,
)
LC_REQ_DYLD = 0x80000000
LC_RPATH = 0x1C | LC_REQ_DYLD
majver = sys.version_info[0]
maxint = majver == 3 and getattr(sys, "maxsize") or getattr(sys, "maxint")


class IncompleteRead(Exception):
    pass


class ReadCheckWrapper:
    """
    Wrap a file-object to raises a exception on incomplete reads.
    """

    def __init__(self, file_obj):
        self._file_obj = file_obj

    def read(self, size):
        buf = self._file_obj.read(size)
        if len(buf) != size:
            raise IncompleteRead("requested number of bytes were not read.")
        return buf

    def __getattr__(self, attr):
        if attr == "read":
            return self.read
        else:
            return getattr(self._file_obj, attr)


class fileview:
    """
    A proxy for file-like objects that exposes a given view of a file.
    Modified from macholib.
    """

    def __init__(self, fileobj, start=0, size=maxint):
        if isinstance(fileobj, fileview):
            self._fileobj = fileobj._fileobj
        else:
            self._fileobj = fileobj
        self._start = start
        self._end = start + size
        self._pos = 0

    def __repr__(self):
        return "<fileview [%d, %d] %r>" % (self._start, self._end, self._fileobj)

    def tell(self):
        return self._pos

    def _checkwindow(self, seekto, op):
        if not (self._start <= seekto <= self._end):
            raise OSError(
                "%s to offset %d is outside window [%d, %d]"
                % (op, seekto, self._start, self._end)
            )

    def seek(self, offset, whence=0):
        seekto = offset
        if whence == os.SEEK_SET:
            seekto += self._start
        elif whence == os.SEEK_CUR:
            seekto += self._start + self._pos
        elif whence == os.SEEK_END:
            seekto += self._end
        else:
            raise OSError(f"Invalid whence argument to seek: {whence!r}")
        self._checkwindow(seekto, "seek")
        self._fileobj.seek(seekto)
        self._pos = seekto - self._start

    def write(self, bytes):
        here = self._start + self._pos
        self._checkwindow(here, "write")
        self._checkwindow(here + len(bytes), "write")
        self._fileobj.seek(here, os.SEEK_SET)
        self._fileobj.write(bytes)
        self._pos += len(bytes)

    def read(self, size=maxint):
        assert size >= 0
        here = self._start + self._pos
        self._checkwindow(here, "read")
        size = min(size, self._end - here)
        self._fileobj.seek(here, os.SEEK_SET)
        bytes = self._fileobj.read(size)
        self._pos += len(bytes)
        return bytes


class UnixExecutable:
    def __init__(self, file, initial_rpaths_transitive=[]):
        self.rpaths_transitive = []
        self.rpaths_nontransitive = []
        self.shared_libraries = []
        self.dt_runpath = []
        self.dt_soname = initial_rpaths_transitive

    def get_rpaths_transitive(self):
        return self.rpaths_transitive

    def get_rpaths_nontransitive(self):
        return self.rpaths_nontransitive

    def get_shared_libraries(self):
        return self.shared_libraries

    def is_executable(self):
        return True

    def get_runpaths(self):
        return self.dt_runpath

    def get_soname(self):
        return self.dt_soname


def read_data(file, endian, num=1):
    """
    Read a given number of 32-bits unsigned integers from the given file
    with the given endianness.
    """
    res = struct.unpack(endian + "L" * num, file.read(num * 4))
    if len(res) == 1:
        return res[0]
    return res


def replace_lc_load_dylib(file, where, bits, endian, cmd, cmdsize, what, val):
    if cmd & ~LC_REQ_DYLD in LC_LOAD_DYLIBS:
        # The first data field in LC_LOAD_DYLIB commands is the
        # offset of the name, starting from the beginning of the
        # command.
        name_offset = read_data(file, endian)
        file.seek(where + name_offset, os.SEEK_SET)
        # Read the NUL terminated string
        load = file.read(cmdsize - name_offset).decode()
        load = load[: load.index("\0")]
        # If the string is what is being replaced, overwrite it.
        if load == what:
            file.seek(where + name_offset, os.SEEK_SET)
            file.write(val.encode() + b"\0")
            return True
    return False


def find_lc_load_dylib(file, where, bits, endian, cmd, cmdsize, what):
    if cmd & ~LC_REQ_DYLD in LC_LOAD_DYLIBS:
        # The first data field in LC_LOAD_DYLIB commands is the
        # offset of the name, starting from the beginning of the
        # command.
        name_offset = read_data(file, endian)
        file.seek(where + name_offset, os.SEEK_SET)
        # Read the NUL terminated string
        load = file.read(cmdsize - name_offset).decode()
        load = load[: load.index("\0")]
        # If the string is what is being replaced, overwrite it.
        if re.match(what, load):
            return load


def find_lc_rpath(file, where, bits, endian, cmd, cmdsize):
    if cmd == LC_RPATH:
        # The first data field in LC_LOAD_DYLIB commands is the
        # offset of the name, starting from the beginning of the
        # command.
        name_offset = read_data(file, endian)
        file.seek(where + name_offset, os.SEEK_SET)
        # Read the NUL terminated string
        load = file.read(cmdsize - name_offset).decode()
        load = load[: load.index("\0")]
        return load


def do_macho(file, bits, endian, lc_operation, *args):
    # Read Mach-O header (the magic number is assumed read by the caller)
    _cputype, _cpusubtype, filetype, ncmds, _sizeofcmds, _flags = read_data(
        file, endian, 6
    )
    # 64-bits header has one more field.
    if bits == 64:
        read_data(file, endian)
    # The header is followed by ncmds commands
    results = []
    for _n in range(ncmds):
        where = file.tell()
        # Read command header
        cmd, cmdsize = read_data(file, endian, 2)
        results.append(lc_operation(file, where, bits, endian, cmd, cmdsize, *args))
        # Seek to the next command
        file.seek(where + cmdsize, os.SEEK_SET)
    return filetype, results


class offset_size:
    def __init__(self, offset=0, size=maxint):
        self.offset = offset
        self.size = size


def do_file(file, lc_operation, off_sz, arch, results, *args):
    file = fileview(file, off_sz.offset, off_sz.size)
    # Read magic number
    magic = read_data(file, BIG_ENDIAN)
    if magic == FAT_MAGIC:
        # Fat binaries contain nfat_arch Mach-O binaries
        nfat_arch = read_data(file, BIG_ENDIAN)
        for _n in range(nfat_arch):
            # Read arch header
            _cputype, _cpusubtype, offset, size, _align = read_data(file, BIG_ENDIAN, 5)
            do_file(file, lc_operation, offset_size(offset, size), arch, results, *args)
    elif magic == MH_MAGIC and arch in ("any", "ppc32", "m68k"):
        results.append(do_macho(file, 32, BIG_ENDIAN, lc_operation, *args))
    elif magic == MH_CIGAM and arch in ("any", "i386"):
        results.append(do_macho(file, 32, LITTLE_ENDIAN, lc_operation, *args))
    elif magic == MH_MAGIC_64 and arch in ("any", "ppc64"):
        results.append(do_macho(file, 64, BIG_ENDIAN, lc_operation, *args))
    elif magic == MH_CIGAM_64 and arch in ("any", "x86_64"):
        results.append(do_macho(file, 64, LITTLE_ENDIAN, lc_operation, *args))


def mach_o_change(path, arch, what, value):
    """
    Replace a given name (what) in any LC_LOAD_DYLIB command found in
    the given binary with a new name (value), provided it's shorter.
    """

    assert len(what) >= len(value)

    results = []
    with open(path, "r+b") as f:
        do_file(f, replace_lc_load_dylib, offset_size(), arch, results, what, value)
    return results


def mach_o_find_dylibs(ofile, arch, regex=".*"):
    """
    Finds the executable's view of where any dylibs live
    without resolving any macros (@rpath, @loader_path, @executable_path)
    """
    results = []
    do_file(ofile, find_lc_load_dylib, offset_size(), arch, results, regex)
    return results


def mach_o_find_rpaths(ofile, arch):
    """
    Finds ofile's list of rpaths
    """
    results = []
    do_file(ofile, find_lc_rpath, offset_size(), arch, results)
    return results


def _get_resolved_location(
    codefile,
    unresolved,
    exe_dir,
    self_dir,
    LD_LIBRARY_PATH="",
    default_paths=None,
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
            else codefile.get_rpaths_transitive()
            + ld_library_paths
            + codefile.get_rpaths_nontransitive()
            + [dp.replace("$SYSROOT", sysroot) for dp in ensure_list(default_paths)]
        )
        for rpath in these_rpaths:
            resolved = (
                unresolved.replace("$RPATH", rpath)
                .replace("$SELFDIR", self_dir)
                .replace("$EXEDIR", exe_dir)
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
        resolved = unresolved.replace("$SELFDIR", self_dir).replace("$EXEDIR", exe_dir)
        exists = os.path.exists(resolved)
        exists_sysroot = exists and sysroot and resolved.startswith(sysroot)
    else:
        if unresolved.startswith("/"):
            return unresolved, None, False
        else:
            return os.path.join(self_dir, unresolved), None, False

    return resolved, rpath_result, exists_sysroot


def _get_resolved_relocated_location(
    codefile, so, src_exedir, src_selfdir, dst_exedir, dst_selfdir
):
    src_resolved, rpath, in_sysroot = _get_resolved_location(
        codefile, so, src_exedir, src_selfdir
    )
    if in_sysroot:
        dst_resolved = src_resolved
    else:
        dst_resolved = _get_resolved_location(
            codefile, so, dst_exedir, dst_selfdir, rpath
        )
    return src_resolved, dst_resolved, in_sysroot


class machofile(UnixExecutable):
    def __init__(self, file, arch, initial_rpaths_transitive=[]):
        self.filename = file.name
        self.shared_libraries = []
        self.dt_runpath = []
        self._dir = os.path.dirname(file.name)
        results = mach_o_find_dylibs(file, arch)
        if not results:
            return
        _, sos = zip(*results)
        file.seek(0)
        self.rpaths_transitive = initial_rpaths_transitive
        _filetypes, rpaths = zip(*mach_o_find_rpaths(file, arch))
        local_rpaths = [
            self.from_os_varnames(rpath.rstrip("/")) for rpath in rpaths[0] if rpath
        ]
        self.rpaths_transitive.extend(local_rpaths)
        self.rpaths_nontransitive = local_rpaths
        self.shared_libraries.extend(
            [(so, self.from_os_varnames(so)) for so in sos[0] if so]
        )
        file.seek(0)

    def to_os_varnames(self, input_):
        """Don't make these functions - they are methods to match the API for elffiles."""
        return (
            input_.replace("$SELFDIR", "@loader_path")
            .replace("$EXEDIR", "@executable_path")
            .replace("$RPATH", "@rpath")
        )

    def from_os_varnames(self, input_):
        """Don't make these functions - they are methods to match the API for elffiles."""
        return (
            input_.replace("@loader_path", "$SELFDIR")
            .replace("@executable_path", "$EXEDIR")
            .replace("@rpath", "$RPATH")
        )

    def get_resolved_shared_libraries(self, src_exedir, src_selfdir, sysroot=""):
        result = []
        for so_orig, so in self.shared_libraries:
            resolved, rpath, in_sysroot = _get_resolved_location(
                self, so, src_exedir, src_selfdir, sysroot
            )
            result.append((so_orig, resolved, rpath, in_sysroot))
        return result

    def get_relocated_shared_libraries(
        self, src_exedir, src_selfdir, dst_exedir, dst_selfdir
    ):
        result = []
        for so in self.shared_libraries:
            resolved, dst_resolved, in_sysroot = _get_resolved_relocated_location(
                self, so, src_exedir, src_selfdir, dst_exedir, dst_selfdir
            )
            result.append((so, resolved, dst_resolved, in_sysroot))
        return result

    def uniqueness_key(self):
        return self.filename


###########################################
# Constants used in the ELF specification #
###########################################

ELF_HDR = 0x7F454C46
E_TYPE_RELOCATABLE = 1
E_TYPE_EXECUTABLE = 2
E_TYPE_SHARED = 3
E_TYPE_CORE = 4
E_MACHINE_UNSPECIFIED = 0x00
E_MACHINE_SPARC = 0x02
E_MACHINE_X86 = 0x03
E_MACHINE_MIPS = 0x08
E_MACHINE_POWERPC = 0x14
E_MACHINE_ARM = 0x28
E_MACHINE_SUPERH = 0x2A
E_MACHINE_IA_64 = 0x32
E_MACHINE_X86_64 = 0x3E
E_MACHINE_AARCH64 = 0xB7
E_MACHINE_RISC_V = 0xF3

# It'd be quicker to use struct.calcsize here and a single
# struct.unpack but it would be ugly and harder to maintain.
PT_NULL = 0
PT_LOAD = 1
PT_DYNAMIC = 2
PT_INTERP = 3
PT_NOTE = 4
PT_SHLIB = 5
PT_PHDR = 6
PT_LOOS = 0x60000000
PT_LOPROC = 0x70000000
PT_HIPROC = 0x7FFFFFFF
PT_GNU_EH_FRAME = PT_LOOS + 0x474E550
PT_GNU_STACK = PT_LOOS + 0x474E551
PT_GNU_RELRO = PT_LOOS + 0x474E552

SHT_PROGBITS = 0x1
SHT_SYMTAB = 0x2
SHT_STRTAB = 0x3
SHT_RELA = 0x4
SHT_HASH = 0x5
SHT_DYNAMIC = 0x6
SHT_NOTE = 0x7
SHT_NOBITS = 0x8
SHT_REL = 0x9
SHT_SHLIB = 0x0A
SHT_DYNSYM = 0x0B
SHT_INIT_ARRAY = 0x0E
SHT_FINI_ARRAY = 0x0F
SHT_PREINIT_ARRAY = 0x10
SHT_GROUP = 0x11
SHT_SYMTAB_SHNDX = 0x12
SHT_NUM = 0x13
SHT_LOOS = 0x60000000

SHF_WRITE = 0x1
SHF_ALLOC = 0x2
SHF_EXECINSTR = 0x4
SHF_MERGE = 0x10
SHF_STRINGS = 0x20
SHF_INFO_LINK = 0x40
SHF_LINK_ORDER = 0x80
SHF_OS_NONCONFORMING = 0x100
SHF_GROUP = 0x200
SHF_TLS = 0x400
SHF_MASKOS = 0x0FF00000
SHF_MASKPROC = 0xF0000000
SHF_ORDERED = 0x4000000
SHF_EXCLUDE = 0x8000000

DT_NULL = 0
DT_NEEDED = 1
DT_PLTRELSZ = 2
DT_PLTGOT = 3
DT_HASH = 4
DT_STRTAB = 5
DT_SYMTAB = 6
DT_RELA = 7
DT_RELASZ = 8
DT_RELAENT = 9
DT_STRSZ = 10
DT_SYMENT = 11
DT_INIT = 12
DT_FINI = 13
DT_SONAME = 14
DT_RPATH = 15
DT_SYMBOLIC = 16
DT_REL = 17
DT_RELSZ = 18
DT_RELENT = 19
DT_PLTREL = 20
DT_DEBUG = 21
DT_TEXTREL = 22
DT_JMPREL = 23
DT_BIND_NOW = 24
DT_INIT_ARRAY = 25
DT_FINI_ARRAY = 26
DT_INIT_ARRAYSZ = 27
DT_FINI_ARRAYSZ = 28
DT_RUNPATH = 29
DT_LOOS = 0x60000000
DT_HIOS = 0x6FFFFFFF
DT_LOPROC = 0x70000000
DT_HIPROC = 0x7FFFFFFF


class elfheader:
    def __init__(self, file):
        (self.hdr,) = struct.unpack(BIG_ENDIAN + "L", file.read(4))
        self.dt_needed = []
        self.dt_rpath = []
        if self.hdr != ELF_HDR:
            return
        (bitness,) = struct.unpack(LITTLE_ENDIAN + "B", file.read(1))
        bitness = 32 if bitness == 1 else 64
        sz_ptr = int(bitness / 8)
        ptr_type = "Q" if sz_ptr == 8 else "L"
        self.bitness = bitness
        self.sz_ptr = sz_ptr
        self.ptr_type = ptr_type
        (endian,) = struct.unpack(LITTLE_ENDIAN + "B", file.read(1))
        endian = LITTLE_ENDIAN if endian == 1 else BIG_ENDIAN
        self.endian = endian
        (self.version,) = struct.unpack(endian + "B", file.read(1))
        (self.osabi,) = struct.unpack(endian + "B", file.read(1))
        (self.abiver,) = struct.unpack(endian + "B", file.read(1))
        struct.unpack(endian + "B" * 7, file.read(7))
        (self.type,) = struct.unpack(endian + "H", file.read(2))
        (self.machine,) = struct.unpack(endian + "H", file.read(2))
        (self.version,) = struct.unpack(endian + "L", file.read(4))
        (self.entry,) = struct.unpack(endian + ptr_type, file.read(sz_ptr))
        (self.phoff,) = struct.unpack(endian + ptr_type, file.read(sz_ptr))
        (self.shoff,) = struct.unpack(endian + ptr_type, file.read(sz_ptr))
        (self.flags,) = struct.unpack(endian + "L", file.read(4))
        (self.ehsize,) = struct.unpack(endian + "H", file.read(2))
        (self.phentsize,) = struct.unpack(endian + "H", file.read(2))
        (self.phnum,) = struct.unpack(endian + "H", file.read(2))
        (self.shentsize,) = struct.unpack(endian + "H", file.read(2))
        (self.shnum,) = struct.unpack(endian + "H", file.read(2))
        (self.shstrndx,) = struct.unpack(endian + "H", file.read(2))
        loc = file.tell()
        if loc != self.ehsize:
            get_logger(__name__).warning(f"file.tell()={loc} != ehsize={self.ehsize}")

    def __str__(self):
        return "bitness {}, endian {}, version {}, type {}, machine {}, entry {}".format(  # noqa
            self.bitness,
            self.endian,
            self.version,
            self.type,
            hex(self.machine),
            hex(self.entry),
        )


class elfsection:
    def __init__(self, eh, file):
        ptr_type = eh.ptr_type
        sz_ptr = eh.sz_ptr
        endian = eh.endian
        # It'd be quicker to use struct.calcsize here and a single
        # struct.unpack but it would be ugly and harder to maintain.
        (self.sh_name,) = struct.unpack(endian + "L", file.read(4))
        (self.sh_type,) = struct.unpack(endian + "L", file.read(4))
        (self.sh_flags,) = struct.unpack(endian + ptr_type, file.read(sz_ptr))
        (self.sh_addr,) = struct.unpack(endian + ptr_type, file.read(sz_ptr))
        (self.sh_offset,) = struct.unpack(endian + ptr_type, file.read(sz_ptr))
        (self.sh_size,) = struct.unpack(endian + ptr_type, file.read(sz_ptr))
        (self.sh_link,) = struct.unpack(endian + "L", file.read(4))
        (self.sh_info,) = struct.unpack(endian + "L", file.read(4))
        (self.sh_addralign,) = struct.unpack(endian + ptr_type, file.read(sz_ptr))
        (self.sh_entsize,) = struct.unpack(endian + ptr_type, file.read(sz_ptr))
        # Lower priority == post processed earlier so that those
        # with higher priority can assume already initialized.
        if self.sh_type == SHT_STRTAB:
            self.priority = 0
        else:
            self.priority = 1

    def postprocess(self, elffile, file):
        ptr_type = elffile.ehdr.ptr_type
        sz_ptr = elffile.ehdr.sz_ptr
        endian = elffile.ehdr.endian
        if self.sh_type == SHT_STRTAB:
            file.seek(self.sh_offset)
            self.table = file.read(self.sh_size).decode()
        elif self.sh_type == SHT_DYNAMIC:
            #
            # Required reading 1:
            # http://blog.qt.io/blog/2011/10/28/rpath-and-runpath/
            #
            # Unless loading object has RUNPATH:
            #   RPATH of the loading object,
            #     then the RPATH of its loader (unless it has a RUNPATH), ...,
            #     until the end of the chain, which is either the executable
            #     or an object loaded by dlopen
            #   Unless executable has RUNPATH:
            #     RPATH of the executable
            # LD_LIBRARY_PATH
            # RUNPATH of the loading object
            # ld.so.cache
            # default dirs
            #
            # Required reading 2:
            # http://www.lumiera.org/documentation/technical/code/linkingStructure.html
            #
            # the $ORIGIN token
            #
            # To support flexible RUNPATH (and RPATH) settings, the GNU ld.so
            # (also the SUN and Irix linkers) allow the usage of some "magic"
            # tokens in the .dynamic section of ELF binaries (both libraries
            # and executables):
            #
            # $ORIGIN
            #
            # the directory containing the executable or library actually
            # triggering the current (innermost) resolution step. Not to be
            # confused with the entity causing the whole linking procedure
            # (an executable to be executed or a dlopen() call)
            #
            # $PLATFORM
            #
            # expands to the architecture/platform tag as provided by the OS
            # kernel
            #
            # $LIB
            #
            # the system libraries directory, which is /lib for the native
            # architecture on FHS compliant GNU/Linux systems.
            #
            dt_strtab_ptr = None
            dt_needed = []
            dt_rpath = []
            dt_runpath = []
            dt_soname = "$EXECUTABLE"
            if self.sh_entsize == 0:
                # Some ELF files (e.g., Guile's .go files) include sections
                # without a table of entries in which case sh_entsize will be 0
                num_entries = 0
            else:
                num_entries = int(self.sh_size / self.sh_entsize)
            for m in range(num_entries):
                file.seek(self.sh_offset + (m * self.sh_entsize))
                (d_tag,) = struct.unpack(endian + ptr_type, file.read(sz_ptr))
                (d_val_ptr,) = struct.unpack(endian + ptr_type, file.read(sz_ptr))
                if d_tag == DT_NEEDED:
                    dt_needed.append(d_val_ptr)
                elif d_tag == DT_RPATH:
                    dt_rpath.append(d_val_ptr)
                elif d_tag == DT_RUNPATH:
                    dt_runpath.append(d_val_ptr)
                elif d_tag == DT_STRTAB:
                    dt_strtab_ptr = d_val_ptr
                elif d_tag == DT_SONAME:
                    dt_soname = d_val_ptr
            if dt_strtab_ptr:
                strsec, _offset = elffile.find_section_and_offset(dt_strtab_ptr)
                if strsec and strsec.sh_type == SHT_STRTAB:
                    for n in dt_needed:
                        end = n + strsec.table[n:].index("\0")
                        elffile.dt_needed.append(strsec.table[n:end])
                    for r in dt_rpath:
                        end = r + strsec.table[r:].index("\0")
                        path = strsec.table[r:end]
                        rpaths = [p for p in path.split(":") if path]
                        elffile.dt_rpath.extend([p.rstrip("/") for p in rpaths])
                    for r in dt_runpath:
                        end = r + strsec.table[r:].index("\0")
                        path = strsec.table[r:end]
                        rpaths = [p for p in path.split(":") if path]
                        elffile.dt_runpath.extend([p.rstrip("/") for p in rpaths])
                    if dt_soname != "$EXECUTABLE":
                        end = dt_soname + strsec.table[dt_soname:].index("\0")
                        elffile.dt_soname = strsec.table[dt_soname:end]

            # runpath always takes precedence.
            if len(elffile.dt_runpath):
                elffile.dt_rpath = []


class programheader:
    def __init__(self, eh, file):
        ptr_type = eh.ptr_type
        sz_ptr = eh.sz_ptr
        endian = eh.endian
        (self.p_type,) = struct.unpack(endian + "L", file.read(4))
        if eh.bitness == 64:
            (self.p_flags,) = struct.unpack(endian + "L", file.read(4))
        (self.p_offset,) = struct.unpack(endian + ptr_type, file.read(sz_ptr))
        (self.p_vaddr,) = struct.unpack(endian + ptr_type, file.read(sz_ptr))
        (self.p_paddr,) = struct.unpack(endian + ptr_type, file.read(sz_ptr))
        (self.p_filesz,) = struct.unpack(endian + ptr_type, file.read(sz_ptr))
        (self.p_memsz,) = struct.unpack(endian + ptr_type, file.read(sz_ptr))
        if eh.bitness == 32:
            (self.p_flags,) = struct.unpack(endian + "L", file.read(4))
        (self.p_align,) = struct.unpack(endian + ptr_type, file.read(sz_ptr))

    def postprocess(self, elffile, file):
        if self.p_type == PT_INTERP:
            file.seek(self.p_offset)
            elffile.program_interpreter = file.read(self.p_filesz - 1).decode()
        elif self.p_type == PT_LOAD:
            file.seek(self.p_offset)
            if hasattr(elffile, "ptload_p_vaddr"):
                elffile.ptload_p_vaddr.append(self.p_vaddr)
                elffile.ptload_p_paddr.append(self.p_paddr)
            else:
                elffile.ptload_p_vaddr = [self.p_vaddr]
                elffile.ptload_p_paddr = [self.p_paddr]


class elffile(UnixExecutable):
    def __init__(self, file, initial_rpaths_transitive=[]):
        self.ehdr = elfheader(file)
        self.dt_needed = []
        self.dt_rpath = []
        self.dt_runpath = []
        self.programheaders = []
        self.elfsections = []
        self.program_interpreter = None
        self.dt_soname = "$EXECUTABLE"
        self._dir = os.path.dirname(file.name)

        for n in range(self.ehdr.phnum):
            file.seek(self.ehdr.phoff + (n * self.ehdr.phentsize))
            self.programheaders.append(programheader(self.ehdr, file))
        for n in range(self.ehdr.shnum):
            file.seek(self.ehdr.shoff + (n * self.ehdr.shentsize))
            self.elfsections.append(elfsection(self.ehdr, file))
        self.elfsections.sort(key=lambda x: x.priority)
        for ph in self.programheaders:
            ph.postprocess(self, file)
        for es in self.elfsections:
            es.postprocess(self, file)

        # TODO :: If we have a program_interpreter we need to run it as:
        # TODO :: LD_DEBUG=all self.program_interpreter --inhibit-cache --list file.name
        # TODO :: then process the output line e.g.:
        # TODO :: search path=/usr/lib/tls/x86_64:/usr/lib/tls:/usr/lib/x86_64:/usr/lib          (system search path) # noqa
        # TODO :: .. and optionally add a sysroot prefix to each of those. This needs to work
        # TODO :: when run through QEMU also, so in that case,
        # TODO :: we must run os.path.join(sysroot,self.program_interpreter)
        # TODO :: Interesting stuff: https://www.cs.virginia.edu/~dww4s/articles/ld_linux.html

        dt_rpath = [p.rstrip("/") for p in self.dt_rpath]
        dt_runpath = [p.rstrip("/") for p in self.dt_runpath]
        self.rpaths_transitive = [
            self.from_os_varnames(rpath)
            for rpath in (initial_rpaths_transitive + dt_rpath)
        ]
        self.rpaths_nontransitive = [
            self.from_os_varnames(rpath) for rpath in dt_runpath
        ]
        # Lookup must be avoided when DT_NEEDED contains any '/'s
        self.shared_libraries = [
            (needed, needed if "/" in needed else "$RPATH/" + needed)
            for needed in self.dt_needed
        ]

    def to_os_varnames(self, input):
        if self.ehdr.sz_ptr == 8:
            libdir = "/lib64"
        else:
            libdir = "/lib"
        return input.replace("$SELFDIR", "$ORIGIN").replace(libdir, "$LIB")

    def from_os_varnames(self, input):
        if self.ehdr.sz_ptr == 8:
            libdir = "/lib64"
        else:
            libdir = "/lib"
        return input.replace("$ORIGIN", "$SELFDIR").replace("$LIB", libdir)

    def find_section_and_offset(self, addr):
        "Can be called immediately after the elfsections have been constructed"
        for es in self.elfsections:
            if addr >= es.sh_addr and addr < es.sh_addr + es.sh_size:
                # sections which do not appear in the memory image of the
                # process should be skipped
                if es.sh_addr == 0:
                    continue
                return es, addr - es.sh_addr
        return None, None

    def get_resolved_shared_libraries(self, src_exedir, src_selfdir, sysroot=""):
        result = []
        default_paths = ["$SYSROOT/lib", "$SYSROOT/usr/lib"]
        if self.ehdr.sz_ptr == 8:
            default_paths.extend(["$SYSROOT/lib64", "$SYSROOT/usr/lib64"])
        for so_orig, so in self.shared_libraries:
            resolved, rpath, in_sysroot = _get_resolved_location(
                self,
                so,
                src_exedir,
                src_selfdir,
                LD_LIBRARY_PATH="",
                default_paths=default_paths,
                sysroot=sysroot,
            )
            result.append((so_orig, resolved, rpath, in_sysroot))
        return result

    def get_dir(self):
        return self._dir

    def uniqueness_key(self):
        return self.dt_soname

    def get_soname(self):
        return self.dt_soname


class inscrutablefile(UnixExecutable):
    def __init__(self, file, initial_rpaths_transitive=[]):
        self._dir = None

    def get_rpaths_transitive(self):
        return []

    def get_resolved_shared_libraries(self, *args, **kw):
        return []

    def get_runpaths(self):
        return []

    def get_dir(self):
        return self._dir

    def uniqueness_key(self):
        return "unknown"


class DLLfile(UnixExecutable):
    def __init__(self, file, initial_rpaths_transitive=[]):
        pass

    def get_rpaths_transitive(self):
        return []

    def get_resolved_shared_libraries(self, *args, **kw):
        return []

    def get_runpaths(self):
        return []

    def get_dir(self):
        return None

    def uniqueness_key(self):
        return "unknown"


class EXEfile:
    def __init__(self, file, initial_rpaths_transitive=[]):
        self.super.__init__(self, file, initial_rpaths_transitive)


def codefile(file, arch="any", initial_rpaths_transitive=[]):
    if file.name.endswith(".dll"):
        return DLLfile(file, list(initial_rpaths_transitive))
    (magic,) = struct.unpack(BIG_ENDIAN + "L", file.read(4))
    file.seek(0)
    if magic in (FAT_MAGIC, MH_MAGIC, MH_CIGAM, MH_CIGAM_64):
        return machofile(file, arch, list(initial_rpaths_transitive))
    elif magic == ELF_HDR:
        return elffile(file, list(initial_rpaths_transitive))
    else:
        return inscrutablefile(file, list(initial_rpaths_transitive))


def codefile_class(filename, skip_symlinks=False):
    if os.path.islink(filename):
        if skip_symlinks:
            return None
        else:
            filename = os.path.realpath(filename)
    if os.path.isdir(filename):
        return None
    if filename.endswith((".dll", ".pyd")):
        return DLLfile
    if filename.endswith(".exe"):
        return EXEfile
    # Java .class files share 0xCAFEBABE with Mach-O FAT_MAGIC.
    if filename.endswith(".class"):
        return None
    if not os.path.exists(filename) or os.path.getsize(filename) < 4:
        return None
    with open(filename, "rb") as file:
        (magic,) = struct.unpack(BIG_ENDIAN + "L", file.read(4))
        file.seek(0)
        if magic in (FAT_MAGIC, MH_MAGIC, MH_CIGAM, MH_CIGAM_64):
            return machofile
        elif magic == ELF_HDR:
            return elffile
    return None


def is_codefile(filename, skip_symlinks=True):
    klass = codefile_class(filename, skip_symlinks=skip_symlinks)
    if not klass:
        return False
    return True


def codefile_type(filename, skip_symlinks=True):
    "Returns None, 'machofile' or 'elffile'"
    klass = codefile_class(filename, skip_symlinks=skip_symlinks)
    if not klass:
        return None
    return klass.__name__


def _trim_sysroot(sysroot):
    if sysroot:
        while sysroot.endswith("/") or sysroot.endswith("\\"):
            sysroot = sysroot[:-1]
    return sysroot


def _get_arch_if_native(arch):
    if arch == "native":
        if sys.platform == "win32":
            arch = "x86_64" if sys.maxsize > 2**32 else "i686"
        else:
            _, _, _, _, arch = os.uname()
    return arch


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
    arch = _get_arch_if_native(arch)
    with open(filename, "rb") as f:
        # TODO :: Problems here:
        # TODO :: 1. macOS can modify RPATH for children in each .so
        # TODO :: 2. Linux can identify the program interpreter which can change the default_paths
        try:
            cf = codefile(ReadCheckWrapper(f), arch)
        except IncompleteRead:
            # the file was incomplete, can occur if a package ships a test file
            # which looks like an ELF file but is not.  Orange3 does this.
            get_logger(__name__).warning(f"problems inspecting linkages for {filename}")
            return None, [], []
        dirname = os.path.dirname(filename)
        results = cf.get_resolved_shared_libraries(dirname, dirname, sysroot)
        if not results:
            return cf.uniqueness_key(), [], []
        orig_names, resolved_names, _, _in_sysroot = map(list, zip(*results))
        return cf.uniqueness_key(), orig_names, resolved_names


def inspect_rpaths(
    filename, resolve_dirnames=True, use_os_varnames=True, sysroot="", arch="native"
):
    if not os.path.exists(filename):
        return [], []
    sysroot = _trim_sysroot(sysroot)
    arch = _get_arch_if_native(arch)
    with open(filename, "rb") as f:
        # TODO :: Problems here:
        # TODO :: 1. macOS can modify RPATH for children in each .so
        # TODO :: 2. Linux can identify the program interpreter which can change the initial RPATHs
        # TODO :: Should '/lib', '/usr/lib' not include (or be?!) `sysroot`(s) instead?
        cf = codefile(f, arch, ["/lib", "/usr/lib"])
        if resolve_dirnames:
            return [
                _get_resolved_location(
                    cf,
                    rpath,
                    os.path.dirname(filename),
                    os.path.dirname(filename),
                    sysroot,
                )[0]
                for rpath in cf.rpaths_nontransitive
            ]
        else:
            if use_os_varnames:
                return [cf.to_os_varnames(rpath) for rpath in cf.rpaths_nontransitive]
            else:
                return cf.rpaths_nontransitive


def get_runpaths(filename, arch="native"):
    if not os.path.exists(filename):
        return []
    arch = _get_arch_if_native(arch)
    with open(filename, "rb") as f:
        cf = codefile(f, arch, ["/lib", "/usr/lib"])
        return cf.get_runpaths()


# TODO :: Consider returning a tree structure or a dict when recurse is True?
def inspect_linkages(
    filename, resolve_filenames=True, recurse=True, sysroot="", arch="native"
):
    already_seen = set()
    todo = {filename}
    done = set()
    results = {}
    while todo != done:
        filename = next(iter(todo - done))
        uniqueness_key, these_orig, these_resolved = _inspect_linkages_this(
            filename, sysroot=sysroot, arch=arch
        )
        if uniqueness_key not in already_seen:
            for orig, resolved in zip(these_orig, these_resolved):
                if resolve_filenames:
                    rec = {"orig": orig, "resolved": os.path.normpath(resolved)}
                else:
                    rec = {"orig": orig}
                results[orig] = rec
            if recurse:
                todo.update(these_resolved)
            already_seen.add(uniqueness_key)
        done.add(filename)
    return results


def inspect_linkages_otool(filename, arch="native"):
    from subprocess import check_output

    args = ["/usr/bin/otool"]
    if arch != "native":
        args.extend(["-arch", arch])
    else:
        # 'x86_64' if sys.maxsize > 2**32  else 'i386'
        args.extend(["-arch", os.uname()[4]])
    args.extend(["-L", filename])
    result = check_output(args).decode(encoding="ascii")
    groups = re.findall(r"^\t(.*) \(compatibility", result, re.MULTILINE)
    return groups


# TODO :: Consider allowing QEMU/binfmt_misc to run foreign binaries + passing a sysroot here?
def inspect_linkages_ldd(filename):
    from subprocess import PIPE, Popen

    process = Popen(["/usr/bin/ldd", filename], stdout=PIPE, stderr=PIPE)
    result, err = process.communicate()
    result = result.decode(encoding="ascii")
    err = err.decode(encoding="ascii")
    groups = re.findall(
        r"^\t(?!linux-gate\.so\.1.*$)[^ ]+ => (.*) \([0-9a-fx]+\)", result, re.MULTILINE
    )
    return groups


def otool(*args):
    parser = argparse.ArgumentParser(prog="otool", add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("-arch", dest="arch_type", help="arch_type", default="native")
    parser.add_argument("-L", dest="filename", help="print shared libraries used")
    args = parser.parse_args(args)
    if args.help:
        print(OTOOL_USAGE)
        return 0
    if args.filename:
        shared_libs = inspect_linkages(
            args.filename, resolve_filenames=False, recurse=False, arch=args.arch_type
        )
        print(
            "Shared libs used (non-recursively) by {} are:\n{}".format(
                args.filename, shared_libs
            )
        )
        return 0
    return 1


def otool_sys(*args):
    import subprocess

    result = subprocess.check_output("/usr/bin/otool", args).decode(encoding="ascii")
    return result


def ldd_sys(*args):
    result = []
    return result


def ldd(*args):
    parser = argparse.ArgumentParser(prog="ldd", add_help=False)
    parser.add_argument("-h", "--help", action="store_true")
    parser.add_argument("filename")
    args = parser.parse_args(args)
    if args.help:
        print(LDD_USAGE)
        return 0
    if args.filename:
        shared_libs = inspect_linkages(
            args.filename, resolve_filenames=False, recurse=True
        )
        print(
            "Shared libs used (recursively) by {} are:\n{}".format(
                args.filename, shared_libs
            )
        )
        return 0
    return 1


def main(argv):
    for idx, progname in enumerate(argv[0:2][::-1]):
        if re.match(r".*ldd(?:$|\.exe|\.py)", progname):
            return ldd(*argv[2 - idx :])
        elif re.match(r".*otool(?:$|\.exe|\.py)", progname):
            return otool(*argv[2 - idx :])
        elif os.path.isfile(progname):
            klass = codefile_class(progname)
            if not klass:
                return 1
            elif klass == elffile:
                return ldd(*argv[1 - idx :])
            elif klass == machofile:
                return otool("-L", *argv[1 - idx :])
    return 1


def main_maybe_test():
    if sys.argv[1] == "test":
        import functools

        tool = sys.argv[2]
        if tool != "otool" and tool != "ldd":
            if sys.platform == "darwin":
                tool = "otool"
            else:
                tool = "ldd"
        test_that = None
        sysroot_args = [
            re.match("--sysroot=([^ ]+)", arg)
            for arg in sys.argv
            if re.match("--sysroot=([^ ]+)", arg)
        ]
        if len(sysroot_args):
            (sysroot,) = sysroot_args[-1].groups(1)
            sysroot = os.path.expanduser(sysroot)
        else:
            sysroot = ""
        if tool == "otool":
            test_this = functools.partial(
                inspect_linkages,
                sysroot=sysroot,
                resolve_filenames=False,
                recurse=False,
            )
            if sys.platform == "darwin":
                test_that = functools.partial(inspect_linkages_otool)
            SOEXT = "dylib"
        elif tool == "ldd":
            test_this = functools.partial(
                inspect_linkages, sysroot=sysroot, resolve_filenames=True, recurse=True
            )
            if sys.platform.startswith("linux"):
                test_that = functools.partial(inspect_linkages_ldd)
            SOEXT = "so"
        # Find a load of dylibs or elfs and compare
        # the output against 'otool -L' or 'ldd'
        # codefiles = glob.glob('/usr/lib/*.'+SOEXT)
        codefiles = glob.glob(sysroot + "/usr/lib/*." + SOEXT)
        # codefiles = ['/usr/bin/file']
        # Sometimes files do not exist:
        # (/usr/lib/libgutenprint.2.dylib -> libgutenprint.2.0.3.dylib)
        codefiles = [
            codefile
            for codefile in codefiles
            if not os.path.islink(codefile) or os.path.exists(os.readlink(codefile))
        ]
        for codefile in codefiles:
            print(f"\nchecking {codefile}")
            this = test_this(codefile)
            if test_that:
                that = test_that(codefile)
            else:
                that = this
            print("\n".join(this))
            assert set(this) == set(
                that
            ), "py-ldd result incorrect for {}, this:\n{}\nvs that:\n{}".format(
                codefile, set(this), set(that)
            )
    else:
        return main(sys.argv)


if __name__ == "__main__":
    sys.exit(main_maybe_test())
