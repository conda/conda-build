# -*- coding: utf-8 -*-
# Copyright (C) 2018 Anaconda, Inc
# SPDX-License-Identifier: Proprietary
from __future__ import absolute_import, division, print_function, unicode_literals

import bz2
from collections import OrderedDict, defaultdict
from datetime import datetime

import json
from numbers import Number
import os
from os.path import abspath, basename, getmtime, getsize, isdir, isfile, join, lexists, splitext, dirname
from shutil import copy2, move
import subprocess
import tarfile
from tempfile import gettempdir
import time
from uuid import uuid4

# Lots of conda internals here.  Should refactor to use exports.
from conda.common.compat import ensure_binary
# from conda.resolve import dashlist

import pytz
from jinja2 import Environment, PackageLoader
from tqdm import tqdm
import yaml
from yaml.constructor import ConstructorError
from yaml.parser import ParserError
from yaml.scanner import ScannerError

import contextlib
import fnmatch
from functools import partial
import logging
import libarchive
import conda_package_handling.api


from . import conda_interface, utils
from .conda_interface import MatchSpec, VersionOrder, human_bytes, context
from .conda_interface import CondaError, CondaHTTPError, get_index, url_path
from .conda_interface import download, TemporaryDirectory
from .utils import glob, get_logger, FileNotFoundError, PermissionError

# try:
#     from conda.base.constants import CONDA_TARBALL_EXTENSIONS
# except Exception:
#     from conda.base.constants import CONDA_TARBALL_EXTENSION
#     CONDA_TARBALL_EXTENSIONS = (CONDA_TARBALL_EXTENSION,)

# TODO: better to define this in conda; doing it here because we're implementing it in conda-build first
CONDA_TARBALL_EXTENSIONS = ('.conda', '.tar.bz2')

try:
    from json.decoder import JSONDecodeError
except ImportError:
    JSONDecodeError = ValueError


log = get_logger(__name__)

try:
    from conda.common.io import ThreadLimitedThreadPoolExecutor, as_completed
except ImportError:
    from concurrent.futures import ThreadPoolExecutor, _base, as_completed
    from concurrent.futures.thread import _WorkItem

    class ThreadLimitedThreadPoolExecutor(ThreadPoolExecutor):

        def __init__(self, max_workers=10):
            super(ThreadLimitedThreadPoolExecutor, self).__init__(max_workers)

        def submit(self, fn, *args, **kwargs):
            """
            This is an exact reimplementation of the `submit()` method on the parent class, except
            with an added `try/except` around `self._adjust_thread_count()`.  So long as there is at
            least one living thread, this thread pool will not throw an exception if threads cannot
            be expanded to `max_workers`.

            In the implementation, we use "protected" attributes from concurrent.futures (`_base`
            and `_WorkItem`). Consider vendoring the whole concurrent.futures library
            as an alternative to these protected imports.

            https://github.com/agronholm/pythonfutures/blob/3.2.0/concurrent/futures/thread.py#L121-L131  # NOQA
            https://github.com/python/cpython/blob/v3.6.4/Lib/concurrent/futures/thread.py#L114-L124
            """
            with self._shutdown_lock:
                if self._shutdown:
                    raise RuntimeError('cannot schedule new futures after shutdown')

                f = _base.Future()
                w = _WorkItem(f, fn, args, kwargs)

                self._work_queue.put(w)
                try:
                    self._adjust_thread_count()
                except RuntimeError:
                    # RuntimeError: can't start new thread
                    # See https://github.com/conda/conda/issues/6624
                    if len(self._threads) > 0:
                        # It's ok to not be able to start new threads if we already have at least
                        # one thread alive.
                        pass
                    else:
                        raise
                return f

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
MAX_THREADS_DEFAULT = 1  # os.cpu_count() if (hasattr(os, "cpu_count") and os.cpu_count() > 1) else 1
LOCK_TIMEOUT_SECS = 3 * 3600
LOCKFILE_NAME = ".lock"
DEFAULT_SUBDIRS = (
    "linux-64",
    "linux-32",
    "linux-ppc64le",
    "linux-armv6l",
    "linux-armv7l",
    "linux-aarch64",
    "win-64",
    "win-32",
    "osx-64",
    "zos-z",
    "noarch",
)

# TODO: this is to make sure that the index doesn't leak tokens.  It breaks use of private channels, though.
# os.environ['CONDA_ADD_ANACONDA_TOKEN'] = "false"


try:
    from cytoolz.itertoolz import concat, concatv, groupby
except ImportError:  # pragma: no cover
    from conda._vendor.toolz.itertoolz import concat, concatv, groupby  # NOQA


def _download_channeldata(channel_url):
    with TemporaryDirectory() as td:
        tf = os.path.join(td, "channeldata.json")
        download(channel_url, tf)
        try:
            with open(tf) as f:
                data = json.load(f)
        except JSONDecodeError:
            data = {}
    return data


def get_build_index(subdir, bldpkgs_dir, output_folder=None, clear_cache=False,
                    omit_defaults=False, channel_urls=None, debug=False, verbose=True,
                    shared_format_cache=True, **kwargs):
    global local_index_timestamp
    global local_subdir
    global cached_index
    global cached_channels
    global channel_data
    mtime = 0

    channel_urls = list(utils.ensure_list(channel_urls))

    if not output_folder:
        output_folder = dirname(bldpkgs_dir)

    # check file modification time - this is the age of our index.
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
            capture = utils.capture
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
            update_index(output_folder, verbose=debug, shared_format_cache=shared_format_cache)

            # silence output from conda about fetching index files
            capture = contextlib.contextmanager(lambda: (yield))

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
                    max_retries = 10
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
                            channel_data[channel.name] = _download_channeldata(channel.base_url + '/channeldata.json')
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
        path = os.path.join(local_folder, folder)
        if not os.path.isdir(path):
            os.makedirs(path)


