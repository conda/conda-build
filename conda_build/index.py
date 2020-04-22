# -*- coding: utf-8 -*-
# Copyright (C) 2018 Anaconda, Inc
# SPDX-License-Identifier: Proprietary
from __future__ import absolute_import, division, print_function, unicode_literals

from base64 import urlsafe_b64encode
import bz2
from collections import OrderedDict
import copy
from datetime import datetime
from functools import partial
import json
import logging
from numbers import Number
import os
from os import lstat, utime
from os.path import abspath, basename, getmtime, getsize, isdir, isfile, join, dirname, lexists
import sys
import time
from uuid import uuid4

try:
    from os import scandir
except ImportError:
    from scandir import scandir

import pytz
from jinja2 import Environment, PackageLoader
from tqdm import tqdm
# import yaml
# from yaml.constructor import ConstructorError
# from yaml.parser import ParserError
# from yaml.scanner import ScannerError
# from yaml.reader import ReaderError

from ruamel_yaml import safe_load as yaml_safe_load
from ruamel_yaml.constructor import ConstructorError
from ruamel_yaml.parser import ParserError
from ruamel_yaml.scanner import ScannerError
from ruamel_yaml.reader import ReaderError

from cytoolz.itertoolz import concat, concatv, groupby

import conda_package_handling.api
from conda_package_handling.api import InvalidArchiveError

from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import Executor

#  BAD BAD BAD - conda internals
# Lots of conda internals here.  Should refactor to use exports.
from conda.common.compat import ensure_binary
from conda.core.subdir_data import SubdirData
from conda.models.channel import Channel

from . import conda_interface, utils
from .conda_interface import MatchSpec, VersionOrder, human_bytes, context, md5_file
from .conda_interface import CondaError, CondaHTTPError, get_index, url_path
from .conda_interface import TemporaryDirectory
from .conda_interface import Resolve
from .utils import get_logger, FileNotFoundError, JSONDecodeError, sha256_checksum, rm_rf

# try:
#     from conda.base.constants import CONDA_TARBALL_EXTENSIONS
# except Exception:
#     from conda.base.constants import CONDA_TARBALL_EXTENSION
#     CONDA_TARBALL_EXTENSIONS = (CONDA_TARBALL_EXTENSION,)

# TODO: better to define this in conda; doing it here because we're implementing it in conda-build first
CONDA_TARBALL_EXTENSIONS = ('.conda', '.tar.bz2')
UTC = pytz.timezone("UTC")

log = get_logger(__name__)


# use this for debugging, because ProcessPoolExecutor isn't pdb/ipdb friendly
class DummyExecutor(Executor):
    def map(self, func, *iterables):
        for iterable in iterables:
            for thing in iterable:
                yield func(thing)


try:
    from conda.base.constants import NAMESPACES_MAP, NAMESPACE_PACKAGE_NAMES
except ImportError:
    NAMESPACES_MAP = {  # base package name, namespace
        "python": "python",
        "r": "r",
        "r-base": "r",
        "mro-base": "r",
        "mro-base_impl": "r",
        "erlang": "erlang",
        "java": "java",
        "openjdk": "java",
        "julia": "julia",
        "latex": "latex",
        "lua": "lua",
        "nodejs": "js",
        "perl": "perl",
        "php": "php",
        "ruby": "ruby",
        "m2-base": "m2",
        "msys2-conda-epoch": "m2w64",
    }
    NAMESPACE_PACKAGE_NAMES = frozenset(NAMESPACES_MAP)
    NAMESPACES = frozenset(NAMESPACES_MAP.values())

local_index_timestamp = 0
cached_index = None
local_subdir = ""
cached_channels = []
channel_data = {}


# TODO: support for libarchive seems to have broken ability to use multiple threads here.
#    The new conda format is so much faster that it more than makes up for it.  However, it
#    would be nice to fix this at some point.
MAX_THREADS_DEFAULT = os.cpu_count() if (hasattr(os, "cpu_count") and os.cpu_count() > 1) else 1
if sys.platform == 'win32':  # see https://github.com/python/cpython/commit/8ea0fd85bc67438f679491fae29dfe0a3961900a
    MAX_THREADS_DEFAULT = min(48, MAX_THREADS_DEFAULT)
LOCK_TIMEOUT_SECS = 3 * 3600
LOCKFILE_NAME = ".lock"

# TODO: this is to make sure that the index doesn't leak tokens.  It breaks use of private channels, though.
# os.environ['CONDA_ADD_ANACONDA_TOKEN'] = "false"


