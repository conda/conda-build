"""
cache conda indexing metadata in sqlite.
"""

from functools import cached_property
import os
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

from . import convert_cache
from .common import connect
from . import package_streaming

from ..utils import (
    CONDA_PACKAGE_EXTENSION_V1,
    CONDA_PACKAGE_EXTENSION_V2,
    CONDA_PACKAGE_EXTENSIONS,
    FileNotFoundError,
    JSONDecodeError,
    get_logger,
)

from conda_package_handling.utils import checksums


log = get_logger(__name__)


INDEX_JSON_PATH = "info/index.json"
ICON_PATH = "info/icon.png"
PATHS_PATH = "info/paths.json"

TABLE_TO_PATH = {
    "index_json": INDEX_JSON_PATH,
    "about": "info/about.json",
    "paths": PATHS_PATH,
    # will use the first one encountered
    "recipe": (
        "info/recipe/meta.yaml",
        "info/recipe/meta.yaml.rendered",
        "info/meta.yaml",
    ),
    # run_exports is rare but used. see e.g. gstreamer.
    # prevents 90% of early tar.bz2 exits.
    # also found in meta.yaml['build']['run_exports']
    "run_exports": "info/run_exports.json",
    "post_install": "info/post_install.json",  # computed
    "icon": ICON_PATH,  # very rare, 16 conda-forge packages
    # recipe_log: always {} in old version of cache
}

PATH_TO_TABLE = {}

for k, v in TABLE_TO_PATH.items():
    if isinstance(v, str):
        PATH_TO_TABLE[v] = k
    else:
        for path in v:
            PATH_TO_TABLE[path] = k

# read, but not saved for later
TABLE_NO_CACHE = {
    "paths",
}

# saved to cache, not found in package
COMPUTED = {"info/post_install.json"}