def update_index(dir_path, check_md5=False, channel_name=None, patch_generator=None, threads=MAX_THREADS_DEFAULT,
                 verbose=False, progress=False, hotfix_source_repo=None, subdirs=None, warn=True, shared_format_cache=True):
    """
    If dir_path contains a directory named 'noarch', the path tree therein is treated
    as though it's a full channel, with a level of subdirs, each subdir having an update
    to repodata.json.  The full channel will also have a channeldata.json file.

    If dir_path does not contain a directory named 'noarch', but instead contains at least
    one '*.tar.bz2' file, the directory is assumed to be a standard subdir, and only repodata.json
    information will be updated.

    """
    base_path, dirname = os.path.split(dir_path)
    if dirname in DEFAULT_SUBDIRS:
        if warn:
            log.warn("The update_index function has changed to index all subdirs at once.  You're pointing it at a single subdir.  "
                    "Please update your code to point it at the channel root, rather than a subdir.")
        return update_index(base_path, check_md5=check_md5, channel_name=channel_name,
                            threads=threads, verbose=verbose, progress=progress,
                            hotfix_source_repo=hotfix_source_repo, shared_format_cache=shared_format_cache)
    return ChannelIndex(dir_path, channel_name, subdirs=subdirs, threads=threads,
                        deep_integrity_check=check_md5).index(patch_generator=patch_generator, verbose=verbose,
                                                              progress=progress,
                                                              hotfix_source_repo=hotfix_source_repo,
                                                              shared_format_cache=shared_format_cache)


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
CHANNELDATA_FIELDS = (
    "description",
    "dev_url",
    "doc_url",
    "doc_source_url",
    "home",
    "license",
    "reference_package",
    "source_url",
    "source_git_url",
    "source_git_tag",
    "source_git_rev",
    "summary",
    "version",
    "subdirs",
    "icon_url",
    "icon_hash",  # "md5:abc123:12"
    "run_exports",
    "binary_prefix",
    "text_prefix",
    "activate.d",
    "deactivate.d",
    "pre_link",
    "post_link",
    "pre_unlink",
    "tags",
    "identifiers",
    "keywords",
    "recipe_origin",
    "commits",
)


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

    for fn in instructions.get('revoke', ()):
        repodata['packages'][fn]['revoked'] = True
        repodata['packages'][fn]['depends'].append('package_has_been_revoked')

    for fn in instructions.get('remove', ()):
        popped = repodata['packages'].pop(fn, None)
        if popped:
            repodata["removed"].append(fn)
    repodata["removed"].sort()

    return repodata


def _get_jinja2_environment():
    def _filter_strftime(dt, dt_format):
        if isinstance(dt, Number):
            if dt > 253402300799:  # 9999-12-31
                dt //= 1000  # convert milliseconds to seconds; see #1988
            dt = datetime.utcfromtimestamp(dt).replace(tzinfo=pytz.timezone("UTC"))
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
    temp_path = join(gettempdir(), str(uuid4()))

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
    try:
        move(temp_path, path)
    except PermissionError:
        utils.copy_into(temp_path, path)
        os.unlink(temp_path)
    return True


def _gather_channeldata_reference_packages(all_repodata_packages):
    groups = groupby('name', all_repodata_packages)
    reference_packages = []
    for group in groups.values():
        try:
            version_groups = groupby('version', group)
            latest_version = sorted(version_groups, key=VersionOrder)[-1]
            build_number_groups = groupby('build_number', version_groups[latest_version])
            latest_build_number = sorted(build_number_groups)[-1]
            ref_pkg = sorted(build_number_groups[latest_build_number],
                                key=lambda x: x['subdir'])[-1]
            ref_pkg["subdirs"] = sorted(set(rec['subdir'] for rec in group))
            ref_pkg["reference_package"] = "%s/%s" % (ref_pkg["subdir"], ref_pkg["fn"])
            reference_packages.append(ref_pkg)
        except KeyError as e:
            log.warn("group {} failed to gather channeldata.  Error was {}.  Skipping this one...".format(group, e))
    return reference_packages


def _collect_namemap(subdirs, patched_repodata, patch_instructions):
    external_dependencies = {
        name_in_channel: namekey
        for pi in patch_instructions.values()
        for name_in_channel, namekey in pi.get('external_dependencies', {}).items()
    }
    namemap = {}  # name_in_channel, cuid_namekey
    namemap.update(external_dependencies)

    ambiguous_namekeys = defaultdict(set)  # name, namekey
    for subdir in subdirs:
        repodata = patched_repodata[subdir]
        for info in repodata['packages'].values():
            namespace, name_in_channel, name = _determine_namespace(info)
            namekey = namespace + ":" + name
            # TODO: this name_in_channel thing should be dropped if the package has an explicitly assigned namespace
            if name_in_channel in namemap:
                # This assertion is important. It guarantees that we don't have packages bridging namespaces.
                # assert namekey == namemap[name_in_channel], (subdir, namekey, namemap[name_in_channel])
                if namekey != namemap[name_in_channel]:
                    ambiguous_namekeys[name_in_channel].add(namemap[name_in_channel])
                    ambiguous_namekeys[name_in_channel].add(namekey)
                    # ambiguous_namekeys.append((subdir, name_in_channel, namekey, namemap[name_in_channel], fn))
            else:
                namemap[name_in_channel] = namekey
    return namemap, ambiguous_namekeys


