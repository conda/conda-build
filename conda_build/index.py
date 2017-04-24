'''
Functions related to creating repodata index files.
'''

from __future__ import absolute_import, division, print_function

import bz2
from functools import partial
import json
import logging
import os
import sys
import tarfile
from os.path import isfile, join, getmtime

from conda_build.utils import file_info, get_lock, try_acquire_locks
from conda_build import utils, conda_interface
from .conda_interface import PY3, md5_file, url_path, CondaHTTPError, get_index

local_index_timestamp = 0
cached_index = None


def read_index_tar(tar_path, config, lock):
    """ Returns the index.json dict inside the given package tarball. """
    if config.locking:
        locks = [lock]
    with try_acquire_locks(locks, config.timeout):
        with tarfile.open(tar_path) as t:
            try:
                return json.loads(t.extractfile('info/index.json').read().decode('utf-8'))
            except EOFError:
                raise RuntimeError("Could not extract %s. File probably corrupt."
                    % tar_path)
            except OSError as e:
                raise RuntimeError("Could not extract %s (%s)" % (tar_path, e))
            except tarfile.ReadError:
                raise RuntimeError("Could not extract metadata from %s. "
                                "File probably corrupt." % tar_path)


def write_repodata(repodata, dir_path, lock, config=None):
    """ Write updated repodata.json and repodata.json.bz2 """
    if not config:
        import conda_build.config
        config = conda_build.config.config
    if config.locking:
        locks = [lock]
    with try_acquire_locks(locks, config.timeout):
        data = json.dumps(repodata, indent=2, sort_keys=True)
        # strip trailing whitespace
        data = '\n'.join(line.rstrip() for line in data.splitlines())
        # make sure we have newline at the end
        if not data.endswith('\n'):
            data += '\n'
        with open(join(dir_path, 'repodata.json'), 'w') as fo:
            fo.write(data)
        with open(join(dir_path, 'repodata.json.bz2'), 'wb') as fo:
            fo.write(bz2.compress(data.encode('utf-8')))


def update_index(dir_path, config, force=False, check_md5=False, remove=True, lock=None,
                 could_be_mirror=True):
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

    log = utils.get_logger(__name__)

    log.debug("updating index in: %s", dir_path)
    if not os.path.isdir(dir_path):
        os.makedirs(dir_path)

    index_path = join(dir_path, '.index.json')

    if not lock:
        lock = get_lock(dir_path)

    locks = []
    if config.locking:
        locks.append(lock)

    index = {}

    with try_acquire_locks(locks, config.timeout):
        if not force:
            try:
                mode_dict = {'mode': 'r', 'encoding': 'utf-8'} if PY3 else {'mode': 'rb'}
                with open(index_path, **mode_dict) as fi:
                    index = json.load(fi)
            except (IOError, ValueError):
                index = {}

        subdir = None

        files = set(fn for fn in os.listdir(dir_path) if fn.endswith('.tar.bz2'))
        if could_be_mirror and any(fn.startswith('_license-') for fn in files):
            sys.exit("""\
    Error:
        Indexing a copy of the Anaconda conda package channel is neither
        necessary nor supported.  If you wish to add your own packages,
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
            if config.verbose:
                print('updating:', fn)
            d = read_index_tar(path, config, lock=lock)
            d.update(file_info(path))
            index[fn] = d
            # there's only one subdir for a given folder, so only read these contents once
            if not subdir:
                subdir = d['subdir']

        for fn in files:
            index[fn]['sig'] = '.' if isfile(join(dir_path, fn + '.sig')) else None

        if remove:
            # remove files from the index which are not on disk
            for fn in set(index) - files:
                if config.verbose:
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
        write_repodata(repodata, dir_path, lock=lock, config=config)
        # subdir_index = CURRENT_INDEX.get(subdir, {})
        # subdir_index.update(index)


def ensure_valid_channel(local_folder, subdir, config):
    for folder in set((subdir, 'noarch')):
        path = os.path.join(local_folder, folder)
        if not os.path.isdir(path):
            os.makedirs(path)
        if not os.path.isfile(os.path.join(path, 'repodata.json')):
            update_index(path, config)


def get_build_index(config, subdir, clear_cache=False, omit_defaults=False):
    global local_index_timestamp
    global cached_index
    log = utils.get_logger(__name__)
    mtime = 0

    if config.output_folder:
        output_folder = config.output_folder
    else:
        output_folder = os.path.dirname(config.bldpkgs_dir)

    # check file modification time - this is the age of our index.
    index_file = os.path.join(output_folder, subdir, 'repodata.json')
    if os.path.isfile(index_file):
        mtime = os.path.getmtime(index_file)

    if not os.path.isfile(index_file) or mtime > local_index_timestamp:
        log.debug("Building new index for subdir '{}' with channels {}, condarc channels "
                  "= {}".format(subdir, config.channel_urls, not omit_defaults))
        # priority: local by croot (can vary), then channels passed as args,
        #     then channels from config.
        if config.debug:
            log_context = partial(utils.LoggingContext, logging.DEBUG)
        elif config.verbose:
            log_context = partial(utils.LoggingContext, logging.INFO)
        else:
            log_context = partial(utils.LoggingContext, logging.CRITICAL + 1)

        urls = list(config.channel_urls)
        if os.path.isdir(output_folder):
            urls.insert(0, url_path(output_folder))
        ensure_valid_channel(output_folder, subdir, config)

        # silence output from conda about fetching index files
        with log_context():
            with utils.capture():
                # replace noarch with native subdir - this ends up building an index with both the
                #      native content and the noarch content.
                if subdir == 'noarch':
                    subdir = conda_interface.subdir
                try:
                    cached_index = get_index(channel_urls=urls,
                                    prepend=not omit_defaults,
                                    use_local=True,
                                    use_cache=False,
                                    platform=subdir)
                # HACK: defaults does not have the many subfolders we support.  Omit it and
                #          try again.
                except CondaHTTPError:
                    if 'defaults' in urls:
                        urls.remove('defaults')
                    cached_index = get_index(channel_urls=urls,
                                             prepend=omit_defaults,
                                             use_local=True,
                                             use_cache=False,
                                             platform=subdir)
        local_index_timestamp = mtime
    return cached_index, local_index_timestamp
