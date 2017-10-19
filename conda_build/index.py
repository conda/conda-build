'''
Functions related to creating repodata index files.
'''

from __future__ import absolute_import, division, print_function

from collections import defaultdict
from conda_build.conda_interface import VersionOrder
from glob import glob

import bz2
import contextlib
from datetime import datetime
from functools import partial
import json
import logging
from numbers import Number
import os
import tarfile
from os.path import isfile, join, getmtime, basename, getsize, isdir

from jinja2 import Environment, PackageLoader
import yaml

from conda_build.utils import file_info, get_lock, try_acquire_locks
from conda_build import utils, conda_interface
from .conda_interface import PY3, md5_file, url_path, CondaHTTPError, get_index, human_bytes

log = logging.getLogger(__name__)

local_index_timestamp = 0
cached_index = None
local_subdir = ""
cached_channels = []


def _read_index_tar(tar_path, lock, locking=True, timeout=90):
    """ Returns the index.json dict inside the given package tarball. """
    locks = []
    if locking:
        locks = [lock]
    with try_acquire_locks(locks, timeout):
        with tarfile.open(tar_path) as t:
            try:
                index_json = json.loads(t.extractfile('info/index.json').read().decode('utf-8'))
            except EOFError:
                raise RuntimeError("Could not extract %s. File probably corrupt."
                    % tar_path)
            except OSError as e:
                raise RuntimeError("Could not extract %s (%s)" % (tar_path, e))
            except tarfile.ReadError:
                raise RuntimeError("Could not extract metadata from %s. "
                                "File probably corrupt." % tar_path)

            try:
                about_json = json.loads(t.extractfile('info/about.json').read().decode('utf-8'))
            except Exception as e:
                log.debug('%r', e, exc_info=True)
                about_json = {}

            try:
                recipe_json = yaml.load(t.extractfile('info/recipe/meta.yaml').read().decode('utf-8'))
            except Exception as e:
                log.debug('%r', e, exc_info=True)
                recipe_json = {}

            return index_json, about_json, recipe_json



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


def _add_extra_path(extra_paths, path):
    if isfile(path):
        extra_paths[basename(path)] = {
            'size': getsize(path),
            'timestamp': int(getmtime(path)),
            'md5': md5_file(path),
        }


def update_index(dir_path, force=False, check_md5=False, remove=True, lock=None,
                 could_be_mirror=True, verbose=True, locking=True, timeout=90,
                 channel_name=None):
    """
    If dir_path contains a directory named 'noarch', the path tree therein is treated
    as though it's a full channel, with a level of subdirs, each subdir having an update
    to repodata.json.  The full channel will also have a channeldata.json file.

    If dir_path does not contain a directory named 'noarch', but instead contains at least
    one '*.tar.bz2' file, the directory is assumed to be a standard subdir, and only repodata.json
    information will be updated.

    """
    is_channel = isdir(join(dir_path, 'noarch'))

    if is_channel:
        subdir_paths = tuple(path for path in (join(dir_path, fn) for fn in os.listdir(dir_path))
                             if isdir(path) and glob(join(path, '*.tar.bz2')))
    else:
        subdir_paths = (dir_path,)

    for subdir_path in subdir_paths:
        update_subdir_index(subdir_path, force, check_md5, remove, lock,
                            could_be_mirror, verbose, locking, timeout,
                            channel_name)

    if is_channel:
        _update_channeldata(dir_path, subdir_paths)

        if channel_name:
            pass