def _warn_on_ambiguous_namekeys(ambiguous_namekeys, subdirs, patched_repodata):
    """
    The following packages ambiguously straddle namespaces and require metadata correction:
        package_name:
        namespace1:
            - subdir/fn1.tar.bz2
            - subdir/fn2.tar.bz2
        namespace2:
            - subdir/fn3.tar.bz2
            - subdir/fn4.tar.bz2

    The associated packages are being removed from the index.
    """
    if ambiguous_namekeys:
        abc = defaultdict(lambda: defaultdict(list))
        for subdir in subdirs:
            repodata = patched_repodata[subdir]
            for fn, info in repodata['packages'].items():
                if info["name"] in ambiguous_namekeys:
                    abc[info["name"]][info["namespace"]].append(subdir + "/" + fn)

        builder = ["WARNING: The following packages ambiguously straddle namespaces and require metadata correction:"]
        for package_name in sorted(abc):
            builder.append("  %s:" % package_name)
            for namespace in sorted(abc[package_name]):
                builder.append("    %s:" % namespace)
                for subdir_fn in sorted(abc[package_name][namespace]):
                    builder.append("      - %s" % subdir_fn)
                    subdir, fn = subdir_fn.split("/")
                    popped = patched_repodata[subdir]["packages"].pop(fn, None)
                    if popped:
                        patched_repodata[subdir]["removed"].append(fn)
        # we remove them from the v2 repodata, not b1
        # builder.append("The associated packages are being removed from the index.")
        builder.append('')
        log.warn("\n".join(builder))


def _add_namespace_to_spec(fn, info, dep_str, namemap, missing_dependencies, subdir):
    if not conda_interface.conda_47:
        return dep_str

    spec = MatchSpec(dep_str)
    if hasattr(spec, 'namespace') and spec.namespace:
        # this spec is fine
        return dep_str
    else:
        # look up namekey
        # spec.name refers to name_in_channel; need to convert to namekey, but the
        #   correct namekey might not even be in the channel
        if spec.name not in namemap:
            missing_dependencies[spec.name].append(subdir + "/" + fn)
            return dep_str
        namekey = namemap[spec.name]
        namespace, name = namekey.split(":", 1)
        try:
            spec = MatchSpec(spec, namespace=namespace, name=name)
        except CondaError:
            spec = MatchSpec(spec, name=name)
        return spec.conda_build_form()


def _make_build_string(build, build_number):
    build_number_as_string = str(build_number)
    if build.endswith(build_number_as_string):
        build = build[:-len(build_number_as_string)]
        build = build.rstrip("_")
    build_string = build
    return build_string


def _warn_on_missing_dependencies(missing_dependencies, patched_repodata):
    """
    The following dependencies do not exist in the channel and are not declared
    as external dependencies:

    dependency1:
        - subdir/fn1.tar.bz2
        - subdir/fn2.tar.bz2
    dependency2:
        - subdir/fn3.tar.bz2
        - subdir/fn4.tar.bz2

    The associated packages are being removed from the index.
    """

    if missing_dependencies:
        builder = [
            "WARNING: The following dependencies do not exist in the channel",
            "    and are not declared as external dependencies:"
        ]
        for dep_name in sorted(missing_dependencies):
            builder.append("  %s" % dep_name)
            for subdir_fn in sorted(missing_dependencies[dep_name]):
                builder.append("    - %s" % subdir_fn)
                subdir, fn = subdir_fn.split("/")
                popped = patched_repodata[subdir]["packages"].pop(fn, None)
                if popped:
                    patched_repodata[subdir]["removed"].append(fn)

        builder.append("The associated packages are being removed from the index.")
        builder.append('')
        log.warn("\n".join(builder))


def _augment_repodata(subdirs, patched_repodata, patch_instructions):
    augmented_repodata = {}

    # TODO: handle packages that need to be renamed

    # Step 1. Collect all package names and associated namespaces.
    #         Attach namespace to every package.
    namemap, ambiguous_namekeys = _collect_namemap(subdirs, patched_repodata, patch_instructions)
    _warn_on_ambiguous_namekeys(ambiguous_namekeys, subdirs, patched_repodata)
    missing_dependencies = defaultdict(list)

    # Step 2. Add depends2 and constrains2, and other fields
    for subdir in subdirs:
        repodata = patched_repodata[subdir]
        for fn, info in repodata['packages'].items():
            info['record_version'] = 1
            if 'constrains' in info:
                constrains_names = set(dep.split()[0] for dep in info["constrains"])
                try:
                    info['constrains2'] = [_add_namespace_to_spec(fn, info, dep, namemap, missing_dependencies, subdir)
                                        for dep in info['constrains']]
                    info['depends2'] = [_add_namespace_to_spec(fn, info, dep, namemap, missing_dependencies, subdir)
                                        for dep in info['depends'] if dep.split()[0] not in constrains_names]
                except CondaError as e:
                    log.warn("Encountered a file ({}) that conda does not like.  Error was: {}.  Skipping this one...".format(fn, e))
            else:
                try:
                    info['depends2'] = [_add_namespace_to_spec(fn, info, dep, namemap, missing_dependencies, subdir)
                                        for dep in info['depends']]
                except CondaError as e:
                    log.warn("Encountered a file ({}) that conda does not like.  Error was: {}.  Skipping this one...".format(fn, e))
            # info['build_string'] =_make_build_string(info["build"], info["build_number"])
        repodata["removed"] = patch_instructions[subdir].get("remove", [])
        augmented_repodata[subdir] = repodata
    _warn_on_missing_dependencies(missing_dependencies, patched_repodata)
    return augmented_repodata


def _cache_post_install_details(paths_cache_path, post_install_cache_path):
    post_install_details_json = {'binary_prefix': False, 'text_prefix': False,
                                 'activate.d': False, 'deactivate.d': False,
                                 'pre_link': False, 'post_link': False, 'pre_unlink': False}
    if os.path.lexists(paths_cache_path):
        with open(paths_cache_path) as f:
            paths = json.load(f).get('paths', [])

    # get embedded prefix data from paths.json
        for f in paths:
            if f.get('prefix_placeholder'):
                if f.get('file_mode') == 'binary':
                    post_install_details_json['binary_prefix'] = True
                elif f.get('file_mode') == 'text':
                    post_install_details_json['text_prefix'] = True
                # check for any activate.d/deactivate.d scripts
                for k in ('activate.d', 'deactivate.d'):
                    if not post_install_details_json.get(k) and f['_path'].startswith('etc/conda/%s' % k):
                        post_install_details_json[k] = True
            # check for any link scripts
            for pat in ('pre-link', 'post-link', 'pre-unlink'):
                if not post_install_details_json.get(pat) and fnmatch.fnmatch(f['_path'], '*/.*-%s.*' % pat):
                    post_install_details_json[pat.replace("-", "_")] = True

    with open(post_install_cache_path, 'w') as fh:
        json.dump(post_install_details_json, fh)


