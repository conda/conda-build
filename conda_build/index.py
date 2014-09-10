'''
Functions related to creating repodata index files.
'''

from __future__ import absolute_import, division, print_function

import os
import bz2
import json
import tarfile
from os.path import join, getmtime

from conda_build.utils import file_info
from conda.compat import PY3

def read_index_tar(tar_path):
    with tarfile.open(tar_path) as t:
        return json.loads(t.extractfile('info/index.json').read().decode('utf-8'))

def write_repodata(repodata, dir_path):
    data = json.dumps(repodata, indent=2, sort_keys=True)
    # strip trailing whitespace
    data = '\n'.join(line.rstrip() for line in data.split('\n'))
    # make sure we have newline at the end
    if not data.endswith('\n'):
        data += '\n'
    with open(join(dir_path, 'repodata.json'), 'w') as fo:
        fo.write(data)
    with open(join(dir_path, 'repodata.json.bz2'), 'wb') as fo:
        fo.write(bz2.compress(data.encode('utf-8')))

def update_index(dir_path, verbose=False, force=False):
    if verbose:
        print("updating index in:", dir_path)
    index_path = join(dir_path, '.index.json')
    if force:
        index = {}
    else:
        try:
            mode_dict = {'mode': 'r', 'encoding': 'utf-8'} if PY3 else {'mode': 'rb'}
            with open(index_path, **mode_dict) as fi:
                index = json.load(fi)
        except (IOError, ValueError):
            index = {}

    files = set(fn for fn in os.listdir(dir_path) if fn.endswith('.tar.bz2'))
    for fn in files:
        path = join(dir_path, fn)
        if fn in index and index[fn]['mtime'] == getmtime(path):
            continue
        if verbose:
            print('updating:', fn)
        d = read_index_tar(path)
        d.update(file_info(path))
        index[fn] = d

    # remove files from the index which are not on disk
    for fn in set(index) - files:
        if verbose:
            print("removing:", fn)
        del index[fn]
    # Deal with Python 2 and 3's different json module type reqs
    mode_dict = {'mode': 'w', 'encoding': 'utf-8'} if PY3 else {'mode': 'wb'}
    with open(index_path, **mode_dict) as fo:
        json.dump(index, fo, indent=2, sort_keys=True, default=str)

    # --- new repodata
    for fn in index:
        info = index[fn]
        for varname in 'arch', 'platform', 'mtime', 'ucs':
            try:
                del info[varname]
            except KeyError:
                pass

    repodata = {'packages': index, 'info': {}}
    write_repodata(repodata, dir_path)
