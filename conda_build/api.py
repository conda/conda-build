# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

"""
This file defines the public API for conda-build.  Adding or removing functions,
or Changing arguments to anything in here should also mean changing the major
version number.
"""

import os as _os

# imports done this way to hide other functions as private
from conda_build.render import render_recipe as _render_recipe
from conda_build.build import test as _test
from conda_build.build import bldpkg_path as _bldpkg_path
from conda_build.config import config as _config
from conda_build.index import update_index as _update_index
import conda_build.build as _build


def render(recipe_path, no_download_source=False, verbose=False, **kwargs):
    return _render_recipe(recipe_path, no_download_source=no_download_source,
                          verbose=verbose, **kwargs)


def get_output_file_path(recipe_path, no_download_source=False, verbose=False, **kwargs):
    metadata, need_source_download = _render_recipe(recipe_path,
                                                    no_download_source=no_download_source,
                                                    verbose=verbose, **kwargs)
    return _bldpkg_path(metadata, **kwargs)


def check(recipe_path, no_download_source=False, verbose=False, **kwargs):
    metadata, need_source_download = _render_recipe(recipe_path,
                                                    no_download_source=no_download_source,
                                                    verbose=verbose, **kwargs)
    metadata.check_fields()


def build(recipe_path, post=None, include_recipe=True, keep_old_work=False,
          need_source_download=True, verbose=False, check=False, skip_existing=False,
          dirty=False, already_built=None,
          **kwargs):
    metadata, need_source_download = _render_recipe(recipe_path,
                                                    no_download_source=(not need_source_download),
                                                    verbose=verbose, dirty=dirty, **kwargs)

    if not already_built:
        already_built = set()

    if metadata.skip():
        print("Skipped: The %s recipe defines build/skip for this "
                "configuration." % metadata.dist())
        return False

    if skip_existing:
        for d in _config.bldpkgs_dirs:
            if not _os.path.isdir(d):
                _os.makedirs(d)
            _update_index(d)
        index = _build.get_build_index(clear_cache=True)

        # 'or m.pkg_fn() in index' is for conda <4.1 and could be removed in the future.
        if ('local::' + metadata.pkg_fn() in index or
                metadata.pkg_fn() in index or
                metadata.pkg_fn() in already_built):
            print(metadata.dist(), "is already built, skipping.")
            return False

    return _build.build(metadata, post=post, include_recipe=include_recipe, dirty=dirty,
                        keep_old_work=keep_old_work, need_source_download=need_source_download,
                        **kwargs)


def test(package_path, move_broken=True, verbose=False, **kwargs):
    # Note: internal test function depends on metadata already having been populated.
    # This may cause problems if post-build version stuff is used, as we have no way to pass
    # metadata out of build.  This is read from an existing package input here.
    metadata, _ = _render_recipe(package_path, no_download_source=False, verbose=verbose, **kwargs)
    return _test(metadata, move_broken=move_broken, **kwargs)
