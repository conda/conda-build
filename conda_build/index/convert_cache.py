"""
Given a conda <subdir>/.cache directory as a .tar.bz2,

Create a sqlite database with the same data.

Intended to be used as a transition between the older format and a newer version
of `conda-build index`, or as the foundation of a package database.
"""

import tarfile
import os
import os.path
import re
import json
import sqlite3

from more_itertools import ichunked
from contextlib import closing

from . import common

# email us if you're thinking about downloading conda-forge to
# regenerate this 264MB file
CACHE_ARCHIVE = os.path.expanduser("~/Downloads/linux-64-cache.tar.bz2")

PATH_INFO = re.compile(
    r"""
    (?P<channel>conda-forge)/
    (?P<subdir>.*)/
    .cache/
    (?P<path>(stat.json|
        (?P<kind>recipe|index|icon|about|recipe_log|run_exports|post_install)/(?P<basename>\S*?)(?P<ext>.\w+$))
    )""",
    re.VERBOSE,
)

# Finds directories like these, we are only concerned with {subdir}/.cache/*
TYPICAL_DIRECTORIES = {
    "",
    "clones/conda-forge/linux-64/.cache/recipe",
    "clones/conda-forge/linux-64",
    "clones/conda-forge/linux-64/.cache/index",
    "clones/conda-forge/linux-64/.cache/icon",  # only a dozen packages have icons
    "clones/conda-forge/linux-64/.cache",  # stat.json
    "clones/conda-forge",
    "clones/conda-forge/linux-64/.cache/about",
    "clones/conda-forge/linux-64/.cache/recipe_log",  # 100% empty {}'s
    "clones/conda-forge/linux-64/.cache/run_exports",  # mostly empty {}'s
    "clones",
    "clones/conda-forge/linux-64/.cache/post_install",
}

# TODO .cache/clone.json ?


def create(conn):
    with conn:
        # BLOB columns are a little faster to LENGTH(col), returning number of
        # bytes instead of number of (possibly multi-byte utf-8) characters
        conn.execute(
            "CREATE TABLE IF NOT EXISTS about (path TEXT PRIMARY KEY, about BLOB)"
        )
        # index is a sql keyword
        # generated columns pulling fields from index_json could be nice
        # has md5, shasum. older? packages do not include timestamp?
        # SELECT path, datetime(json_extract(index_json, '$.timestamp'), 'unixepoch'), index_json from index_json
        conn.execute(
            "CREATE TABLE IF NOT EXISTS index_json (path TEXT PRIMARY KEY, index_json BLOB)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS recipe (path TEXT PRIMARY KEY, recipe BLOB)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS recipe_log (path TEXT PRIMARY KEY, recipe_log BLOB)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS run_exports (path TEXT PRIMARY KEY, run_exports BLOB)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS post_install (path TEXT PRIMARY KEY, post_install BLOB)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS icon (path TEXT PRIMARY KEY, icon_png BLOB)"
        )
        # Stat data. Compare to other tables, on-disk mtimes to see what's changed.
        #   "arrow-cpp-1.0.1-py310h33a019f_53_cuda.tar.bz2": {
        #     "mtime": 1636410074,
        #     "size": 22088344
        #   },
        # DATETIME(mtime, 'unixepoch')
        conn.execute(
            "CREATE TABLE IF NOT EXISTS stat (path TEXT PRIMARY KEY, mtime INTEGER, size INTEGER)"
        )

        try:
            conn.execute("SELECT stage FROM stat LIMIT 1")
        except sqlite3.OperationalError:
            for colname in ('stage', 'sha256', 'md5', 'last_modified', 'etag'):
                conn.execute("ALTER TABLE stat ADD COLUMN {colname} TEXT")

        # # individual large path json files separated into many rows
        # # should be stored in a separate sqlite db
        # conn.execute(
        #     "CREATE TABLE IF NOT EXISTS path (path_id INTEGER PRIMARY KEY, path TEXT UNIQUE)"
        # )
        # # TODO fields
        # conn.execute(
        #     """CREATE TABLE IF NOT EXISTS path_entry (
        #         path_id INTEGER REFERENCES path (path_id),
        #         path TEXT,
        #         sha256 TEXT,
        #         md5 TEXT
        #         )
        #     """
        # )
        # conn.execute(
        #     "CREATE UNIQUE INDEX IF NOT EXISTS idx_path_entry ON path_entry (path_id, path)"
        # )


def extract_cache(path):
    """
    Yield interesting (match, tar entry) members of tarball at path.
    """
    dirnames = set()
    tf = tarfile.open(path)
    last_len = len(dirnames)
    try:
        for entry in tf:
            match = PATH_INFO.search(entry.name)
            if match:
                yield match, tf.extractfile(entry)
            dirnames.add(os.path.dirname(entry.name))
            next_len = len(dirnames)
            if last_len < next_len:
                print(f"{next_len} directories, {entry.name}")
            last_len = next_len
    except KeyboardInterrupt:
        print("Interrupted!")

    print(dirnames)


# regex excludes arbitrary names
TABLE_MAP = {"index": "index_json"}

CHUNK_SIZE = 4096  # packages * cache folders = cache files


def db_path(match):
    """
    A primary key that should be unique for all {subdir}/.cache
    """
    return f"{match['channel']}/{match['subdir']}/{match['basename']}"


def convert_cache(conn):
    # chunked must be as lazy as possible to prevent tar seeks
    for i, chunk in enumerate(ichunked(extract_cache(CACHE_ARCHIVE), CHUNK_SIZE)):
        print(f"BEGIN {i}")
        with conn:  # transaction
            for match, member in chunk:

                if match["path"] == "stat.json":
                    conn.execute("DELETE FROM stat")
                    for key, value in json.load(member).items():
                        value["path"] = f"{match['channel']}/{match['subdir']}/{key}"
                        conn.execute(
                            "INSERT OR REPLACE INTO stat (path, mtime, size) VALUES (:path, :mtime, :size)",
                            value,
                        )

                elif match["ext"] == ".json":
                    # {'channel': 'conda-forge', 'subdir': 'linux-64', 'path':
                    # 'post_install/vim-8.2.2905-py36he996604_0.tar.bz2.json',
                    # 'kind': 'post_install', 'basename':
                    # 'vim-8.2.2905-py36he996604_0.tar.bz2', 'ext': '.json'}
                    table = TABLE_MAP.get(match["kind"], match["kind"])
                    conn.execute(
                        f"""
                    INSERT OR IGNORE INTO {table} (path, {table})
                    VALUES (:path, json(:data))
                    """,
                        {"path": db_path(match), "data": member.read()},
                    )

                elif match["kind"] == "icon":
                    conn.execute(
                        """
                    INSERT OR IGNORE INTO icon (path, icon_png)
                    VALUES (:path, :data)
                    """,
                        {"path": db_path(match), "data": member.read()},
                    )

                else:
                    print("unhandled", match.groupdict())


def go():
    conn = common.connect("linux-64-cache.db")
    create(conn)
    with closing(conn):
        convert_cache(conn)


if __name__ == "__main__":
    go()


# typically 600-10,000 MB
MB_PER_DAY = """
select
  date(mtime, 'unixepoch') as d,
  printf('%0.2f', sum(size) / 1e6) as MB
from
  stat
group by
  date(mtime, 'unixepoch')
order by
  mtime desc
"""
