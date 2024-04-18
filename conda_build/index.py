# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import json
import logging
import os
import time
from functools import partial
from os.path import dirname

from conda.base.context import context
from conda.core.index import get_index
from conda.exceptions import CondaHTTPError
from conda_index.index import update_index as _update_index

from . import utils
from .conda_interface import url_path
from .deprecations import deprecated
from .utils import (
    CONDA_PACKAGE_EXTENSION_V1,
    CONDA_PACKAGE_EXTENSION_V2,
    JSONDecodeError,
    get_logger,
    on_win,
)

log = get_logger(__name__)


local_index_timestamp = 0
cached_index = None
local_subdir = ""
local_output_folder = ""
cached_channels = []
_channel_data = {}
deprecated.constant("24.1", "24.5", "channel_data", _channel_data)


# TODO: support for libarchive seems to have broken ability to use multiple threads here.
#    The new conda format is so much faster that it more than makes up for it.  However, it
#    would be nice to fix this at some point.
_MAX_THREADS_DEFAULT = os.cpu_count() or 1
if on_win:  # see https://github.com/python/cpython/commit/8ea0fd85bc67438f679491fae29dfe0a3961900a
    _MAX_THREADS_DEFAULT = min(48, _MAX_THREADS_DEFAULT)
deprecated.constant("24.3", "24.5", "MAX_THREADS_DEFAULT", _MAX_THREADS_DEFAULT)
deprecated.constant("24.3", "24.5", "LOCK_TIMEOUT_SECS", 3 * 3600)
deprecated.constant("24.3", "24.5", "LOCKFILE_NAME", ".lock")

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
    """
    Used during package builds to create/get a channel including any local or
    newly built packages. This function both updates and gets index data.
    """
    global local_index_timestamp
    global local_subdir
    global local_output_folder
    global cached_index
    global cached_channels
    global _channel_data
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
            _delegated_update_index(output_folder, verbose=debug)

            # replace noarch with native subdir - this ends up building an index with both the
            #      native content and the noarch content.

            if subdir == "noarch":
                subdir = context.subdir
            try:
                # get_index() is like conda reading the index, not conda_index
                # creating a new index.
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

            expanded_channels = {rec.channel for rec in cached_index}

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
                                    _channel_data[channel.name] = json.load(f)
                                break
                            except (OSError, JSONDecodeError):
                                time.sleep(0.2)
                                retry += 1
                else:
                    # download channeldata.json for url
                    if not context.offline:
                        try:
                            _channel_data[channel.name] = utils.download_channeldata(
                                channel.base_url + "/channeldata.json"
                            )
                        except CondaHTTPError:
                            continue
                # collapse defaults metachannel back into one superchannel, merging channeldata
                if channel.base_url in context.default_channels and _channel_data.get(
                    channel.name
                ):
                    packages = superchannel.get("packages", {})
                    packages.update(_channel_data[channel.name])
                    superchannel["packages"] = packages
            _channel_data["defaults"] = superchannel
        local_index_timestamp = os.path.getmtime(index_file)
        local_subdir = subdir
        local_output_folder = output_folder
        cached_channels = channel_urls
    return cached_index, local_index_timestamp, _channel_data


def _ensure_valid_channel(local_folder, subdir):
    for folder in {subdir, "noarch"}:
        path = os.path.join(local_folder, folder)
        if not os.path.isdir(path):
            os.makedirs(path)


def _delegated_update_index(
    dir_path,
    check_md5=False,
    channel_name=None,
    patch_generator=None,
    threads=1,
    verbose=False,
    progress=False,
    subdirs=None,
    warn=True,
    current_index_versions=None,
    debug=False,
):
    """
    update_index as called by conda-build, delegating to standalone conda-index.
    Needed to allow update_index calls on single subdir.
    """
    # conda-build calls update_index on a single subdir internally, but
    # conda-index expects to index every subdir under dir_path
    parent_path, dirname = os.path.split(dir_path)
    if dirname in utils.DEFAULT_SUBDIRS:
        dir_path = parent_path
        subdirs = [dirname]

    log_level = logging.DEBUG if debug else logging.INFO if verbose else logging.WARNING
    with utils.LoggingContext(log_level):
        return _update_index(
            dir_path,
            check_md5=check_md5,
            channel_name=channel_name,
            patch_generator=patch_generator,
            threads=threads,
            verbose=verbose,
            progress=progress,
            subdirs=subdirs,
            warn=warn,
            current_index_versions=current_index_versions,
            debug=debug,
        )


@deprecated(
    "24.1.0", "24.5.0", addendum="Use `conda_index._apply_instructions` instead."
)
def _apply_instructions(subdir, repodata, instructions):
    repodata.setdefault("removed", [])
    utils.merge_or_update_dict(
        repodata.get("packages", {}),
        instructions.get("packages", {}),
        merge=False,
        add_missing_keys=False,
    )
    # we could have totally separate instructions for .conda than .tar.bz2, but it's easier if we assume
    #    that a similarly-named .tar.bz2 file is the same content as .conda, and shares fixes
    new_pkg_fixes = {
        k.replace(CONDA_PACKAGE_EXTENSION_V1, CONDA_PACKAGE_EXTENSION_V2): v
        for k, v in instructions.get("packages", {}).items()
    }

    utils.merge_or_update_dict(
        repodata.get("packages.conda", {}),
        new_pkg_fixes,
        merge=False,
        add_missing_keys=False,
    )
    utils.merge_or_update_dict(
        repodata.get("packages.conda", {}),
        instructions.get("packages.conda", {}),
        merge=False,
        add_missing_keys=False,
    )

    for fn in instructions.get("revoke", ()):
        for key in ("packages", "packages.conda"):
            if fn.endswith(CONDA_PACKAGE_EXTENSION_V1) and key == "packages.conda":
                fn = fn.replace(CONDA_PACKAGE_EXTENSION_V1, CONDA_PACKAGE_EXTENSION_V2)
            if fn in repodata[key]:
                repodata[key][fn]["revoked"] = True
                repodata[key][fn]["depends"].append("package_has_been_revoked")

    for fn in instructions.get("remove", ()):
        for key in ("packages", "packages.conda"):
            if fn.endswith(CONDA_PACKAGE_EXTENSION_V1) and key == "packages.conda":
                fn = fn.replace(CONDA_PACKAGE_EXTENSION_V1, CONDA_PACKAGE_EXTENSION_V2)
            popped = repodata[key].pop(fn, None)
            if popped:
                repodata["removed"].append(fn)
    repodata["removed"].sort()

    return repodata
