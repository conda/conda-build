# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import argparse
from os.path import join
from pathlib import Path

from conda.base.context import context
from rattler_build.progress import RichProgressCallback
from rattler_build.render import RenderConfig
from rattler_build.stage0 import Stage0Recipe
from rattler_build.tool_config import PlatformConfig, ToolConfiguration
from rattler_build.variant_config import VariantConfig

from ..config import CondaPkgFormat, Config

CONFIG_FILES = {"conda_build_config.yaml", "variants.yaml"}


def check_arguments_rattler(
    command: str, parsed: argparse.Namespace, parsed_only_recipe: argparse.Namespace
) -> None:
    """Validate that arguments are compatible with rattler CLI commands.

    Compares the full argparse.namespace object containing all command-line arguments against
    a stripped-down version to check for any arguments that are not supported by
    rattler-build.

    Args:
        command: The CLI command being executed (e.g. 'build', 'debug')
        parsed: Namespace object containing all parsed command-line arguments
            from the main argument parser.
        parsed_only_recipe: Namespace object containing only the recipe file as
            an argument.
    """

    diff = {
        k: v for k, v in vars(parsed).items() if vars(parsed_only_recipe).get(k) != v
    }

    VALID_ARGS = {
        "build": {
            "recipe",
            "variant_config_files",
            "verbose",
            "exclusive_config_files",
            "extra_meta",
            "output_folder",
            "set_build_id",
            "debug",
            "notest",
            "quiet",
            "skip_existing",
            "include_recipe",
            "conda_pkg_format",
            "zstd_compression_level",
            "channel",
        },
        "render": {
            "recipe",
            "variant_config_files",
            "verbose",
            "exclusive_config_files",
            "channel",
        },
        "debug": {
            "recipe",
            "output_id",
            "variant_config_files",
            "exclusive_config_files",
        },
    }

    # check for unsupported CLI arguments
    unsupported_keys = diff.keys() - VALID_ARGS.get(command, set())
    if unsupported_keys:
        raise ValueError(
            f"Invalid arguments for conda-{command}: {', '.join(sorted(unsupported_keys))}"
        )

    # check for unsupported condarc values
    condarc_settings = set(context.conda_build.keys())
    unsupported_condarc_keys = condarc_settings - set().union(*VALID_ARGS.values())

    if unsupported_condarc_keys:
        raise ValueError(
            f"Invalid condarc settings for conda-{command}: {', '.join(sorted(unsupported_condarc_keys))}"
        )