def _cache_recipe(tmpdir, recipe_cache_path):
    recipe_path_search_order = (
                'info/recipe/meta.yaml.rendered',
                'info/recipe/meta.yaml',
                'info/meta.yaml',
            )
    for path in recipe_path_search_order:
        recipe_path = os.path.join(tmpdir, path)
        if os.path.lexists(recipe_path):
            break
        recipe_path = None

    recipe_json = {}
    if recipe_path:
        with open(recipe_path) as f:
            try:
                recipe_json = yaml.safe_load(f)
            except (ConstructorError, ParserError, ScannerError):
                pass
    try:
        recipe_json_str = json.dumps(recipe_json, skipkeys=True)
    except TypeError:
        recipe_json.get('requirements', {}).pop('build')
        recipe_json_str = json.dumps(recipe_json, skipkeys=True)
    with open(recipe_cache_path, 'w') as fh:
        fh.write(recipe_json_str)
    return recipe_json


def _cache_run_exports(tmpdir, run_exports_cache_path):
    run_exports = {}
    try:
        with open(os.path.join(tmpdir, 'info', 'run_exports.json')) as f:
            run_exports = json.load(f)
    except (IOError, FileNotFoundError):
        try:
            with open(os.path.join(tmpdir, 'info', 'run_exports.yaml')) as f:
                run_exports = yaml.safe_load(f)
        except (IOError, FileNotFoundError):
            log.debug("%s has no run_exports file (this is OK)" % tmpdir)
    with open(run_exports_cache_path, 'w') as fh:
        json.dump(run_exports, fh)


def _cache_icon(tmpdir, recipe_json, icon_cache_path):
    # If a conda package contains an icon, also extract and cache that in an .icon/
    # directory.  The icon file name is the name of the package, plus the extension
    # of the icon file as indicated by the meta.yaml `app/icon` key.
    # apparently right now conda-build renames all icons to 'icon.png'
    # What happens if it's an ico file, or a svg file, instead of a png? Not sure!
    app_icon_path = recipe_json.get('app', {}).get('icon')
    if app_icon_path:
        icon_path = os.path.join(tmpdir, 'info', 'recipe', app_icon_path)
        if not os.path.lexists(icon_path):
            icon_path = os.path.join(tmpdir, 'info', 'icon.png')
        if os.path.lexists(icon_path):
            icon_cache_path += splitext(app_icon_path)[-1]
            move(icon_path, icon_cache_path)


def _make_subdir_index_html(channel_name, subdir, repodata_packages, extra_paths):
    environment = _get_jinja2_environment()
    template = environment.get_template('subdir-index.html.j2')
    rendered_html = template.render(
        title="%s/%s" % (channel_name or '', subdir),
        packages=repodata_packages,
        current_time=datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")),
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
        current_time=datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")),
    )
    return rendered_html


def _get_source_repo_git_info(path):
    is_repo = subprocess.check_output(["git", "rev-parse", "--is-inside-work-tree"], cwd=path)
    if is_repo.strip().decode('utf-8') == "true":
        output = subprocess.check_output(['git', 'log',
                                        "--pretty=format:'%h|%ad|%an|%s'",
                                        "--date=unix"], cwd=path)
        commits = []
        for line in output.decode("utf-8").strip().splitlines():
            _hash, _time, _author, _desc = line.split("|")
            commits.append({"hash": _hash, "timestamp": int(_time),
                            "author": _author, "description": _desc})
    return commits


@contextlib.contextmanager
def _tmp_chdir(dest):
    curdir = os.getcwd()
    try:
        os.chdir(dest)
        yield
    finally:
        os.chdir(curdir)


def _collect_commits(package_order, hotfix_source_repo, cutoff_time):
    commit_info = {}

    for package_name, info in package_order.items():
        commits = info.get('commits', [])
        for commit in commits:
            commit['timestamp'] = int(commit['timestamp'])
        commits = [commit for commit in commits if commit['timestamp'] > cutoff_time]
        commits.sort(key=lambda x: x['timestamp'], reverse=True)
        if commits:
            commit_info["%s (%s)" % (package_name, info['version'])] = {"recipe_origin": info.get('recipe_origin'),
                                                                        "commits": commits}
    if hotfix_source_repo:
        commit_info['index hotfixes'] = {"recipe_origin": hotfix_source_repo,
                                        "commits": sorted([commit for commit in _get_source_repo_git_info(hotfix_source_repo)
                                                if commit["timestamp"] > cutoff_time],
                                            key=lambda x: x["timestamp"], reverse=True)}
    sorted_commit_info = OrderedDict()

    order = sorted(commit_info, key=lambda k: commit_info[k]['commits'][0]['timestamp'], reverse=True)
    for k in order:
        sorted_commit_info[k] = commit_info[k]
    return sorted_commit_info


def _cache_info_file(tmpdir, info_fn, cache_path):
    info_path = os.path.join(tmpdir, 'info', info_fn)
    if os.path.lexists(info_path):
        try:
            os.makedirs(os.path.dirname(cache_path))
        except:
            pass
        move(info_path, cache_path)


def _remove_file_extension(fn):
    cache_fn = fn
    for ext in CONDA_TARBALL_EXTENSIONS:
        cache_fn = cache_fn.replace(ext, '')
    return cache_fn


