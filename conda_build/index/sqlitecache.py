"""
cache conda indexing metadata in sqlite.
"""

import os.path

from os.path import join

from metayaml.convert_cache import create, convert_cache
from metayaml.common import *  # XXX vendor

from ..utils import (
    CONDA_PACKAGE_EXTENSION_V1,
    CONDA_PACKAGE_EXTENSION_V2,
    CONDA_PACKAGE_EXTENSIONS,
    FileNotFoundError,
    JSONDecodeError,
    get_logger,
    glob,
)

def _alternate_file_extension(fn):
    cache_fn = fn
    for ext in CONDA_PACKAGE_EXTENSIONS:
        cache_fn = cache_fn.replace(ext, "")
    other_ext = set(CONDA_PACKAGE_EXTENSIONS) - {fn.replace(cache_fn, "")}
    return cache_fn + next(iter(other_ext))


class CondaIndexCache:
    def __init__(self, subdir_path, subdir):
        self.cache_dir = os.path.join(subdir_path, ".cache")
        self.subdir = subdir
        self.db_filename = os.path.join(self.cache_dir, "cache.db")
        self.cache_is_brand_new = not os.path.exists(self.db_filename)
        self.db = connect(self.db_filename)
        create(self.db)

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
        # XXX no long-term need to emulate old json
        return {
            row["path"]: {"mtime": row["mtime"], "size": row["size"]}
            for row in self.db.execute("SELECT path, mtime, size FROM stat")
        }


    def _extract_to_cache(self, channel_root, subdir, fn, second_try=False):
        # This method WILL reread the tarball. Probably need another one to exit early if
        # there are cases where it's fine not to reread.  Like if we just rebuild repodata
        # from the cached files, but don't use the existing repodata.json as a starting point.
        subdir_path = join(channel_root, subdir)

        # allow .conda files to reuse cache from .tar.bz2 and vice-versa.
        # Assumes that .tar.bz2 and .conda files have exactly the same
        # contents. This is convention, but not guaranteed, nor checked.
        alternate_cache_fn = _alternate_file_extension(fn)
        cache_fn = fn

        abs_fn = join(subdir_path, fn)

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
                    # so inefficient
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
