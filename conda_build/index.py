'''
Functions related to creating repodata index files.
'''

from __future__ import absolute_import, division, print_function

import os
import bz2
import sys
import json
import tarfile
from os.path import isfile, join, getmtime

from conda_build.utils import file_info
from conda.compat import PY3
from conda.utils import md5_file


def read_index_tar(tar_path):
    """ Returns the index.json dict inside the given package tarball. """
    try:
        with tarfile.open(tar_path) as t:
            try:
                return json.loads(t.extractfile('info/index.json').read().decode('utf-8'))
            except EOFError:
                raise RuntimeError("Could not extract %s. File probably corrupt."
                    % tar_path)
            except OSError as e:
                raise RuntimeError("Could not extract %s (%s)" % (tar_path, e))
    except tarfile.ReadError:
        raise RuntimeError("Could not extract metadata from %s. File probably corrupt." % tar_path)

def write_repodata(repodata, dir_path):
    """ Write updated repodata.json and repodata.json.bz2 """
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

def update_index(dir_path, verbose=False, force=False, check_md5=False, remove=True):
    """
    Update all index files in dir_path with changed packages.

    :param verbose: Should detailed status messages be output?
    :type verbose: bool
    :param force: Whether to re-index all packages (including those that
                  haven't changed) or not.
    :type force: bool
    :param check_md5: Whether to check MD5s instead of mtimes for determining
                      if a package changed.
    :type check_md5: bool
    """
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
    if any(fn.startswith('_license-') for fn in files):
        sys.exit("""\
Error:
    Indexing a copy of the Anaconda conda package channel is neither
    necessary nor supported.  If you which to add your own packages,
    you can do so by adding them to a separate channel.
""")
    for fn in files:
        path = join(dir_path, fn)
        if fn in index:
            if check_md5:
                if index[fn]['md5'] == md5_file(path):
                    continue
            elif index[fn]['mtime'] == getmtime(path):
                continue
        if verbose:
            print('updating:', fn)
        d = read_index_tar(path)
        d.update(file_info(path))
        index[fn] = d

    for fn in files:
        index[fn]['sig'] = '.' if isfile(join(dir_path, fn + '.sig')) else None

    if remove:
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

        if 'requires' in info and 'depends' not in info:
            info['depends'] = info['requires']

    repodata = {'packages': index, 'info': {}}
    write_repodata(repodata, dir_path)
