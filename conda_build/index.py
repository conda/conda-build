# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import logging
import os
from functools import partial
from os.path import dirname

from conda.base.context import context
from conda.core.index import get_index
from conda.exceptions import CondaHTTPError
from conda.utils import url_path
from conda_index.index import update_index as _update_index

from . import utils
from .utils import (
    get_logger,
)

log = get_logger(__name__)


local_index_timestamp = 0
cached_index = None
local_subdir = ""
local_output_folder = ""
cached_channels = []

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

        local_index_timestamp = os.path.getmtime(index_file)
        local_subdir = subdir
        local_output_folder = output_folder
        cached_channels = channel_urls
    return cached_index, local_index_timestamp, None


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
            write_bz2=False,
            write_zst=False,
        )
