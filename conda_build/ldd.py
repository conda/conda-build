from __future__ import absolute_import, division, print_function

import re
import subprocess

from conda_build import post

LDD_RE = re.compile(r'\s*(.*?)\s*=>\s*(.*?)\s*\(.*\)')
LDD_NOT_FOUND_RE = re.compile(r'\s*(.*?)\s*=>\s*not found')

def ldd(path):
    "thin wrapper around ldd"
    lines = subprocess.check_output(['ldd', path]).decode('utf-8').splitlines()
    res = []
    for line in lines:
        if '=>' not in line:
            continue

        assert line[0] == '\t', (path, line)
        m = LDD_RE.match(line)
        if m:
            res.append(m.groups())
            continue
        m = LDD_NOT_FOUND_RE.match(line)
        if m:
            res.append((m.group(1), 'not found'))
            continue
        if 'ld-linux' in line:
            continue
        raise RuntimeError("Unexpected output from ldd: %s" % line)

    return res
