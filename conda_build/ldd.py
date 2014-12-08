from __future__ import absolute_import, division, print_function

import re
import subprocess
import json
from os.path import join

from conda.install import rm_rf
from conda.utils import memoized

from conda_build import post
from conda_build.config import config
from conda_build.build import create_env


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

@memoized
def get_package_linkages(dist, prefix):
    with open(join(prefix, 'conda-meta', dist +
        '.json')) as f:
        data = json.load(f)

    res = {}
    files = data['files']
    for f in files:
        path = join(prefix, f)
        if post.is_obj(path):
            res[f] = ldd(path)

    return res