def get_build_index(subdir, bldpkgs_dir, output_folder=None, clear_cache=False,
                    omit_defaults=False, channel_urls=None, debug=False, verbose=True,
                    **kwargs):
    global local_index_timestamp
    global local_subdir
    global cached_index
    global cached_channels
    global channel_data
    mtime = 0

    channel_urls = list(utils.ensure_list(channel_urls))

    if not output_folder:
        output_folder = dirname(bldpkgs_dir)

    # check file modification time - this is the age of our local index.
    index_file = os.path.join(output_folder, subdir, 'repodata.json')
    if os.path.isfile(index_file):
        mtime = os.path.getmtime(index_file)

    if (clear_cache or
            not os.path.isfile(index_file) or
            local_subdir != subdir or
            mtime > local_index_timestamp or
            cached_channels != channel_urls):

        # priority: (local as either croot or output_folder IF NOT EXPLICITLY IN CHANNEL ARGS),
        #     then channels passed as args (if local in this, it remains in same order),
        #     then channels from condarc.
        urls = list(channel_urls)

        loggers = utils.LoggingContext.default_loggers + [__name__]
        if debug:
            log_context = partial(utils.LoggingContext, logging.DEBUG, loggers=loggers)
        elif verbose:
            log_context = partial(utils.LoggingContext, logging.WARN, loggers=loggers)
        else:
            log_context = partial(utils.LoggingContext, logging.CRITICAL + 1, loggers=loggers)
        with log_context():
            # this is where we add the "local" channel.  It's a little smarter than conda, because
            #     conda does not know about our output_folder when it is not the default setting.
            if os.path.isdir(output_folder):
                local_path = url_path(output_folder)
                # replace local with the appropriate real channel.  Order is maintained.
                urls = [url if url != 'local' else local_path for url in urls]
                if local_path not in urls:
                    urls.insert(0, local_path)
            _ensure_valid_channel(output_folder, subdir)
            update_index(output_folder, verbose=debug)

            # replace noarch with native subdir - this ends up building an index with both the
            #      native content and the noarch content.

            if subdir == 'noarch':
                subdir = conda_interface.subdir
            try:
                cached_index = get_index(channel_urls=urls,
                                prepend=not omit_defaults,
                                use_local=False,
                                use_cache=context.offline,
                                platform=subdir)
            # HACK: defaults does not have the many subfolders we support.  Omit it and
            #          try again.
            except CondaHTTPError:
                if 'defaults' in urls:
                    urls.remove('defaults')
                cached_index = get_index(channel_urls=urls,
                                            prepend=omit_defaults,
                                            use_local=False,
                                            use_cache=context.offline,
                                            platform=subdir)

            expanded_channels = {rec.channel for rec in cached_index.values()}

            superchannel = {}
            # we need channeldata.json too, as it is a more reliable source of run_exports data
            for channel in expanded_channels:
                if channel.scheme == "file":
                    location = channel.location
                    if utils.on_win:
                        location = location.lstrip("/")
                    elif (not os.path.isabs(channel.location) and
                            os.path.exists(os.path.join(os.path.sep, channel.location))):
                        location = os.path.join(os.path.sep, channel.location)
                    channeldata_file = os.path.join(location, channel.name, 'channeldata.json')
                    retry = 0
                    max_retries = 1
                    if os.path.isfile(channeldata_file):
                        while retry < max_retries:
                            try:
                                with open(channeldata_file, "r+") as f:
                                    channel_data[channel.name] = json.load(f)
                                break
                            except (IOError, JSONDecodeError):
                                time.sleep(0.2)
                                retry += 1
                else:
                    # download channeldata.json for url
                    if not context.offline:
                        try:
                            channel_data[channel.name] = utils.download_channeldata(channel.base_url + '/channeldata.json')
                        except CondaHTTPError:
                            continue
                # collapse defaults metachannel back into one superchannel, merging channeldata
                if channel.base_url in context.default_channels and channel_data.get(channel.name):
                    packages = superchannel.get('packages', {})
                    packages.update(channel_data[channel.name])
                    superchannel['packages'] = packages
            channel_data['defaults'] = superchannel
        local_index_timestamp = os.path.getmtime(index_file)
        local_subdir = subdir
        cached_channels = channel_urls
    return cached_index, local_index_timestamp, channel_data


def _ensure_valid_channel(local_folder, subdir):
    for folder in {subdir, 'noarch'}:
        path = join(local_folder, folder)
        if not isdir(path):
            os.makedirs(path)


def update_index(dir_path, check_md5=False, channel_name=None, patch_generator=None, threads=MAX_THREADS_DEFAULT,
                 verbose=False, progress=False, hotfix_source_repo=None, subdirs=None, warn=True,
                 current_index_versions=None, debug=False):
    """
    If dir_path contains a directory named 'noarch', the path tree therein is treated
    as though it's a full channel, with a level of subdirs, each subdir having an update
    to repodata.json.  The full channel will also have a channeldata.json file.

    If dir_path does not contain a directory named 'noarch', but instead contains at least
    one '*.tar.bz2' file, the directory is assumed to be a standard subdir, and only repodata.json
    information will be updated.

    """
    base_path, dirname = os.path.split(dir_path)
    if dirname in utils.DEFAULT_SUBDIRS:
        if warn:
            log.warn("The update_index function has changed to index all subdirs at once.  You're pointing it at a single subdir.  "
                    "Please update your code to point it at the channel root, rather than a subdir.")
        return update_index(base_path, check_md5=check_md5, channel_name=channel_name,
                            threads=threads, verbose=verbose, progress=progress,
                            hotfix_source_repo=hotfix_source_repo,
                            current_index_versions=current_index_versions)
    return ChannelIndex(
        dir_path, channel_name, subdirs=subdirs, threads=threads, deep_integrity_check=check_md5, debug=debug
    ).index(
        patch_generator=patch_generator, verbose=verbose, progress=progress,
        hotfix_source_repo=hotfix_source_repo, current_index_versions=current_index_versions
    )


def _determine_namespace(info):
    if info.get('namespace'):
        namespace = info['namespace']
    else:
        depends_names = set()
        for spec in info.get('depends', []):
            try:
                depends_names.add(MatchSpec(spec).name)
            except CondaError:
                pass
        spaces = depends_names & NAMESPACE_PACKAGE_NAMES
        if len(spaces) == 1:
            namespace = NAMESPACES_MAP[spaces.pop()]
        else:
            namespace = "global"
        info['namespace'] = namespace

    if not info.get('namespace_in_name') and '-' in info['name']:
        namespace_prefix, reduced_name = info['name'].split('-', 1)
        if namespace_prefix == namespace:
            info['name_in_channel'] = info['name']
            info['name'] = reduced_name

    return namespace, info.get('name_in_channel', info['name']), info['name']


def _make_seconds(timestamp):
    timestamp = int(timestamp)
    if timestamp > 253402300799:  # 9999-12-31
        timestamp //= 1000  # convert milliseconds to seconds; see conda/conda-build#1988
    return timestamp


# ==========================================================================


REPODATA_VERSION = 1
CHANNELDATA_VERSION = 1
REPODATA_JSON_FN = 'repodata.json'
REPODATA_FROM_PKGS_JSON_FN = 'repodata_from_packages.json'
CHANNELDATA_FIELDS = frozenset((
    "description",
    "dev_url",
    "doc_url",
    "doc_source_url",
    "home",
    "license",
    "reference_package",
    "source_url",
    "source_git_url",
    "summary",
    "version",
    "timestamp",
    "spdx_license",
    "license_family",
    "subdirs",
    "icon_url",
    "icon_hash",  # "md5:abc123:12"
))
REPODATA_RECORD_FILTER_FIELDS = frozenset((
    'arch',
    'has_prefix',
    'mtime',
    'platform',
    'ucs',
    'requires_features',
    'binstar',
    'target-triplet',
    'machine',
    'operatingsystem',
))


