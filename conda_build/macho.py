from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import subprocess
from io import open
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


def is_macho(path):
    if path.endswith(NO_EXT) or islink(path) or not isfile(path):
        return False
    with open(path, 'rb') as fi:
        head = fi.read(4)
    return bool(head in MAGIC)


def otool(path):
    "thin wrapper around otool -L"
    lines = subprocess.check_output(['otool', '-L', path]).decode('utf-8').splitlines()
    assert lines[0].startswith(path), path
    res = []
    for line in lines[1:]:
        assert line[0] == '\t'
        res.append(line.split()[0])
    return res


def install_name_change(path, cb_func):
    """
    change dynamic shared library install names of Mach-O binary `path`.

    `cb_func` is a callback function which called for each shared library name.
    It is called with `path` and the current shared library install name,
    and return the new name (or None if the name should be unchanged).
    """
    changes = []
    for link in otool(path):
        new_link = cb_func(path, link)
        if new_link:
            changes.append((link, new_link))

    for old, new in changes:
        args = ['install_name_tool', '-change', old, new, path]
        print(' '.join(args))
        p = subprocess.Popen(args, stderr=subprocess.PIPE)
        stdout, stderr = p.communicate()
        if "Mach-O dynamic shared library stub file" in stderr:
            print("Skipping Mach-O dynamic shared library stub file %s" % path)
            pass
        else:
            print(stderr, file=sys.stderr)
        if p.returncode:
            raise RuntimeError("install_name_tool failed with exit status %d"
                % p.returncode)

if __name__ == '__main__':
    import sys
    if sys.platform == 'darwin':
        for path in '/bin/ls', '/etc/locate.rc':
            print(path, is_macho(path))
