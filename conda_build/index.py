# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import bz2
import copy
import fnmatch
import functools
import json
import logging
import os
import subprocess
import sys
import time
from collections import OrderedDict
from concurrent.futures import Executor, ProcessPoolExecutor
from datetime import datetime
from functools import partial
from itertools import groupby
from numbers import Number
from os.path import (
    abspath,
    basename,
    dirname,
    getmtime,
    getsize,
    isfile,
    join,
    splitext,
)
from pathlib import Path
from uuid import uuid4

import conda_package_handling.api
import pytz
import yaml

# Lots of conda internals here.  Should refactor to use exports.
from conda.common.compat import ensure_binary

#  BAD BAD BAD - conda internals
from conda.core.subdir_data import SubdirData
from conda.models.channel import Channel
from conda_index.index import update_index as _update_index
from conda_package_handling.api import InvalidArchiveError
from jinja2 import Environment, PackageLoader
from tqdm import tqdm
from yaml.constructor import ConstructorError
from yaml.parser import ParserError
from yaml.reader import ReaderError
from yaml.scanner import ScannerError

from conda_build import conda_interface, utils

from .conda_interface import (
    CondaError,
    CondaHTTPError,
    MatchSpec,
    Resolve,
    TemporaryDirectory,
    VersionOrder,
    context,
    get_index,
    human_bytes,
    url_path,
)
from .deprecations import deprecated
from .utils import (
    CONDA_PACKAGE_EXTENSION_V1,
    CONDA_PACKAGE_EXTENSION_V2,
    CONDA_PACKAGE_EXTENSIONS,
    FileNotFoundError,
    JSONDecodeError,
    get_logger,
    glob,
)

log = get_logger(__name__)


# use this for debugging, because ProcessPoolExecutor isn't pdb/ipdb friendly
class DummyExecutor(Executor):
    def map(self, func, *iterables):
        for iterable in iterables:
            for thing in iterable:
                yield func(thing)


try:
    from conda.base.constants import NAMESPACE_PACKAGE_NAMES, NAMESPACES_MAP
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
local_output_folder = ""
cached_channels = []
channel_data = {}


# TODO: support for libarchive seems to have broken ability to use multiple threads here.
#    The new conda format is so much faster that it more than makes up for it.  However, it
#    would be nice to fix this at some point.
MAX_THREADS_DEFAULT = (
    os.cpu_count() if (hasattr(os, "cpu_count") and os.cpu_count() > 1) else 1
)
if (
    sys.platform == "win32"
):  # see https://github.com/python/cpython/commit/8ea0fd85bc67438f679491fae29dfe0a3961900a
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
    """
    Used during package builds to create/get a channel including any local or
    newly built packages. This function both updates and gets index data.
    """
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
            _delegated_update_index(output_folder, verbose=debug)

            # replace noarch with native subdir - this ends up building an index with both the
            #      native content and the noarch content.

            if subdir == "noarch":
                subdir = conda_interface.subdir
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


# Everything below is deprecated to maintain API/feature compatibility.


@deprecated("3.25.0", "4.0.0", addendum="Use standalone conda-index.")
def update_index(
    dir_path,
    check_md5=False,
    channel_name=None,
    patch_generator=None,
    threads=MAX_THREADS_DEFAULT,
    verbose=False,
    progress=False,
    hotfix_source_repo=None,
    subdirs=None,
    warn=True,
    current_index_versions=None,
    debug=False,
    index_file=None,
):
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
            log.warn(
                "The update_index function has changed to index all subdirs at once.  You're pointing it at a single subdir.  "
                "Please update your code to point it at the channel root, rather than a subdir."
            )
        return update_index(
            base_path,
            check_md5=check_md5,
            channel_name=channel_name,
            threads=threads,
            verbose=verbose,
            progress=progress,
            hotfix_source_repo=hotfix_source_repo,
            current_index_versions=current_index_versions,
        )
    return ChannelIndex(
        dir_path,
        channel_name,
        subdirs=subdirs,
        threads=threads,
        deep_integrity_check=check_md5,
        debug=debug,
    ).index(
        patch_generator=patch_generator,
        verbose=verbose,
        progress=progress,
        hotfix_source_repo=hotfix_source_repo,
        current_index_versions=current_index_versions,
        index_file=index_file,
    )


def _determine_namespace(info):
    if info.get("namespace"):
        namespace = info["namespace"]
    else:
        depends_names = set()
        for spec in info.get("depends", []):
            try:
                depends_names.add(MatchSpec(spec).name)
            except CondaError:
                pass
        spaces = depends_names & NAMESPACE_PACKAGE_NAMES
        if len(spaces) == 1:
            namespace = NAMESPACES_MAP[spaces.pop()]
        else:
            namespace = "global"
        info["namespace"] = namespace

    if not info.get("namespace_in_name") and "-" in info["name"]:
        namespace_prefix, reduced_name = info["name"].split("-", 1)
        if namespace_prefix == namespace:
            info["name_in_channel"] = info["name"]
            info["name"] = reduced_name

    return namespace, info.get("name_in_channel", info["name"]), info["name"]


def _make_seconds(timestamp):
    timestamp = int(timestamp)
    if timestamp > 253402300799:  # 9999-12-31
        timestamp //= (
            1000  # convert milliseconds to seconds; see conda/conda-build#1988
        )
    return timestamp


# ==========================================================================


REPODATA_VERSION = 1
CHANNELDATA_VERSION = 1
REPODATA_JSON_FN = "repodata.json"
REPODATA_FROM_PKGS_JSON_FN = "repodata_from_packages.json"
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
            record[field_name] = record[field_name].strip().replace("\n", " ")
        except AttributeError:
            # sometimes description gets added as a list instead of just a string
            record[field_name] = record[field_name][0].strip().replace("\n", " ")


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


