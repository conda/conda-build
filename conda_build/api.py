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
import os, sys, subprocess

# make the Config class available in the api namespace
from conda_build.config import (Config, get_or_merge_config, get_channel_urls,
                                DEFAULT_PREFIX_LENGTH as _prefix_length)
from conda_build.utils import ensure_list as _ensure_list
from conda_build.utils import expand_globs as _expand_globs
from conda_build.utils import get_logger as _get_logger
from os.path import dirname, expanduser, join
from conda_build.utils import pathhash as _pathhash

def render(recipe_path, config=None, variants=None, permit_unsatisfiable_variants=True,
           finalize=True, bypass_env_check=False, **kwargs):
    """Given path to a recipe, return the MetaData object(s) representing that recipe, with jinja2
       templates evaluated.

    Returns a list of (metadata, needs_download, needs_reparse in env) tuples"""
    from conda_build.render import render_recipe_cached, finalize_metadata
    from conda_build.exceptions import DependencyNeedsBuildingError
    from conda_build.conda_interface import NoPackagesFoundError
    from collections import OrderedDict
    config = get_or_merge_config(config, **kwargs)

    metadata_tuples = render_recipe_cached(recipe_path, bypass_env_check=bypass_env_check,
                                           config=config, variants=variants,
                                           permit_unsatisfiable_variants=permit_unsatisfiable_variants)
    output_metas = OrderedDict()
    for meta, download, render_in_env in metadata_tuples:
        if not meta.skip() or not config.trim_skip:
            for od, om in meta.get_output_metadata_set(
                    permit_unsatisfiable_variants=permit_unsatisfiable_variants,
                    permit_undefined_jinja=not finalize,
                    bypass_env_check=bypass_env_check):
                if not om.skip() or not config.trim_skip:
                    if 'type' not in od or od['type'] == 'conda':
                        if finalize and not om.final:
                            try:
                                om = finalize_metadata(om,
                                        permit_unsatisfiable_variants=permit_unsatisfiable_variants)
                            except (DependencyNeedsBuildingError, NoPackagesFoundError):
                                if not permit_unsatisfiable_variants:
                                    raise

                        # remove outputs section from output objects for simplicity
                        if not om.path and om.meta.get('outputs'):
                            om.parent_outputs = om.meta['outputs']
                            del om.meta['outputs']

                        output_metas[om.dist(), om.config.variant.get('target_platform'),
                                    tuple((var, om.config.variant[var])
                                        for var in om.get_used_vars())] = \
                            ((om, download, render_in_env))
                    else:
                        output_metas["{}: {}".format(om.type, om.name()), om.config.variant.get('target_platform'),
                                    tuple((var, om.config.variant[var])
                                        for var in om.get_used_vars())] = \
                            ((om, download, render_in_env))

    return list(output_metas.values())

'''
from conda_build.utils import pathhash
@memoized_to_cached_picked_file
def render(recipe_path, config=None, variants=None, permit_unsatisfiable_variants=True,
           finalize=True, bypass_env_check=False, **kwargs):
    # Bisecting the recipe requires rendering it first to:
    # 1. Make sure it has as many git_refs as we have elements in bisect_git_ref_starts
    from conda_build.cli.main_render import render_parsed_args_to_config_and_variants
    from conda_build.variants import get_package_variants
    metadata = render_uncached(recipe_path, config=config,
                               variants=variants, permit_unsatisfiable_variants=permit_unsatisfiable_variants,
                               finalize=finalize, bypass_env_check=bypass_env_check,
                               **kwargs)
    return metadata
'''

def output_yaml(metadata, file_path=None, suppress_outputs=False):
    """Save a rendered recipe in its final form to the path given by file_path"""
    from conda_build.render import output_yaml
    return output_yaml(metadata, file_path, suppress_outputs=suppress_outputs)


