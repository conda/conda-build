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
from conda_build.config import Config, get_or_merge_config


def _ensure_list(recipe_arg):
    from conda.compat import string_types as _string_types
    if isinstance(recipe_arg, _string_types):
        recipe_arg = [recipe_arg]
    return recipe_arg


def render(recipe_path, config=None, **kwargs):
    from conda_build.render import render_recipe
    config = get_or_merge_config(config, **kwargs)
    return render_recipe(recipe_path, no_download_source=config.no_download_source, config=config)


def output_yaml(metadata, file_path=None):
    from conda_build.render import output_yaml
    return output_yaml(metadata, file_path)


def get_output_file_path(recipe_path, no_download_source=False, config=None, **kwargs):
    from conda_build.render import render_recipe, bldpkg_path
    config = get_or_merge_config(config, **kwargs)
    metadata, _, _ = render_recipe(recipe_path,
                                   no_download_source=no_download_source,
                                   config=config)
    return bldpkg_path(metadata, config)


def check(recipe_path, no_download_source=False, config=None, **kwargs):
    from conda_build.render import render_recipe
    config = get_or_merge_config(config, **kwargs)
    metadata, need_source_download = render_recipe(recipe_path,
                                                   no_download_source=no_download_source,
                                                   config=config)
    metadata.check_fields()


def build(recipe_path, post=None, need_source_download=True,
          already_built=None, build_only=False, notest=False,
          config=None, **kwargs):

    import os
    import time
    import conda.config as cc
    from conda.utils import url_path
    from conda_build.render import render_recipe
    from conda_build.build import build_tree, get_build_index, update_index

    config = get_or_merge_config(config, **kwargs)

    recipe_path = _ensure_list(recipe_path)

    build_metadata = []
    for recipe in recipe_path:
        metadata, need_source_download, need_reparse_in_env = render_recipe(recipe,
                                            no_download_source=(not need_source_download),
                                            config=config)

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

            urls = [url_path(config.croot)] + cc.get_rc_urls() + cc.get_local_urls() + ['local', ]
            if config.channel_urls:
                urls.extend(config.channel_urls)

            # will be empty if none found, and evalute to False
            package_exists = [url for url in urls if url + '::' + metadata.pkg_fn() in index]
            if (package_exists or metadata.pkg_fn() in index or
                    metadata.pkg_fn() in already_built):
                print(metadata.dist(), "is already built in {0}, skipping.".format(package_exists))
                continue

        build_metadata.append((metadata, need_source_download, need_reparse_in_env))

    return build_tree(build_metadata, build_only=build_only, post=post, notest=notest,
                      need_source_download=need_source_download, already_built=already_built,
                      config=config)


def test(package_path, move_broken=True, config=None, **kwargs):
    import os
    from conda.compat import TemporaryDirectory
    from conda_build.build import test
    from conda_build.render import render_recipe
    from conda_build.utils import tar_xf
    # Note: internal test function depends on metadata already having been populated.
    # This may cause problems if post-build version stuff is used, as we have no way to pass
    # metadata out of build.  This is read from an existing package input here.

    config = get_or_merge_config(config, **kwargs)
    with TemporaryDirectory() as tmp:
        tar_xf(package_path, tmp)
        recipe_dir = os.path.join(tmp, 'info', 'recipe')

        # try to extract the static meta.yaml and load metadata from it
        if os.path.isdir(recipe_dir):
            metadata, _, _ = render_recipe(recipe_dir, config=config)
        else:
            # fall back to old way (use recipe, rather than package)
            metadata, _, _ = render_recipe(package_path, no_download_source=False,
                                        config=config, **kwargs)

        test_result = test(metadata, config=config, move_broken=move_broken)
    return test_result


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


def skeletonize(packages, repo, output_dir=".", version=None, recursive=False,
                config=None, **kwargs):
    """Generate a conda recipe from an external repo.  Translates metadata from external
    sources into expected conda recipe format."""

    config = get_or_merge_config(config, **kwargs)
    packages = _ensure_list(packages)

    module = getattr(__import__("conda_build.skeletons", globals=globals(), locals=locals(),
                                fromlist=[repo]),
                     repo)
    func_args = module.skeletonize.__code__.co_varnames
    kwargs = {name: value for name, value in kwargs.items() if name in func_args}
    skeleton_return = module.skeletonize(packages, output_dir=output_dir, version=version,
                                            recursive=recursive, config=config, **kwargs)
    return skeleton_return


def develop(recipe_dir, prefix=_sys.prefix, no_pth_file=False,
            build_ext=False, clean=False, uninstall=False):
    """Install a Python package in 'development mode'.

This works by creating a conda.pth file in site-packages."""
    from .develop import execute
    recipe_dir = _ensure_list(recipe_dir)
    return execute(recipe_dir, prefix, no_pth_file, build_ext, clean, uninstall)


def convert(package_files, output_dir=".", show_imports=False, platforms=None, force=False,
                  dependencies=None, verbose=False, quiet=True, dry_run=False):
    """Convert changes a package from one platform to another.  It applies only to things that are
    portable, such as pure python, or header-only C/C++ libraries."""
    from .convert import conda_convert
    if not platforms:
        platforms = []
    if package_files.endswith('tar.bz2'):
        return conda_convert(package_files, output_dir=output_dir, show_imports=show_imports,
                             platforms=platforms, force=force, verbose=verbose, quiet=quiet,
                             dry_run=dry_run, dependencies=dependencies)
    elif package_files.endswith('.whl'):
        raise RuntimeError('Conversion from wheel packages is not '
                            'implemented yet, stay tuned.')
    else:
        raise RuntimeError("cannot convert: %s" % package_files)


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


def inspect_objects(packages, prefix=_sys.prefix, groupby='filename'):
    from .inspect import inspect_objects
    packages = _ensure_list(packages)
    return inspect_objects(packages, prefix=prefix, groupby=groupby)


def create_metapackage(name, version, entry_points=(), build_string=None, build_number=0,
                       dependencies=(), home=None, license=None, summary=None,
                       config=None):
    from .metapackage import create_metapackage
    if not config:
        config = Config()
    return create_metapackage(name=name, version=version, entry_points=entry_points,
                              build_string=build_string, build_number=build_number,
                              dependencies=dependencies, home=home,
                              license=license, summary=summary, config=config)


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
