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
from conda_build.utils import expand_globs as _expand_globs
from conda_build.utils import conda_43 as _conda_43
from conda_build.utils import get_logger as _get_logger


def render(recipe_path, config=None, variants=None, permit_unsatisfiable_variants=True,
           **kwargs):
    """Given path to a recipe, return the MetaData object(s) representing that recipe, with jinja2
       templates evaluated.

    Returns a list of (metadata, needs_download, needs_reparse in env) tuples"""
    from conda_build.render import render_recipe
    config = get_or_merge_config(config, **kwargs)

    metadata_tuples, index = render_recipe(recipe_path,
                                    no_download_source=config.no_download_source,
                                    config=config, variants=variants,
                                    permit_unsatisfiable_variants=permit_unsatisfiable_variants)

    output_metas = []
    for meta, download, render_in_env in metadata_tuples:
        for _, om in meta.get_output_metadata_set(
                permit_unsatisfiable_variants=permit_unsatisfiable_variants):
            output_metas.append((om, download, render_in_env))
    return output_metas


def output_yaml(metadata, file_path=None):
    """Save a rendered recipe in its final form to the path given by file_path"""
    from conda_build.render import output_yaml
    return output_yaml(metadata, file_path)


def get_output_file_paths(recipe_path_or_metadata, no_download_source=False, config=None,
                         variants=None, **kwargs):
    """Get output file paths for any packages that would be created by a recipe

    Both split packages (recipes with more than one ouptut) and build matrices,
    created with variants, contribute to the list of file paths here.
    """
    from conda_build.render import bldpkg_path
    from conda_build.conda_interface import string_types
    config = get_or_merge_config(config, **kwargs)
    if hasattr(recipe_path_or_metadata, '__iter__') and not isinstance(recipe_path_or_metadata,
                                                                       string_types):
        list_of_metas = [hasattr(item[0], 'config') for item in recipe_path_or_metadata
                        if len(item) == 3]

        if list_of_metas and all(list_of_metas):
            metadata = recipe_path_or_metadata
        else:
            raise ValueError("received mixed list of metas: {}".format(recipe_path_or_metadata))
    elif isinstance(recipe_path_or_metadata, string_types):
        # first, render the parent recipe (potentially multiple outputs, depending on variants).
        metadata = render(recipe_path_or_metadata, no_download_source=no_download_source,
                            variants=variants, config=config)
    else:
        assert hasattr(recipe_path_or_metadata, 'config'), ("Expecting metadata object - got {}"
                                                            .format(recipe_path_or_metadata))
        metadata = [(recipe_path_or_metadata, None, None)]
    #    Next, loop over outputs that each metadata defines
    outs = []
    for (m, _, _) in metadata:
        if m.skip():
            outs.append("Skipped: {} defines build/skip for this configuration."
                        .format(m.path))
        else:
            outs.append(bldpkg_path(m))
    return sorted(list(set(outs)))


def get_output_file_path(recipe_path_or_metadata, no_download_source=False, config=None,
                         variants=None, **kwargs):
    """Get output file paths for any packages that would be created by a recipe

    Both split packages (recipes with more than one ouptut) and build matrices,
    created with variants, contribute to the list of file paths here.
    """
    log = _get_logger(__name__)
    log.warn("deprecation warning: this function has been renamed to get_output_file_paths, "
             "to reflect that potentially multiple paths are returned.  This function will be "
             "removed in the conda-build 4.0 release.")
    return get_output_file_paths(recipe_path_or_metadata,
                                 no_download_source=no_download_source,
                                 config=config, variants=variants, **kwargs)


def check(recipe_path, no_download_source=False, config=None, variants=None, **kwargs):
    """Check validity of input recipe path

    Verifies that recipe can be completely rendered, and that fields of the rendered recipe are
    valid fields, with some value checking.
    """
    config = get_or_merge_config(config, **kwargs)
    metadata = render(recipe_path, no_download_source=no_download_source,
                      config=config, variants=variants)
    return all(m[0].check_fields() for m in metadata)