def _get_jinja2_environment():
    def _filter_strftime(dt, dt_format):
        if isinstance(dt, Number):
            if dt > 253402300799:  # 9999-12-31
                dt //= 1000  # convert milliseconds to seconds; see #1988
            dt = datetime.utcfromtimestamp(dt).replace(tzinfo=pytz.timezone("UTC"))
        return dt.strftime(dt_format)

    def _filter_add_href(text, link, **kwargs):
        if link:
            kwargs_list = [f'href="{link}"']
            kwargs_list.append(f'alt="{text}"')
            kwargs_list += [f'{k}="{v}"' for k, v in kwargs.items()]
            return "<a {}>{}</a>".format(" ".join(kwargs_list), text)
        else:
            return text

    environment = Environment(
        loader=PackageLoader("conda_build", "templates"),
    )
    environment.filters["human_bytes"] = human_bytes
    environment.filters["strftime"] = _filter_strftime
    environment.filters["add_href"] = _filter_add_href
    environment.trim_blocks = True
    environment.lstrip_blocks = True

    return environment


def _maybe_write(path, content, write_newline_end=False, content_is_binary=False):
    # Create the temp file next "path" so that we can use an atomic move, see
    # https://github.com/conda/conda-build/issues/3833
    temp_path = f"{path}.{uuid4()}"

    if not content_is_binary:
        content = ensure_binary(content)
    with open(temp_path, "wb") as fh:
        fh.write(content)
        if write_newline_end:
            fh.write(b"\n")
    if isfile(path):
        if utils.md5_file(temp_path) == utils.md5_file(path):
            # No need to change mtimes. The contents already match.
            os.unlink(temp_path)
            return False
    # log.info("writing %s", path)
    utils.move_with_fallback(temp_path, path)
    return True


def _make_build_string(build, build_number):
    build_number_as_string = str(build_number)
    if build.endswith(build_number_as_string):
        build = build[: -len(build_number_as_string)]
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
            "    and are not declared as external dependencies:",
        ]
        for dep_name in sorted(missing_dependencies):
            builder.append("  %s" % dep_name)
            for subdir_fn in sorted(missing_dependencies[dep_name]):
                builder.append("    - %s" % subdir_fn)
                subdir, fn = subdir_fn.split("/")
                popped = patched_repodata["packages"].pop(fn, None)
                if popped:
                    patched_repodata["removed"].append(fn)

        builder.append("The associated packages are being removed from the index.")
        builder.append("")
        log.warn("\n".join(builder))


def _cache_post_install_details(paths_cache_path, post_install_cache_path):
    post_install_details_json = {
        "binary_prefix": False,
        "text_prefix": False,
        "activate.d": False,
        "deactivate.d": False,
        "pre_link": False,
        "post_link": False,
        "pre_unlink": False,
    }
    if os.path.lexists(paths_cache_path):
        with open(paths_cache_path) as f:
            paths = json.load(f).get("paths", [])

        # get embedded prefix data from paths.json
        for f in paths:
            if f.get("prefix_placeholder"):
                if f.get("file_mode") == "binary":
                    post_install_details_json["binary_prefix"] = True
                elif f.get("file_mode") == "text":
                    post_install_details_json["text_prefix"] = True
            # check for any activate.d/deactivate.d scripts
            for k in ("activate.d", "deactivate.d"):
                if not post_install_details_json.get(k) and f["_path"].startswith(
                    "etc/conda/%s" % k
                ):
                    post_install_details_json[k] = True
            # check for any link scripts
            for pat in ("pre-link", "post-link", "pre-unlink"):
                if not post_install_details_json.get(pat) and fnmatch.fnmatch(
                    f["_path"], "*/.*-%s.*" % pat
                ):
                    post_install_details_json[pat.replace("-", "_")] = True

    with open(post_install_cache_path, "w") as fh:
        json.dump(post_install_details_json, fh)


