'''
Functions related to creating repodata index files.
'''

from __future__ import absolute_import, division, print_function

import bz2
from collections import defaultdict
import contextlib
from datetime import datetime
from functools import partial
from glob import glob
import json
import logging
from numbers import Number
import os
from os.path import basename, dirname, getmtime, getsize, isdir, isfile, join
from shutil import copy2
import tarfile

from jinja2 import Environment, PackageLoader
import yaml

from . import conda_interface, utils
from .conda_interface import (CondaHTTPError, VersionOrder, get_index, human_bytes, md5_file,
                              url_path)
from .utils import file_info, get_lock, rm_rf, try_acquire_locks, get_logger

log = get_logger(__name__)

local_index_timestamp = 0
cached_index = None
local_subdir = ""
cached_channels = []


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
        _ensure_valid_channel(output_folder, subdir, verbose=verbose, locking=locking,
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


def _ensure_valid_channel(local_folder, subdir, verbose=True, locking=True, timeout=90):
    for folder in {subdir, 'noarch'}:
        path = os.path.join(local_folder, folder)
        if not os.path.isdir(path):
            os.makedirs(path)
        if not os.path.isfile(os.path.join(path, 'repodata.json')):
            update_index(path, verbose=verbose, locking=locking, timeout=timeout)


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
    base_subdirs = ('noarch', 'linux-64', 'linux-32', 'osx-64', 'win-64', 'win-32')
    is_channel = any(isdir(join(dir_path, base_subdir)) for base_subdir in base_subdirs)

    if is_channel:
        subdir_paths = tuple(path for path in (join(dir_path, fn) for fn in os.listdir(dir_path))
                             if isdir(path) and glob(join(path, '*.tar.bz2')))
    else:
        subdir_paths = (dir_path,)

    for subdir_path in subdir_paths:
        if len(subdir_paths) > 1:
            print('==> indexing: %s <==' % join(dir_path, subdir_path))
        update_subdir_index(subdir_path, force, check_md5, remove, lock,
                            could_be_mirror, verbose, locking, timeout,
                            channel_name)

    if is_channel:
        channeldata_path = join(dir_path, 'channeldata.json')
        print('==> building: %s <==' % channeldata_path)
        channeldata = _build_channeldata(dir_path, subdir_paths)
        with open(channeldata_path, 'w') as fh:
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
    paths_path = join(dir_path, '.paths.json')
    recipe_path = join(dir_path, '.recipe.json')

    if not lock:
        lock = get_lock(dir_path)

    locks = []
    if locking:
        locks.append(lock)

    index = {}
    about = {}
    paths = {}
    recipe = {}

    with try_acquire_locks(locks, timeout):
        if not force:

            def read_json_caching_file(path):
                if isfile(path):
                    with open(path) as fi:
                        return json.load(fi)
                else:
                    return {}
            index = read_json_caching_file(index_path)
            about = read_json_caching_file(about_path)
            paths = read_json_caching_file(paths_path)
            recipe = read_json_caching_file(recipe_path)

        files = tuple(basename(path) for path in glob(join(dir_path, '*.tar.bz2')))
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
            index_json, about_json, paths_json, recipe_json = _read_index_tar(
                path, lock=lock, locking=locking, timeout=timeout
            )
            index_json.update(file_info(path))
            index[fn] = index_json
            about[fn] = about_json
            paths[fn] = paths_json
            recipe[fn] = recipe_json

        if remove:
            # remove files from the index which are not on disk
            for fn in set(index) - set(files):
                if verbose:
                    print("removing:", fn)
                del index[fn]
        if not isdir(dirname(index_path)):
            os.makedirs(dirname(index_path))
        with open(index_path, 'w') as fo:
            json.dump(index, fo, indent=2, sort_keys=True)
        with open(about_path, 'w') as fo:
            json.dump(about, fo, indent=2, sort_keys=True)
        with open(paths_path, 'w') as fo:
            json.dump(paths, fo, indent=2, sort_keys=True)
        with open(recipe_path, 'w') as fo:
            json.dump(recipe, fo, indent=2, sort_keys=True)

        for fn in index:
            info = index[fn]
            if 'timestamp' not in info and 'mtime' in info:
                info['timestamp'] = int(info['mtime'])
            # keep timestamp in original format right now.  Pending further testing and eventual
            #       switch to standard UNIX timestamp (in sec)
            # if info['timestamp'] > 253402300799:  # 9999-12-31
            #     info['timestamp'] //= 1000  # convert milliseconds to seconds; see #1988
            for varname in 'arch', 'mtime', 'platform', 'ucs':
                info.pop(varname, None)

            # old repodata used to have a requires key rather than depends
            if 'requires' in info and 'depends' not in info:
                info['depends'] = info['requires']

        subdir = basename(dir_path)
        repodata = {
            'packages': index,
            'info': {
                'subdir': subdir,
            },
        }
        _write_repodata(repodata, dir_path, lock=lock, locking=locking, timeout=timeout)

        if channel_name:
            extra_paths = {}
            _add_extra_path(extra_paths, join(dir_path, 'repodata.json'))
            _add_extra_path(extra_paths, join(dir_path, 'repodata.json.bz2'))
            rendered_html = _make_subdir_index_html(channel_name, basename(dir_path),
                                                    repodata, extra_paths)
            with open(join(dir_path, 'index.html'), 'w') as fh:
                fh.write(rendered_html)


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
            except KeyError:
                about_json = {}

            try:
                paths_json = json.loads(t.extractfile('info/paths.json').read().decode('utf-8'))
            except KeyError:
                paths_json = {}

            try:
                recipe_text = t.extractfile('info/recipe/meta.yaml').read().decode('utf-8')
                recipe_json = yaml.load(recipe_text)
            except KeyError:
                recipe_json = {}

            # If a conda package contains an icon, also extract and cache that in an .icon/
            # directory.  The icon file name is the name of the package, plus the extension
            # of the icon file as indicated by the meta.yaml `app/icon` key.
            app_icon = recipe_json.get('app', {}).get('icon')
            if app_icon:
                icon_dir = join(dirname(tar_path), '.icons')
                if not isdir(icon_dir):
                    os.makedirs(icon_dir)

                # apparently right now conda-build renames all icons to 'icon.png'
                # What happens if it's an ico file, or a svg file, instead of a png? Not sure!
                # icondata = t.extractfile(app_icon).read()
                icondata = t.extractfile('info/icon.png').read()
                icon_filename = '.'.join((basename(tar_path), app_icon.rsplit('.')[-1]))
                with open(join(icon_dir, icon_filename), 'wb') as fh:
                    fh.write(icondata)

            return index_json, about_json, paths_json, recipe_json


def write_repodata(repodata, dir_path, lock, locking=90, timeout=90, **kw):
    """compatibility shim for conda-build-all"""
    log.warn("Using unsupported internal conda-build api (write_repodata).  Please update your "
             "code to use conda_build.api.update_index instead.")
    return _write_repodata(repodata, dir_path, lock, locking, timeout)


def _write_repodata(repodata, dir_path, lock, locking=90, timeout=90):
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


def _clear_newline_chars(record, field_name):
    if field_name in record:
        record[field_name] = record[field_name].strip().replace('\n', ' ')


def _build_channeldata(dir_path, subdir_paths):
    index_data = {}
    about_data = {}
    paths_data = {}
    recipe_data = {}
    for subdir_path in subdir_paths:
        with open(join(subdir_path, '.index.json')) as fh:
            index_data[basename(subdir_path)] = json.loads(fh.read())
        with open(join(subdir_path, '.about.json')) as fh:
            about_data[basename(subdir_path)] = json.loads(fh.read())
        with open(join(subdir_path, '.paths.json')) as fh:
            paths_data[basename(subdir_path)] = json.loads(fh.read())
        with open(join(subdir_path, '.recipe.json')) as fh:
            recipe_data[basename(subdir_path)] = json.loads(fh.read())

    subdir_names = tuple(sorted(index_data))

    package_groups = defaultdict(list)
    for subdir_path in index_data:
        subdir = basename(subdir_path)
        for fn, record in index_data[subdir_path].items():
            record['fn'] = fn
            if 'subdir' not in record:
                record['subdir'] = subdir
            record.update(about_data.get(subdir_path, {}).get(fn, {}))
            _source_section = recipe_data.get(subdir_path, {}).get(fn, {}).get('source', {})
            if isinstance(_source_section, (list, tuple)):
                _source_section = _source_section[0]
            for key in ('url', 'git_url', 'git_rev', 'git_tag'):
                value = _source_section.get(key)
                if value:
                    record['source_%s' % key] = value
            record['_has_icon'] = bool(
                recipe_data.get(subdir_path, {}).get(fn, {}).get('app', {}).get('icon')
            )
            package_groups[record['name']].append(record)

    FIELDS = (
        "description",
        "dev_url",
        "doc_url",
        "doc_source_url",
        "home",
        "license",
        "source_url",
        "source_git_url",
        "source_git_tag",
        "source_git_rev",
        "summary",
        "version",
        "subdirs",
        "icon_url",
        "icon_hash",  # "md5:abc123:12"
    )

    package_data = {}
    for name, package_group in package_groups.items():
        latest_version = sorted(
            package_group, key=lambda x: VersionOrder(x['version'])
        )[-1]['version']
        latest_version_records = tuple(rec for rec in package_group
                                       if rec['version'] == latest_version)
        best_record = sorted(latest_version_records, key=lambda x: x['build_number'])[-1]
        # Only subdirs that contain the latest version number are included here.
        # Build numbers are ignored for reporting which subdirs contain the latest version
        # of the package.
        subdirs = sorted(filter(None, set(rec.get('subdir') for rec in latest_version_records)))
        package_data[name] = {k: v for k, v in best_record.items() if k in FIELDS}
        package_data[name]["reference_package"] = "%s/%s" % (best_record['subdir'],
                                                             best_record['fn'])

        # recipe_data[best_record['subdir']][best_record['fn']]

        _clear_newline_chars(package_data[name], 'description')
        _clear_newline_chars(package_data[name], 'summary')
        package_data[name]['subdirs'] = subdirs

        if best_record['_has_icon']:
            icon_files = glob(join(dir_path, best_record['subdir'], '.icons',
                                   best_record['fn'] + '.*'))
            if icon_files:
                extracted_icon_path = join(dir_path, best_record['subdir'], '.icons',
                                           icon_files[0])
                icon_ext = extracted_icon_path.rsplit('.', 1)[-1]

                icon_md5 = md5_file(extracted_icon_path)
                icon_size = getsize(extracted_icon_path)

                artifact_icon_path = 'icons/%s.%s' % (best_record['name'], icon_ext)
                if not isdir(dirname(artifact_icon_path)):
                    os.makedirs(dirname(artifact_icon_path))
                if isfile(artifact_icon_path):
                    old_icon_md5 = md5_file(artifact_icon_path)
                    old_icon_size = getsize(artifact_icon_path)
                    if old_icon_md5 == icon_md5 and old_icon_size == icon_size:
                        rm_rf(artifact_icon_path)
                        copy2(extracted_icon_path, artifact_icon_path)
                else:
                    copy2(extracted_icon_path, artifact_icon_path)

                package_data[name]['icon_url'] = artifact_icon_path
                package_data[name]['icon_hash'] = "md5:%s:%s" % (icon_md5, icon_size)

    channeldata = {
        'channeldata_version': 1,
        'subdirs': subdir_names,
        'packages': package_data,
    }
    return channeldata


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
