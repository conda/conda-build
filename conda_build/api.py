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
from conda_build.config import Config, get_or_merge_config, DEFAULT_PREFIX_LENGTH as _prefix_length
from conda_build.utils import ensure_list as _ensure_list


def render(recipe_path, config=None, **kwargs):
    from conda_build.render import render_recipe
    config = get_or_merge_config(config, **kwargs)
    return render_recipe(recipe_path, no_download_source=config.no_download_source, config=config)


def output_yaml(metadata, file_path=None):
    from conda_build.render import output_yaml
    return output_yaml(metadata, file_path)


def get_output_file_path(recipe_path_or_metadata, no_download_source=False, config=None, **kwargs):
    from conda_build.render import render_recipe, bldpkg_path
    config = get_or_merge_config(config, **kwargs)
    if hasattr(recipe_path_or_metadata, 'config'):
        metadata = recipe_path_or_metadata
    else:
        metadata, _, _ = render_recipe(recipe_path_or_metadata,
                                    no_download_source=no_download_source,
                                    config=config)
    return bldpkg_path(metadata)


def check(recipe_path, no_download_source=False, config=None, **kwargs):
    from conda_build.render import render_recipe
    config = get_or_merge_config(config, **kwargs)
    metadata, _, _ = render_recipe(recipe_path, no_download_source=no_download_source,
                                   config=config)
    return metadata.check_fields()


def build(recipe_paths_or_metadata, post=None, need_source_download=True,
          build_only=False, notest=False, config=None, **kwargs):
    import os
    from conda_build.build import build_tree

    config = get_or_merge_config(config, **kwargs)

    recipes = _ensure_list(recipe_paths_or_metadata)
    absolute_recipes = []
    for recipe in recipes:
        if hasattr(recipe, "config"):
            absolute_recipes.append(recipe)
        elif os.path.isabs(recipe):
            absolute_recipes.append(recipe)
        else:
            absolute_recipes.append(os.path.normpath(os.path.join(os.getcwd(), recipe)))

    return build_tree(absolute_recipes, build_only=build_only, post=post, notest=notest,
                      need_source_download=need_source_download, config=config)


def test(recipedir_or_package_or_metadata, move_broken=True, config=None, **kwargs):
    import os
    from conda_build.conda_interface import url_path
    from conda_build.build import test
    from conda_build.render import render_recipe
    from conda_build.utils import get_recipe_abspath, rm_rf
    from conda_build import source

    config = get_or_merge_config(config, **kwargs)

    # we want to know if we're dealing with package input.  If so, we can move the input on success.
    is_package = False
    need_cleanup = False

    if hasattr(recipedir_or_package_or_metadata, 'config'):
        metadata = recipedir_or_package_or_metadata
        recipe_config = metadata.config
    else:
        recipe_dir, need_cleanup = get_recipe_abspath(recipedir_or_package_or_metadata)
        config.need_cleanup = need_cleanup

        # This will create a new local build folder if and only if config doesn't already have one.
        #   What this means is that if we're running a test immediately after build, we use the one
        #   that the build already provided
        metadata, _, _ = render_recipe(recipe_dir, config=config)
        recipe_config = config
        # this recipe came from an extracted tarball.
        if need_cleanup:
            # ensure that the local location of the package is indexed, so that conda can find the
            #    local package
            local_location = os.path.dirname(recipedir_or_package_or_metadata)
            # strip off extra subdir folders
            for platform in ('win', 'linux', 'osx'):
                if os.path.basename(local_location).startswith(platform + "-"):
                    local_location = os.path.dirname(local_location)
            update_index(local_location, config=config)
            if not os.path.abspath(local_location):
                local_location = os.path.normpath(os.path.abspath(
                    os.path.join(os.getcwd(), local_location)))
            local_url = url_path(local_location)
            # channel_urls is an iterable, but we don't know if it's a tuple or list.  Don't know
            #    how to add elements.
            recipe_config.channel_urls = list(recipe_config.channel_urls)
            recipe_config.channel_urls.insert(0, local_url)
            is_package = True
            if metadata.meta.get('test') and metadata.meta['test'].get('source_files'):
                source.provide(metadata.path, metadata.get_section('source'), config=config)

    with recipe_config:
        # This will create a new local build folder if and only if config doesn't already have one.
        #   What this means is that if we're running a test immediately after build, we use the one
        #   that the build already provided

        recipe_config.compute_build_id(metadata.name())
        test_result = test(metadata, config=recipe_config, move_broken=move_broken)

        if (test_result and is_package and hasattr(recipe_config, 'output_folder') and
                recipe_config.output_folder):
            os.rename(recipedir_or_package_or_metadata,
                      os.path.join(recipe_config.output_folder,
                                   os.path.basename(recipedir_or_package_or_metadata)))
    if need_cleanup:
        rm_rf(recipe_dir)
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

    version = getattr(config, "version", version)
    if version:
        kwargs.update({'version': version})
    if recursive:
        kwargs.update({'version': version})
    if output_dir != ".":
        kwargs.update({'output_dir': output_dir})

    # here we're dumping all extra kwargs as attributes on the config object.  We'll extract
    #    only relevant ones below
    config = get_or_merge_config(config, **kwargs)
    config.compute_build_id('skeleton')
    packages = _ensure_list(packages)

    # This is a little bit of black magic.  The idea is that for any keyword argument that
    #    we inspect from the given module's skeletonize funtion, we should hoist the argument
    #    off of the config object, and pass it as a keyword argument.  This is sort of the
    #    inverse of what we do in the CLI code - there we take CLI arguments and dangle them
    #    all on the config object as attributes.
    module = getattr(__import__("conda_build.skeletons", globals=globals(), locals=locals(),
                                fromlist=[repo]),
                     repo)

    func_args = module.skeletonize.__code__.co_varnames
    kwargs = {name: getattr(config, name) for name in dir(config) if name in func_args}
    kwargs.update({name: value for name, value in kwargs.items() if name in func_args})
    # strip out local arguments that we pass directly
    for arg in skeletonize.__code__.co_varnames:
        if arg in kwargs:
            del kwargs[arg]
    with config:
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