def _cache_recipe(tmpdir, recipe_cache_path):
    recipe_path_search_order = (
        "info/recipe/meta.yaml.rendered",
        "info/recipe/meta.yaml",
        "info/meta.yaml",
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
            except (ConstructorError, ParserError, ScannerError, ReaderError):
                pass
    try:
        recipe_json_str = json.dumps(recipe_json)
    except TypeError:
        recipe_json.get("requirements", {}).pop("build")
        recipe_json_str = json.dumps(recipe_json)
    with open(recipe_cache_path, "w") as fh:
        fh.write(recipe_json_str)
    return recipe_json


def _cache_run_exports(tmpdir, run_exports_cache_path):
    run_exports = {}
    try:
        with open(os.path.join(tmpdir, "info", "run_exports.json")) as f:
            run_exports = json.load(f)
    except (OSError, FileNotFoundError):
        try:
            with open(os.path.join(tmpdir, "info", "run_exports.yaml")) as f:
                run_exports = yaml.safe_load(f)
        except (OSError, FileNotFoundError):
            log.debug("%s has no run_exports file (this is OK)" % tmpdir)
    with open(run_exports_cache_path, "w") as fh:
        json.dump(run_exports, fh)


def _cache_icon(tmpdir, recipe_json, icon_cache_path):
    # If a conda package contains an icon, also extract and cache that in an .icon/
    # directory.  The icon file name is the name of the package, plus the extension
    # of the icon file as indicated by the meta.yaml `app/icon` key.
    # apparently right now conda-build renames all icons to 'icon.png'
    # What happens if it's an ico file, or a svg file, instead of a png? Not sure!
    app_icon_path = recipe_json.get("app", {}).get("icon")
    if app_icon_path:
        icon_path = os.path.join(tmpdir, "info", "recipe", app_icon_path)
        if not os.path.lexists(icon_path):
            icon_path = os.path.join(tmpdir, "info", "icon.png")
        if os.path.lexists(icon_path):
            icon_cache_path += splitext(app_icon_path)[-1]
            utils.move_with_fallback(icon_path, icon_cache_path)


def _make_subdir_index_html(channel_name, subdir, repodata_packages, extra_paths):
    environment = _get_jinja2_environment()
    template = environment.get_template("subdir-index.html.j2")
    rendered_html = template.render(
        title="{}/{}".format(channel_name or "", subdir),
        packages=repodata_packages,
        current_time=datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")),
        extra_paths=extra_paths,
    )
    return rendered_html


def _make_channeldata_index_html(channel_name, channeldata):
    environment = _get_jinja2_environment()
    template = environment.get_template("channeldata-index.html.j2")
    rendered_html = template.render(
        title=channel_name,
        packages=channeldata["packages"],
        subdirs=channeldata["subdirs"],
        current_time=datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")),
    )
    return rendered_html


def _get_source_repo_git_info(path):
    is_repo = subprocess.check_output(
        ["git", "rev-parse", "--is-inside-work-tree"], cwd=path
    )
    if is_repo.strip().decode("utf-8") == "true":
        output = subprocess.check_output(
            ["git", "log", "--pretty=format:'%h|%ad|%an|%s'", "--date=unix"], cwd=path
        )
        commits = []
        for line in output.decode("utf-8").strip().splitlines():
            _hash, _time, _author, _desc = line.split("|")
            commits.append(
                {
                    "hash": _hash,
                    "timestamp": int(_time),
                    "author": _author,
                    "description": _desc,
                }
            )
    return commits


def _cache_info_file(tmpdir, info_fn, cache_path):
    info_path = os.path.join(tmpdir, "info", info_fn)
    if os.path.lexists(info_path):
        utils.move_with_fallback(info_path, cache_path)


def _alternate_file_extension(fn):
    cache_fn = fn
    for ext in CONDA_PACKAGE_EXTENSIONS:
        cache_fn = cache_fn.replace(ext, "")
    other_ext = set(CONDA_PACKAGE_EXTENSIONS) - {fn.replace(cache_fn, "")}
    return cache_fn + next(iter(other_ext))


def _get_resolve_object(subdir, file_path=None, precs=None, repodata=None):
    packages = {}
    conda_packages = {}
    if file_path:
        with open(file_path) as fi:
            packages = json.load(fi)
            recs = json.load(fi)
            for k, v in recs.items():
                if k.endswith(CONDA_PACKAGE_EXTENSION_V1):
                    packages[k] = v
                elif k.endswith(CONDA_PACKAGE_EXTENSION_V2):
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

    channel = Channel("https://conda.anaconda.org/dummy-channel/%s" % subdir)
    sd = SubdirData(channel)
    sd._process_raw_repodata_str(json.dumps(repodata))
    sd._loaded = True
    SubdirData._cache_[channel.url(with_credentials=True)] = sd

    index = {prec: prec for prec in precs or sd._package_records}
    r = Resolve(index, channels=(channel,))
    return r


def _get_newest_versions(r, pins={}):
    groups = {}
    for g_name, g_recs in r.groups.items():
        if g_name in pins:
            matches = []
            for pin in pins[g_name]:
                version = r.find_matches(MatchSpec(f"{g_name}={pin}"))[0].version
                matches.extend(r.find_matches(MatchSpec(f"{g_name}={version}")))
        else:
            version = r.groups[g_name][0].version
            matches = r.find_matches(MatchSpec(f"{g_name}={version}"))
        groups[g_name] = matches
    return [pkg for group in groups.values() for pkg in group]


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
                        expanded_groups[ms.name] = set(
                            expanded_groups.get(ms.name, [])
                        ) | set(
                            original_r.find_matches(MatchSpec(f"{ms.name}={version}"))
                        )
                seen_specs.add(dep_spec)
    return [pkg for group in expanded_groups.values() for pkg in group]


def _add_prev_ver_for_features(new_r, orig_r):
    expanded_groups = copy.deepcopy(new_r.groups)
    for g_name in new_r.groups:
        if not any(m.track_features or m.features for m in new_r.groups[g_name]):
            # no features so skip
            continue

        # versions are sorted here so this is the latest
        latest_version = VersionOrder(str(new_r.groups[g_name][0].version))
        if g_name in orig_r.groups:
            # now we iterate through the list to find the next to latest
            # without a feature
            keep_m = None
            for i in range(len(orig_r.groups[g_name])):
                _m = orig_r.groups[g_name][i]
                if VersionOrder(str(_m.version)) <= latest_version and not (
                    _m.track_features or _m.features
                ):
                    keep_m = _m
                    break
            if keep_m is not None:
                expanded_groups[g_name] = {keep_m} | set(
                    expanded_groups.get(g_name, [])
                )

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
        matches = set(r.find_matches(MatchSpec(f"{g_name}={version}")))
        if g_name in pins:
            for pin_value in pins[g_name]:
                version = r.find_matches(MatchSpec(f"{g_name}={pin_value}"))[0].version
                matches.update(r.find_matches(MatchSpec(f"{g_name}={version}")))
        groups[g_name] = matches

    # add the deps of the stuff in the index
    new_r = _get_resolve_object(
        subdir, precs=[pkg for group in groups.values() for pkg in group]
    )
    new_r = _get_resolve_object(subdir, precs=_add_missing_deps(new_r, r))

    # now for any pkg with features, add at least one previous version
    # also return
    return set(_add_prev_ver_for_features(new_r, r))


def _build_current_repodata(subdir, repodata, pins):
    r = _get_resolve_object(subdir, repodata=repodata)
    keep_pkgs = _shard_newest_packages(subdir, r, pins)
    new_repodata = {
        k: repodata[k] for k in set(repodata.keys()) - {"packages", "packages.conda"}
    }
    packages = {}
    conda_packages = {}
    for keep_pkg in keep_pkgs:
        if keep_pkg.fn.endswith(CONDA_PACKAGE_EXTENSION_V2):
            conda_packages[keep_pkg.fn] = repodata["packages.conda"][keep_pkg.fn]
            # in order to prevent package churn we consider the md5 for the .tar.bz2 that matches the .conda file
            #    This holds when .conda files contain the same files as .tar.bz2, which is an assumption we'll make
            #    until it becomes more prevalent that people provide only .conda files and just skip .tar.bz2
            counterpart = keep_pkg.fn.replace(
                CONDA_PACKAGE_EXTENSION_V2, CONDA_PACKAGE_EXTENSION_V1
            )
            conda_packages[keep_pkg.fn]["legacy_bz2_md5"] = (
                repodata["packages"].get(counterpart, {}).get("md5")
            )
        elif keep_pkg.fn.endswith(CONDA_PACKAGE_EXTENSION_V1):
            packages[keep_pkg.fn] = repodata["packages"][keep_pkg.fn]
    new_repodata["packages"] = packages
    new_repodata["packages.conda"] = conda_packages
    return new_repodata


class ChannelIndex:
    def __init__(
        self,
        channel_root,
        channel_name,
        subdirs=None,
        threads=MAX_THREADS_DEFAULT,
        deep_integrity_check=False,
        debug=False,
    ):
        self.channel_root = abspath(channel_root)
        self.channel_name = channel_name or basename(channel_root.rstrip("/"))
        self._subdirs = subdirs
        self.thread_executor = (
            DummyExecutor()
            if debug or sys.version_info.major == 2 or threads == 1
            else ProcessPoolExecutor(threads)
        )
        self.deep_integrity_check = deep_integrity_check

    def index(
        self,
        patch_generator,
        hotfix_source_repo=None,
        verbose=False,
        progress=False,
        current_index_versions=None,
        index_file=None,
    ):
        if verbose:
            level = logging.DEBUG
        else:
            level = logging.ERROR

        with utils.LoggingContext(level, loggers=[__name__]):
            if not self._subdirs:
                detected_subdirs = {
                    subdir.name
                    for subdir in os.scandir(self.channel_root)
                    if subdir.name in utils.DEFAULT_SUBDIRS and subdir.is_dir()
                }
                log.debug("found subdirs %s" % detected_subdirs)
                self.subdirs = subdirs = sorted(detected_subdirs | {"noarch"})
            else:
                self.subdirs = subdirs = sorted(set(self._subdirs) | {"noarch"})

            # Step 1. Lock local channel.
            with utils.try_acquire_locks(
                [utils.get_lock(self.channel_root)], timeout=900
            ):
                channel_data = {}
                channeldata_file = os.path.join(self.channel_root, "channeldata.json")
                if os.path.isfile(channeldata_file):
                    with open(channeldata_file) as f:
                        channel_data = json.load(f)
                # Step 2. Collect repodata from packages, save to pkg_repodata.json file
                with tqdm(
                    total=len(subdirs), disable=(verbose or not progress), leave=False
                ) as t:
                    for subdir in subdirs:
                        t.set_description("Subdir: %s" % subdir)
                        t.update()
                        with tqdm(
                            total=8, disable=(verbose or not progress), leave=False
                        ) as t2:
                            t2.set_description("Gathering repodata")
                            t2.update()
                            _ensure_valid_channel(self.channel_root, subdir)
                            repodata_from_packages = self.index_subdir(
                                subdir,
                                verbose=verbose,
                                progress=progress,
                                index_file=index_file,
                            )

                            t2.set_description("Writing pre-patch repodata")
                            t2.update()
                            self._write_repodata(
                                subdir,
                                repodata_from_packages,
                                REPODATA_FROM_PKGS_JSON_FN,
                            )

                            # Step 3. Apply patch instructions.
                            t2.set_description("Applying patch instructions")
                            t2.update()
                            patched_repodata, patch_instructions = self._patch_repodata(
                                subdir, repodata_from_packages, patch_generator
                            )

                            # Step 4. Save patched and augmented repodata.
                            # If the contents of repodata have changed, write a new repodata.json file.
                            # Also create associated index.html.

                            t2.set_description("Writing patched repodata")
                            t2.update()
                            self._write_repodata(
                                subdir, patched_repodata, REPODATA_JSON_FN
                            )
                            t2.set_description("Building current_repodata subset")
                            t2.update()
                            current_repodata = _build_current_repodata(
                                subdir, patched_repodata, pins=current_index_versions
                            )
                            t2.set_description("Writing current_repodata subset")
                            t2.update()
                            self._write_repodata(
                                subdir,
                                current_repodata,
                                json_filename="current_repodata.json",
                            )

                            t2.set_description("Writing subdir index HTML")
                            t2.update()
                            self._write_subdir_index_html(subdir, patched_repodata)

                            t2.set_description("Updating channeldata")
                            t2.update()
                            self._update_channeldata(
                                channel_data, patched_repodata, subdir
                            )

                # Step 7. Create and write channeldata.
                self._write_channeldata_index_html(channel_data)
                self._write_channeldata(channel_data)

    def index_subdir(self, subdir, index_file=None, verbose=False, progress=False):
        subdir_path = join(self.channel_root, subdir)
        self._ensure_dirs(subdir)
        repodata_json_path = join(subdir_path, REPODATA_FROM_PKGS_JSON_FN)

        if verbose:
            log.info("Building repodata for %s" % subdir_path)

        # gather conda package filenames in subdir
        # we'll process these first, because reading their metadata is much faster
        fns_in_subdir = {
            fn
            for fn in os.listdir(subdir_path)
            if fn.endswith(".conda") or fn.endswith(".tar.bz2")
        }

        # load current/old repodata
        try:
            with open(repodata_json_path) as fh:
                old_repodata = json.load(fh) or {}
        except (OSError, JSONDecodeError):
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
        stat_cache_path = join(subdir_path, ".cache", "stat.json")
        try:
            with open(stat_cache_path) as fh:
                stat_cache = json.load(fh) or {}
        except:
            stat_cache = {}

        stat_cache_original = stat_cache.copy()

        remove_set = old_repodata_fns - fns_in_subdir
        ignore_set = set(old_repodata.get("removed", []))
        try:
            # calculate all the paths and figure out what we're going to do with them
            # add_set: filenames that aren't in the current/old repodata, but exist in the subdir
            if index_file:
                with open(index_file) as fin:
                    add_set = set()
                    for line in fin:
                        fn_subdir, fn = line.strip().split("/")
                        if fn_subdir != subdir:
                            continue
                        if fn.endswith(".conda") or fn.endswith(".tar.bz2"):
                            add_set.add(fn)
            else:
                add_set = fns_in_subdir - old_repodata_fns

            add_set -= ignore_set

            # update_set: Filenames that are in both old repodata and new repodata,
            #     and whose contents have changed based on file size or mtime. We're
            #     not using md5 here because it takes too long. If needing to do full md5 checks,
            #     use the --deep-integrity-check flag / self.deep_integrity_check option.
            update_set = self._calculate_update_set(
                subdir,
                fns_in_subdir,
                old_repodata_fns,
                stat_cache,
                verbose=verbose,
                progress=progress,
            )
            # unchanged_set: packages in old repodata whose information can carry straight
            #     across to new repodata
            unchanged_set = set(old_repodata_fns - update_set - remove_set - ignore_set)

            assert isinstance(unchanged_set, set)  # faster `in` queries

            # clean up removed files
            removed_set = old_repodata_fns - fns_in_subdir
            for fn in removed_set:
                if fn in stat_cache:
                    del stat_cache[fn]

            new_repodata_packages = {
                k: v
                for k, v in old_repodata.get("packages", {}).items()
                if k in unchanged_set
            }
            new_repodata_conda_packages = {
                k: v
                for k, v in old_repodata.get("packages.conda", {}).items()
                if k in unchanged_set
            }

            for k in sorted(unchanged_set):
                if not (k in new_repodata_packages or k in new_repodata_conda_packages):
                    fn, rec = ChannelIndex._load_index_from_cache(
                        self.channel_root, subdir, fn, stat_cache
                    )
                    # this is how we pass an exception through.  When fn == rec, there's been a problem,
                    #    and we need to reload this file
                    if fn == rec:
                        update_set.add(fn)
                    else:
                        if fn.endswith(CONDA_PACKAGE_EXTENSION_V1):
                            new_repodata_packages[fn] = rec
                        else:
                            new_repodata_conda_packages[fn] = rec

            # Invalidate cached files for update_set.
            # Extract and cache update_set and add_set, then add to new_repodata_packages.
            # This is also where we update the contents of the stat_cache for successfully
            #   extracted packages.
            # Sorting here prioritizes .conda files ('c') over .tar.bz2 files ('b')
            hash_extract_set = (*add_set, *update_set)

            extract_func = functools.partial(
                ChannelIndex._extract_to_cache, self.channel_root, subdir
            )
            # split up the set by .conda packages first, then .tar.bz2.  This avoids race conditions
            #    with execution in parallel that would end up in the same place.
            for conda_format in tqdm(
                CONDA_PACKAGE_EXTENSIONS,
                desc="File format",
                disable=(verbose or not progress),
                leave=False,
            ):
                for fn, mtime, size, index_json in tqdm(
                    self.thread_executor.map(
                        extract_func,
                        (fn for fn in hash_extract_set if fn.endswith(conda_format)),
                    ),
                    desc="hash & extract packages for %s" % subdir,
                    disable=(verbose or not progress),
                    leave=False,
                ):
                    # fn can be None if the file was corrupt or no longer there
                    if fn and mtime:
                        stat_cache[fn] = {"mtime": int(mtime), "size": size}
                        if index_json:
                            if fn.endswith(CONDA_PACKAGE_EXTENSION_V2):
                                new_repodata_conda_packages[fn] = index_json
                            else:
                                new_repodata_packages[fn] = index_json
                        else:
                            log.error(
                                "Package at %s did not contain valid index.json data.  Please"
                                " check the file and remove/redownload if necessary to obtain "
                                "a valid package." % os.path.join(subdir_path, fn)
                            )

            new_repodata = {
                "packages": new_repodata_packages,
                "packages.conda": new_repodata_conda_packages,
                "info": {
                    "subdir": subdir,
                },
                "repodata_version": REPODATA_VERSION,
                "removed": sorted(list(ignore_set)),
            }
        finally:
            if stat_cache != stat_cache_original:
                # log.info("writing stat cache to %s", stat_cache_path)
                with open(stat_cache_path, "w") as fh:
                    json.dump(stat_cache, fh)
        return new_repodata

    def _ensure_dirs(self, subdir: str):
        """Create cache directories within a subdir.

        Args:
            subdir (str): name of the subdirectory
        """
        # Create all cache directories in the subdir.
        cache_path = Path(self.channel_root, subdir, ".cache")
        cache_path.mkdir(parents=True, exist_ok=True)
        (cache_path / "index").mkdir(exist_ok=True)
        (cache_path / "about").mkdir(exist_ok=True)
        (cache_path / "paths").mkdir(exist_ok=True)
        (cache_path / "recipe").mkdir(exist_ok=True)
        (cache_path / "run_exports").mkdir(exist_ok=True)
        (cache_path / "post_install").mkdir(exist_ok=True)
        (cache_path / "icon").mkdir(exist_ok=True)
        (cache_path / "recipe_log").mkdir(exist_ok=True)
        Path(self.channel_root, "icons").mkdir(exist_ok=True)

    def _calculate_update_set(
        self,
        subdir,
        fns_in_subdir,
        old_repodata_fns,
        stat_cache,
        verbose=False,
        progress=True,
    ):
        # Determine the packages that already exist in repodata, but need to be updated.
        # We're not using md5 here because it takes too long.
        candidate_fns = fns_in_subdir & old_repodata_fns
        subdir_path = join(self.channel_root, subdir)

        update_set = set()
        for fn in tqdm(
            iter(candidate_fns),
            desc="Finding updated files",
            disable=(verbose or not progress),
            leave=False,
        ):
            if fn not in stat_cache:
                update_set.add(fn)
            else:
                stat_result = os.stat(join(subdir_path, fn))
                if (
                    int(stat_result.st_mtime) != int(stat_cache[fn]["mtime"])
                    or stat_result.st_size != stat_cache[fn]["size"]
                ):
                    update_set.add(fn)
        return update_set

    @staticmethod
    def _extract_to_cache(channel_root, subdir, fn, second_try=False):
        # This method WILL reread the tarball. Probably need another one to exit early if
        # there are cases where it's fine not to reread.  Like if we just rebuild repodata
        # from the cached files, but don't use the existing repodata.json as a starting point.
        subdir_path = join(channel_root, subdir)

        # allow .conda files to reuse cache from .tar.bz2 and vice-versa.
        # Assumes that .tar.bz2 and .conda files have exactly the same
        # contents. This is convention, but not guaranteed, nor checked.
        alternate_cache_fn = _alternate_file_extension(fn)
        cache_fn = fn

        abs_fn = os.path.join(subdir_path, fn)

        stat_result = os.stat(abs_fn)
        size = stat_result.st_size
        mtime = stat_result.st_mtime
        retval = fn, mtime, size, None

        index_cache_path = join(subdir_path, ".cache", "index", cache_fn + ".json")
        about_cache_path = join(subdir_path, ".cache", "about", cache_fn + ".json")
        paths_cache_path = join(subdir_path, ".cache", "paths", cache_fn + ".json")
        recipe_cache_path = join(subdir_path, ".cache", "recipe", cache_fn + ".json")
        run_exports_cache_path = join(
            subdir_path, ".cache", "run_exports", cache_fn + ".json"
        )
        post_install_cache_path = join(
            subdir_path, ".cache", "post_install", cache_fn + ".json"
        )
        icon_cache_path = join(subdir_path, ".cache", "icon", cache_fn)

        log.debug("hashing, extracting, and caching %s" % fn)

        alternate_cache = False
        if not os.path.exists(index_cache_path) and os.path.exists(
            index_cache_path.replace(fn, alternate_cache_fn)
        ):
            alternate_cache = True

        try:
            # allow .tar.bz2 files to use the .conda cache, but not vice-versa.
            #    .conda readup is very fast (essentially free), but .conda files come from
            #    converting .tar.bz2 files, which can go wrong.  Forcing extraction for
            #    .conda files gives us a check on the validity of that conversion.
            if not fn.endswith(CONDA_PACKAGE_EXTENSION_V2) and os.path.isfile(
                index_cache_path
            ):
                with open(index_cache_path) as f:
                    index_json = json.load(f)
            elif not alternate_cache and (
                second_try or not os.path.exists(index_cache_path)
            ):
                with TemporaryDirectory() as tmpdir:
                    conda_package_handling.api.extract(
                        abs_fn, dest_dir=tmpdir, components="info"
                    )
                    index_file = os.path.join(tmpdir, "info", "index.json")
                    if not os.path.exists(index_file):
                        return retval
                    with open(index_file) as f:
                        index_json = json.load(f)

                    _cache_info_file(tmpdir, "about.json", about_cache_path)
                    _cache_info_file(tmpdir, "paths.json", paths_cache_path)
                    _cache_info_file(tmpdir, "recipe_log.json", paths_cache_path)
                    _cache_run_exports(tmpdir, run_exports_cache_path)
                    _cache_post_install_details(
                        paths_cache_path, post_install_cache_path
                    )
                    recipe_json = _cache_recipe(tmpdir, recipe_cache_path)
                    _cache_icon(tmpdir, recipe_json, icon_cache_path)

                # decide what fields to filter out, like has_prefix
                filter_fields = {
                    "arch",
                    "has_prefix",
                    "mtime",
                    "platform",
                    "ucs",
                    "requires_features",
                    "binstar",
                    "target-triplet",
                    "machine",
                    "operatingsystem",
                }
                for field_name in filter_fields & set(index_json):
                    del index_json[field_name]
            elif alternate_cache:
                # we hit the cache of the other file type.  Copy files to this name, and replace
                #    the size, md5, and sha256 values
                paths = [
                    index_cache_path,
                    about_cache_path,
                    paths_cache_path,
                    recipe_cache_path,
                    run_exports_cache_path,
                    post_install_cache_path,
                    icon_cache_path,
                ]
                bizarro_paths = [_.replace(fn, alternate_cache_fn) for _ in paths]
                for src, dest in zip(bizarro_paths, paths):
                    if os.path.exists(src):
                        try:
                            os.makedirs(os.path.dirname(dest))
                        except:
                            pass
                        utils.copy_into(src, dest)

                with open(index_cache_path) as f:
                    index_json = json.load(f)
            else:
                with open(index_cache_path) as f:
                    index_json = json.load(f)

            # calculate extra stuff to add to index.json cache, size, md5, sha256
            #    This is done always for all files, whether the cache is loaded or not,
            #    because the cache may be from the other file type.  We don't store this
            #    info in the cache to avoid confusion.
            index_json.update(conda_package_handling.api.get_pkg_details(abs_fn))

            with open(index_cache_path, "w") as fh:
                json.dump(index_json, fh)
            retval = fn, mtime, size, index_json
        except (InvalidArchiveError, KeyError, EOFError, JSONDecodeError):
            if not second_try:
                return ChannelIndex._extract_to_cache(
                    channel_root, subdir, fn, second_try=True
                )
        return retval

    @staticmethod
    def _load_index_from_cache(channel_root, subdir, fn, stat_cache):
        index_cache_path = join(channel_root, subdir, ".cache", "index", fn + ".json")
        try:
            with open(index_cache_path) as fh:
                index_json = json.load(fh)
        except (OSError, JSONDecodeError):
            index_json = fn

        return fn, index_json

    @staticmethod
    def _load_all_from_cache(channel_root, subdir, fn):
        subdir_path = join(channel_root, subdir)
        try:
            mtime = getmtime(join(subdir_path, fn))
        except FileNotFoundError:
            return {}
        # In contrast to self._load_index_from_cache(), this method reads up pretty much
        # all of the cached metadata, except for paths. It all gets dumped into a single map.
        index_cache_path = join(subdir_path, ".cache", "index", fn + ".json")
        about_cache_path = join(subdir_path, ".cache", "about", fn + ".json")
        recipe_cache_path = join(subdir_path, ".cache", "recipe", fn + ".json")
        run_exports_cache_path = join(
            subdir_path, ".cache", "run_exports", fn + ".json"
        )
        post_install_cache_path = join(
            subdir_path, ".cache", "post_install", fn + ".json"
        )
        icon_cache_path_glob = join(subdir_path, ".cache", "icon", fn + ".*")
        recipe_log_path = join(subdir_path, ".cache", "recipe_log", fn + ".json")

        data = {}
        for path in (
            recipe_cache_path,
            about_cache_path,
            index_cache_path,
            post_install_cache_path,
            recipe_log_path,
        ):
            try:
                if os.path.getsize(path) != 0:
                    with open(path) as fh:
                        data.update(json.load(fh))
            except (OSError, EOFError):
                pass

        try:
            icon_cache_paths = glob(icon_cache_path_glob)
            if icon_cache_paths:
                icon_cache_path = sorted(icon_cache_paths)[-1]
                icon_ext = icon_cache_path.rsplit(".", 1)[-1]
                channel_icon_fn = "{}.{}".format(data["name"], icon_ext)
                icon_url = "icons/" + channel_icon_fn
                icon_channel_path = join(channel_root, "icons", channel_icon_fn)
                icon_md5 = utils.md5_file(icon_cache_path)
                icon_hash = f"md5:{icon_md5}:{getsize(icon_cache_path)}"
                data.update(icon_hash=icon_hash, icon_url=icon_url)
                # log.info("writing icon from %s to %s", icon_cache_path, icon_channel_path)
                utils.move_with_fallback(icon_cache_path, icon_channel_path)
        except:
            pass

        # have to stat again, because we don't have access to the stat cache here
        data["mtime"] = mtime

        source = data.get("source", {})
        try:
            data.update({"source_" + k: v for k, v in source.items()})
        except AttributeError:
            # sometimes source is a  list instead of a dict
            pass
        _clear_newline_chars(data, "description")
        _clear_newline_chars(data, "summary")
        try:
            with open(run_exports_cache_path) as fh:
                data["run_exports"] = json.load(fh)
        except (OSError, EOFError):
            data["run_exports"] = {}
        return data

    def _write_repodata(self, subdir, repodata, json_filename):
        repodata_json_path = join(self.channel_root, subdir, json_filename)
        new_repodata_binary = (
            json.dumps(
                repodata,
                indent=2,
                sort_keys=True,
            )
            .replace("':'", "': '")
            .encode("utf-8")
        )
        write_result = _maybe_write(
            repodata_json_path, new_repodata_binary, write_newline_end=True
        )
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
                    "size": getsize(path),
                    "timestamp": int(getmtime(path)),
                    "sha256": utils.sha256_checksum(path),
                    "md5": utils.md5_file(path),
                }

        extra_paths = OrderedDict()
        _add_extra_path(extra_paths, join(subdir_path, REPODATA_JSON_FN))
        _add_extra_path(extra_paths, join(subdir_path, REPODATA_JSON_FN + ".bz2"))
        _add_extra_path(extra_paths, join(subdir_path, REPODATA_FROM_PKGS_JSON_FN))
        _add_extra_path(
            extra_paths, join(subdir_path, REPODATA_FROM_PKGS_JSON_FN + ".bz2")
        )
        # _add_extra_path(extra_paths, join(subdir_path, "repodata2.json"))
        _add_extra_path(extra_paths, join(subdir_path, "patch_instructions.json"))
        rendered_html = _make_subdir_index_html(
            self.channel_name, subdir, repodata_packages, extra_paths
        )
        index_path = join(subdir_path, "index.html")
        return _maybe_write(index_path, rendered_html)

    def _write_channeldata_index_html(self, channeldata):
        rendered_html = _make_channeldata_index_html(self.channel_name, channeldata)
        index_path = join(self.channel_root, "index.html")
        _maybe_write(index_path, rendered_html)

    def _update_channeldata(self, channel_data, repodata, subdir):
        legacy_packages = repodata["packages"]
        conda_packages = repodata["packages.conda"]

        use_these_legacy_keys = set(legacy_packages.keys()) - {
            k[:-6] + CONDA_PACKAGE_EXTENSION_V1 for k in conda_packages.keys()
        }
        all_packages = conda_packages.copy()
        all_packages.update({k: legacy_packages[k] for k in use_these_legacy_keys})
        package_data = channel_data.get("packages", {})

        def _append_group(groups, candidates):
            candidate = sorted(candidates, key=lambda x: x[1].get("timestamp", 0))[-1]
            pkg_dict = candidate[1]
            pkg_name = pkg_dict["name"]

            run_exports = package_data.get(pkg_name, {}).get("run_exports", {})
            if (
                pkg_name not in package_data
                or subdir not in package_data.get(pkg_name, {}).get("subdirs", [])
                or package_data.get(pkg_name, {}).get("timestamp", 0)
                < _make_seconds(pkg_dict.get("timestamp", 0))
                or run_exports
                and pkg_dict["version"] not in run_exports
            ):
                groups.append(candidate)

        groups = []
        for name, group in groupby(all_packages.items(), lambda x: x[1]["name"]):
            if name not in package_data or package_data[name].get("run_exports"):
                # pay special attention to groups that have run_exports - we need to process each version
                # group by version; take newest per version group.  We handle groups that are not
                #    in the index t all yet similarly, because we can't check if they have any run_exports
                for _, vgroup in groupby(group, lambda x: x[1]["version"]):
                    _append_group(groups, vgroup)
            else:
                # take newest per group
                _append_group(groups, group)

        def _replace_if_newer_and_present(pd, data, erec, data_newer, k):
            if data.get(k) and (data_newer or not erec.get(k)):
                pd[k] = data[k]
            else:
                pd[k] = erec.get(k)

        # unzipping
        fns, fn_dicts = [], []
        if groups:
            fns, fn_dicts = zip(*groups)

        load_func = functools.partial(
            ChannelIndex._load_all_from_cache,
            self.channel_root,
            subdir,
        )
        for fn_dict, data in zip(fn_dicts, self.thread_executor.map(load_func, fns)):
            if data:
                data.update(fn_dict)
                name = data["name"]
                # existing record
                erec = package_data.get(name, {})
                data_v = data.get("version", "0")
                erec_v = erec.get("version", "0")
                data_newer = VersionOrder(data_v) > VersionOrder(erec_v)

                package_data[name] = package_data.get(name, {})
                # keep newer value for these
                for k in (
                    "description",
                    "dev_url",
                    "doc_url",
                    "doc_source_url",
                    "home",
                    "license",
                    "source_url",
                    "source_git_url",
                    "summary",
                    "icon_url",
                    "icon_hash",
                    "tags",
                    "identifiers",
                    "keywords",
                    "recipe_origin",
                    "version",
                ):
                    _replace_if_newer_and_present(
                        package_data[name], data, erec, data_newer, k
                    )

                # keep any true value for these, since we don't distinguish subdirs
                for k in (
                    "binary_prefix",
                    "text_prefix",
                    "activate.d",
                    "deactivate.d",
                    "pre_link",
                    "post_link",
                    "pre_unlink",
                ):
                    package_data[name][k] = any((data.get(k), erec.get(k)))

                package_data[name]["subdirs"] = sorted(
                    list(set(erec.get("subdirs", []) + [subdir]))
                )
                # keep one run_exports entry per version of the package, since these vary by version
                run_exports = erec.get("run_exports", {})
                exports_from_this_version = data.get("run_exports")
                if exports_from_this_version:
                    run_exports[data_v] = data.get("run_exports")
                package_data[name]["run_exports"] = run_exports
                package_data[name]["timestamp"] = _make_seconds(
                    max(
                        data.get("timestamp", 0),
                        channel_data.get(name, {}).get("timestamp", 0),
                    )
                )

        channel_data.update(
            {
                "channeldata_version": CHANNELDATA_VERSION,
                "subdirs": sorted(
                    list(set(channel_data.get("subdirs", []) + [subdir]))
                ),
                "packages": package_data,
            }
        )

    def _write_channeldata(self, channeldata):
        # trim out commits, as they can take up a ton of space.  They're really only for the RSS feed.
        for _pkg, pkg_dict in channeldata.get("packages", {}).items():
            if "commits" in pkg_dict:
                del pkg_dict["commits"]
        channeldata_path = join(self.channel_root, "channeldata.json")
        content = json.dumps(channeldata, indent=2, sort_keys=True).replace(
            "':'", "': '"
        )
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
        gen_patch_path = patch_generator or join(self.channel_root, "gen_patch.py")
        if isfile(gen_patch_path):
            log.debug(f"using patch generator {gen_patch_path} for {subdir}")

            # https://stackoverflow.com/a/41595552/2127762
            try:
                from importlib.util import module_from_spec, spec_from_file_location

                spec = spec_from_file_location("a_b", gen_patch_path)
                mod = module_from_spec(spec)

                spec.loader.exec_module(mod)
            # older pythons
            except ImportError:
                import imp

                mod = imp.load_source("a_b", gen_patch_path)

            instructions = mod._patch_repodata(repodata, subdir)

            if instructions.get("patch_instructions_version", 0) > 1:
                raise RuntimeError("Incompatible patch instructions version")

            return instructions
        else:
            if patch_generator:
                raise ValueError(
                    "Specified metadata patch file '{}' does not exist.  Please try an absolute "
                    "path, or examine your relative path carefully with respect to your cwd.".format(
                        patch_generator
                    )
                )
            return {}

    def _write_patch_instructions(self, subdir, instructions):
        new_patch = json.dumps(instructions, indent=2, sort_keys=True).replace(
            "':'", "': '"
        )
        patch_instructions_path = join(
            self.channel_root, subdir, "patch_instructions.json"
        )
        _maybe_write(patch_instructions_path, new_patch, True)

    def _load_instructions(self, subdir):
        patch_instructions_path = join(
            self.channel_root, subdir, "patch_instructions.json"
        )
        if isfile(patch_instructions_path):
            log.debug("using patch instructions %s" % patch_instructions_path)
            with open(patch_instructions_path) as fh:
                instructions = json.load(fh)
                if instructions.get("patch_instructions_version", 0) > 1:
                    raise RuntimeError("Incompatible patch instructions version")
                return instructions
        return {}

    def _patch_repodata(self, subdir, repodata, patch_generator=None):
        if patch_generator and any(
            patch_generator.endswith(ext) for ext in CONDA_PACKAGE_EXTENSIONS
        ):
            instructions = self._load_patch_instructions_tarball(
                subdir, patch_generator
            )
        else:
            instructions = self._create_patch_instructions(
                subdir, repodata, patch_generator
            )
        if instructions:
            self._write_patch_instructions(subdir, instructions)
        else:
            instructions = self._load_instructions(subdir)
        if instructions.get("patch_instructions_version", 0) > 1:
            raise RuntimeError("Incompatible patch instructions version")

        return _apply_instructions(subdir, repodata, instructions), instructions
