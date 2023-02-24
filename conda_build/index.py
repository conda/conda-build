# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
conda-build's use of conda-index, delegated to now-separate conda-index package.
"""

import json
import logging
import os
import sys
import time
from concurrent.futures import Executor
from functools import partial
from os.path import dirname

import conda_index.index

from conda_build import conda_interface, utils

from .conda_interface import CondaHTTPError, context, get_index, url_path
from .utils import JSONDecodeError, get_logger

log = get_logger(__name__)


# use this for debugging, because ProcessPoolExecutor isn't pdb/ipdb friendly
class DummyExecutor(Executor):
    def map(self, func, *iterables):
        for iterable in iterables:
            for thing in iterable:
                yield func(thing)


local_index_timestamp = 0
cached_index = None
local_subdir = ""
local_output_folder = ""
cached_channels = []
channel_data = {}


# TODO: support for libarchive seems to have broken ability to use multiple threads here.
#    The new conda format is so much faster that it more than makes up for it.  However, it
#    would be nice to fix this at some point.
try:
    MAX_THREADS_DEFAULT = os.cpu_count() or 1  # can be None in rare cases
except AttributeError:
    MAX_THREADS_DEFAULT = 1

# see https://github.com/python/cpython/commit/8ea0fd85bc67438f679491fae29dfe0a3961900a
if sys.platform == "win32":  
    MAX_THREADS_DEFAULT = min(48, MAX_THREADS_DEFAULT)
LOCK_TIMEOUT_SECS = 3 * 3600
LOCKFILE_NAME = ".lock"

# TODO: this is to make sure that the index doesn't leak tokens.  It breaks use of private channels, though.
# os.environ['CONDA_ADD_ANACONDA_TOKEN'] = "false"


def get_build_index(
    subdir,
    bldpkgs_dir,
    output_folder=None,
    clear_cache=False,
    omit_defaults=False,
    channel_urls=None,
    debug=False,
    verbose=True,
    locking=None,
    timeout=None,
):
    global local_index_timestamp
    global local_subdir
    global local_output_folder
    global cached_index
    global cached_channels
    global channel_data
    mtime = 0

    channel_urls = list(utils.ensure_list(channel_urls))

    if not output_folder:
        output_folder = dirname(bldpkgs_dir)

    # check file modification time - this is the age of our local index.
    index_file = os.path.join(output_folder, subdir, "repodata.json")
    if os.path.isfile(index_file):
        mtime = os.path.getmtime(index_file)

    if (
        clear_cache
        or not os.path.isfile(index_file)
        or local_subdir != subdir
        or local_output_folder != output_folder
        or mtime > local_index_timestamp
        or cached_channels != channel_urls
    ):

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
            log_context = partial(
                utils.LoggingContext, logging.CRITICAL + 1, loggers=loggers
            )
        with log_context():
            # this is where we add the "local" channel.  It's a little smarter than conda, because
            #     conda does not know about our output_folder when it is not the default setting.
            if os.path.isdir(output_folder):
                local_path = url_path(output_folder)
                # replace local with the appropriate real channel.  Order is maintained.
                urls = [url if url != "local" else local_path for url in urls]
                if local_path not in urls:
                    urls.insert(0, local_path)
            _ensure_valid_channel(output_folder, subdir)
            update_index(output_folder, verbose=debug)

            # replace noarch with native subdir - this ends up building an index with both the
            #      native content and the noarch content.

            if subdir == "noarch":
                subdir = conda_interface.subdir
            try:
                cached_index = get_index(
                    channel_urls=urls,
                    prepend=not omit_defaults,
                    use_local=False,
                    use_cache=context.offline,
                    platform=subdir,
                )
            # HACK: defaults does not have the many subfolders we support.  Omit it and
            #          try again.
            except CondaHTTPError:
                if "defaults" in urls:
                    urls.remove("defaults")
                cached_index = get_index(
                    channel_urls=urls,
                    prepend=omit_defaults,
                    use_local=False,
                    use_cache=context.offline,
                    platform=subdir,
                )

            expanded_channels = {rec.channel for rec in cached_index.values()}

            superchannel = {}
            # we need channeldata.json too, as it is a more reliable source of run_exports data
            for channel in expanded_channels:
                if channel.scheme == "file":
                    location = channel.location
                    if utils.on_win:
                        location = location.lstrip("/")
                    elif not os.path.isabs(channel.location) and os.path.exists(
                        os.path.join(os.path.sep, channel.location)
                    ):
                        location = os.path.join(os.path.sep, channel.location)
                    channeldata_file = os.path.join(
                        location, channel.name, "channeldata.json"
                    )
                    retry = 0
                    max_retries = 1
                    if os.path.isfile(channeldata_file):
                        while retry < max_retries:
                            try:
                                with open(channeldata_file, "r+") as f:
                                    channel_data[channel.name] = json.load(f)
                                break
                            except (OSError, JSONDecodeError):
                                time.sleep(0.2)
                                retry += 1
                else:
                    # download channeldata.json for url
                    if not context.offline:
                        try:
                            channel_data[channel.name] = utils.download_channeldata(
                                channel.base_url + "/channeldata.json"
                            )
                        except CondaHTTPError:
                            continue
                # collapse defaults metachannel back into one superchannel, merging channeldata
                if channel.base_url in context.default_channels and channel_data.get(
                    channel.name
                ):
                    packages = superchannel.get("packages", {})
                    packages.update(channel_data[channel.name])
                    superchannel["packages"] = packages
            channel_data["defaults"] = superchannel
        local_index_timestamp = os.path.getmtime(index_file)
        local_subdir = subdir
        local_output_folder = output_folder
        cached_channels = channel_urls
    return cached_index, local_index_timestamp, channel_data


def _ensure_valid_channel(local_folder, subdir):
    for folder in {subdir, "noarch"}:
        path = os.path.join(local_folder, folder)
        if not os.path.isdir(path):
            os.makedirs(path)


def update_index(
    dir_path,
    check_md5=False,
    channel_name=None,
    patch_generator=None,
    threads=1,
    verbose=False,
    progress=False,
    hotfix_source_repo=None,
    subdirs=None,
    warn=True,
    current_index_versions=None,
    debug=False,
    index_file=None,
):
    # conda-build calls update_index on a single subdir internally, but
    # conda-index expects to index every subdir under dir_path
    parent_path, dirname = os.path.split(dir_path)
    if dirname in utils.DEFAULT_SUBDIRS:
        dir_path = parent_path
        subdirs = [dirname]

    return conda_index.index.update_index(
        dir_path,
        check_md5=check_md5,
        channel_name=channel_name,
        patch_generator=patch_generator,
        threads=threads,
        verbose=verbose,
        progress=progress,
        # hotfix_source_repo=None, # unused
        subdirs=subdirs,
        warn=warn,
        current_index_versions=current_index_versions,
        debug=debug,
        # index_file=None,  # unused
    )
