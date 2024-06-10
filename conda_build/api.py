# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
This file defines the public API for conda-build.  Adding or removing functions,
or Changing arguments to anything in here should also mean changing the major
version number.

Design philosophy: put variability into config.  Make each function here accept kwargs,
but only use those kwargs in config.  Config must change to support new features elsewhere.
"""

from __future__ import annotations

# imports are done locally to keep the api clean and limited strictly
#    to conda-build's functionality.
import os
import sys
from os.path import dirname, expanduser, join
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

# make the Config class available in the api namespace
from .config import DEFAULT_PREFIX_LENGTH as _prefix_length
from .config import Config, get_channel_urls, get_or_merge_config
from .metadata import MetaData, MetaDataTuple
from .utils import (
    CONDA_PACKAGE_EXTENSIONS,
    LoggingContext,
    ensure_list,
    expand_globs,
    find_recipe,
    get_skip_message,
    on_win,
)

if TYPE_CHECKING:
    from typing import Any, Literal

    StatsDict = dict[str, Any]


def render(
    recipe_path: str | os.PathLike | Path,
    config: Config | None = None,
    variants: dict[str, Any] | None = None,
    permit_unsatisfiable_variants: bool = True,
    finalize: bool = True,
    bypass_env_check: bool = False,
    **kwargs,
) -> list[MetaDataTuple]:
    """Given path to a recipe, return the MetaData object(s) representing that recipe, with jinja2
       templates evaluated.

    Returns a list of (metadata, need_download, need_reparse in env) tuples"""
    from .render import render_metadata_tuples, render_recipe

    config = get_or_merge_config(config, **kwargs)

    metadata_tuples = render_recipe(
        recipe_path,
        bypass_env_check=bypass_env_check,
        no_download_source=config.no_download_source,
        config=config,
        variants=variants,
        permit_unsatisfiable_variants=permit_unsatisfiable_variants,
    )
    return render_metadata_tuples(
        metadata_tuples,
        config=config,
        permit_unsatisfiable_variants=permit_unsatisfiable_variants,
        finalize=finalize,
        bypass_env_check=bypass_env_check,
    )


def output_yaml(
    metadata: MetaData,
    file_path: str | os.PathLike | Path | None = None,
    suppress_outputs: bool = False,
) -> str:
    """Save a rendered recipe in its final form to the path given by file_path"""
    from .render import output_yaml

    return output_yaml(metadata, file_path, suppress_outputs=suppress_outputs)


def get_output_file_paths(
    recipe_path_or_metadata: str
    | os.PathLike
    | Path
    | MetaData
    | Iterable[MetaDataTuple],
    no_download_source: bool = False,
    config: Config | None = None,
    variants: dict[str, Any] | None = None,
    **kwargs,
) -> list[str]:
    """Get output file paths for any packages that would be created by a recipe

    Both split packages (recipes with more than one output) and build matrices,
    created with variants, contribute to the list of file paths here.
    """
    from .render import bldpkg_path

    config = get_or_merge_config(config, **kwargs)

    if isinstance(recipe_path_or_metadata, (str, Path)):
        # first, render the parent recipe (potentially multiple outputs, depending on variants).
        metadata_tuples = render(
            recipe_path_or_metadata,
            no_download_source=no_download_source,
            variants=variants,
            config=config,
            finalize=True,
            **kwargs,
        )

    elif isinstance(recipe_path_or_metadata, MetaData):
        metadata_tuples = [MetaDataTuple(recipe_path_or_metadata, False, False)]

    elif isinstance(recipe_path_or_metadata, Iterable) and all(
        isinstance(recipe, MetaDataTuple)
        and isinstance(recipe.metadata, MetaData)
        and isinstance(recipe.need_download, bool)
        and isinstance(recipe.need_reparse, bool)
        for recipe in recipe_path_or_metadata
    ):
        metadata_tuples = recipe_path_or_metadata

    else:
        raise ValueError(
            f"Unknown input type: {type(recipe_path_or_metadata)}; expecting "
            "PathLike object, MetaData object, or a list of tuples containing "
            "(MetaData, bool, bool)."
        )

    # Next, loop over outputs that each metadata defines
    outs = []
    for metadata, _, _ in metadata_tuples:
        if metadata.skip():
            outs.append(get_skip_message(metadata))
        else:
            outs.append(bldpkg_path(metadata))
    return sorted(set(outs))


def check(
    recipe_path: str | os.PathLike | Path,
    no_download_source: bool = False,
    config: Config | None = None,
    variants: dict[str, Any] | None = None,
    **kwargs,
) -> bool:
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
    recipe_paths_or_metadata: str | os.PathLike | Path | MetaData,
    post: bool | None = None,
    need_source_download: bool = True,
    build_only: bool = False,
    notest: bool = False,
    config: Config | None = None,
    variants: dict[str, Any] | None = None,
    stats: StatsDict | None = None,
    **kwargs,
) -> list[str]:
    """Run the build step.

    If recipe paths are provided, renders recipe before building.
    Tests built packages by default.  notest=True to skip test."""
    from .build import build_tree

    assert post in (None, True, False), (
        "post must be boolean or None.  Remember, you must pass "
        "other arguments (config) by keyword."
    )

    recipes: list[str | MetaData] = []
    for recipe in ensure_list(recipe_paths_or_metadata):
        if isinstance(recipe, (str, os.PathLike, Path)):
            for recipe in expand_globs(recipe, os.getcwd()):
                try:
                    recipes.append(find_recipe(recipe))
                except OSError:
                    continue
        elif isinstance(recipe, MetaData):
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
    recipedir_or_package_or_metadata: str | os.PathLike | Path | MetaData,
    move_broken: bool = True,
    config: Config | None = None,
    stats: StatsDict | None = None,
    **kwargs,
) -> bool:
    """Run tests on either packages (.tar.bz2 or extracted) or recipe folders

    For a recipe folder, it renders the recipe enough to know what package to download, and obtains
    it from your currently configuured channels."""
    from .build import test

    if hasattr(recipedir_or_package_or_metadata, "config"):
        config = recipedir_or_package_or_metadata.config
    else:
        config = get_or_merge_config(config, **kwargs)

    # if people don't pass in an object to capture stats in, they won't get them returned.
    #     We'll still track them, though.
    stats = stats or {}

    with config:
        # This will create a new local build folder if and only if config
        #   doesn't already have one. What this means is that if we're
        #   running a test immediately after build, we use the one that the
        #   build already provided
        return test(
            recipedir_or_package_or_metadata,
            config=config,
            move_broken=move_broken,
            stats=stats,
        )


def list_skeletons() -> list[str]:
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
    packages: str | Iterable[str],
    repo: Literal["cpan", "cran", "luarocks", "pypi", "rpm"],
    output_dir: str = ".",
    version: str | None = None,
    recursive: bool = False,
    config: Config | None = None,
    **kwargs,
) -> None:
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
    packages = ensure_list(packages)

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
        module.skeletonize(
            packages,
            output_dir=output_dir,
            version=version,
            recursive=recursive,
            config=config,
            **kwargs,
        )


def develop(
    recipe_dir: str | Iterable[str],
    prefix: str = sys.prefix,
    no_pth_file: bool = False,
    build_ext: bool = False,
    clean: bool = False,
    uninstall: bool = False,
) -> None:
    """Install a Python package in 'development mode'.

    This works by creating a conda.pth file in site-packages."""
    from .develop import execute

    recipe_dir = ensure_list(recipe_dir)
    execute(recipe_dir, prefix, no_pth_file, build_ext, clean, uninstall)


def convert(
    package_file: str,
    output_dir: str = ".",
    show_imports: bool = False,
    platforms: str | Iterable[str] | None = None,
    force: bool = False,
    dependencies: str | Iterable[str] | None = None,
    verbose: bool = False,
    quiet: bool = True,
    dry_run: bool = False,
) -> None:
    """Convert changes a package from one platform to another.  It applies only to things that are
    portable, such as pure python, or header-only C/C++ libraries."""
    from .convert import conda_convert

    platforms = ensure_list(platforms)
    dependencies = ensure_list(dependencies)
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
            "Conversion from wheel packages is not implemented yet, stay tuned."
        )
    else:
        raise RuntimeError(f"cannot convert: {package_file}")


def test_installable(channel: str = "defaults") -> bool:
    """Check to make sure that packages in channel are installable.
    This is a consistency check for the channel."""
    from .inspect_pkg import test_installable

    return test_installable(channel)


def inspect_linkages(
    packages: str | Iterable[str],
    prefix: str | os.PathLike | Path = sys.prefix,
    untracked: bool = False,
    all_packages: bool = False,
    show_files: bool = False,
    groupby: Literal["package", "dependency"] = "package",
    sysroot: str = "",
) -> str:
    from .inspect_pkg import inspect_linkages

    packages = ensure_list(packages)
    return inspect_linkages(
        packages,
        prefix=prefix,
        untracked=untracked,
        all_packages=all_packages,
        show_files=show_files,
        groupby=groupby,
        sysroot=sysroot,
    )


def inspect_objects(packages, prefix=sys.prefix, groupby="filename"):
    from .inspect_pkg import inspect_objects

    packages = ensure_list(packages)
    return inspect_objects(packages, prefix=prefix, groupby=groupby)


def inspect_prefix_length(packages, min_prefix_length=_prefix_length):
    from .tarcheck import check_prefix_lengths

    config = Config(prefix_length=min_prefix_length)
    packages = ensure_list(packages)
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


def debug(
    recipe_or_package_path_or_metadata_tuples,
    path=None,
    test=False,
    output_id=None,
    config=None,
    verbose: bool = True,
    link_source_method="auto",
    **kwargs,
):
    """Set up either build/host or test environments, leaving you with a quick tool to debug
    your package's build or test phase.
    """
    import logging
    import time
    from fnmatch import fnmatch

    from .build import build as run_build
    from .build import test as run_test
    from .metadata import MetaData

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

    metadata_tuples: list[MetaDataTuple] = []

    best_link_source_method = "skip"
    if isinstance(recipe_or_package_path_or_metadata_tuples, str):
        if path_is_build_dir:
            for metadata_conda_debug in metadatas_conda_debug:
                best_link_source_method = "symlink"
                metadata = MetaData(metadata_conda_debug, config, {})
                metadata_tuples.append(MetaDataTuple(metadata, False, True))
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
                    f"Specified --output-id matches more than one output ({matched_outputs}). "
                    "Please refine your output id so that only a single output is found."
                )
            elif not matched_outputs:
                raise ValueError(
                    f"Specified --output-id did not match any outputs. Available outputs are: {outputs} "
                    "Please check it and try again"
                )
        if len(matched_outputs) > 1 and not path_is_build_dir:
            raise ValueError(
                f"More than one output found for this recipe ({outputs}). "
                "Please use the --output-id argument to filter down to a single output."
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
                f"{metadata.name()}-{metadata.version()}",
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
                    f"You do not have the necessary permissions to create symlinks in {dn}\nerror: {str(e)}"
                )
            except Exception as e:
                raise Exception(
                    f"Unknown error creating symlinks in {dn}\nerror: {str(e)}"
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
