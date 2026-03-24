# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import argparse
from os.path import join
from pathlib import Path

import yaml
from conda.base.context import context
from rattler_build import (
    RattlerBuildError,
    RecipeParseError,
)
from rattler_build.progress import LogEvent, SimpleProgressCallback
from rattler_build.render import RenderConfig
from rattler_build.stage0 import Stage0Recipe
from rattler_build.tool_config import PlatformConfig, ToolConfiguration
from rattler_build.variant_config import VariantConfig

from ..config import CondaPkgFormat, Config
from ..exceptions import CondaBuildUserError
from ..utils import get_logger

CONFIG_FILES = {"conda_build_config.yaml", "variants.yaml"}

log = get_logger(__name__)


class CondaProgressCallback(SimpleProgressCallback):
    def __init__(self, show_logs: bool = True):
        super().__init__()
        self.show_logs = show_logs

    def on_log(self, event: LogEvent) -> None:
        if not self.show_logs:
            return

        level_name = {"error": "error", "warn": "warning"}.get(event.level, "info")
        getattr(log, level_name)(event.message)


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
            "override_channels",
        },
        "render": {
            "recipe",
            "variant_config_files",
            "exclusive_config_files",
            "channel",
            "override_channels",
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


def process_recipes(
    recipes: list[str],
    variant_config: VariantConfig,
    command: str,
    output_dir: str,
    channels: list[str],
    show_logs: bool,
    no_build_id: bool,
    package_format: str,
    no_include_recipe: bool,
    tool_config: ToolConfiguration,
    platform_config: PlatformConfig,
    render_config: RenderConfig,
) -> int:

    succeeded: list[str] = []
    failed: dict[str, str] = {}

    for recipe_path in recipes:
        recipe_path_str = str(recipe_path)

        # load the recipe file
        try:
            recipe = Stage0Recipe.from_file(Path(recipe_path))
        except RecipeParseError as e:
            err = CondaBuildUserError(
                f"Failed to process recipe file {recipe_path}: {str(e)}"
            )
            failed[recipe_path_str] = str(err)
            continue

        # render the recipe
        try:
            rendered = recipe.render(variant_config, render_config)
        except RattlerBuildError as e:
            err = CondaBuildUserError(
                f"Failed to render recipe {recipe_path}: {str(e)}"
            )
            failed[recipe_path_str] = str(err)
            continue

        if command == "render":
            for item in rendered:
                data = item.recipe.to_dict()
                print(yaml.safe_dump(data, indent=2, sort_keys=False))
            succeeded.append(recipe_path_str)
            continue

        # build all rendered variants
        for i, variant in enumerate(rendered, 1):
            print(f"\nBuilding variant {i}/{len(rendered)} for recipe {recipe_path}")

            try:
                variant.run_build(
                    tool_config=tool_config,
                    output_dir=output_dir,
                    channels=channels,
                    progress_callback=CondaProgressCallback(show_logs=show_logs),
                    no_build_id=no_build_id,
                    package_format=package_format,
                    no_include_recipe=no_include_recipe,
                )
            except RattlerBuildError as e:
                err = CondaBuildUserError(
                    f"Failed to build recipe {recipe_path}: {str(e)}"
                )
                failed[recipe_path_str] = str(err)
                continue

        # if all variants built without raising, mark recipe as succeeded
        succeeded.append(recipe_path_str)

    # summary
    print("\n=== Build summary ===")
    if succeeded:
        print("Succeeded:")
        for path in succeeded:
            print(f"  - {path}")
    else:
        print("Succeeded: none")

    if failed:
        print("\nFailed:")
        msg = "Recipe build failures:\n" + "\n".join(
            f"  - {p}: {e}" for p, e in failed.items()
        )
        raise CondaBuildUserError(msg)
    else:
        print("\nFailed: none")

    return 1 if failed else 0


def run_rattler(command: str, parsed_args: argparse.Namespace, config: Config) -> int:
    """Run rattler-build for v1 recipes"""
    if command not in ("build", "render"):
        raise ValueError(f"Unrecognized subcommand: {command}")

    # Initialize configuration defaults
    test_strategy: str | None = None
    skip_existing: bool | None = None
    noarch_build_platform: str | None = None
    channel_priority: str | None = None
    output_dir: str = config.croot
    no_include_recipe: bool = False
    no_build_id: bool = False
    package_format: str | None = None
    channels: list[str] = []
    extra_context: dict[str] = {}
    show_logs: bool = getattr(parsed_args, "quiet", False) is False
    target_platform: str = config.variant.get("host_platform", config.subdir)
    build_platform: str = config.variant.get("build_platform", config.subdir)
    host_platform: str = config.variant.get("target_platform", config.subdir)
    noarch_build_platform: str = config.variant.get(
        "noarch_build_platform", config.subdir
    )
    variant_config: VariantConfig = VariantConfig()

    # TODO: investigate why is config.channel_urls
    # does not pick up condarc settings, need to use context.channels
    if parsed_args.override_channels:
        if not parsed_args.channel:
            raise CondaBuildUserError(
                "Channels must be specified using -c/--channel argument when --override-channels is used."
            )
        channels = list(parsed_args.channel)
    else:
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

    channels = list(dict.fromkeys(channels))

    if context.channel_priority == "strict":
        channel_priority = "strict"
    else:
        channel_priority = "disabled"

    if command in ("build", "render"):
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

    # TODO: output_name does not exist in python bindings
    # if parsed_args.output_id:
    # cmd.extend(["--output-name", parsed_args.output_id])
    if command == "build":
        if parsed_args.extra_meta:
            extra_context.update(parsed_args.extra_meta)
        if parsed_args.output_folder:
            output_dir = parsed_args.output_folder
        no_build_id = not parsed_args.set_build_id
        skip_existing = parsed_args.skip_existing or "none"
        no_include_recipe = not parsed_args.include_recipe
        if parsed_args.conda_pkg_format == CondaPkgFormat.V2:
            package_format = "conda"
        else:
            package_format = ".tar.bz2"

    # common tool / platform / render configuration
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

    if command in ("build", "render"):
        if command in ("render"):
            recipe_path = join(parsed_args.recipe, "recipe.yaml")
            recipes = [recipe_path]
        else:
            recipes = [
                join(recipe_dir, "recipe.yaml") for recipe_dir in parsed_args.recipe
            ]

        # configure variant
        # merge config files in the order they are stacked
        if config_files:
            for variant in config_files:
                variant_config = variant_config.merge(VariantConfig.from_file(variant))

        return process_recipes(
            recipes=recipes,
            variant_config=variant_config,
            command=command,
            output_dir=output_dir,
            channels=channels,
            show_logs=show_logs,
            no_build_id=no_build_id,
            package_format=package_format,
            no_include_recipe=no_include_recipe,
            tool_config=tool_config,
            platform_config=platform_config,
            render_config=render_config,
        )