def get_output_file_paths(recipe_path_or_metadata, no_download_source=False, config=None,
                         variants=None, **kwargs):
    """Get output file paths for any packages that would be created by a recipe

    Both split packages (recipes with more than one output) and build matrices,
    created with variants, contribute to the list of file paths here.
    """
    from conda_build.render import bldpkg_path
    from conda_build.conda_interface import string_types
    from conda_build.utils import get_skip_message
    config = get_or_merge_config(config, no_download_source=no_download_source, **kwargs)
    assert config.no_download_source == no_download_source

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
        metadata = render(recipe_path_or_metadata, variants=variants,
                          config=config, finalize=True, **kwargs)
    else:
        assert hasattr(recipe_path_or_metadata, 'config'), ("Expecting metadata object - got {}"
                                                            .format(recipe_path_or_metadata))
        metadata = [(recipe_path_or_metadata, None, None)]
    #    Next, loop over outputs that each metadata defines
    outs = []
    for (m, _, _) in metadata:
        if m.skip():
            outs.append(get_skip_message(m))
        else:
            outs.append(bldpkg_path(m))
    return sorted(list(set(outs)))


def get_output_file_path(recipe_path_or_metadata, no_download_source=False, config=None,
                         variants=None, **kwargs):
    """Get output file paths for any packages that would be created by a recipe

    Both split packages (recipes with more than one output) and build matrices,
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
          build_only=False, notest=False, config=None, variants=None, stats=None,
          **kwargs):
    """Run the build step.

    If recipe paths are provided, renders recipe before building.
    Tests built packages by default.  notest=True to skip test."""
    import os
    from conda_build.build import build_tree
    from conda_build.conda_interface import string_types
    from conda_build.utils import find_recipe

    assert post in (None, True, False), ("post must be boolean or None.  Remember, you must pass "
                                         "other arguments (config) by keyword.")

    recipes = []
    for recipe in _ensure_list(recipe_paths_or_metadata):
        if isinstance(recipe, string_types):
            for recipe in _expand_globs(recipe, os.getcwd()):
                try:
                    recipe = find_recipe(recipe)
                except IOError:
                    continue
                recipes.append(recipe)
        elif hasattr(recipe, "config"):
            recipes.append(recipe)
        else:
            raise ValueError("Recipe passed was unrecognized object: {}".format(recipe))

    if not recipes:
        raise ValueError('No valid recipes found for input: {}'.format(recipe_paths_or_metadata))

    return build_tree(
        recipes,
        config=get_or_merge_config(config, **kwargs),
        # If people don't pass in an object to capture stats in, they won't get them returned.
        # We'll still track them, though.
        stats=stats or {},
        build_only=build_only,
        post=post,
        notest=notest,
        variants=variants
    )


def test(recipedir_or_package_or_metadata, move_broken=True, config=None, stats=None, **kwargs):
    """Run tests on either packages (.tar.bz2 or extracted) or recipe folders

    For a recipe folder, it renders the recipe enough to know what package to download, and obtains
    it from your currently configuured channels."""
    from conda_build.build import test

    if hasattr(recipedir_or_package_or_metadata, 'config'):
        config = recipedir_or_package_or_metadata.config
    else:
        config = get_or_merge_config(config, **kwargs)

    # if people don't pass in an object to capture stats in, they won't get them returned.
    #     We'll still track them, though.
    if not stats:
        stats = {}

    with config:
        # This will create a new local build folder if and only if config
        #   doesn't already have one. What this means is that if we're
        #   running a test immediately after build, we use the one that the
        #   build already provided
        test_result = test(recipedir_or_package_or_metadata, config=config, move_broken=move_broken,
                           stats=stats)
    return test_result


def bisect(recipedir_or_package_or_metadata, move_broken=True, config=None, stats=None, **kwargs):
    # Some checks.
    starts = config.bisect_git_ref_starts
    ends = config.bisect_git_ref_ends
    if not starts:
        raise ValueError("bisect: You must pass at least one --start git reference")
    if not ends:
        ends = []
    if len(starts) != len(ends) and len(ends):
        raise ValueError("bisect: You must pass as many --starts as --ends (or no ends at all)")
    if config.bisect_recipe_repo:
        pass
    else:
        recipe_and_cbc_hash = _pathhash(recipedir_or_package_or_metadata, if_file_use_dir=True)
        metadata_tuples = render(recipedir_or_package_or_metadata, config=config,
                                 no_download_source=False, variants=None,
                                 persistent_cache=config.persistent_cb_cache,
                                 persistent_cache_seed=recipe_and_cbc_hash,
                                 persistent_cache_suffix='.rendered')
    sys.exit(1)
    from conda_build.build import get_all_replacements
    from conda_build import utils
    try:
        from conda.base.constants import CONDA_PACKAGE_EXTENSIONS, CONDA_PACKAGE_EXTENSION_V1, \
            CONDA_PACKAGE_EXTENSION_V2
    except Exception:
        from conda.base.constants import CONDA_TARBALL_EXTENSION as CONDA_PACKAGE_EXTENSION_V1

    post = True
    built_packages = []
    notest = False
    for (metadata, need_source_download, need_reparse_in_env) in metadata_tuples:
        get_all_replacements(metadata.config.variant)
        if post is None:
            utils.rm_rf(metadata.config.host_prefix)
            utils.rm_rf(metadata.config.build_prefix)
            utils.rm_rf(metadata.config.test_prefix)
        if metadata.name() not in metadata.config.build_folder:
            metadata.config.compute_build_id(metadata.name(), reset=True)
        from conda_build.build import build as conda_build_build
        packages_from_this = conda_build_build(metadata, stats=None,
                                   post=post,
                                   need_source_download=need_source_download,
                                   need_reparse_in_env=need_reparse_in_env,
                                   built_packages=built_packages,
                                   notest=notest,
                                   )
        if not notest:
            for pkg, dict_and_meta in packages_from_this.items():
                if pkg.endswith(CONDA_PACKAGE_EXTENSIONS) and os.path.isfile(pkg):
                    # we only know how to test conda packages
                    test(pkg, config=metadata.config.copy(), stats=stats)
                _, meta = dict_and_meta
                downstreams = meta.meta.get('test', {}).get('downstreams')
                if downstreams:
                    channel_urls = tuple(utils.ensure_list(metadata.config.channel_urls) +
                                         [utils.path2url(os.path.abspath(os.path.dirname(
                                             os.path.dirname(pkg))))])
                    log = utils.get_logger(__name__)
                    # downstreams can be a dict, for adding capability for worker labels
                    if hasattr(downstreams, 'keys'):
                        downstreams = list(downstreams.keys())
                        log.warn("Dictionary keys for downstreams are being "
                                 "ignored right now.  Coming soon...")
                    else:
                        downstreams = utils.ensure_list(downstreams)
                    for dep in downstreams:
                        log.info("Testing downstream package: {}".format(dep))
                        # resolve downstream packages to a known package

                        r_string = ''.join(random.choice(
                            string.ascii_uppercase + string.digits) for _ in range(10))
                        specs = meta.ms_depends('run') + [MatchSpec(dep),
                                                          MatchSpec(' '.join(meta.dist().rsplit('-', 2)))]
                        specs = [utils.ensure_valid_spec(spec) for spec in specs]
                        try:
                            with TemporaryDirectory(prefix="_", suffix=r_string) as tmpdir:
                                actions = environ.get_install_actions(
                                    tmpdir, specs, env='run',
                                    subdir=meta.config.host_subdir,
                                    bldpkgs_dirs=meta.config.bldpkgs_dirs,
                                    channel_urls=channel_urls)
                        except (UnsatisfiableError, DependencyNeedsBuildingError) as e:
                            log.warn("Skipping downstream test for spec {}; was "
                                     "unsatisfiable.  Error was {}".format(dep, e))
                            continue
                        # make sure to download that package to the local cache if not there
                        local_file = execute_download_actions(meta, actions, 'host',
                                                              package_subset=dep,
                                                              require_files=True)
                        # test that package, using the local channel so that our new
                        #    upstream dep gets used
                        test(list(local_file.values())[0][0],
                             config=meta.config.copy(), stats=stats)

                built_packages.update({pkg: dict_and_meta})
        else:
            built_packages.update(packages_from_this)

        for (metadata, need_source_download, need_reparse_in_env) in metadata_tuples:
            get_all_replacements(metadata.config.variant)
            if post is None:
                utils.rm_rf(metadata.config.host_prefix)
                utils.rm_rf(metadata.config.build_prefix)
                utils.rm_rf(metadata.config.test_prefix)
            if metadata.name() not in metadata.config.build_folder:
                metadata.config.compute_build_id(metadata.name(), reset=True)

            packages_from_this = build(metadata, stats,
                                       post=post,
                                       need_source_download=need_source_download,
                                       need_reparse_in_env=need_reparse_in_env,
                                       built_packages=built_packages,
                                       notest=notest,
                                       )
            if not notest:
                for pkg, dict_and_meta in packages_from_this.items():
                    if pkg.endswith(CONDA_PACKAGE_EXTENSIONS) and os.path.isfile(pkg):
                        # we only know how to test conda packages
                        test(pkg, config=metadata.config.copy(), stats=stats)
                    _, meta = dict_and_meta
                    downstreams = meta.meta.get('test', {}).get('downstreams')
                    if downstreams:
                        channel_urls = tuple(utils.ensure_list(metadata.config.channel_urls) +
                                             [utils.path2url(os.path.abspath(os.path.dirname(
                                                 os.path.dirname(pkg))))])
                        log = utils.get_logger(__name__)
                        # downstreams can be a dict, for adding capability for worker labels
                        if hasattr(downstreams, 'keys'):
                            downstreams = list(downstreams.keys())
                            log.warn("Dictionary keys for downstreams are being "
                                     "ignored right now.  Coming soon...")
                        else:
                            downstreams = utils.ensure_list(downstreams)
                        for dep in downstreams:
                            log.info("Testing downstream package: {}".format(dep))
                            # resolve downstream packages to a known package

                            r_string = ''.join(random.choice(
                                string.ascii_uppercase + string.digits) for _ in range(10))
                            specs = meta.ms_depends('run') + [MatchSpec(dep),
                                                              MatchSpec(' '.join(meta.dist().rsplit('-', 2)))]
                            specs = [utils.ensure_valid_spec(spec) for spec in specs]
                            try:
                                with TemporaryDirectory(prefix="_", suffix=r_string) as tmpdir:
                                    actions = environ.get_install_actions(
                                        tmpdir, specs, env='run',
                                        subdir=meta.config.host_subdir,
                                        bldpkgs_dirs=meta.config.bldpkgs_dirs,
                                        channel_urls=channel_urls)
                            except (UnsatisfiableError, DependencyNeedsBuildingError) as e:
                                log.warn("Skipping downstream test for spec {}; was "
                                         "unsatisfiable.  Error was {}".format(dep, e))
                                continue
                            # make sure to download that package to the local cache if not there
                            local_file = execute_download_actions(meta, actions, 'host',
                                                                  package_subset=dep,
                                                                  require_files=True)
                            # test that package, using the local channel so that our new
                            #    upstream dep gets used
                            test(list(local_file.values())[0][0],
                                 config=meta.config.copy(), stats=stats)

                    built_packages.update({pkg: dict_and_meta})
            else:
                built_packages.update(packages_from_this)


def list_skeletons():
    """List available skeletons for generating conda recipes from external sources.

    The returned list is generally the names of supported repositories (pypi, cran, etc.)"""
    import pkgutil
    modules = pkgutil.iter_modules([join(dirname(__file__), 'skeletons')])
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
        output_dir = expanduser(output_dir)
        kwargs.update({'output_dir': output_dir})

    # here we're dumping all extra kwargs as attributes on the config object.  We'll extract
    #    only relevant ones below
    config = get_or_merge_config(config, **kwargs)
    config.compute_build_id('skeleton')
    packages = _ensure_list(packages)

    # This is a little bit of black magic.  The idea is that for any keyword argument that
    #    we inspect from the given module's skeletonize function, we should hoist the argument
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
    from .inspect_pkg import test_installable
    return test_installable(channel)


def inspect_linkages(packages, prefix=_sys.prefix, untracked=False, all_packages=False,
                     show_files=False, groupby='package', sysroot=''):
    from .inspect_pkg import inspect_linkages
    packages = _ensure_list(packages)
    return inspect_linkages(packages, prefix=prefix, untracked=untracked, all_packages=all_packages,
                            show_files=show_files, groupby=groupby, sysroot=sysroot)


def inspect_objects(packages, prefix=_sys.prefix, groupby='filename'):
    from .inspect_pkg import inspect_objects
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
    from .inspect_pkg import get_hash_input
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


def update_index(dir_paths, config=None, force=False, check_md5=False, remove=False, channel_name=None,
                 subdir=None, threads=None, patch_generator=None, verbose=False, progress=False,
                 hotfix_source_repo=None, current_index_versions=None, **kwargs):
    import yaml
    from locale import getpreferredencoding
    import os
    from .conda_interface import PY3, string_types
    from conda_build.index import update_index
    from conda_build.utils import ensure_list
    dir_paths = [os.path.abspath(path) for path in _ensure_list(dir_paths)]
    # Don't use byte strings in Python 2
    if not PY3:
        dir_paths = [path.decode(getpreferredencoding()) for path in dir_paths]

    if isinstance(current_index_versions, string_types):
        with open(current_index_versions) as f:
            current_index_versions = yaml.safe_load(f)

    for path in dir_paths:
        update_index(path, check_md5=check_md5, channel_name=channel_name,
                     patch_generator=patch_generator, threads=threads, verbose=verbose,
                     progress=progress, hotfix_source_repo=hotfix_source_repo,
                     subdirs=ensure_list(subdir), current_index_versions=current_index_versions,
                     index_file=kwargs.get('index_file', None))


def debug(recipe_or_package_path_or_metadata_tuples, path=None, test=False,
          output_id=None, config=None, verbose=True, link_source_method='auto', **kwargs):
    """Set up either build/host or test environments, leaving you with a quick tool to debug
    your package's build or test phase.
    """
    from fnmatch import fnmatch
    import logging
    import os
    import time
    from conda_build.conda_interface import string_types
    from conda_build.build import test as run_test, build as run_build
    from conda_build.utils import CONDA_PACKAGE_EXTENSIONS, on_win, LoggingContext
    is_package = False
    default_config = get_or_merge_config(config, **kwargs)
    args = {"set_build_id": False}
    path_is_build_dir = False
    workdirs = [os.path.join(recipe_or_package_path_or_metadata_tuples, d)
                for d in (os.listdir(recipe_or_package_path_or_metadata_tuples) if
                    os.path.isdir(recipe_or_package_path_or_metadata_tuples) else [])
                if (d.startswith('work') and
                os.path.isdir(os.path.join(recipe_or_package_path_or_metadata_tuples, d)))]
    metadatas_conda_debug = [os.path.join(f, "metadata_conda_debug.yaml") for f in workdirs
                            if os.path.isfile(os.path.join(f, "metadata_conda_debug.yaml"))]
    metadatas_conda_debug = sorted(metadatas_conda_debug)
    if len(metadatas_conda_debug):
        path_is_build_dir = True
        path = recipe_or_package_path_or_metadata_tuples
    if not path:
        path = os.path.join(default_config.croot, "debug_{}".format(int(time.time() * 1000)))
    config = get_or_merge_config(config=default_config, croot=path, verbose=verbose, _prefix_length=10,
                                 **args)

    config.channel_urls = get_channel_urls(kwargs)

    metadata_tuples = []

    best_link_source_method = 'skip'
    if isinstance(recipe_or_package_path_or_metadata_tuples, string_types):
        if path_is_build_dir:
            for metadata_conda_debug in metadatas_conda_debug:
                best_link_source_method = 'symlink'
                from conda_build.metadata import MetaData
                metadata = MetaData(metadata_conda_debug, config, {})
                metadata_tuples.append((metadata, False, True))
        else:
            ext = os.path.splitext(recipe_or_package_path_or_metadata_tuples)[1]
            if not ext or not any(ext in _ for _ in CONDA_PACKAGE_EXTENSIONS):
                metadata_tuples = render(recipe_or_package_path_or_metadata_tuples, config=config, **kwargs)
            else:
                # this is a package, we only support testing
                test = True
                is_package = True
    else:
        metadata_tuples = recipe_or_package_path_or_metadata_tuples

    if metadata_tuples:
        outputs = get_output_file_paths(metadata_tuples)
        matched_outputs = outputs
        if output_id:
            matched_outputs = [_ for _ in outputs if fnmatch(os.path.basename(_), output_id)]
            if len(matched_outputs) > 1:
                raise ValueError("Specified --output-id matches more than one output ({}).  Please refine your output id so that only "
                    "a single output is found.".format(matched_outputs))
            elif not matched_outputs:
                raise ValueError("Specified --output-id did not match any outputs.  Available outputs are: {} Please check it and try again".format(outputs))
        if len(matched_outputs) > 1 and not path_is_build_dir:
            raise ValueError("More than one output found for this recipe ({}).  Please use the --output-id argument to filter down "
                            "to a single output.".format(outputs))
        else:
            matched_outputs = outputs

        target_metadata = metadata_tuples[outputs.index(matched_outputs[0])][0]
        # make sure that none of the _placehold stuff gets added to env paths
        target_metadata.config.prefix_length = 10

    if best_link_source_method == 'symlink':
        for metadata, _, _ in metadata_tuples:
            debug_source_loc = os.path.join(os.sep + 'usr', 'local', 'src', 'conda',
                                            '{}-{}'.format(metadata.get_value('package/name'),
                                                           metadata.get_value('package/version')))
            link_target = os.path.dirname(metadata.meta_path)
            try:
                dn = os.path.dirname(debug_source_loc)
                try:
                    os.makedirs(dn)
                except FileExistsError:
                    pass
                try:
                    os.unlink(debug_source_loc)
                except:
                    pass
                print("Making debug info source symlink: {} => {}".format(debug_source_loc, link_target))
                os.symlink(link_target, debug_source_loc)
            except PermissionError as e:
                raise Exception("You do not have the necessary permissions to create symlinks in {}\nerror: {}"
                                .format(dn, str(e)))
            except Exception as e:
                raise Exception("Unknown error creating symlinks in {}\nerror: {}"
                                .format(dn, str(e)))
    ext = ".bat" if on_win else ".sh"

    if verbose:
        log_context = LoggingContext()
    else:
        log_context = LoggingContext(logging.CRITICAL + 1)

    if path_is_build_dir:
        activation_file = "build_env_setup" + ext
        activation_string = "cd {work_dir} && {source} {activation_file}\n".format(
            work_dir=target_metadata.config.work_dir,
            source="call" if on_win else "source",
            activation_file=os.path.join(target_metadata.config.work_dir, activation_file))
    elif not test:
        with log_context:
            run_build(target_metadata, stats={}, provision_only=True)
        activation_file = "build_env_setup" + ext
        activation_string = "cd {work_dir} && {source} {activation_file}\n".format(
            work_dir=target_metadata.config.work_dir,
            source="call" if on_win else "source",
            activation_file=os.path.join(target_metadata.config.work_dir, activation_file))
    else:
        if not is_package:
            raise ValueError("Debugging for test mode is only supported for package files that already exist. "
                             "Please build your package first, then use it to create the debugging environment.")
        else:
            test_input = recipe_or_package_path_or_metadata_tuples
        # use the package to create an env and extract the test files.  Stop short of running the tests.
        # tell people what steps to take next
        with log_context:
            run_test(test_input, config=config, stats={}, provision_only=True)
        activation_file = os.path.join(config.test_dir, "conda_test_env_vars" + ext)
        activation_string = "cd {work_dir} && {source} {activation_file}\n".format(
            work_dir=config.test_dir,
            source="call" if on_win else "source",
            activation_file=os.path.join(config.test_dir, activation_file))
    return activation_string