def _update_channeldata(dir_path, subdir_paths):
        index_data = {}
        about_data = {}
        recipe_data = {}
        for subdir_path in subdir_paths:
            with open(join(subdir_path, '.index.json')) as fh:
                index_data[basename(subdir_path)] = json.loads(fh.read())
            with open(join(subdir_path, '.about.json')) as fh:
                about_data[basename(subdir_path)] = json.loads(fh.read())
            with open(join(subdir_path, '.recipe.json')) as fh:
                recipe_data[basename(subdir_path)] = json.loads(fh.read())

        subdir_names = tuple(index_data)

        package_groups = defaultdict(list)
        for subdir_path in index_data:
            for fn, record in index_data[subdir_path].items():
                record.update(about_data.get(subdir_path, {}).get(fn, {}))
                _source_section = recipe_data.get(subdir_path, {}).get(fn, {}).get('source', {})
                for key in ('url', 'git_url', 'git_tag'):
                    value = _source_section.get(key)
                    if value:
                        record['source_%s' % key] = value
                package_groups[record['name']].append(record)

        FIELDS = (
            "description",
            "dev_url",
            "doc_url",
            "doc_source_url",
            "home",
            "license",
            "source_git_url",
            "summary",
            "version",
            "source_git_tag",
            "subdirs",

            "icon_url",
        )

        package_data = {}
        for name, package_group in package_groups.items():
            latest_version = sorted(package_group, key=lambda x: VersionOrder(x['version']))[-1]['version']
            best_record = sorted(
                (rec for rec in package_group if rec['version'] == latest_version),
                key=lambda x: x['build_number']
            )[-1]
            package_data[name] = {k: v for k, v in best_record.items() if k in FIELDS}

        channeldata = {
            'channeldata_version': 1,
            'subdirs': subdir_names,
            'packages': package_data,
        }
        with open(join(dir_path, 'channeldata.json'), 'w') as fh:
            fh.write(json.dumps(channeldata, indent=2, sort_keys=True, separators=(',', ': ')))


def update_subdir_index(dir_path, force=False, check_md5=False, remove=True, lock=None,
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
    about_path = join(dir_path, '.about.json')
    recipe_path = join(dir_path, '.recipe.json')

    if not lock:
        lock = get_lock(dir_path)

    locks = []
    if locking:
        locks.append(lock)

    index = {}
    about = {}
    recipe = {}

    with try_acquire_locks(locks, timeout):
        if not force:
            try:
                mode_dict = {'mode': 'r', 'encoding': 'utf-8'} if PY3 else {'mode': 'rb'}
                with open(index_path, **mode_dict) as fi:
                    index = json.load(fi)
            except (IOError, ValueError):
                index = {}

            try:
                mode_dict = {'mode': 'r', 'encoding': 'utf-8'} if PY3 else {'mode': 'rb'}
                with open(about_path, **mode_dict) as fi:
                    about = json.load(fi)
            except (IOError, ValueError):
                about = {}

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
            index_json, about_json, recipe_json = _read_index_tar(path, lock=lock, locking=locking, timeout=timeout)
            index_json.update(file_info(path))
            index[fn] = index_json
            about[fn] = about_json
            recipe[fn] = recipe_json

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
        with open(about_path, **mode_dict) as fo:
            json.dump(about, fo, indent=2, sort_keys=True, default=str)
        with open(recipe_path, **mode_dict) as fo:
            json.dump(recipe, fo, indent=2, sort_keys=True, default=str)

        # --- new repodata
        for fn in index:
            info = index[fn]
            if 'timestamp' not in info and 'mtime' in info:
                info['timestamp'] = int(info['mtime'])
            # keep timestamp in original format right now.  Pending further testing and eventual
            #       switch to standard UNIX timestamp (in sec)
            # if info['timestamp'] > 253402300799:  # 9999-12-31
            #     info['timestamp'] //= 1000  # convert milliseconds to seconds; see #1988
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
            _add_extra_path(extra_paths, join(dir_path, 'repodata.json'))
            _add_extra_path(extra_paths, join(dir_path, 'repodata.json.bz2'))
            rendered_html = _make_subdir_index_html(channel_name, basename(dir_path), repodata, extra_paths)
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


def _make_subdir_index_html(channel_name, subdir, repodata, extra_paths):
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
