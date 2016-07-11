# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

"""
This file defines the public API for conda-build.  Adding or removing functions,
or Changing arguments to anything in here should also mean changing the major
version number.

Design philosophy: put variability into config.  Make each function here accept kwargs,
but only use those kwargs in config.  Config must change to support new features elsewhere.
"""

# imports are done locally to keep the api clean and limited strictly
#    to conda-build's functionality.

import sys as _sys

# make the Config class available in the api namespace
from conda_build.config import Config


def _ensure_list(recipe_arg):
    from conda.compat import string_types as _string_types
    if isinstance(recipe_arg, _string_types):
        recipe_arg = [recipe_arg]
    return recipe_arg


def render(recipe_path, no_download_source=False, verbose=False, **kwargs):
    from conda_build.render import render_recipe
    if kwargs:
        config = Config(**kwargs)
    return render_recipe(recipe_path, no_download_source=no_download_source,
                         verbose=config.verbose, dirty=config.dirty)


def output_yaml(metadata, file_path=None):
    from conda_build.render import output_yaml
    return output_yaml(metadata, file_path)


def get_output_file_path(recipe_path, no_download_source=False, config=None, **kwargs):
    from conda_build.render import render_recipe, bldpkg_path

    if not config:
        config = Config()

    if kwargs:
        config = Config(**kwargs)

    metadata, need_source_download = render_recipe(recipe_path,
                                                   no_download_source=no_download_source,
                                                   verbose=config.verbose, dirty=config.dirty)
    return bldpkg_path(metadata)


def check(recipe_path, no_download_source=False, config=None, **kwargs):
    from conda_build.render import render_recipe

    if not config:
        config = Config()

    metadata, need_source_download = render_recipe(recipe_path,
                                                   no_download_source=no_download_source,
                                                   verbose=config.verbose, dirty=config.dirty)
    metadata.check_fields()


def build(recipe_path, post=None, need_source_download=True, check=False,
          already_built=None, build_only=False, notest=False,
          config=None, **kwargs):

    import os
    from conda_build.render import render_recipe
    from conda_build.build import build_tree, get_build_index, update_index
    from conda_build.config import config

    if not config:
        config = Config()

    if kwargs:
        config = Config(**kwargs)

    recipe_path = _ensure_list(recipe_path)

    build_recipes = []
    for recipe in recipe_path:
        metadata, _ = render_recipe(recipe,
                                    no_download_source=(not need_source_download),
                                    verbose=config.verbose, dirty=config.dirty)

        if not already_built:
            already_built = set()

        if metadata.skip():
            print("Skipped: The %s recipe defines build/skip for this "
                    "configuration." % metadata.dist())
            continue

        if config.skip_existing:
            for d in config.bldpkgs_dirs:
                if not os.path.isdir(d):
                    os.makedirs(d)
                update_index(d)
            index = get_build_index(config=config, clear_cache=True)

            # 'or m.pkg_fn() in index' is for conda <4.1 and could be removed in the future.
            if ('local::' + metadata.pkg_fn() in index or
                    metadata.pkg_fn() in index or
                    metadata.pkg_fn() in already_built):
                print(metadata.dist(), "is already built, skipping.")
                continue

        build_recipes.append(recipe)

    return build_tree(build_recipes, build_only=build_only, post=post, notest=notest,
                      need_source_download=True, already_built=already_built,
                      config=config)


def test(package_path, move_broken=True, config=None, **kwargs):
    from conda_build.render import render_recipe
    from conda_build.build import test
    # Note: internal test function depends on metadata already having been populated.
    # This may cause problems if post-build version stuff is used, as we have no way to pass
    # metadata out of build.  This is read from an existing package input here.

    if not config:
        config = Config()

    if kwargs:
        config = Config(**kwargs)

    metadata, _ = render_recipe(package_path, no_download_source=False,
                                verbose=config.verbose, dirty=config.dirty, **kwargs)
    return test(metadata, move_broken=move_broken,
                activate=config.activate, verbose=config.verbose)


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
    """Verify a signed package"""
    from .sign import verify
    return verify(file_path)


def list_skeletons():
    """List available skeletons for generating conda recipes from external sources.

    The returned list is generally the names of supported repositories (pypi, cran, etc.)"""
    import pkgutil
    modules = pkgutil.iter_modules(['conda_build/skeletons'])
    files = []
    for _, name, _ in modules:
        if not name.startswith("_"):
            files.append(name)
    return files


def skeletonize(packages, repo, output_dir=".", version=None, recursive=False, **kwargs):
    """Generate a conda recipe from an external repo.  Translates metadata from external
    sources into expected conda recipe format."""
    import importlib

    packages = _ensure_list(packages)

    module = importlib.import_module("conda_build.skeletons." + repo)
    skeleton_return = module.skeletonize(packages, output_dir=output_dir, version=version,
                                            recursive=recursive, **kwargs)
    return skeleton_return


def develop(recipe_dir, prefix=_sys.prefix, no_pth_file=False,
            build_ext=False, clean=False, uninstall=False):
    """Install a Python package in 'development mode'.

This works by creating a conda.pth file in site-packages."""
    from .develop import execute
    recipe_dir = _ensure_list(recipe_dir)
    return execute(recipe_dir, prefix, no_pth_file, build_ext, clean, uninstall)


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


def test_installable(channel='defaults'):
    """Check to make sure that packages in channel are installable.
    This is a consistency check for the channel."""
    from .inspect import test_installable
    return test_installable(channel)


def inspect_linkages(packages, prefix=_sys.prefix, untracked=False, all=False,
                     show_files=False, groupby='package'):
    from .inspect import inspect_linkages
    packages = _ensure_list(packages)
    return inspect_linkages(packages, prefix=prefix, untracked=untracked,
                            all=all, show_files=show_files, groupby=groupby)


def inspect_objects(packages, prefix=_sys.prefix, groupby='package'):
    from .inspect import inspect_objects
    packages = _ensure_list(packages)
    return inspect_objects(packages, prefix=prefix, groupby=groupby)


def create_metapackage(name, version, entry_points=(), build_string=None,
                       dependencies=(), home=None, license=None, summary=None,
                       anaconda_upload=None):
    from .metapackage import create_metapackage
    if anaconda_upload is None:
        import conda.config
        anaconda_upload = conda.config.anaconda_upload
    return create_metapackage(name=name, version=version, entry_points=entry_points,
                              build_string=build_string, dependencies=dependencies, home=home,
                              license=license, summary=summary, anaconda_upload=anaconda_upload)


def update_index(dir_paths, config=None, force=False, check_md5=False, remove=False):
    from locale import getpreferredencoding
    import os
    from conda.compat import PY3
    from conda_build.index import update_index
    dir_paths = [os.path.abspath(path) for path in _ensure_list(dir_paths)]
    # Don't use byte strings in Python 2
    if not PY3:
        dir_paths = [path.decode(getpreferredencoding()) for path in dir_paths]

    if not config:
        config = Config()

    for path in dir_paths:
        update_index(path, verbose=config.verbose, force=force, check_md5=check_md5, remove=remove)