def _load_json(path):
    try:
        with open(path) as fh:
            data = fh.read()
            if data:
                return json.loads(data)
    except EnvironmentError:
        return {}


def _clear_newline_chars(record, field_name):
    if field_name in record:
        try:
            record[field_name] = record[field_name].strip().replace('\n', ' ')
        except AttributeError:
            # sometimes description gets added as a list instead of just a string
            record[field_name] = record[field_name][0].strip().replace('\n', ' ')


def _apply_instructions(subdir, repodata, instructions):
    repodata.setdefault("removed", [])
    utils.merge_or_update_dict(repodata.get('packages', {}), instructions.get('packages', {}), merge=False,
                               add_missing_keys=False)
    # we could have totally separate instructions for .conda than .tar.bz2, but it's easier if we assume
    #    that a similarly-named .tar.bz2 file is the same content as .conda, and shares fixes
    new_pkg_fixes = {k.replace('.tar.bz2', '.conda'): v for k, v in instructions.get('packages', {}).items()}

    utils.merge_or_update_dict(repodata.get('packages.conda', {}), new_pkg_fixes, merge=False,
                               add_missing_keys=False)
    utils.merge_or_update_dict(repodata.get('packages.conda', {}), instructions.get('packages.conda', {}), merge=False,
                               add_missing_keys=False)

    for fn in instructions.get('revoke', ()):
        for key in ('packages', 'packages.conda'):
            if fn.endswith('.tar.bz2') and key == 'packages.conda':
                fn = fn.replace('.tar.bz2', '.conda')
            if fn in repodata[key]:
                repodata[key][fn]['revoked'] = True
                repodata[key][fn]['depends'].append('package_has_been_revoked')

    for fn in instructions.get('remove', ()):
        for key in ('packages', 'packages.conda'):
            if fn.endswith('.tar.bz2') and key == 'packages.conda':
                fn = fn.replace('.tar.bz2', '.conda')
            popped = repodata[key].pop(fn, None)
            if popped:
                repodata["removed"].append(fn)
    repodata["removed"].sort()

    return repodata


def _get_jinja2_environment():
    def _filter_strftime(dt, dt_format):
        if isinstance(dt, Number):
            if dt > 253402300799:  # 9999-12-31
                dt //= 1000  # convert milliseconds to seconds; see #1988
            dt = datetime.utcfromtimestamp(dt).replace(tzinfo=UTC)
        return dt.strftime(dt_format)

    def _filter_add_href(text, link, **kwargs):
        if link:
            kwargs_list = ['href="{0}"'.format(link)]
            kwargs_list.append('alt="{0}"'.format(text))
            kwargs_list += ['{0}="{1}"'.format(k, v) for k, v in kwargs.items()]
            return '<a {0}>{1}</a>'.format(' '.join(kwargs_list), text)
        else:
            return text

    environment = Environment(
        loader=PackageLoader('conda_build', 'templates'),
    )
    environment.filters['human_bytes'] = human_bytes
    environment.filters['strftime'] = _filter_strftime
    environment.filters['add_href'] = _filter_add_href
    environment.trim_blocks = True
    environment.lstrip_blocks = True

    return environment


def _maybe_write(path, content, write_newline_end=False, content_is_binary=False):
    # Create the temp file next "path" so that we can use an atomic move, see
    # https://github.com/conda/conda-build/issues/3833
    temp_path = '%s.%s' % (path, uuid4())

    if not content_is_binary:
        content = ensure_binary(content)
    with open(temp_path, 'wb') as fh:
        fh.write(content)
        if write_newline_end:
            fh.write(b'\n')
    if isfile(path):
        if utils.md5_file(temp_path) == utils.md5_file(path):
            # No need to change mtimes. The contents already match.
            os.unlink(temp_path)
            return False
    # log.info("writing %s", path)
    utils.move_with_fallback(temp_path, path)
    return True


def _make_subdir_index_html(channel_name, subdir, repodata_packages, extra_paths):
    environment = _get_jinja2_environment()
    template = environment.get_template('subdir-index.html.j2')
    rendered_html = template.render(
        title="%s/%s" % (channel_name or '', subdir),
        packages=repodata_packages,
        current_time=datetime.utcnow().replace(tzinfo=UTC),
        extra_paths=extra_paths,
    )
    return rendered_html


def _make_channeldata_index_html(channel_name, channeldata):
    environment = _get_jinja2_environment()
    template = environment.get_template('channeldata-index.html.j2')
    rendered_html = template.render(
        title=channel_name,
        packages=channeldata['packages'],
        subdirs=channeldata['subdirs'],
        current_time=datetime.utcnow().replace(tzinfo=UTC),
    )
    return rendered_html


def _get_resolve_object(subdir, file_path=None, precs=None, repodata=None):
    packages = {}
    conda_packages = {}
    if file_path:
        with open(file_path) as fi:
            packages = json.load(fi)
            recs = json.load(fi)
            for k, v in recs.items():
                if k.endswith('.tar.bz2'):
                    packages[k] = v
                elif k.endswith('.conda'):
                    conda_packages[k] = v
    if not repodata:
        repodata = {
            "info": {
                "subdir": subdir,
                "arch": context.arch_name,
                "platform": context.platform,
            },
            "packages": packages,
            "packages.conda": conda_packages,
        }

    channel = Channel('https://conda.anaconda.org/dummy-channel/%s' % subdir)
    sd = SubdirData(channel)
    sd._process_raw_repodata_str(json.dumps(repodata))
    sd._loaded = True
    SubdirData._cache_[channel.url(with_credentials=True)] = sd

    index = {prec: prec for prec in precs or sd._package_records}
    r = Resolve(index, channels=(channel,))
    return r


