'''
Functions related to creating repodata index files.
'''

from __future__ import absolute_import, division, print_function

import bz2
import contextlib
from datetime import datetime
from functools import partial
import json
import logging
from numbers import Number
import os
import tarfile
from os.path import isfile, join, getmtime, basename, getsize

from jinja2 import Environment, PackageLoader

from conda_build.utils import file_info, get_lock, try_acquire_locks
from conda_build import utils, conda_interface
from .conda_interface import PY3, md5_file, url_path, CondaHTTPError, get_index, human_bytes

local_index_timestamp = 0
cached_index = None
local_subdir = ""
cached_channels = []


def read_index_tar(tar_path, lock, locking=True, timeout=90):
    """ Returns the index.json dict inside the given package tarball. """
    locks = []
    if locking:
        locks = [lock]
    with try_acquire_locks(locks, timeout):
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


def write_repodata(repodata, dir_path, lock, locking=90, timeout=90):
    """ Write updated repodata.json and repodata.json.bz2 """
    locks = []
    if locking:
        locks = [lock]
    with try_acquire_locks(locks, timeout):
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


def update_index(dir_path, force=False, check_md5=False, remove=True, lock=None,
                 could_be_mirror=True, verbose=True, locking=True, timeout=90,
                 channel_name=None):
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
    if locking:
        locks.append(lock)

    index = {}

    with try_acquire_locks(locks, timeout):
        if not force:
            try:
                mode_dict = {'mode': 'r', 'encoding': 'utf-8'} if PY3 else {'mode': 'rb'}
                with open(index_path, **mode_dict) as fi:
                    index = json.load(fi)
            except (IOError, ValueError):
                index = {}

        files = set(fn for fn in os.listdir(dir_path) if fn.endswith('.tar.bz2'))
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
            d = read_index_tar(path, lock=lock, locking=locking, timeout=timeout)
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
            if 'timestamp' not in info and 'mtime' in info:
                info['timestamp'] = int(info['mtime'])
            if info['timestamp'] > 253402300799:  # 9999-12-31
                info['timestamp'] //= 1000  # convert milliseconds to seconds; see #1988
            for varname in 'arch', 'mtime', 'platform', 'ucs':
                try:
                    del info[varname]
                except KeyError:
                    pass

            if 'requires' in info and 'depends' not in info:
                info['depends'] = info['requires']

        repodata = {'packages': index, 'info': {}}
        write_repodata(repodata, dir_path, lock=lock, locking=locking, timeout=timeout)

        if channel_name:
            extra_paths = {}
            def add_extra_path(path):
                if isfile(path):
                    extra_paths[basename(path)] = {
                        'size': getsize(path),
                        'timestamp': int(getmtime(path)),
                        'md5': md5_file(path),
                    }
            add_extra_path(join(dir_path, 'repodata.json'))
            add_extra_path(join(dir_path, 'repodata.json.bz2'))
            rendered_html = make_index_html(channel_name, basename(dir_path), repodata, extra_paths)
            with open(join(dir_path, 'index.html'), 'w') as fh:
                fh.write(rendered_html)


def ensure_valid_channel(local_folder, subdir, verbose=True, locking=True, timeout=90):
    for folder in set((subdir, 'noarch')):
        path = os.path.join(local_folder, folder)
        if not os.path.isdir(path):
            os.makedirs(path)
        if not os.path.isfile(os.path.join(path, 'repodata.json')):
            update_index(path, verbose=verbose, locking=locking, timeout=timeout)


def get_build_index(subdir, bldpkgs_dir, output_folder=None, clear_cache=False,
                    omit_defaults=False, channel_urls=None, debug=False, verbose=True,
                    locking=True, timeout=90):
    global local_index_timestamp
    global local_subdir
    global cached_index
    global cached_channels
    log = utils.get_logger(__name__)
    mtime = 0

    channel_urls = list(utils.ensure_list(channel_urls))

    if not output_folder:
        output_folder = os.path.dirname(bldpkgs_dir)

    # check file modification time - this is the age of our index.
    index_file = os.path.join(output_folder, subdir, 'repodata.json')
    if os.path.isfile(index_file):
        mtime = os.path.getmtime(index_file)

    if (clear_cache or
            not os.path.isfile(index_file) or
            local_subdir != subdir or
            mtime > local_index_timestamp or
            cached_channels != channel_urls):

        log.debug("Building new index for subdir '{}' with channels {}, condarc channels "
                  "= {}".format(subdir, channel_urls, not omit_defaults))
        # priority: local by croot (can vary), then channels passed as args,
        #     then channels from config.
        capture = contextlib.contextmanager(lambda: (yield))
        if debug:
            log_context = partial(utils.LoggingContext, logging.DEBUG)
        elif verbose:
            log_context = partial(utils.LoggingContext, logging.WARN)
        else:
            log_context = partial(utils.LoggingContext, logging.CRITICAL + 1)
            capture = utils.capture

        urls = list(channel_urls)
        if os.path.isdir(output_folder):
            urls.insert(0, url_path(output_folder))
        ensure_valid_channel(output_folder, subdir, verbose=verbose, locking=locking,
                             timeout=timeout)

        # silence output from conda about fetching index files
        with log_context():
            with capture():
                # replace noarch with native subdir - this ends up building an index with both the
                #      native content and the noarch content.
                if subdir == 'noarch':
                    subdir = conda_interface.subdir
                try:
                    cached_index = get_index(channel_urls=urls,
                                    prepend=not omit_defaults,
                                    use_local=False,
                                    use_cache=False,
                                    platform=subdir)
                # HACK: defaults does not have the many subfolders we support.  Omit it and
                #          try again.
                except CondaHTTPError:
                    if 'defaults' in urls:
                        urls.remove('defaults')
                    cached_index = get_index(channel_urls=urls,
                                             prepend=omit_defaults,
                                             use_local=False,
                                             use_cache=False,
                                             platform=subdir)
        local_index_timestamp = os.path.getmtime(index_file)
        local_subdir = subdir
        cached_channels = channel_urls
    return cached_index, local_index_timestamp


def make_index_html(channel_name, subdir, repodata, extra_paths):
    def _filter_strftime(dt, dt_format):
        if isinstance(dt, Number):
            if dt > 253402300799:  # 9999-12-31
                dt //= 1000  # convert milliseconds to seconds; see #1988
            dt = datetime.utcfromtimestamp(dt)
        return dt.strftime(dt_format)

    environment = Environment(
        loader=PackageLoader('conda_build', 'templates'),
    )
    environment.filters['human_bytes'] = human_bytes
    environment.filters['strftime'] = _filter_strftime
    template = environment.get_template('subdir-index.html.j2')
    rendered_html = template.render(
        title="%s/%s" % (channel_name, subdir),
        packages=repodata['packages'],
        current_time=datetime.utcnow(),
        extra_paths=extra_paths,
    )
    return rendered_html