def convert(package_file, output_dir=".", show_imports=False, platforms=None, force=False,
                  dependencies=None, verbose=False, quiet=True, dry_run=False):
    """Convert changes a package from one platform to another.  It applies only to things that are
    portable, such as pure python, or header-only C/C++ libraries."""
    from .convert import conda_convert
    if not platforms:
        platforms = []
    if package_file.endswith('tar.bz2'):
        return conda_convert(package_file, output_dir=output_dir, show_imports=show_imports,
                             platforms=platforms, force=force, verbose=verbose, quiet=quiet,
                             dry_run=dry_run, dependencies=dependencies)
    elif package_file.endswith('.whl'):
        raise RuntimeError('Conversion from wheel packages is not '
                            'implemented yet, stay tuned.')
    else:
        raise RuntimeError("cannot convert: %s" % package_file)


def test_installable(channel='defaults'):
    """Check to make sure that packages in channel are installable.
    This is a consistency check for the channel."""
    from .inspect import test_installable
    return test_installable(channel)


def inspect_linkages(packages, prefix=_sys.prefix, untracked=False, all_packages=False,
                     show_files=False, groupby='package'):
    from .inspect import inspect_linkages
    packages = _ensure_list(packages)
    return inspect_linkages(packages, prefix=prefix, untracked=untracked, all_packages=all_packages,
                            show_files=show_files, groupby=groupby)


def inspect_objects(packages, prefix=_sys.prefix, groupby='filename'):
    from .inspect import inspect_objects
    packages = _ensure_list(packages)
    return inspect_objects(packages, prefix=prefix, groupby=groupby)


def inspect_prefix_length(packages, min_prefix_length=_prefix_length):
    from conda_build.tarcheck import check_prefix_lengths
    packages = _ensure_list(packages)
    prefix_lengths = check_prefix_lengths(packages, min_prefix_length)
    if prefix_lengths:
        print("Packages with binary prefixes shorter than %d characters:"
                % min_prefix_length)
        for fn, length in prefix_lengths.items():
            print("{0} ({1} chars)".format(fn, length))
    else:
        print("No packages found with binary prefixes shorter than %d characters."
                % min_prefix_length)
    return len(prefix_lengths) == 0


def create_metapackage(name, version, entry_points=(), build_string=None, build_number=0,
                       dependencies=(), home=None, license_name=None, summary=None,
                       config=None):
    from .metapackage import create_metapackage
    if not config:
        config = Config()
    return create_metapackage(name=name, version=version, entry_points=entry_points,
                              build_string=build_string, build_number=build_number,
                              dependencies=dependencies, home=home,
                              license_name=license_name, summary=summary, config=config)


def update_index(dir_paths, config=None, force=False, check_md5=False, remove=False):
    from locale import getpreferredencoding
    import os
    from .conda_interface import PY3
    from conda_build.index import update_index
    dir_paths = [os.path.abspath(path) for path in _ensure_list(dir_paths)]
    # Don't use byte strings in Python 2
    if not PY3:
        dir_paths = [path.decode(getpreferredencoding()) for path in dir_paths]

    if not config:
        config = Config()

    for path in dir_paths:
        update_index(path, config, force=force, check_md5=check_md5, remove=remove)