class ChannelIndex(object):

    def __init__(self, channel_root, channel_name, subdirs=None, threads=MAX_THREADS_DEFAULT,
                 deep_integrity_check=False):
        self.channel_root = abspath(channel_root)
        self.channel_name = channel_name or basename(channel_root.rstrip('/'))
        self._subdirs = subdirs
        self.thread_executor = ThreadLimitedThreadPoolExecutor(threads)
        self.deep_integrity_check = deep_integrity_check

    def index(self, patch_generator, hotfix_source_repo=None, verbose=False, progress=False, shared_format_cache=True):
        if verbose:
            level = logging.DEBUG
        else:
            level = logging.ERROR

        with utils.LoggingContext(level, loggers=[__name__]):
            if not self._subdirs:
                detected_subdirs = set(subdir for subdir in os.listdir(self.channel_root)
                                    if subdir in DEFAULT_SUBDIRS and isdir(join(self.channel_root, subdir)))
                log.debug("found subdirs %s" % detected_subdirs)
                self.subdirs = subdirs = sorted(detected_subdirs | {'noarch'})
            else:
                self.subdirs = subdirs = sorted(set(self._subdirs) | {'noarch'})

            # Step 1. Lock local channel.
            with utils.try_acquire_locks([utils.get_lock(self.channel_root)], timeout=900):
                # Step 2. Collect repodata from packages.
                repodata_from_packages = {}
                with tqdm(total=len(subdirs), disable=(verbose or not progress)) as t:
                    for subdir in subdirs:
                        t.set_description("Subdir: %s" % subdir)
                        t.update()
                        _ensure_valid_channel(self.channel_root, subdir)
                        repodata_from_packages[subdir] = self.index_subdir(
                            subdir, verbose=verbose, progress=progress, shared_format_cache=shared_format_cache)

                # Step 3. Apply patch instructions.
                patched_repodata = {}
                patch_instructions = {}
                for subdir in subdirs:
                    patched_repodata[subdir], patch_instructions[subdir] = self._patch_repodata(
                        subdir, repodata_from_packages[subdir], patch_generator)

                # Step 4. Save patched and augmented repodata.
                for subdir in subdirs:
                    # If the contents of repodata have changed, write a new repodata.json file.
                    # Also create associated index.html.
                    self._write_repodata(subdir, patched_repodata[subdir])

                # Step 5. Augment repodata with additional information.
                augmented_repodata = _augment_repodata(subdirs, patched_repodata, patch_instructions)

                # Step 6. Create and save repodata2.json
                repodata2 = {}
                for subdir in subdirs:
                    repodata2[subdir] = self._create_repodata2(subdir, augmented_repodata[subdir])
                    changed = self._write_repodata2(subdir, repodata2[subdir])
                    if changed:
                        self._write_subdir_index_html(subdir, repodata2[subdir])

                # Step 7. Create and write channeldata.
                all_repodata_packages = tuple(concat(repodata["packages"] for repodata in repodata2.values()))
                reference_packages = _gather_channeldata_reference_packages(all_repodata_packages)
                channel_data, package_mtimes = self._build_channeldata(subdirs, reference_packages, shared_format_cache)
                self._write_channeldata_index_html(channel_data)
                self._write_channeldata_rss(channel_data, package_mtimes, hotfix_source_repo)
                self._write_channeldata(channel_data)

    def index_subdir(self, subdir, verbose=False, progress=False, shared_format_cache=True):
        subdir_path = join(self.channel_root, subdir)
        self._ensure_dirs(subdir)
        repodata_json_path = join(subdir_path, REPODATA_JSON_FN)

        if verbose:
            log.info("Building repodata for %s" % subdir_path)

        # gather conda package filenames in subdir
        # we'll process these first, because reading their metadata is much faster
        fns_in_subdir = {fn for fn in os.listdir(subdir_path) if fn.endswith('.conda') or fn.endswith('.tar.bz2')}

        # load current/old repodata
        try:
            with open(repodata_json_path) as fh:
                old_repodata = json.load(fh) or {}
        except (EnvironmentError, JSONDecodeError):
            # log.info("no repodata found at %s", repodata_json_path)
            old_repodata = {}
        old_repodata_packages = old_repodata.get("packages", {})
        old_repodata_conda_packages = old_repodata.get("packages.conda", {})
        old_repodata_fns = set(old_repodata_packages) | set(old_repodata_conda_packages)

        # Load stat cache. The stat cache has the form
        #   {
        #     'package_name.tar.bz2': {
        #       'mtime': 123456,
        #       'md5': 'abd123',
        #     },
        #   }
        stat_cache_path = join(subdir_path, '.cache', 'stat.json')
        try:
            with open(stat_cache_path) as fh:
                stat_cache = json.load(fh) or {}
        except:
            stat_cache = {}

        stat_cache_original = stat_cache.copy()

        try:
            # calculate all the paths and figure out what we're going to do with them
            # add_set: filenames that aren't in the current/old repodata, but exist in the subdir
            add_set = fns_in_subdir - old_repodata_fns
            remove_set = old_repodata_fns - fns_in_subdir
            ignore_set = set(old_repodata.get('removed', []))
            add_set -= ignore_set

            # update_set: Filenames that are in both old repodata and new repodata,
            #     and whose contents have changed based on file size or mtime. We're
            #     not using md5 here because it takes too long. If needing to do full md5 checks,
            #     use the --deep-integrity-check flag / self.deep_integrity_check option.
            update_set = self._calculate_update_set(
                subdir, add_set, old_repodata_fns, stat_cache,
                verbose=verbose, progress=progress
            )
            # unchanged_set: packages in old repodata whose information can carry straight
            #     across to new repodata
            unchanged_set = sorted(old_repodata_fns - update_set - remove_set - ignore_set)

            # clean up removed files
            removed_set = (old_repodata_fns - fns_in_subdir)
            for fn in removed_set:
                if fn in stat_cache:
                    del stat_cache[fn]

            new_repodata_packages = {}
            new_repodata_conda_packages = {}
            for fn in sorted(unchanged_set):
                try:
                    new_repodata_packages[fn] = self._load_index_from_cache(subdir, fn, stat_cache,
                                                                            shared_format_cache)
                except IOError:
                    update_set.add(fn)

            # Invalidate cached files for update_set.
            # Extract and cache update_set and add_set, then add to new_repodata_packages.
            # This is also where we update the contents of the stat_cache for successfully
            #   extracted packages.
            # Sorting here prioritizes .conda files ('c') over .tar.bz2 files ('b')
            hash_extract_set = sorted(set(concatv(add_set, update_set)),
                                      key=lambda x: os.path.splitext(x)[1],
                                      reverse=True)
            # log.info("hashing and extracting %d packages", len(hash_extract_set))
            futures = tuple(self.thread_executor.submit(
                self._extract_to_cache, subdir, fn, shared_format_cache
            ) for fn in hash_extract_set)
            with tqdm(desc="hash & extract packages for %s" % subdir,
                      total=len(futures), disable=(verbose or not progress)) as t:
                for future in as_completed(futures):
                    fn, mtime, size, index_json = future.result()
                    # fn can be None if the file was corrupt or no longer there
                    if fn and mtime:
                        # the progress bar shows package names, but we don't know what their name is before they complete.
                        t.set_description("Hash & extract: %s" % fn)
                        t.update()
                        stat_cache[fn] = {'mtime': int(mtime), 'size': size}
                        if fn.endswith(".conda"):
                            new_repodata_conda_packages[fn] = index_json
                        else:
                            new_repodata_packages[fn] = index_json
            new_repodata = {
                'packages': new_repodata_packages,
                'packages.conda': new_repodata_conda_packages,
                'info': {
                    'subdir': subdir,
                },
                'repodata_version': REPODATA_VERSION,
                'removed': sorted(list(ignore_set))
            }
        finally:
            if stat_cache != stat_cache_original:
                # log.info("writing stat cache to %s", stat_cache_path)
                with open(stat_cache_path, 'w') as fh:
                    json.dump(stat_cache, fh)
        return new_repodata

    def _ensure_dirs(self, subdir):
        # Create all cache directories in the subdir.
        ensure = lambda path: isdir(path) or os.makedirs(path)
        cache_path = join(self.channel_root, subdir, '.cache')
        ensure(cache_path)
        ensure(join(cache_path, 'index'))
        ensure(join(cache_path, 'about'))
        ensure(join(cache_path, 'paths'))
        ensure(join(cache_path, 'recipe'))
        ensure(join(cache_path, 'run_exports'))
        ensure(join(cache_path, 'post_install'))
        ensure(join(cache_path, 'icon'))
        ensure(join(self.channel_root, 'icons'))
        ensure(join(cache_path, 'recipe_log'))

    def _calculate_update_set(self, subdir, fns_in_subdir, old_repodata_fns, stat_cache, verbose=False, progress=False):
        # Determine the packages that already exist in repodata, but need to be updated.
        # We're not using md5 here because it takes too long.
        candidate_fns = fns_in_subdir & old_repodata_fns
        subdir_path = join(self.channel_root, subdir)

        stat_results = tuple((fn, os.lstat(
            join(subdir_path, fn))) for fn in candidate_fns)

        update_set = set(fn for fn, stat_result in tqdm(stat_results, desc="Finding updated files",
                                                        disable=(verbose or not progress))
                         if int(stat_result.st_mtime) != stat_cache.get(fn, {}).get('mtime') or
                         stat_result.st_size != stat_cache.get(fn, {}).get('size'))
        return update_set

    def _extract_to_cache(self, subdir, fn, shared_format_cache):
        # This method WILL reread the tarball. Probably need another one to exit early if
        # there are cases where it's fine not to reread.  Like if we just rebuild repodata
        # from the cached files, but don't use the existing repodata.json as a starting point.
        subdir_path = join(self.channel_root, subdir)

        # try to use any existing .conda format here, because extracting it will be much, much faster
        # default value indicates either corrupt or removed file.  For corrupt, there
        #      is an error message shown.
        retval = fn, None, None, None

        # allow .conda files to reuse cache from .tar.bz2 and vice-versa.
        # Assumes that .tar.bz2 and .conda files have exactly the same
        # contents. This is convention, but not guaranteed, nor checked.
        cache_fn = _remove_file_extension(fn) if shared_format_cache else fn

        abs_fn = os.path.join(subdir_path, fn)

        index_cache_path = join(subdir_path, '.cache', 'index', cache_fn + '.json')
        about_cache_path = join(subdir_path, '.cache', 'about', cache_fn + '.json')
        paths_cache_path = join(subdir_path, '.cache', 'paths', cache_fn + '.json')
        recipe_cache_path = join(subdir_path, '.cache', 'recipe', cache_fn + '.json')
        run_exports_cache_path = join(subdir_path, '.cache', 'run_exports', cache_fn + '.json')
        post_install_cache_path = join(subdir_path, '.cache', 'post_install', cache_fn + '.json')
        icon_cache_path = join(subdir_path, '.cache', 'icon', cache_fn)

        log.debug("hashing, extracting, and caching %s" % fn)
        try:
            if not os.path.exists(index_cache_path):
                with TemporaryDirectory() as tmpdir:
                    conda_package_handling.api.extract(abs_fn, dest_dir=tmpdir, components="info")
                    index_file = os.path.join(tmpdir, 'info', 'index.json')
                    if not os.path.exists(index_file):
                        return retval
                    with open(index_file) as f:
                        index_json = json.load(f)

                    _cache_info_file(tmpdir, 'about.json', about_cache_path)
                    _cache_info_file(tmpdir, 'paths.json', paths_cache_path)
                    _cache_info_file(tmpdir, 'recipe_log.json', paths_cache_path)
                    _cache_run_exports(tmpdir, run_exports_cache_path)
                    _cache_post_install_details(paths_cache_path, post_install_cache_path)
                    recipe_json = _cache_recipe(tmpdir, recipe_cache_path)
                    _cache_icon(tmpdir, recipe_json, icon_cache_path)

            else:
                with open(index_cache_path) as f:
                    index_json = json.load(f)

            # calculate extra stuff to add to index.json cache, size, md5, sha256
            #    This is done for both the old and possibly the new file format.
            #    The old one is the one that shows up in repodata.json.  The new
            #    one makes up the stat cache.
            stat_result = os.lstat(abs_fn)
            size = stat_result.st_size
            mtime = stat_result.st_mtime
            index_json.update(conda_package_handling.api.get_pkg_details(abs_fn))

            # decide what fields to filter out, like has_prefix
            filter_fields = {
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
            }
            for field_name in filter_fields & set(index_json):
                del index_json[field_name]

            with open(index_cache_path, 'w') as fh:
                json.dump(index_json, fh)
            retval = fn, mtime, size, index_json
        except (libarchive.exception.ArchiveError, tarfile.ReadError, KeyError, EOFError) as e:
            log.error("Package %s appears to be corrupt.  Please remove it and re-download it" % abs_fn)
            log.error(e.message)
        return retval

    def _load_index_from_cache(self, subdir, fn, stat_cache, shared_format_cache):
        cache_fn = fn
        if shared_format_cache:
            cache_fn = _remove_file_extension(fn)
        index_cache_path = join(self.channel_root, subdir, '.cache', 'index', cache_fn + '.json')
        log.debug("loading index cache %s" % index_cache_path)

        with open(index_cache_path) as fh:
            index_json = json.load(fh)

        return index_json

    def _load_all_from_cache(self, subdir, fn, shared_format_cache):
        subdir_path = join(self.channel_root, subdir)
        # allow .conda files to reuse cache from .tar.bz2 and vice-versa.
        # Assumes that .tar.bz2 and .conda files have exactly the same
        # contents. This is convention, but not guaranteed, nor checked.
        cache_fn = fn
        if shared_format_cache:
            cache_fn = _remove_file_extension(fn)

        try:
            mtime = getmtime(join(subdir_path, fn))
        except FileNotFoundError:
            return {}
        # In contrast to self._load_index_from_cache(), this method reads up pretty much
        # all of the cached metadata, except for paths. It all gets dumped into a single map.
        index_cache_path = join(subdir_path, '.cache', 'index', cache_fn + '.json')
        about_cache_path = join(subdir_path, '.cache', 'about', cache_fn + '.json')
        recipe_cache_path = join(subdir_path, '.cache', 'recipe', cache_fn + '.json')
        run_exports_cache_path = join(subdir_path, '.cache', 'run_exports', cache_fn + '.json')
        post_install_cache_path = join(subdir_path, '.cache', 'post_install', cache_fn + '.json')
        icon_cache_path_glob = join(subdir_path, '.cache', 'icon', cache_fn + ".*")
        recipe_log_path = join(subdir_path, '.cache', 'recipe_log', cache_fn + '.json')

        data = {}
        for path in (recipe_cache_path, about_cache_path, index_cache_path, post_install_cache_path, recipe_log_path):
            try:
                if os.path.getsize(path) != 0:
                    with open(path) as fh:
                        data.update(json.load(fh))
            except (OSError, EOFError, IOError):
                pass

        icon_cache_paths = glob(icon_cache_path_glob)
        if icon_cache_paths:
            icon_cache_path = sorted(icon_cache_paths)[-1]
            icon_ext = icon_cache_path.rsplit('.', 1)[-1]
            channel_icon_fn = "%s.%s" % (data['name'], icon_ext)
            icon_url = "icons/" + channel_icon_fn
            icon_channel_path = join(self.channel_root, 'icons', channel_icon_fn)
            icon_md5 = utils.md5_file(icon_cache_path)
            icon_hash = "md5:%s:%s" % (icon_md5, getsize(icon_cache_path))
            data.update(icon_hash=icon_hash, icon_url=icon_url)
            if lexists(icon_channel_path) and utils.md5_file(icon_channel_path) != icon_md5:
                os.unlink(icon_channel_path)
            if not lexists(icon_channel_path):
                # log.info("writing icon from %s to %s", icon_cache_path, icon_channel_path)
                copy2(icon_cache_path, icon_channel_path)

        # have to stat again, because we don't have access to the stat cache here
        data['mtime'] = mtime

        source = data.get("source", {})
        try:
            data.update({"source_" + k: v for k, v in source.items()})
        except AttributeError:
            # sometimes source is a  list instead of a dict
            pass
        _clear_newline_chars(data, 'description')
        _clear_newline_chars(data, 'summary')
        try:
            with open(run_exports_cache_path) as fh:
                data["run_exports"] = json.load(fh)
        except (OSError, EOFError):
            data["run_exports"] = {}
        return data

    def _write_repodata(self, subdir, repodata):
        repodata_json_path = join(self.channel_root, subdir, REPODATA_JSON_FN)
        new_repodata_binary = json.dumps(repodata, indent=2, sort_keys=True,
                                  separators=(',', ': ')).encode("utf-8")
        write_result = _maybe_write(repodata_json_path, new_repodata_binary, write_newline_end=True)
        if write_result:
            repodata_bz2_path = repodata_json_path + ".bz2"
            bz2_content = bz2.compress(new_repodata_binary)
            _maybe_write(repodata_bz2_path, bz2_content, content_is_binary=True)
        return write_result

    def _write_subdir_index_html(self, subdir, repodata):
        repodata_packages = repodata["packages"]
        subdir_path = join(self.channel_root, subdir)

        def _add_extra_path(extra_paths, path):
            if isfile(join(self.channel_root, path)):
                extra_paths[basename(path)] = {
                    'size': getsize(path),
                    'timestamp': int(getmtime(path)),
                    'md5': utils.md5_file(path),
                }

        extra_paths = OrderedDict()
        _add_extra_path(extra_paths, join(subdir_path, REPODATA_JSON_FN))
        _add_extra_path(extra_paths, join(subdir_path, REPODATA_JSON_FN + '.bz2'))
        _add_extra_path(extra_paths, join(subdir_path, "repodata2.json"))
        _add_extra_path(extra_paths, join(subdir_path, "patch_instructions.json"))
        rendered_html = _make_subdir_index_html(
            self.channel_name, subdir, repodata_packages, extra_paths
        )
        index_path = join(subdir_path, 'index.html')
        return _maybe_write(index_path, rendered_html)

    def _write_channeldata_rss(self, channeldata, package_mtimes, hotfix_source_repo):
        cutoff_time = time.time() - 14 * 24 * 3600

        current = {name: channeldata['packages'][name] for name, mtime in package_mtimes.items()
                   if mtime > cutoff_time}

        # our RSS feed is fed by up to 2 things:
        #    - package recipe_log.json files
        #    - commit log from the repo where we get our patch instructions from.  This is a config option and cli flag.
        commit_info = _collect_commits(current, hotfix_source_repo, cutoff_time)

        environment = _get_jinja2_environment()
        template = environment.get_template('rss.xml.j2')
        rendered_xml = template.render(
            channel_name=self.channel_name,
            channel_url="https://anaconda.org",  # TODO: figure this out
            current_time=datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")),

            commit_info=commit_info,
            trim_blocks=True
        )

        rss_path = join(self.channel_root, 'rss.xml')
        _maybe_write(rss_path, rendered_xml)
        return rendered_xml

    def _write_channeldata_index_html(self, channeldata):
        rendered_html = _make_channeldata_index_html(
            self.channel_name, channeldata
        )
        index_path = join(self.channel_root, 'index.html')
        _maybe_write(index_path, rendered_html)

    def _build_channeldata(self, subdirs, reference_packages, shared_format_cache):
        package_data = {}
        package_mtimes = {}

        futures = tuple(self.thread_executor.submit(
            self._load_all_from_cache, rec["subdir"], rec["fn"], shared_format_cache
        ) for rec in reference_packages)
        for rec, future in zip(reference_packages, futures):
            data = future.result()
            if data:
                data.update(rec)
                name = data['name']
                package_data[name] = {k: v for k, v in data.items() if k in CHANNELDATA_FIELDS}
                package_mtimes[name] = data['mtime']

        channeldata = {
            'channeldata_version': CHANNELDATA_VERSION,
            'subdirs': subdirs,
            'packages': package_data,
        }
        return channeldata, package_mtimes

    def _write_channeldata(self, channeldata):
        # trim out commits, as they can take up a ton of space.  They're really only for the RSS feed.
        for _pkg, pkg_dict in channeldata.get('packages', {}).items():
            if "commits" in pkg_dict:
                del pkg_dict['commits']
        channeldata_path = join(self.channel_root, 'channeldata.json')
        content = json.dumps(channeldata, indent=2, sort_keys=True, separators=(',', ': '))
        _maybe_write(channeldata_path, content, True)

    def _load_patch_instructions_tarball(self, subdir, patch_generator):
        patch_instructions_file = utils.package_has_file(patch_generator,
                                                         os.path.join(subdir, "patch_instructions.json"))
        instructions = {}
        if patch_instructions_file:
            instructions = json.loads(patch_instructions_file)
        return instructions

    def _create_patch_instructions(self, subdir, repodata, patch_generator=None):
        gen_patch_path = patch_generator or join(self.channel_root, 'gen_patch.py')
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
        new_patch = json.dumps(instructions, indent=2, sort_keys=True, separators=(',', ': '))
        patch_instructions_path = join(self.channel_root, subdir, 'patch_instructions.json')
        _maybe_write(patch_instructions_path, new_patch, True)

    def _load_instructions(self, subdir):
        patch_instructions_path = join(self.channel_root, subdir, 'patch_instructions.json')
        if isfile(patch_instructions_path):
            log.debug("using patch instructions %s" % patch_instructions_path)
            with open(patch_instructions_path) as fh:
                instructions = json.load(fh)
                if instructions.get('patch_instructions_version', 0) > 1:
                    raise RuntimeError("Incompatible patch instructions version")
                return instructions
        return {}

    def _patch_repodata(self, subdir, repodata, patch_generator=None):
        if patch_generator and patch_generator.endswith("bz2"):
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

    def _create_repodata2(self, subdir, augmented_repodata):
        repodata2 = augmented_repodata  # I guess we're mutating in place for now
        repodata2["repodata_version"] = 2
        revoked_set = set()

        channel_name = self.channel_name

        for fn, info in repodata2["packages"].items():
            info["record_version"] = 2
            if 'depends2' not in info:
                continue
            info["requires"] = info["depends2"]
            del info["depends"]
            del info["depends2"]
            if "constrains2" in info:
                info["constrains"] = info["constrains2"]
                del info["constrains2"]

            info["fn"] = fn  # rename fn to filename?
            # add "location", relative to subdir

            info["channel_name"] = channel_name
            if "timestamp" in info:
                info["timestamp"] = _make_seconds(info["timestamp"])

            # noarch -> package_type: noarch_generic, noarch_python
            if "noarch" in info:
                if info["noarch"] == "python":
                    info["package_type"] = "noarch_python"
                del info["noarch"]

            # dump features
            info.pop("features", None)  # 😱

            # convert track_features to list
            if "track_features" in info:
                info["track_features"] = info["track_features"].split(" ")

            # enforce md5 and sha256
            assert "md5" in info
            # assert "sha256" in info  # TODO: re-enable
            assert "size" in info, (subdir, fn, info)

            # drop arch and platform, enforce subdir
            info.pop("arch", None)
            info.pop("platform", None)
            info["subdir"] = subdir

            if info.get('revoked'):
                revoked_set.add(fn)

        sort_key = lambda x: (
            x["namespace"] == "global" and "0" or x["namespace"],
            x["name"],
            VersionOrder(x["version"]),
            x["build_number"],
            # x["build_string"],
            x["build"],
        )

        package_groups = groupby(lambda x: x.get('revoked', False), augmented_repodata["packages"].values())
        repodata2["packages"] = sorted(package_groups.get(False, ()), key=sort_key)
        repodata2["revoked"] = sorted(package_groups.get(True, ()), key=sort_key)

        return repodata2

    def _write_repodata2(self, subdir, repodata2):
        repodata_json_path = join(self.channel_root, subdir, "repodata2.json")
        new_repodata = json.dumps(repodata2, indent=2, sort_keys=True, separators=(',', ': '))
        return _maybe_write(repodata_json_path, new_repodata, True)