def build(recipe_paths_or_metadata, post=None, need_source_download=True,
          build_only=False, notest=False, config=None, variants=None, **kwargs):
    """Run the build step.

    If recipe paths are provided, renders recipe before building.
    Tests built packages by default.  notest=True to skip test."""

    import os
    from conda_build.build import build_tree
    from conda_build.conda_interface import string_types
    from conda_build.utils import find_recipe

    assert post in (None, True, False), ("post must be boolean or None.  Remember, you must pass "
                                         "other arguments (config) by keyword.")

    config = get_or_merge_config(config, **kwargs)

    recipe_paths_or_metadata = _ensure_list(recipe_paths_or_metadata)
    for recipe in recipe_paths_or_metadata:
        if not any((hasattr(recipe, "config"), isinstance(recipe, string_types))):
            raise ValueError("Recipe passed was unrecognized object: {}".format(recipe))
    string_paths = [p for p in recipe_paths_or_metadata if isinstance(p, string_types)]
    paths = _expand_globs(string_paths, os.getcwd())
    recipes = []
    for recipe in paths:
        try:
            recipes.append(find_recipe(recipe))
        except IOError:
            continue
    metadata = [m for m in recipe_paths_or_metadata if hasattr(m, 'config')]
    recipes.extend(metadata)
    absolute_recipes = []
    for recipe in recipes:
        if hasattr(recipe, "config"):
            absolute_recipes.append(recipe)
        else:
            if not os.path.isabs(recipe):
                recipe = os.path.normpath(os.path.join(os.getcwd(), recipe))
            if not os.path.exists(recipe):
                raise ValueError("Path to recipe did not exist: {}".format(recipe))
            absolute_recipes.append(recipe)

    if not absolute_recipes:
        raise ValueError('No valid recipes found for input: {}'.format(recipe_paths_or_metadata))
    return build_tree(absolute_recipes, build_only=build_only, post=post, notest=notest,
                      need_source_download=need_source_download, config=config, variants=variants)


def test(recipedir_or_package_or_metadata, move_broken=True, config=None, **kwargs):
    """Run tests on either a package or a recipe folder

    For a recipe folder, it renders the recipe enough to know what package to download, and obtains
    it from your currently configuured channels."""
    from conda_build.build import test

    if hasattr(recipedir_or_package_or_metadata, 'config'):
        config = recipedir_or_package_or_metadata.config
    else:
        config = get_or_merge_config(config, **kwargs)

    with config:
        # This will create a new local build folder if and only if config doesn't already have one.
        #   What this means is that if we're running a test immediately after build, we use the one
        #   that the build already provided

        test_result = test(recipedir_or_package_or_metadata, config=config,
                           move_broken=move_broken)

    return test_result


def keygen(name="conda_build_signing", size=2048):
    """Create a private/public key pair for package verification purposes

    name: string name of key to be generated.
    size: length of the RSA key, in bits.  Should be power of 2.
    """
    if _conda_43():
        raise ValueError("Signing is not supported with Conda v4.3 and above.  Aborting.")
    from .sign import keygen
    return keygen(name, size)


def import_sign_key(private_key_path, new_name=None):
    """
    private_key_path: specify a private key to be imported.  The public key is
          generated automatically.  Specify ```new_name``` also to rename the
          private key in the copied location.
    """
    if _conda_43():
        raise ValueError("Signing is not supported with Conda v4.3 and above.  Aborting.")
    from .sign import import_key
    return import_key(private_key_path, new_name=new_name)


def sign(file_path, key_name_or_path=None):
    """Create a signature file for accompanying a package"""
    if _conda_43():
        raise ValueError("Signing is not supported with Conda v4.3 and above.  Aborting.")
    from .sign import sign_and_write
    return sign_and_write(file_path, key_name_or_path)


def verify(file_path):
    """Verify a signed package"""
    if _conda_43():
        raise ValueError("Signing is not supported with Conda v4.3 and above.  Aborting.")
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
        kwargs.update({'recursive': recursive})
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
    platforms = _ensure_list(platforms)
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
    config = Config(prefix_length=min_prefix_length)
    packages = _ensure_list(packages)
    prefix_lengths = check_prefix_lengths(packages, config)
    if prefix_lengths:
        print("Packages with binary prefixes shorter than %d characters:"
                % min_prefix_length)
        for fn, length in prefix_lengths.items():
            print("{0} ({1} chars)".format(fn, length))
    else:
        print("No packages found with binary prefixes shorter than %d characters."
                % min_prefix_length)
    return len(prefix_lengths) == 0


def inspect_hash_inputs(packages):
    """Return dictionaries of data that created the hash value (h????) for the provided package(s)

    Returns a dictionary with a key for each input package and a value of the dictionary loaded
    from the package's info/hash_input.json file
    """
    from .inspect import get_hash_input
    return get_hash_input(packages)


def create_metapackage(name, version, entry_points=(), build_string=None, build_number=0,
                       dependencies=(), home=None, license_name=None, summary=None,
                       config=None, **kwargs):
    from .metapackage import create_metapackage
    config = get_or_merge_config(config, **kwargs)
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