def run_rattler(command: str, parsed_args: argparse.Namespace, config: Config) -> int:
    """Run rattler-build for v1 recipes"""
    if command not in ("build", "render", "debug"):
        raise ValueError(f"Unrecognized subcommand: {command}")

    # Initialize configuration defaults
    test_strategy = None
    skip_existing = None
    noarch_build_platform = None
    channel_priority = None
    output_dir = config.croot
    no_include_recipe = False
    no_build_id = False
    package_format = None
    debug = False
    channels = []
    extra_context = {}
    show_logs = not parsed_args.quiet
    target_platform = config.variant.get("host_platform", config.subdir)
    build_platform = config.variant.get("build_platform", config.subdir)
    host_platform = config.variant.get("target_platform", config.subdir)
    noarch_build_platform = config.variant.get("noarch_build_platform", config.subdir)

    # TODO: investigate why is config.channel_urls
    # does not pick up condarc settings, need to use context.channels
    channels = list(context.channels)
    if config.channel_urls:
        for url in config.channel_urls:
            # TODO: fix -c local
            # TypeError: argument 'channels': 'Channel' object cannot be cast as 'str'
            if url in context.custom_multichannels:
                channels.extend(
                    [local_url for local_url in context.custom_multichannels[url]]
                )
            else:
                channels.append(url)

    if context.channel_priority == "strict":
        channel_priority = "strict"
    else:
        channel_priority = "disabled"

    if command in ("build", "render"):
        # TODO: --ignore-recipe-variants only available via deprecated
        # rattler_build.cli_api:build_recipes()
        # cmd.append("--ignore-recipe-variants")

        from ..variants import find_config_files

        if len(parsed_args.recipe) > 1:
            # multi-recipe case: check if any has cbc or variants.yaml
            # if yes -> unsupported case, error out
            # if no  -> find config files
            recipes_with_cfg = [
                recipe
                for recipe in parsed_args.recipe
                if any(Path(recipe, cfg).is_file() for cfg in CONFIG_FILES)
            ]
            if recipes_with_cfg:
                raise ValueError(
                    f"Recipe configuration files detected but multiple recipes were passed: {recipes_with_cfg}"
                )
            else:
                config_files = find_config_files(
                    None, config, recipe_config_filenames=None
                )
        else:
            # single-recipe case: include recipe config files if any exist
            config_files = find_config_files(
                Path(parsed_args.recipe[0]),
                config,
                recipe_config_filenames=CONFIG_FILES,
            )

        # if config.verbose:
        # TODO: find this option in py-rattler-build
        # cmd.append("--verbose")

    # if command == "debug":
    # TODO: output_name does not exist in python bindings
    # if parsed_args.output_id:
    # cmd.extend(["--output-name", parsed_args.output_id])
    elif command == "build":
        if parsed_args.extra_meta:
            extra_context.update(parsed_args.extra_meta)
        if parsed_args.output_folder:
            output_dir = parsed_args.output_folder
        no_build_id = not parsed_args.set_build_id
        debug = parsed_args.debug
        test_strategy = "skip" if parsed_args.notest else "native"
        # if parsed_args.quiet:
        # TODO: quiet does not exist in py-rattler-build
        # cmd.append("-q")
        skip_existing = parsed_args.skip_existing or "none"
        no_include_recipe = not parsed_args.include_recipe
        if parsed_args.conda_pkg_format == CondaPkgFormat.V2:
            package_format = "conda"
        else:
            package_format = ".tar.bz2"

    if command in ("build", "render"):
        if command == "render":
            recipe_path = join(parsed_args.recipe, "recipe.yaml")
            recipes = [recipe_path]
        else:
            recipes = [
                join(recipe_dir, "recipe.yaml") for recipe_dir in parsed_args.recipe
            ]

        from ..variants import find_config_files

        results = []

        # configure variant
        for variant in config_files:
            variant_config = VariantConfig.from_file(variant)

        # coon tool / platform / render configuration
        tool_config = ToolConfiguration(
            test_strategy=test_strategy,
            skip_existing=skip_existing,
            noarch_build_platform=noarch_build_platform,
            channel_priority=channel_priority,
        )

        platform_config = PlatformConfig(
            target_platform=target_platform,
            build_platform=build_platform,
            host_platform=host_platform,
        )

        render_config = RenderConfig(
            platform=platform_config,
            extra_context=extra_context,
        )

        # iterate over all recipes
        for recipe_path in recipes:
            recipe = Stage0Recipe.from_file(Path(recipe_path))

            variant_config = None
            for variant_file in config_files:
                variant_config = VariantConfig.from_file(variant_file)

            # render the recipe
            rendered = recipe.render(variant_config, render_config)

            if command == "render":
                import json

                data = rendered[0].recipe.to_dict()
                print(json.dumps(data, indent=2, sort_keys=True))
                continue

            # build all rendered variants
            for i, variant in enumerate(rendered, 1):
                print(
                    f"\n🔨 Building variant {i}/{len(rendered)} "
                    f"for recipe {recipe_path}"
                )

                with RichProgressCallback(show_logs=show_logs) as progress_callback:
                    result = variant.run_build(
                        tool_config=tool_config,
                        output_dir=output_dir,
                        channels=channels,
                        progress_callback=progress_callback,
                        recipe_path=recipe_path,
                        no_build_id=no_build_id,
                        package_format=package_format,
                        no_include_recipe=no_include_recipe,
                        debug=debug,
                    )
                    results.append(result)

                    print("\n" + "=" * 60)
                    print("Build Result:")
                    print("=" * 60)
                    print(f"   Package: {result.name} {result.version}")
                    print(f"   Build string: {result.build_string}")
                    print(f"   Platform: {result.platform}")
                    print(f"   Build time: {result.build_time:.2f}s")

        return 0