class CondaIndexCache:
    def __init__(self, channel_root, channel, subdir):
        self.channel_root = channel_root
        self.channel = channel
        self.subdir = subdir

        log.debug(f"CondaIndexCache {channel=}, {subdir=}")

        self.subdir_path = os.path.join(channel_root, subdir)
        self.cache_dir = os.path.join(self.subdir_path, ".cache")
        self.db_filename = os.path.join(self.cache_dir, "cache.db")
        self.cache_is_brand_new = not os.path.exists(self.db_filename)

        os.makedirs(self.cache_dir, exist_ok=True)

        log.debug(f"{self.db_filename=} {self.cache_is_brand_new=}")

    def __getstate__(self):
        """
        Remove db connection when pickled.
        """
        return {k: self.__dict__[k] for k in self.__dict__ if k != "db"}

    def __setstate__(self, d):
        self.__dict__ = d

    @cached_property
    def db(self):
        """
        Connection to our sqlite3 database.

        Ability to pickle if db has not been accessed?
        """
        conn = connect(self.db_filename)
        convert_cache.create(conn)
        return conn

    def convert(self, force=False):
        """
        Load filesystem cache into sqlite.
        """
        if self.cache_is_brand_new or force:
            convert_cache.convert_cache(
                self.db,
                convert_cache.extract_cache_filesystem(self.cache_dir),
                override_channel=self.channel,
            )

    def stat_cache(self) -> dict:
        """
        Load path: mtime, size mapping
        """
        # XXX no long-term need to emulate old stat.json
        return {
            # XXX work correctly with windows \ separator
            os.path.basename(row["path"]): {"mtime": row["mtime"], "size": row["size"]}
            for row in self.db.execute(
                "SELECT path, mtime, size FROM stat WHERE stage IS NULL"
            )
        }

    def save_stat_cache(self, stat_cache: dict):
        with self.db:
            self.db.execute("DELETE FROM stat WHERE stage IS NULL")

            self.db.executemany(
                "INSERT OR REPLACE INTO stat (path, mtime, size, stage) VALUES (:path, :mtime, :size, NULL)",
                (
                    (
                        self.database_path(fn),
                        value["mtime"],
                        value["size"],
                    )
                    for (fn, value) in stat_cache.items()
                ),
            )

    def load_index_from_cache(self, fn):
        # XXX prefer bulk load; can't pass list as :param though, and many small
        # queries are efficient in sqlite.
        # sqlite cache may be fast enough to forget reusing repodata.json
        # often when you think this function would be called, it actually calls extract_to_cache
        cached_row = self.db.execute(
            "SELECT index_json FROM index_json WHERE path = :path",
            {"path": self.database_path(fn)},
        ).fetchone()

        if cached_row:
            # XXX load cached cached index.json from sql in bulk
            # sqlite has very low latency but we can do better
            return json.loads(cached_row[0])
        else:
            return fn  # odd legacy error handling

    def extract_to_cache(self, channel_root, subdir, fn):
        # XXX original skips this on warm cache
        with self.db:  # transaction
            return self._extract_to_cache_(channel_root, subdir, fn)

    def database_path(self, fn):
        return f"{self.channel}/{self.subdir}/{fn}"

    def _extract_to_cache_(
        self, channel_root, subdir, fn, second_try=False, stat_result=None
    ):
        # This method WILL reread the tarball. Probably need another one to exit early if
        # there are cases where it's fine not to reread.  Like if we just rebuild repodata
        # from the cached files, but don't use the existing repodata.json as a starting point.
        subdir_path = join(channel_root, subdir)

        abs_fn = join(subdir_path, fn)

        if stat_result is None:
            stat_result = os.stat(abs_fn)

        size = stat_result.st_size
        mtime = stat_result.st_mtime
        retval = fn, mtime, size, None

        log.debug("sql hashing, extracting, and caching %s" % fn)

        try:
            # skip re-use conda/bz2 cache in sqlite version
            database_path = self.database_path(fn)

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

                wanted = set(PATH_TO_TABLE) - COMPUTED

                # when we see one of these, remove the rest from wanted
                recipe_want_one = {
                    "info/recipe/meta.yaml.rendered",
                    "info/recipe/meta.yaml",  # by far the most common
                    "info/meta.yaml",
                }

                have = {}
                package_stream = iter(package_streaming.stream_conda_info(abs_fn))
                for tar, member in package_stream:
                    if member.name in wanted:
                        wanted.remove(member.name)
                        have[member.name] = tar.extractfile(member).read()

                        # immediately parse index.json, decide whether we need icon
                        if member.name == INDEX_JSON_PATH:  # early exit when no icon
                            index_json = json.loads(have[member.name])
                            if index_json.get("icon") is None:
                                wanted = wanted - {ICON_PATH}

                        if member.name in recipe_want_one:
                            # convert yaml; don't look for any more recipe files
                            have[member.name] = _cache_recipe(have[member.name])
                            wanted = wanted - recipe_want_one

                    if not wanted:  # we got what we wanted
                        # XXX debug: how many files / bytes did we avoid reading
                        package_stream.close()
                        log.debug(f"{fn} early exit")

                if wanted and wanted != {"info/run_exports.json"}:
                    # very common for some metadata to be missing
                    log.debug(f"{fn} missing {wanted} has {set(have.keys())}")

                index_json = json.loads(have["info/index.json"])

                # XXX used to check for "info/run_exports.yaml"; check if still relevant
                # _cache_run_exports(tmpdir, run_exports_cache_path)

                # populate run_exports.json (all False's if there was no
                # paths.json). paths.json should not be needed after this; don't
                # cache large paths.json unless we want a "search for paths"
                # feature unrelated to repodata.json
                try:
                    paths_str = have.pop(PATHS_PATH)
                except KeyError:
                    paths_str = ""
                have["info/post_install.json"] = _cache_post_install_details(paths_str)

                # XXX will not delete cached recipe, if missing
                for have_path in have:
                    table = PATH_TO_TABLE[have_path]
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

    def load_all_from_cache(self, fn, mtime=None):
        subdir_path = self.subdir_path
        try:
            # XXX save recent stat calls for a significant speedup
            mtime = mtime or os.stat(join(subdir_path, fn)).st_mtime
        except FileNotFoundError:
            # XXX don't call if it won't be found
            print("FILE NOT FOUND in load_all_from_cache")
            return {}

        # In contrast to self._load_index_from_cache(), this method reads up pretty much
        # all of the cached metadata, except for paths. It all gets dumped into a single map.

        UNHOLY_UNION = """
        SELECT
            index_json,
            about,
            post_install,
            recipe,
            run_exports
            -- icon_png
        FROM
            index_json
            LEFT JOIN about USING (path)
            LEFT JOIN post_install USING (path)
            LEFT JOIN recipe USING (path)
            LEFT JOIN run_exports USING (path)
            -- LEFT JOIN icon USING (path)
        WHERE
            index_json.path = :path
        LIMIT 2
        """  # each table must USING (path) or will cross join

        rows = self.db.execute(UNHOLY_UNION, {"path": self.database_path(fn)}).fetchall()
        assert len(rows) < 2
        try:
            row = rows[0]
        except IndexError:
            row = None
        data = {}
        # this order matches the old implementation. clobber recipe, about fields with index_json.
        for column in ("recipe", "about", "post_install", "index_json"):
            if row[column]:  # is not null or empty
                data.update(json.loads(row[column]))

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

        # if run_exports was NULL / empty string, 'loads' the empty object
        data["run_exports"] = json.loads(row["run_exports"] or "{}")

        return data


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


def _clear_newline_chars(record, field_name):
    if field_name in record:
        try:
            record[field_name] = record[field_name].strip().replace("\n", " ")
        except AttributeError:
            # sometimes description gets added as a list instead of just a string
            record[field_name] = record[field_name][0].strip().replace("\n", " ")
