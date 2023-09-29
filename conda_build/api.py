# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
This file defines the public API for conda-build.  Adding or removing functions,
or Changing arguments to anything in here should also mean changing the major
version number.

Design philosophy: put variability into config.  Make each function here accept kwargs,
but only use those kwargs in config.  Config must change to support new features elsewhere.
"""

import sys as _sys

# imports are done locally to keep the api clean and limited strictly
#    to conda-build's functionality.
from os.path import dirname, expanduser, join
from pathlib import Path

# make the Config class available in the api namespace
from conda_build.config import DEFAULT_PREFIX_LENGTH as _prefix_length
from conda_build.config import Config, get_channel_urls, get_or_merge_config
from conda_build.utils import ensure_list as _ensure_list
from conda_build.utils import expand_globs as _expand_globs
from conda_build.utils import get_logger as _get_logger

from .deprecations import deprecated


def render(
    recipe_path,
    config=None,
    variants=None,
    permit_unsatisfiable_variants=True,
    finalize=True,
    bypass_env_check=False,
    **kwargs,
):
    """Given path to a recipe, return the MetaData object(s) representing that recipe, with jinja2
       templates evaluated.

    Returns a list of (metadata, needs_download, needs_reparse in env) tuples"""
    from collections import OrderedDict

    from conda_build.conda_interface import NoPackagesFoundError
    from conda_build.exceptions import DependencyNeedsBuildingError
    from conda_build.render import finalize_metadata, render_recipe

    config = get_or_merge_config(config, **kwargs)

    metadata_tuples = render_recipe(
        recipe_path,
        bypass_env_check=bypass_env_check,
        no_download_source=config.no_download_source,
        config=config,
        variants=variants,
        permit_unsatisfiable_variants=permit_unsatisfiable_variants,
    )
    output_metas = OrderedDict()
    for meta, download, render_in_env in metadata_tuples:
        if not meta.skip() or not config.trim_skip:
            for od, om in meta.get_output_metadata_set(
                permit_unsatisfiable_variants=permit_unsatisfiable_variants,
                permit_undefined_jinja=not finalize,
                bypass_env_check=bypass_env_check,
            ):
                if not om.skip() or not config.trim_skip:
                    if "type" not in od or od["type"] == "conda":
                        if finalize and not om.final:
                            try:
                                om = finalize_metadata(
                                    om,
                                    permit_unsatisfiable_variants=permit_unsatisfiable_variants,
                                )
                            except (DependencyNeedsBuildingError, NoPackagesFoundError):
                                if not permit_unsatisfiable_variants:
                                    raise

                        # remove outputs section from output objects for simplicity
                        if not om.path and om.meta.get("outputs"):
                            om.parent_outputs = om.meta["outputs"]
                            del om.meta["outputs"]

                        output_metas[
                            om.dist(),
                            om.config.variant.get("target_platform"),
                            tuple(
                                (var, om.config.variant[var])
                                for var in om.get_used_vars()
                            ),
                        ] = (om, download, render_in_env)
                    else:
                        output_metas[
                            f"{om.type}: {om.name()}",
                            om.config.variant.get("target_platform"),
                            tuple(
                                (var, om.config.variant[var])
                                for var in om.get_used_vars()
                            ),
                        ] = (om, download, render_in_env)

    return list(output_metas.values())


def output_yaml(metadata, file_path=None, suppress_outputs=False):
    """Save a rendered recipe in its final form to the path given by file_path"""
    from conda_build.render import output_yaml

    return output_yaml(metadata, file_path, suppress_outputs=suppress_outputs)


def get_output_file_paths(
    recipe_path_or_metadata,
    no_download_source=False,
    config=None,
    variants=None,
    **kwargs,
):
    """Get output file paths for any packages that would be created by a recipe

    Both split packages (recipes with more than one output) and build matrices,
    created with variants, contribute to the list of file paths here.
    """
    from conda_build.render import bldpkg_path
    from conda_build.utils import get_skip_message

    config = get_or_merge_config(config, **kwargs)

    if hasattr(recipe_path_or_metadata, "__iter__") and not isinstance(
        recipe_path_or_metadata, str
    ):
        list_of_metas = [
            hasattr(item[0], "config")
            for item in recipe_path_or_metadata
            if len(item) == 3
        ]

        if list_of_metas and all(list_of_metas):
            metadata = recipe_path_or_metadata
        else:
            raise ValueError(f"received mixed list of metas: {recipe_path_or_metadata}")
    elif isinstance(recipe_path_or_metadata, (str, Path)):
        # first, render the parent recipe (potentially multiple outputs, depending on variants).
        metadata = render(
            recipe_path_or_metadata,
            no_download_source=no_download_source,
            variants=variants,
            config=config,
            finalize=True,
            **kwargs,
        )
    else:
        assert hasattr(
            recipe_path_or_metadata, "config"
        ), f"Expecting metadata object - got {recipe_path_or_metadata}"
        metadata = [(recipe_path_or_metadata, None, None)]
    #    Next, loop over outputs that each metadata defines
    outs = []
    for m, _, _ in metadata:
        if m.skip():
            outs.append(get_skip_message(m))
        else:
            outs.append(bldpkg_path(m))
    return sorted(list(set(outs)))


def get_output_file_path(
    recipe_path_or_metadata,
    no_download_source=False,
    config=None,
    variants=None,
    **kwargs,
):
    """Get output file paths for any packages that would be created by a recipe

    Both split packages (recipes with more than one output) and build matrices,
    created with variants, contribute to the list of file paths here.
    """
    log = _get_logger(__name__)
    log.warn(
        "deprecation warning: this function has been renamed to get_output_file_paths, "
        "to reflect that potentially multiple paths are returned.  This function will be "
        "removed in the conda-build 4.0 release."
    )
    return get_output_file_paths(
        recipe_path_or_metadata,
        no_download_source=no_download_source,
        config=config,
        variants=variants,
        **kwargs,
    )


def check(recipe_path, no_download_source=False, config=None, variants=None, **kwargs):
    """Check validity of input recipe path

    Verifies that recipe can be completely rendered, and that fields of the rendered recipe are
    valid fields, with some value checking.
    """
    config = get_or_merge_config(config, **kwargs)
    metadata = render(
        recipe_path,
        no_download_source=no_download_source,
        config=config,
        variants=variants,
    )
    return all(m[0].check_fields() for m in metadata)


def build(
    recipe_paths_or_metadata,
    post=None,
    need_source_download=True,
    build_only=False,
    notest=False,
    config=None,
    variants=None,
    stats=None,
    **kwargs,
):
    """Run the build step.

    If recipe paths are provided, renders recipe before building.
    Tests built packages by default.  notest=True to skip test."""
    import os

    from conda_build.build import build_tree
    from conda_build.utils import find_recipe

    assert post in (None, True, False), (
        "post must be boolean or None.  Remember, you must pass "
        "other arguments (config) by keyword."
    )

    recipes = []
    for recipe in _ensure_list(recipe_paths_or_metadata):
        if isinstance(recipe, str):
            for recipe in _expand_globs(recipe, os.getcwd()):
                try:
                    recipe = find_recipe(recipe)
                except OSError:
                    continue
                recipes.append(recipe)
        elif hasattr(recipe, "config"):
            recipes.append(recipe)
        else:
            raise ValueError(f"Recipe passed was unrecognized object: {recipe}")

    if not recipes:
        raise ValueError(
            f"No valid recipes found for input: {recipe_paths_or_metadata}"
        )

    return build_tree(
        recipes,
        config=get_or_merge_config(config, **kwargs),
        # If people don't pass in an object to capture stats in, they won't get them returned.
        # We'll still track them, though.
        stats=stats or {},
        build_only=build_only,
        post=post,
        notest=notest,
        variants=variants,
    )


def test(
    recipedir_or_package_or_metadata,
    move_broken=True,
    config=None,
    stats=None,
    **kwargs,
):
    """Run tests on either packages (.tar.bz2 or extracted) or recipe folders

    For a recipe folder, it renders the recipe enough to know what package to download, and obtains
    it from your currently configuured channels."""
    from conda_build.build import test

    if hasattr(recipedir_or_package_or_metadata, "config"):
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
        test_result = test(
            recipedir_or_package_or_metadata,
            config=config,
            move_broken=move_broken,
            stats=stats,
        )
    return test_result


def list_skeletons():
    """List available skeletons for generating conda recipes from external sources.

    The returned list is generally the names of supported repositories (pypi, cran, etc.)
    """
    import pkgutil

    modules = pkgutil.iter_modules([join(dirname(__file__), "skeletons")])
    files = []
    for _, name, _ in modules:
        if not name.startswith("_"):
            files.append(name)
    return files


def skeletonize(
    packages, repo, output_dir=".", version=None, recursive=False, config=None, **kwargs
):
    """Generate a conda recipe from an external repo.  Translates metadata from external
    sources into expected conda recipe format."""

    version = getattr(config, "version", version)
    if version:
        kwargs.update({"version": version})
    if recursive:
        kwargs.update({"recursive": recursive})
    if output_dir != ".":
        output_dir = expanduser(output_dir)
        kwargs.update({"output_dir": output_dir})

    # here we're dumping all extra kwargs as attributes on the config object.  We'll extract
    #    only relevant ones below
    config = get_or_merge_config(config, **kwargs)
    config.compute_build_id("skeleton")
    packages = _ensure_list(packages)

    # This is a little bit of black magic.  The idea is that for any keyword argument that
    #    we inspect from the given module's skeletonize function, we should hoist the argument
    #    off of the config object, and pass it as a keyword argument.  This is sort of the
    #    inverse of what we do in the CLI code - there we take CLI arguments and dangle them
    #    all on the config object as attributes.
    module = getattr(
        __import__(
            "conda_build.skeletons", globals=globals(), locals=locals(), fromlist=[repo]
        ),
        repo,
    )

    func_args = module.skeletonize.__code__.co_varnames
    kwargs = {name: getattr(config, name) for name in dir(config) if name in func_args}
    kwargs.update({name: value for name, value in kwargs.items() if name in func_args})
    # strip out local arguments that we pass directly
    for arg in skeletonize.__code__.co_varnames:
        if arg in kwargs:
            del kwargs[arg]
    with config:
        skeleton_return = module.skeletonize(
            packages,
            output_dir=output_dir,
            version=version,
            recursive=recursive,
            config=config,
            **kwargs,
        )
    return skeleton_return


def develop(
    recipe_dir,
    prefix=_sys.prefix,
    no_pth_file=False,
    build_ext=False,
    clean=False,
    uninstall=False,
):
    """Install a Python package in 'development mode'.

    This works by creating a conda.pth file in site-packages."""
    from .develop import execute

    recipe_dir = _ensure_list(recipe_dir)
    return execute(recipe_dir, prefix, no_pth_file, build_ext, clean, uninstall)


def convert(
    package_file,
    output_dir=".",
    show_imports=False,
    platforms=None,
    force=False,
    dependencies=None,
    verbose=False,
    quiet=True,
    dry_run=False,
):
    """Convert changes a package from one platform to another.  It applies only to things that are
    portable, such as pure python, or header-only C/C++ libraries."""
    from .convert import conda_convert

    platforms = _ensure_list(platforms)
    if package_file.endswith("tar.bz2"):
        return conda_convert(
            package_file,
            output_dir=output_dir,
            show_imports=show_imports,
            platforms=platforms,
            force=force,
            verbose=verbose,
            quiet=quiet,
            dry_run=dry_run,
            dependencies=dependencies,
        )
    elif package_file.endswith(".whl"):
        raise RuntimeError(
            "Conversion from wheel packages is not " "implemented yet, stay tuned."
        )
    else:
        raise RuntimeError("cannot convert: %s" % package_file)


def test_installable(channel="defaults"):
    """Check to make sure that packages in channel are installable.
    This is a consistency check for the channel."""
    from .inspect_pkg import test_installable

    return test_installable(channel)


def inspect_linkages(
    packages,
    prefix=_sys.prefix,
    untracked=False,
    all_packages=False,
    show_files=False,
    groupby="package",
    sysroot="",
):
    from .inspect_pkg import inspect_linkages

    packages = _ensure_list(packages)
    return inspect_linkages(
        packages,
        prefix=prefix,
        untracked=untracked,
        all_packages=all_packages,
        show_files=show_files,
        groupby=groupby,
        sysroot=sysroot,
    )


def inspect_objects(packages, prefix=_sys.prefix, groupby="filename"):
    from .inspect_pkg import inspect_objects

    packages = _ensure_list(packages)
    return inspect_objects(packages, prefix=prefix, groupby=groupby)


def inspect_prefix_length(packages, min_prefix_length=_prefix_length):
    from conda_build.tarcheck import check_prefix_lengths

    config = Config(prefix_length=min_prefix_length)
    packages = _ensure_list(packages)
    prefix_lengths = check_prefix_lengths(packages, config)
    if prefix_lengths:
        print(
            "Packages with binary prefixes shorter than %d characters:"
            % min_prefix_length
        )
        for fn, length in prefix_lengths.items():
            print(f"{fn} ({length} chars)")
    else:
        print(
            "No packages found with binary prefixes shorter than %d characters."
            % min_prefix_length
        )
    return len(prefix_lengths) == 0


def inspect_hash_inputs(packages):
    """Return dictionaries of data that created the hash value (h????) for the provided package(s)

    Returns a dictionary with a key for each input package and a value of the dictionary loaded
    from the package's info/hash_input.json file
    """
    from .inspect_pkg import get_hash_input

    return get_hash_input(packages)


def create_metapackage(
    name,
    version,
    entry_points=(),
    build_string=None,
    build_number=0,
    dependencies=(),
    home=None,
    license_name=None,
    summary=None,
    config=None,
    **kwargs,
):
    from .metapackage import create_metapackage

    config = get_or_merge_config(config, **kwargs)
    return create_metapackage(
        name=name,
        version=version,
        entry_points=entry_points,
        build_string=build_string,
        build_number=build_number,
        dependencies=dependencies,
        home=home,
        license_name=license_name,
        summary=summary,
        config=config,
    )


@deprecated("3.25.0", "4.0.0", addendum="Use standalone conda-index.")
def update_index(
    dir_paths,
    config=None,
    force=False,
    check_md5=False,
    remove=False,
    channel_name=None,
    subdir=None,
    threads=None,
    patch_generator=None,
    verbose=False,
    progress=False,
    hotfix_source_repo=None,
    current_index_versions=None,
    **kwargs,
):
    import os

    import yaml

    from conda_build.index import update_index as legacy_update_index
    from conda_build.utils import ensure_list

    dir_paths = [os.path.abspath(path) for path in _ensure_list(dir_paths)]

    if isinstance(current_index_versions, str):
        with open(current_index_versions) as f:
            current_index_versions = yaml.safe_load(f)

    for path in dir_paths:
        legacy_update_index(
            path,
            check_md5=check_md5,
            channel_name=channel_name,
            patch_generator=patch_generator,
            threads=threads,
            verbose=verbose,
            progress=progress,
            subdirs=ensure_list(subdir),
            current_index_versions=current_index_versions,
            index_file=kwargs.get("index_file", None),
        )


def debug(
    recipe_or_package_path_or_metadata_tuples,
    path=None,
    test=False,
    output_id=None,
    config=None,
    verbose=True,
    link_source_method="auto",
    **kwargs,
):
    """Set up either build/host or test environments, leaving you with a quick tool to debug
    your package's build or test phase.
    """
    import logging
    import os
    import time
    from fnmatch import fnmatch

    from conda_build.build import build as run_build
    from conda_build.build import test as run_test
    from conda_build.utils import CONDA_PACKAGE_EXTENSIONS, LoggingContext, on_win

    is_package = False
    default_config = get_or_merge_config(config, **kwargs)
    args = {"set_build_id": False}
    path_is_build_dir = False
    workdirs = [
        os.path.join(recipe_or_package_path_or_metadata_tuples, d)
        for d in (
            os.listdir(recipe_or_package_path_or_metadata_tuples)
            if os.path.isdir(recipe_or_package_path_or_metadata_tuples)
            else []
        )
        if (
            d.startswith("work")
            and os.path.isdir(
                os.path.join(recipe_or_package_path_or_metadata_tuples, d)
            )
        )
    ]
    metadatas_conda_debug = [
        os.path.join(f, "metadata_conda_debug.yaml")
        for f in workdirs
        if os.path.isfile(os.path.join(f, "metadata_conda_debug.yaml"))
    ]
    metadatas_conda_debug = sorted(metadatas_conda_debug)
    if len(metadatas_conda_debug):
        path_is_build_dir = True
        path = recipe_or_package_path_or_metadata_tuples
    if not path:
        path = os.path.join(default_config.croot, f"debug_{int(time.time() * 1000)}")
    config = get_or_merge_config(
        config=default_config, croot=path, verbose=verbose, _prefix_length=10, **args
    )

    config.channel_urls = get_channel_urls(kwargs)

    metadata_tuples = []

    best_link_source_method = "skip"
    if isinstance(recipe_or_package_path_or_metadata_tuples, str):
        if path_is_build_dir:
            for metadata_conda_debug in metadatas_conda_debug:
                best_link_source_method = "symlink"
                from conda_build.metadata import MetaData

                metadata = MetaData(metadata_conda_debug, config, {})
                metadata_tuples.append((metadata, False, True))
        else:
            ext = os.path.splitext(recipe_or_package_path_or_metadata_tuples)[1]
            if not ext or not any(ext in _ for _ in CONDA_PACKAGE_EXTENSIONS):
                metadata_tuples = render(
                    recipe_or_package_path_or_metadata_tuples, config=config, **kwargs
                )
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
            matched_outputs = [
                _ for _ in outputs if fnmatch(os.path.basename(_), output_id)
            ]
            if len(matched_outputs) > 1:
                raise ValueError(
                    "Specified --output-id matches more than one output ({}).  Please refine your output id so that only "
                    "a single output is found.".format(matched_outputs)
                )
            elif not matched_outputs:
                raise ValueError(
                    f"Specified --output-id did not match any outputs.  Available outputs are: {outputs} Please check it and try again"
                )
        if len(matched_outputs) > 1 and not path_is_build_dir:
            raise ValueError(
                "More than one output found for this recipe ({}).  Please use the --output-id argument to filter down "
                "to a single output.".format(outputs)
            )
        else:
            matched_outputs = outputs

        target_metadata = metadata_tuples[outputs.index(matched_outputs[0])][0]
        # make sure that none of the _placehold stuff gets added to env paths
        target_metadata.config.prefix_length = 10

    if best_link_source_method == "symlink":
        for metadata, _, _ in metadata_tuples:
            debug_source_loc = os.path.join(
                os.sep + "usr",
                "local",
                "src",
                "conda",
                "{}-{}".format(
                    metadata.get_value("package/name"),
                    metadata.get_value("package/version"),
                ),
            )
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
                print(
                    f"Making debug info source symlink: {debug_source_loc} => {link_target}"
                )
                os.symlink(link_target, debug_source_loc)
            except PermissionError as e:
                raise Exception(
                    "You do not have the necessary permissions to create symlinks in {}\nerror: {}".format(
                        dn, str(e)
                    )
                )
            except Exception as e:
                raise Exception(
                    "Unknown error creating symlinks in {}\nerror: {}".format(
                        dn, str(e)
                    )
                )
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
            activation_file=os.path.join(
                target_metadata.config.work_dir, activation_file
            ),
        )
    elif not test:
        with log_context:
            run_build(target_metadata, stats={}, provision_only=True)
        activation_file = "build_env_setup" + ext
        activation_string = "cd {work_dir} && {source} {activation_file}\n".format(
            work_dir=target_metadata.config.work_dir,
            source="call" if on_win else "source",
            activation_file=os.path.join(
                target_metadata.config.work_dir, activation_file
            ),
        )
    else:
        if not is_package:
            raise ValueError(
                "Debugging for test mode is only supported for package files that already exist. "
                "Please build your package first, then use it to create the debugging environment."
            )
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
            activation_file=os.path.join(config.test_dir, activation_file),
        )
    return activation_string