def _add_missing_deps(new_r, original_r):
    """For each package in new_r, if any deps are not satisfiable, backfill them from original_r."""

    expanded_groups = copy.deepcopy(new_r.groups)
    seen_specs = set()
    for g_name, g_recs in new_r.groups.items():
        for g_rec in g_recs:
            for dep_spec in g_rec.depends:
                if dep_spec in seen_specs:
                    continue
                ms = MatchSpec(dep_spec)
                if not new_r.find_matches(ms):
                    matches = original_r.find_matches(ms)
                    if matches:
                        version = matches[0].version
                        expanded_groups[ms.name] = (
                            set(expanded_groups.get(ms.name, [])) |
                            set(original_r.find_matches(MatchSpec('%s=%s' % (ms.name, version)))))
                seen_specs.add(dep_spec)
    return [pkg for group in expanded_groups.values() for pkg in group]


def _shard_newest_packages(subdir, r, pins=None):
    """Captures only the newest versions of software in the resolve object.

    For things where more than one version is supported simultaneously (like Python),
    pass pins as a dictionary, with the key being the package name, and the value being
    a list of supported versions.  For example:

    {'python': ["2.7", "3.6"]}
    """
    groups = {}
    pins = pins or {}
    for g_name, g_recs in r.groups.items():
        # always do the latest implicitly
        version = r.groups[g_name][0].version
        matches = set(r.find_matches(MatchSpec('%s=%s' % (g_name, version))))
        if g_name in pins:
            for pin_value in pins[g_name]:
                version = r.find_matches(MatchSpec('%s=%s' % (g_name, pin_value)))[0].version
                matches.update(r.find_matches(MatchSpec('%s=%s' % (g_name, version))))
        groups[g_name] = matches
    new_r = _get_resolve_object(subdir, precs=[pkg for group in groups.values() for pkg in group])
    return set(_add_missing_deps(new_r, r))


def _build_current_repodata(subdir, repodata, pins):
    r = _get_resolve_object(subdir, repodata=repodata)
    keep_pkgs = _shard_newest_packages(subdir, r, pins)
    keys = set(repodata.keys()) - {'packages', 'packages.conda'}
    new_repodata = {k: repodata[k] for k in keys}
    packages = {}
    conda_packages = {}
    for keep_pkg in keep_pkgs:
        if keep_pkg.fn.endswith('.conda'):
            conda_packages[keep_pkg.fn] = repodata['packages.conda'][keep_pkg.fn]
            # in order to prevent package churn we consider the md5 for the .tar.bz2 that matches the .conda file
            #    This holds when .conda files contain the same files as .tar.bz2, which is an assumption we'll make
            #    until it becomes more prevalent that people provide only .conda files and just skip .tar.bz2
            counterpart = keep_pkg.fn.replace('.conda', '.tar.bz2')
            conda_packages[keep_pkg.fn]['legacy_bz2_md5'] = repodata['packages'].get(counterpart, {}).get('md5')
        elif keep_pkg.fn.endswith('.tar.bz2'):
            packages[keep_pkg.fn] = repodata['packages'][keep_pkg.fn]
    new_repodata['packages'] = packages
    new_repodata['packages.conda'] = conda_packages
    return new_repodata


def json_dumps_compact(obj):
    return json.dumps(
        obj,
        ensure_ascii=False,
        indent=None,
        sort_keys=True,
        separators=(",", ":"),
        skipkeys=True,
    )


