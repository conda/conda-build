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

# imports are done this way to keep the api clean and limited to conda-build's functionality.

import importlib as _importlib
import os as _os
import pkgutil as _pkgutil
import re as _re

from conda.compat import string_types as _string_types

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
          dirty=False, already_built=None, build_only=False, notest=False, anaconda_upload=True,
          token=None, user=None, **kwargs):

    if isinstance(recipe_path, _string_types):
        recipe_path = [recipe_path]

    build_recipes = []
    for recipe in recipe_path:
        metadata, _ = _render_recipe(recipe,
                                    no_download_source=(not need_source_download),
                                    verbose=verbose, dirty=dirty, **kwargs)

        if not already_built:
            already_built = set()

        if metadata.skip():
            print("Skipped: The %s recipe defines build/skip for this "
                    "configuration." % metadata.dist())
            continue

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
                continue

        build_recipes.append(recipe)

    return _build.build_tree(build_recipes, build_only=build_only, post=post, notest=notest,
                             anaconda_upload=anaconda_upload, skip_existing=skip_existing,
                             keep_old_work=keep_old_work, include_recipe=include_recipe,
                             need_source_download=True, already_built=already_built,
                             token=token, user=user, dirty=dirty)


def test(package_path, move_broken=True, verbose=False, **kwargs):
    # Note: internal test function depends on metadata already having been populated.
    # This may cause problems if post-build version stuff is used, as we have no way to pass
    # metadata out of build.  This is read from an existing package input here.
    metadata, _ = _render_recipe(package_path, no_download_source=False, verbose=verbose, **kwargs)
    return _test(metadata, move_broken=move_broken, **kwargs)


def keygen(name="conda_build_signing", size=2048):
    """Create a private/public key pair for package verification purposes

    name: string name of key to be generated.
    size: length of the RSA key, in bits.  Should be power of 2.
    """
    from .sign import keygen
    return keygen(name, size)


def import_sign_key(private_key_path, new_name=None):
    """
    private_key_path: specify a private key to be imported.  The public key is
          generated automatically.  Specify ```new_name``` also to rename the
          private key in the copied location.
    """
    from .sign import import_key
    return import_key(private_key_path, new_name=new_name)


def sign(file_path, key_name_or_path=None):
    from .sign import sign_and_write
    return sign_and_write(file_path, key_name_or_path)


def verify(file_path):
    from .sign import verify
    return verify(file_path)


def list_skeletons():
    """List available skeletons for generating conda recipes from external sources.

    The returned list is generally the names of supported repositories (pypi, cran, etc.)"""
    modules = _pkgutil.iter_modules(['conda_build/skeletons'])
    files = []
    for _, name, _ in modules:
        if not name.startswith("_"):
            files.append(name)
    return files


def _is_url(name_or_url):
    return _re.findall(r"^(https?:\/\/)?([\da-z\.-]+)\.([a-z\.]{2,6})([\/\w \.-]*)*\/?$",
                       name_or_url) != []


def skeletonize(packages, repo, output_dir=".", version=None, recursive=False, **kw):
    """Generate a conda recipe from an external repo.  Translates metadata from external
    sources into expected conda recipe format."""
    if isinstance(packages, _string_types):
        packages = [packages]

    module = _importlib.import_module("conda_build.skeletons." + repo)
    skeleton_return = module.skeletonize(packages, output_dir=output_dir, version=version,
                                            recursive=recursive, **kw)
    return skeleton_return


def convert(file_path, output_dir=".", show_imports=False, platforms=None, force=False,
                  verbose=False, quiet=True, dry_run=False):
    """Convert changes a package from one platform to another.  It applies only to things that are
    portable, such as pure python, or header-only C/C++ libraries."""
    from .convert import conda_convert
    if file_path.endswith('tar.bz2'):
        return conda_convert(file_path)
    elif file_path.endswith('.whl'):
        raise RuntimeError('Conversion from wheel packages is not '
                            'implemented yet, stay tuned.')
    else:
        raise RuntimeError("cannot convert: %s" % file)
