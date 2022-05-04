"""
cache conda indexing metadata in sqlite.
"""

import os.path
import json
import fnmatch
import sqlite3

import yaml
from yaml.constructor import ConstructorError
from yaml.parser import ParserError
from yaml.scanner import ScannerError
from yaml.reader import ReaderError

from conda_package_handling.api import InvalidArchiveError

from os.path import join

from .convert_cache import create, convert_cache
from .common import connect
from . import package_streaming

from ..utils import (
    CONDA_PACKAGE_EXTENSION_V1,
    CONDA_PACKAGE_EXTENSION_V2,
    CONDA_PACKAGE_EXTENSIONS,
    FileNotFoundError,
    JSONDecodeError,
    get_logger,
    glob,
)

from conda_package_handling.utils import checksums


log = get_logger(__name__)


class CondaIndexCache:
    def __init__(self, subdir_path, subdir):
        print(f"CondaIndexCache {subdir_path=}, {subdir=}")
        self.cache_dir = os.path.join(subdir_path, ".cache")
        self.subdir_path = subdir_path  # must include channel name
        self.subdir = subdir
        self.db_filename = os.path.join(self.cache_dir, "cache.db")
        self.cache_is_brand_new = not os.path.exists(self.db_filename)
        self.db = connect(self.db_filename)
        print(f"{self.db_filename=} {self.cache_is_brand_new=}")
        create(self.db)

    @property
    def channel(self):
        # XXX
        return os.path.basename(os.path.dirname(self.subdir_path))

    def convert(self, force=False):
        """
        Load filesystem cache into sqlite.
        """
        if self.cache_is_brand_new or force:
            raise NotImplementedError("convert_cache expects a tar archive")
            # stream a new tarfile archive...
            convert_cache(self.db, self.cache_dir)

    def stat_cache(self):
        """
        Load path: mtime, size mapping
        """
        # XXX no long-term need to emulate old stat.json
        return {
            row["path"]: {"mtime": row["mtime"], "size": row["size"]}
            for row in self.db.execute("SELECT path, mtime, size FROM stat")
        }

    def extract_to_cache(self, channel_root, subdir, fn):
        with self.db:  # transaction
            return self._extract_to_cache_(channel_root, subdir, fn)

    def save_stat_cache(self, stat_cache):
        # XXX smarter to do this differently in sql
        with self.db:
            self.db.execute("DELETE FROM stat")
            for fn, value in stat_cache.items():
                # XXX update caller to deal with this type of key
                value["path"] = f"{self.channel}/{self.subdir}/{fn}"

                self.db.execute(
                    "INSERT OR REPLACE INTO stat (path, mtime, size) VALUES (:path, :mtime, :size)",
                    value,
                )

    def _extract_to_cache_(self, channel_root, subdir, fn, second_try=False):
        # This method WILL reread the tarball. Probably need another one to exit early if
        # there are cases where it's fine not to reread.  Like if we just rebuild repodata
        # from the cached files, but don't use the existing repodata.json as a starting point.
        subdir_path = join(channel_root, subdir)

        abs_fn = join(subdir_path, fn)

        stat_result = os.stat(abs_fn)
        size = stat_result.st_size
        mtime = stat_result.st_mtime
        retval = fn, mtime, size, None

        log.debug("sql hashing, extracting, and caching %s" % fn)

        try:
            # skip re-use conda/bz2 cache in sqlite version
            database_path = f"{self.channel}/{self.subdir}/{fn}"

            # None, or a tuple containing the row
            # don't bother skipping on second_try
            cached_row = self.db.execute(
                "SELECT index_json FROM index_json WHERE path = :path",
                {"path": database_path},
            ).fetchone()

            if cached_row and not second_try:
                # XXX load cached cached index.json from sql in bulk
                # sqlite has very low latency but we can do better
                index_json = json.loads(cached_row[0])

            else:
                TABLE_TO_PATH = {
                    "index_json": "info/index.json",
                    "about": "info/about.json",
                    "paths": "info/paths.json",
                    "recipe": "info/recipe/meta.yaml",
                    "run_exports": "info/run_exports.json",  # rare but used. see e.g. gstreamer. prevents 90% of early tar.bz2 exits.
                    "post_install": "info/post_install.json",  # computed
                    # icon: too rare. 16 conda-forge packages.
                    # recipe_log: always {} in old version of cache
                }

                TABLE_NO_CACHE = {
                    "paths",
                }

                COMPUTED = {"info/post_install.json"}

                wanted = set(TABLE_TO_PATH.values()) - COMPUTED

                recipe_want_one = {
                    "info/recipe/meta.yaml.rendered",
                    "info/recipe/meta.yaml",  # by far the most common
                    "info/meta.yaml",
                }

                have = {}
                package_stream = iter(package_streaming.stream_conda_info(abs_fn))
                for tar, member in package_stream:
                    if (
                        member.name in wanted and member.name not in recipe_want_one
                    ):  # XXX ugly
                        wanted.remove(member.name)
                        have[member.name] = tar.extractfile(member).read()
                    elif member.name in recipe_want_one:  # XXX ugly
                        recipe_want_one.clear()
                        have["info/recipe/meta.yaml"] = _cache_recipe(
                            tar.extractfile(member)
                        )
                        wanted.remove("info/recipe/meta.yaml")  # XXX ugly
                    if not wanted and len(recipe_want_one) < 3:  # we got what we wanted
                        # XXX debug: how many files / bytes did we avoid reading
                        package_stream.send(True)
                        print(f"{fn} early exit")
                if wanted and wanted != {"info/run_exports.json"}:
                    # very common for some metadata to be missing
                    log.info(f"{fn} missing {wanted} has {set(have.keys())}")

                index_json = json.loads(have["info/index.json"])

                # XXX used to check for "info/run_exports.yaml"; check if still relevant
                # _cache_run_exports(tmpdir, run_exports_cache_path)

                # populate run_exports.json (all False's if there was no
                # paths.json). paths.json should not be needed after this; don't
                # cache large paths.json unless we want a "search for paths"
                # feature unrelated to repodata.json
                try:
                    paths_str = have.pop("info/paths.json")
                except KeyError:
                    paths_str = ""
                have["info/post_install.json"] = _cache_post_install_details(paths_str)

                for table, have_path in TABLE_TO_PATH.items():
                    if table in TABLE_NO_CACHE:
                        continue  # not cached

                    parameters = {"path": database_path, "data": have.get(have_path)}
                    if parameters["data"] is not None:
                        query = f"""
                            INSERT OR IGNORE INTO {table} (path, {table})
                            VALUES (:path, json(:data))
                            """
                    else:
                        query = f"""
                            DELETE FROM {table} WHERE path = :path
                            """
                    try:
                        self.db.execute(query, parameters)
                    except sqlite3.OperationalError:  # e.g. malformed json. will rollback txn?
                        log.exception("table=%s parameters=%s", table, parameters)
                        # XXX delete from cache
                        raise

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

            # calculate extra stuff to add to index.json cache, size, md5, sha256
            #    This is done always for all files, whether the cache is loaded or not,
            #    because the cache may be from the other file type.  We don't store this
            #    info in the cache to avoid confusion.

            # conda_package_handling wastes a stat call to give us this information
            # XXX store this info in the cache while avoiding confusion
            # (existing index_json['sha256', 'md5'] may be good)
            # XXX stop using md5
            md5, sha256 = checksums(abs_fn, ("md5", "sha256"))

            new_info = {"md5": md5, "sha256": sha256, "size": size}
            for digest_type in "md5", "sha256":
                if digest_type in index_json:
                    assert (
                        index_json[digest_type] == new_info[digest_type]
                    ), "cached index json digest mismatch"

            index_json.update(new_info)

            # sqlite json() function removes whitespace
            self.db.execute(
                "INSERT OR REPLACE INTO index_json (path, index_json) VALUES (:path, json(:index_json))",
                {"path": database_path, "index_json": json.dumps(index_json)},
            )
            retval = fn, mtime, size, index_json

        except (InvalidArchiveError, KeyError, EOFError, JSONDecodeError):
            if not second_try:
                # recursion
                return self._extract_to_cache(channel_root, subdir, fn, second_try=True)

        return retval


def _cache_post_install_details(paths_json_str):
    post_install_details_json = {
        "binary_prefix": False,
        "text_prefix": False,
        "activate.d": False,
        "deactivate.d": False,
        "pre_link": False,
        "post_link": False,
        "pre_unlink": False,
    }
    if paths_json_str:  # if paths exists at all
        paths = json.loads(paths_json_str).get("paths", [])

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

    return json.dumps(post_install_details_json)


def _cache_recipe(recipe_reader):
    recipe_json = {}

    try:
        recipe_json = yaml.safe_load(recipe_reader)
    except (ConstructorError, ParserError, ScannerError, ReaderError):
        pass

    try:
        recipe_json_str = json.dumps(recipe_json)
    except TypeError:
        recipe_json.get("requirements", {}).pop("build")  # XXX weird
        recipe_json_str = json.dumps(recipe_json)

    return recipe_json_str