class ChannelIndex(object):

    def __init__(self, channel_root, channel_name, subdirs=None, threads=MAX_THREADS_DEFAULT,
                 deep_integrity_check=False, debug=False):
        self.packages_channel_root_path = abspath(channel_root)
        self.metadata_root_path = self.packages_channel_root_path
        # breaking out metadata_root_path allows writing metadata to a location different from where
        # packages reside

        self.channel_name = channel_name or basename(channel_root.rstrip('/'))
        self._subdirs = subdirs
        self.thread_executor = (DummyExecutor()
                                if(debug or sys.version_info.major == 2 or threads == 1)
                                else ProcessPoolExecutor(threads))
        self.deep_integrity_check = deep_integrity_check

    def index(self, patch_generator, hotfix_source_repo=None, verbose=False, progress=False,
              current_index_versions=None):
        if verbose:
            level = logging.DEBUG
        else:
            level = logging.ERROR

        with utils.LoggingContext(level, loggers=[__name__]):
            if not self._subdirs:
                detected_subdirs = set(subdir for subdir in os.listdir(self.packages_channel_root_path)
                                    if subdir in utils.DEFAULT_SUBDIRS and isdir(join(self.packages_channel_root_path, subdir)))
                log.debug("found subdirs %s" % detected_subdirs)
                self.subdirs = subdirs = sorted(detected_subdirs | {'noarch'})
            else:
                self.subdirs = subdirs = sorted(set(self._subdirs) | {'noarch'})

            # Step 1. Lock local channel.
            lock_paths = {self.packages_channel_root_path, self.metadata_root_path}
            with utils.try_acquire_locks([utils.get_lock(p) for p in lock_paths], timeout=900):
                # Step 2. Collect repodata from packages, save to pkg_repodata.json file
                repodatas = {}
                with tqdm(total=len(subdirs), disable=(verbose or not progress), leave=False) as t:
                    for subdir in subdirs:
                        t.set_description("Subdir: %s" % subdir)
                        t.update()
                        with tqdm(total=8, disable=(verbose or not progress), leave=False) as t2:
                            t2.set_description("Gathering repodata")
                            t2.update()
                            _ensure_valid_channel(self.metadata_root_path, subdir)
                            repodata_from_packages = self.index_subdir(
                                subdir, verbose=verbose, progress=progress
                            )

                            t2.set_description("Writing pre-patch repodata")
                            t2.update()
                            self._write_repodata(subdir, repodata_from_packages,
                                                REPODATA_FROM_PKGS_JSON_FN)

                            # Step 3. Apply patch instructions.
                            t2.set_description("Applying patch instructions")
                            t2.update()
                            patched_repodata, patch_instructions = self._patch_repodata(
                                subdir, repodata_from_packages, patch_generator)

                            # Step 4. Save patched and augmented repodata.
                            # If the contents of repodata have changed, write a new repodata.json file.
                            # Also create associated index.html.

                            t2.set_description("Writing patched repodata")
                            t2.update()
                            self._write_repodata(subdir, patched_repodata, REPODATA_JSON_FN)
                            t2.set_description("Building current_repodata subset")
                            t2.update()
                            current_repodata = _build_current_repodata(subdir, patched_repodata,
                                                                       pins=current_index_versions)
                            t2.set_description("Writing current_repodata subset")
                            t2.update()
                            self._write_repodata(subdir, current_repodata, json_filename="current_repodata.json")

                            t2.set_description("Writing subdir index HTML")
                            t2.update()
                            self._write_subdir_index_html(subdir, patched_repodata)

                            t2.set_description("Collecting channeldata packages")
                            t2.update()
                            repodatas[subdir] = patched_repodata

                # Step 6. Build channeldata.
                reference_packages = self._gather_channeldata_reference_packages(repodatas)
                channeldata = self._build_channeldata(subdirs, reference_packages)

                # Step 7. Create and write channeldata.
                self._write_channeldata_index_html(channeldata)
                self._write_channeldata(channeldata)

    def index_subdir(self, subdir, verbose=False, progress=False, deep_integrity_check=False):
        packages_subdir_path = join(self.packages_channel_root_path, subdir)
        repodata_from_packages_path = join(self.metadata_root_path, subdir, REPODATA_FROM_PKGS_JSON_FN)

        if verbose:
            log.info("Building repodata for %s" % packages_subdir_path)

        # gather conda package filenames in subdir
        # we'll process these first, because reading their metadata is much faster
        groups = groupby(lambda fn: fn[-6:], (entry.name for entry in scandir(packages_subdir_path)))
        conda_fns = set(groups.get(".conda", ()))
        tar_bz2_fns = set(groups.get("ar.bz2", ()))
        fns_in_subdir = conda_fns | tar_bz2_fns

        # # transmute doesn't seem to be working
        # make_conda_fns = set(fn[:-8] for fn in tar_bz2_fns) - set(fn[:-6] for fn in conda_fns)
        # desc = "create missing .conda files for %s" % subdir
        # num_make_conda_fns = len(make_conda_fns)
        # log.debug("transmuting total of %s .tar.bz2 packages", num_make_conda_fns)
        # for q, fn_base in enumerate(tqdm(sorted(make_conda_fns), desc=desc, disable=verbose or not progress)):
        #     # TODO: add fine-grained lock
        #     fn = fn_base + ".tar.bz2"
        #     log.debug("transmuting [%s/%s] %s/%s ", q+1, num_make_conda_fns, packages_subdir_path, fn)
        #     try:
        #         conda_package_handling.api.transmute(fn, ".conda", out_folder=packages_subdir_path)
        #     except:  # bare exception intentially used;
        #         log.exception("something happened")
        #         package_path = join(packages_subdir_path, fn_base) + ".conda"
        #         if lexists(package_path):
        #             os.unlink(package_path)
        #         raise

        # load current/old repodata
        if lexists(repodata_from_packages_path) and not self.deep_integrity_check:
            with open(repodata_from_packages_path) as fh:
                try:
                    old_repodata = json.load(fh) or {}
                except JSONDecodeError:
                    old_repodata = {}
        else:
            old_repodata = {}
        old_repodata_packages = old_repodata.get("packages", {})
        old_repodata_conda_packages = old_repodata.get("packages.conda", {})
        old_repodata_fns = set(old_repodata_packages) | set(old_repodata_conda_packages)

        # calculate all the paths and figure out what we're going to do with them
        # add_set: filenames that aren't in the current/old repodata, but exist in the subdir
        add_set = fns_in_subdir - old_repodata_fns
        remove_set = old_repodata_fns - fns_in_subdir
        all_removed = (old_repodata_fns | set(old_repodata.get('removed', ()))) - fns_in_subdir

        # update_set: Filenames that are in both old repodata and new repodata,
        #     and whose contents have changed based on file size or mtime. We're
        #     not using md5 here because it takes too long. If needing to do full md5 checks,
        #     use the --deep-integrity-check flag / self.deep_integrity_check option.
        candidate_fns = fns_in_subdir & old_repodata_fns
        update_set = self._calculate_update_set(
            self.packages_channel_root_path, subdir, candidate_fns, old_repodata,
        )
        # unchanged_set: packages in old repodata whose information can carry straight
        #     across to new repodata
        unchanged_set = candidate_fns - update_set

        log.debug(
            "found %s additions, %s updates, %s unchanged, %s removed",
            len(add_set), len(update_set), len(unchanged_set), len(remove_set)
        )

        new_repodata_packages = {
            k: v for k, v in old_repodata.get('packages', {}).items() if k in unchanged_set
        }
        new_repodata_conda_packages = {
            k: v for k, v in old_repodata.get('packages.conda', {}).items() if k in unchanged_set
        }

        # Invalidate cached files for update_set.
        # Extract and cache update_set and add_set, then add to new_repodata_packages.
        extract_fns = sorted(concatv(add_set, update_set))
        num_extract_fns = len(extract_fns)
        for q, fn in enumerate(tqdm(extract_fns, desc="extracting metadata", disable=verbose or not progress)):
            log.debug("extracting metadata [%s/%s] %s/%s", q + 1, num_extract_fns, subdir, fn)
            repodata_record = self.extract_metadata(
                self.packages_channel_root_path, self.metadata_root_path, subdir, fn, deep_integrity_check
            )
            if repodata_record is None:
                # extraction error
                pass
            elif fn[-6:] == ".conda":
                new_repodata_conda_packages[fn] = repodata_record
            elif fn[-8:] == ".tar.bz2":
                new_repodata_packages[fn] = repodata_record
            else:
                raise NotImplementedError("This should never happen.")

        new_repodata = {
            "$schema": "https://schemas.conda.io/repodata-1.schema.json",
            "repodata_version": REPODATA_VERSION,
            "info": {
                "subdir": subdir,
            },
            "packages": new_repodata_packages,
            "packages.conda": new_repodata_conda_packages,
            "removed": sorted(all_removed)
        }
        return new_repodata

    @staticmethod
    def _calculate_update_set(channel_root, subdir, candidate_fns, old_repodata):
        # Determine the packages that already exist in repodata, but need to be updated.
        # We're not using md5 here because it takes too long.

        def _get_repodata_record(fn):
            return old_repodata["packages.conda"][fn] if fn[-6:] == ".conda" else old_repodata["packages"][fn]

        subdir_path = join(channel_root, subdir)
        update_set = set()
        for fn in candidate_fns:
            repodata_record = _get_repodata_record(fn)
            st = lstat(join(subdir_path, fn))
            if _make_seconds(st.st_mtime) != repodata_record["timestamp"] or st.st_size != repodata_record["size"]:
                update_set.add(fn)
        return update_set

    @classmethod
    def extract_metadata(cls, channel_root, metadata_root_path, subdir, fn, deep_integrity_check=False):
        package_path = join(channel_root, subdir, fn)
        metadata_dir_path = join(metadata_root_path, subdir, ".cache", fn) + ".metadata"
        repodata_record_file = join(metadata_dir_path, "repodata_record.json")
        ext = ".conda" if fn[-6:] == ".conda" else ".tar.bz2"
        st = lstat(package_path)
        size = st.st_size

        # return early if the work is done
        sha256 = None  # saving one potential re-hash
        if lexists(repodata_record_file):
            with open(repodata_record_file) as fh:
                repodata_record = json.load(fh)
            return_early = repodata_record["size"] == size and repodata_record["timestamp"] == st.st_mtime
            if return_early and deep_integrity_check:
                sha256 = sha256_checksum(package_path)
                return_early = repodata_record["sha256"] == sha256
            if return_early:
                return repodata_record
            else:
                rm_rf(metadata_dir_path)

        # If this is a .tar.bz2 file, see if we can use the metadata from a sibling .conda file instead.
        # # allow .tar.bz2 files to use the .conda cache, but not vice-versa.
        # #    .conda readup is very fast (essentially free), but .conda files come from
        # #    converting .tar.bz2 files, which can go wrong.  Forcing extraction for
        # #    .conda files gives us a check on the validity of that conversion.
        if ext == ".tar.bz2":
            conda_package_path = package_path[:-8] + ".conda"
            if lexists(conda_package_path):
                extracted = cls._run_extraction(conda_package_path, metadata_dir_path)
            else:
                extracted = cls._run_extraction(package_path, metadata_dir_path)
        else:
            extracted = cls._run_extraction(package_path, metadata_dir_path)
        if not extracted:
            # returning None means we had an extraction error
            return None

        try:
            with open(join(metadata_dir_path, "info", "index.json")) as fh:
                repodata_record = json.load(fh)
        except FileNotFoundError:
            log.error("Corrupt package at %s", package_path)
            return None

        timestamp = _make_seconds(repodata_record.get("timestamp", st.st_mtime))
        sha256 = sha256 or sha256_checksum(package_path)
        md5 = md5_file(package_path)

        derived_fn = "{0}-{1}-{2}{3}".format(
            repodata_record["name"], repodata_record["version"], repodata_record["build"], ext
        )
        assert derived_fn == fn, (derived_fn, fn)
        derived_subdir = repodata_record.get("subdir")
        if derived_subdir and derived_subdir != subdir:
            log.warning("subdir mismatch in info/index.json (%s != %s) for %s", derived_subdir, subdir, package_path)
        repodata_record.update({
            "fn": fn,
            "md5": md5,
            "sha256": sha256,
            "size": size,
            "timestamp": timestamp,
            "subdir": subdir,
        })
        for field_name in REPODATA_RECORD_FILTER_FIELDS & set(repodata_record):
            del repodata_record[field_name]

        all_metadata = dict(repodata_record)
        recipe_obj = cls._cache_conda_recipe(metadata_dir_path)
        all_metadata.update(recipe_obj)
        icon_obj = all_metadata["icon"] = cls._cache_icon(metadata_dir_path, repodata_record, recipe_obj)
        if icon_obj:
            all_metadata["icon_hash"] = icon_obj["icon_hash"]
            all_metadata["icon_url"] = "icons/%s" % icon_obj["icon_fn"]
        all_metadata["run_exports"] = cls._cache_run_exports(metadata_dir_path)

        about_obj = cls._cache_about(metadata_dir_path)
        all_metadata.update(about_obj)
        # recipe_log_path = join(metadata_dir_path, "info", "recipe_log.json")  # it's info/recipe/recipe_log.txt
        # all_metadata["recipe_log"] = _load_json(recipe_log_path)

        with open(repodata_record_file, "w") as fh:
            fh.write(json_dumps_compact(repodata_record))
        utime(repodata_record_file, (timestamp, timestamp))
        utime(package_path, (timestamp, timestamp))

        all_metadata_path = join(metadata_dir_path, "all_metadata.json")
        with open(all_metadata_path, "w") as fh:
            fh.write(json_dumps_compact(all_metadata))
        utime(all_metadata_path, (timestamp, timestamp))

        return repodata_record

    @staticmethod
    def _run_extraction(package_path, metadata_dir_path):
        try:
            conda_package_handling.api.extract(package_path, dest_dir=metadata_dir_path, components="info")
            return True
        except (InvalidArchiveError, EnvironmentError) as e:
            log.exception(e)
            return False

    @staticmethod
    def _cache_conda_recipe(metadata_dir_path):
        recipe_path_search_order = (
            "info/recipe/meta.yaml.rendered",
            "info/recipe/meta.yaml",
            "info/meta.yaml",
        )
        recipe_path = next((p for p in recipe_path_search_order if lexists(join(metadata_dir_path, p))),
                           None)
        if recipe_path:
            with open(join(metadata_dir_path, recipe_path)) as fh:
                recipe_yaml_str = fh.read()
        else:  # pragma: no cover
            recipe_yaml_str = "{}"
        try:
            recipe_obj = yaml_safe_load(recipe_yaml_str)
        except (ConstructorError, ParserError, ScannerError, ReaderError):  # pragma: no cover
            recipe_obj = {}

        source = recipe_obj.get("source", {})
        try:
            recipe_obj.update({"source_" + k: v for k, v in source.items()})
        except AttributeError:  # pragma: no cover
            # sometimes source is a list instead of a dict
            recipe_obj.update({"source_" + k: v for k, v in source[0].items()})
        about = recipe_obj.get("about", {})
        _clear_newline_chars(about, "description")
        _clear_newline_chars(about, "summary")

        try:
            recipe_json_str = json_dumps_compact(recipe_obj)
        except TypeError:  # pragma: no cover
            recipe_obj.get('requirements', {}).pop('build', None)
            recipe_json_str = json_dumps_compact(recipe_obj)
        with open(join(metadata_dir_path, "recipe.json"), 'w') as fh:
            fh.write(recipe_json_str)
        return recipe_obj

    @staticmethod
    def _cache_icon(metadata_dir_path, repodata_record, recipe_obj):
        # If a conda package contains an icon, also extract and cache that in an .icon/
        # directory.  The icon file name is the name of the package, plus the extension
        # of the icon file as indicated by the meta.yaml `app/icon` key.
        # apparently right now conda-build renames all icons to 'icon.png'
        # What happens if it's an ico file, or a svg file, instead of a png? Not sure!
        icon_path = None
        app_icon_path = recipe_obj.get("app", {}).get("icon")
        if app_icon_path:
            test_path = join(metadata_dir_path, "info", "recipe", app_icon_path)
            if lexists(test_path):
                icon_path = test_path
        if not icon_path:
            test_path = join(metadata_dir_path, "info", "icon.png")
            if lexists(test_path):
                icon_path = test_path
        icon_json = {}
        if icon_path:
            icon_ext = icon_path.rsplit('.', 1)[-1]  # app_icon_path can be something other than .png
            channel_icon_fn = repodata_record["name"] + icon_ext
            icon_cache_path = join(metadata_dir_path, channel_icon_fn)
            with open(icon_path, "rb") as fh:
                icon_binary = fh.read()
            with open(icon_cache_path, "wb") as fh:
                fh.write(icon_binary)
            icon_base64 = urlsafe_b64encode(icon_binary)
            icon_md5 = md5_file(icon_cache_path)
            icon_sha256 = sha256_checksum(icon_cache_path)
            timestamp = repodata_record["timestamp"]
            utime(icon_cache_path, (timestamp, timestamp))
            st = lstat(icon_cache_path)
            icon_size = st.st_size
            icon_json = {
                "icon_fn": channel_icon_fn,
                "icon_sha256": icon_sha256,
                "icon_size": icon_size,
                "icon_md5": icon_md5,
                "icon_hash": "md5:%s:%s" % (icon_md5, icon_size),
                "icon_timestamp": timestamp,
                "icon_base64": icon_base64,
            }
            with open(join(metadata_dir_path, "icon.json"), "w") as fh:
                fh.write(json_dumps_compact(icon_json))
        return icon_json

    @staticmethod
    def _cache_run_exports(metadata_dir_path):
        run_exports = {}
        try:
            with open(join(metadata_dir_path, 'info', 'run_exports.json')) as fj:
                run_exports = json.load(fj)
        except EnvironmentError:
            try:
                with open(join(metadata_dir_path, 'info', 'run_exports.yaml')) as fh:
                    run_exports = yaml_safe_load(fh)
            except EnvironmentError:
                log.debug("%s has no run_exports file (this is OK)", metadata_dir_path)
        with open(join(metadata_dir_path, "run_exports.json"), "w") as fh:
            fh.write(json_dumps_compact(run_exports))
        return run_exports

    @staticmethod
    def _cache_about(metadata_dir_path):
        about_info_path = join(metadata_dir_path, "info", "about.json")
        about_obj = _load_json(about_info_path)
        _clear_newline_chars(about_obj, "description")
        _clear_newline_chars(about_obj, "summary")
        about_cache_path = join(metadata_dir_path, "about.json")
        with open(about_cache_path, "w") as fh:
            fh.write(json_dumps_compact(about_obj))
        return about_obj

    @staticmethod
    def load_all_metadata_from_cache(metadata_root_path, subdir, fn):
        all_metadata_path = join(metadata_root_path, subdir, ".cache", fn + ".metadata", "all_metadata.json")
        with open(all_metadata_path) as fh:
            return json.load(fh)

    def _write_repodata(self, subdir, repodata, json_filename):
        metadata_root_path = self.metadata_root_path
        repodata_json_path = join(metadata_root_path, subdir, json_filename)
        new_repodata_binary = json_dumps_compact(repodata).encode("utf-8")
        write_result = _maybe_write(repodata_json_path, new_repodata_binary, write_newline_end=True)
        if write_result:
            repodata_bz2_path = repodata_json_path + ".bz2"
            bz2_content = bz2.compress(new_repodata_binary)
            _maybe_write(repodata_bz2_path, bz2_content, content_is_binary=True)
        return write_result

    def _write_subdir_index_html(self, subdir, repodata):
        metadata_root_path = self.metadata_root_path
        repodata_packages = repodata["packages"]

        def _add_extra_path(extra_paths, path):
            if isfile(join(metadata_root_path, path)):
                extra_paths[basename(path)] = {
                    'size': getsize(path),
                    'timestamp': int(getmtime(path)),
                    'sha256': utils.sha256_checksum(path),
                    'md5': utils.md5_file(path),
                }

        extra_paths = OrderedDict()
        _add_extra_path(extra_paths, join(metadata_root_path, subdir, REPODATA_JSON_FN))
        _add_extra_path(extra_paths, join(metadata_root_path, subdir, REPODATA_JSON_FN + '.bz2'))
        _add_extra_path(extra_paths, join(metadata_root_path, subdir, REPODATA_FROM_PKGS_JSON_FN))
        _add_extra_path(extra_paths, join(metadata_root_path, subdir, REPODATA_FROM_PKGS_JSON_FN + '.bz2'))
        # _add_extra_path(extra_paths, join(metadata_root_path, subdir, "repodata2.json"))
        _add_extra_path(extra_paths, join(metadata_root_path, subdir, "patch_instructions.json"))
        rendered_html = _make_subdir_index_html(
            metadata_root_path, subdir, repodata_packages, extra_paths
        )
        index_path = join(metadata_root_path, subdir, 'index.html')
        return _maybe_write(index_path, rendered_html)

    def _write_channeldata_index_html(self, channeldata):
        metadata_root_path = self.metadata_root_path
        index_path = join(metadata_root_path, 'index.html')
        rendered_html = _make_channeldata_index_html(
            self.channel_name, channeldata
        )
        _maybe_write(index_path, rendered_html)

    @staticmethod
    def _gather_channeldata_reference_packages(repodatas):
        groups = groupby("name", concat(
            concatv(repodata["packages"].values(), repodata["packages.conda"].values()) for repodata in
            repodatas.values()))
        reference_packages = []
        for name, group in groups.items():
            version_groups = groupby("version", group)
            latest_version = sorted(version_groups, key=VersionOrder)[-1]
            build_number_groups = groupby("build_number", version_groups[latest_version])
            latest_build_number = sorted(build_number_groups)[-1]
            ref_pkg = sorted(build_number_groups[latest_build_number],
                             key=lambda x: (x["timestamp"], x["subdir"]))[-1].copy()
            ref_pkg["subdirs"] = sorted(set(rec['subdir'] for rec in group))
            ref_pkg["reference_package"] = "%s/%s" % (ref_pkg["subdir"], ref_pkg["fn"])
            reference_packages.append(ref_pkg)
        return reference_packages

    def _build_channeldata(self, subdirs, reference_packages):
        metadata_root_path = self.metadata_root_path
        _CHANNELDATA_FIELDS = CHANNELDATA_FIELDS
        package_data = {}
        for ref_pkg_rec in reference_packages:
            subdir, fn = ref_pkg_rec["subdir"], ref_pkg_rec["fn"]
            all_metadata = self.load_all_metadata_from_cache(metadata_root_path, subdir, fn)
            all_metadata.update(ref_pkg_rec)
            fields = set(all_metadata) & _CHANNELDATA_FIELDS
            package_data[ref_pkg_rec["name"]] = {k: all_metadata[k] for k in fields}
        channeldata = {
            "schema_version": CHANNELDATA_VERSION,
            "$schema": "https://schemas.conda.io/channeldata-1.schema.json",
            "subdirs": subdirs,
            "packages": package_data,
        }
        return channeldata

    def _write_channeldata(self, channeldata):
        metadata_root_path = self.metadata_root_path
        # trim out commits, as they can take up a ton of space.  They're really only for the RSS feed.
        for _pkg, pkg_dict in channeldata.get('packages', {}).items():
            if "commits" in pkg_dict:
                del pkg_dict['commits']
        channeldata_path = join(metadata_root_path, 'channeldata.json')
        content = json_dumps_compact(channeldata)
        _maybe_write(channeldata_path, content, True)

    def _load_patch_instructions_tarball(self, subdir, patch_generator):
        instructions = {}
        with TemporaryDirectory() as tmpdir:
            conda_package_handling.api.extract(patch_generator, dest_dir=tmpdir)
            instructions_file = os.path.join(tmpdir, subdir, "patch_instructions.json")
            if os.path.isfile(instructions_file):
                with open(instructions_file) as f:
                    instructions = json.load(f)
        return instructions

    def _create_patch_instructions(self, subdir, repodata, patch_generator=None):
        gen_patch_path = patch_generator or join(self.packages_channel_root_path, 'gen_patch.py')
        if isfile(gen_patch_path):
            log.debug("using patch generator %s for %s" % (gen_patch_path, subdir))

            # https://stackoverflow.com/a/41595552/2127762
            try:
                from importlib.util import spec_from_file_location, module_from_spec
                spec = spec_from_file_location('a_b', gen_patch_path)
                mod = module_from_spec(spec)

                spec.loader.exec_module(mod)
            # older pythons
            except ImportError:
                import imp
                mod = imp.load_source('a_b', gen_patch_path)

            instructions = mod._patch_repodata(repodata, subdir)

            if instructions.get('patch_instructions_version', 0) > 1:
                raise RuntimeError("Incompatible patch instructions version")

            return instructions
        else:
            if patch_generator:
                raise ValueError("Specified metadata patch file '{}' does not exist.  Please try an absolute "
                                 "path, or examine your relative path carefully with respect to your cwd."
                                 .format(patch_generator))
            return {}

    def _write_patch_instructions(self, subdir, instructions):
        metadata_root_path = self.metadata_root_path
        patch_instructions_path = join(metadata_root_path, subdir, 'patch_instructions.json')
        new_patch = json_dumps_compact(instructions)
        _maybe_write(patch_instructions_path, new_patch, True)

    def _load_instructions(self, subdir):
        patch_instructions_path = join(self.packages_channel_root_path, subdir, 'patch_instructions.json')
        if isfile(patch_instructions_path):
            log.debug("using patch instructions %s" % patch_instructions_path)
            with open(patch_instructions_path) as fh:
                instructions = json.load(fh)
                if instructions.get('patch_instructions_version', 0) > 1:
                    raise RuntimeError("Incompatible patch instructions version")
                return instructions
        return {}

    def _patch_repodata(self, subdir, repodata, patch_generator=None):
        if patch_generator and any(patch_generator.endswith(ext) for ext in CONDA_TARBALL_EXTENSIONS):
            instructions = self._load_patch_instructions_tarball(subdir, patch_generator)
        else:
            instructions = self._create_patch_instructions(subdir, repodata, patch_generator)
        if instructions:
            self._write_patch_instructions(subdir, instructions)
        else:
            instructions = self._load_instructions(subdir)
        if instructions.get('patch_instructions_version', 0) > 1:
            raise RuntimeError("Incompatible patch instructions version")

        return _apply_instructions(subdir, repodata, instructions), instructions
