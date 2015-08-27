from __future__ import absolute_import, division, print_function

import sys
import subprocess
from os.path import islink, isfile

NO_EXT = (
    '.py', '.pyc', '.pyo', '.h', '.a', '.c', '.txt', '.html',
    '.xml', '.png', '.jpg', '.gif', '.class',
)

MAGIC = {
    b'\xca\xfe\xba\xbe': 'MachO-universal',
    b'\xce\xfa\xed\xfe': 'MachO-i386',
    b'\xcf\xfa\xed\xfe': 'MachO-x86_64',
    b'\xfe\xed\xfa\xce': 'MachO-ppc',
    b'\xfe\xed\xfa\xcf': 'MachO-ppc64',
}

FILETYPE = {
    1: 'MH_OBJECT',
    2: 'MH_EXECUTE',
    3: 'MH_FVMLIB',
    4: 'MH_CORE',
    5: 'MH_PRELOAD',
    6: 'MH_DYLIB',
    7: 'MH_DYLINKER',
    8: 'MH_BUNDLE',
    9: 'MH_DYLIB_STUB',
    10: 'MH_DSYM',
    11: 'MH_KEXT_BUNDLE',
}


def is_macho(path):
    if path.endswith(NO_EXT) or islink(path) or not isfile(path):
        return False
    with open(path, 'rb') as fi:
        head = fi.read(4)
    return bool(head in MAGIC)


def is_dylib(path):
    return human_filetype(path) == 'DYLIB'

def human_filetype(path):
    lines = subprocess.check_output(['otool', '-h', path]).decode('utf-8').splitlines()
    assert lines[0].startswith(path), path

    for line in lines:
        if line.strip().startswith('0x'):
            header = line.split()
            filetype = int(header[4])
            return FILETYPE[filetype][3:]

def otool(path):
    "thin wrapper around otool -L"
    lines = subprocess.check_output(['otool', '-L', path]).decode('utf-8').splitlines()
    assert lines[0].startswith(path), path
    res = []
    for line in lines[1:]:
        assert line[0] == '\t', path
        res.append(line.split()[0])
    return res

def get_rpaths(path):
    lines = subprocess.check_output(['otool', '-l',
        path]).decode('utf-8').splitlines()
    check_for_rpath = False
    rpaths = []
    for line in lines:
        if 'cmd LC_RPATH' in line:
            check_for_rpath = True
        if check_for_rpath and 'path' in line:
            _, rpath, _ = line.split(None, 2)
            rpaths.append(rpath)
    return rpaths

def install_name_change(path, cb_func):
    """
    change dynamic shared library install names of Mach-O binary `path`.

    `cb_func` is a callback function which called for each shared library name.
    It is called with `path` and the current shared library install name,
    and return the new name (or None if the name should be unchanged).
    """
    changes = []
    for link in otool(path):
        # The first link may be the install name of the library itself, but
        # this isn't a big deal because install_name_tool -change is a no-op
        # if given a dependent install name that doesn't exist.
        new_link = cb_func(path, link)
        if new_link:
            changes.append((link, new_link))

    ret = True
    for old, new in changes:
        args = ['install_name_tool', '-change', old, new, path]
        print(' '.join(args))
        p = subprocess.Popen(args, stderr=subprocess.PIPE)
        stdout, stderr = p.communicate()
        stderr = stderr.decode('utf-8')
        if "Mach-O dynamic shared library stub file" in stderr:
            print("Skipping Mach-O dynamic shared library stub file %s" % path)
            ret = False
            continue
        else:
            print(stderr, file=sys.stderr)
        if p.returncode:
            raise RuntimeError("install_name_tool failed with exit status %d"
                % p.returncode)
    return ret

if __name__ == '__main__':
    if sys.platform == 'darwin':
        for path in '/bin/ls', '/etc/locate.rc':
            print(path, is_macho(path))
