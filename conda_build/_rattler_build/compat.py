# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import yaml
from conda.base.context import context
from rattler_build import (
    Package,
    RattlerBuildError,
    RecipeParseError,
)
from rattler_build.progress import SimpleProgressCallback
from rattler_build.render import RenderConfig
from rattler_build.stage0 import Stage0Recipe
from rattler_build.tool_config import PlatformConfig, ToolConfiguration
from rattler_build.variant_config import VariantConfig

from ..config import CondaPkgFormat
from ..exceptions import CondaBuildUserError
from ..utils import get_logger

if TYPE_CHECKING:
    import argparse

    from rattler_build.progress import LogEvent

    from ..config import Config

CONFIG_FILES = {"conda_build_config.yaml", "variants.yaml"}

log = get_logger(__name__)


@dataclass(kw_only=True)
class OutputResult:
    name: str
    success: bool
    error: str | None = None


@dataclass(kw_only=True)
class RecipeResult:
    recipe_path: str
    outputs: list[OutputResult] = field(default_factory=list)
    error: str | None = None

    @property
    def failed(self) -> bool:
        return self.error is not None or any(
            not output.success for output in self.outputs
        )

    @property
    def success(self) -> bool:
        return bool(self.outputs) and not self.failed


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


def process_recipe(
    recipe_path: str,
    variant_config: VariantConfig,
    command: str,
    output_dir: str,
    channels: list[str],
    show_logs: bool,
    no_build_id: bool,
    package_format: str | None,
    no_include_recipe: bool,
    tool_config: ToolConfiguration,
    render_config: RenderConfig,
    parsed_args: argparse.Namespace,
) -> RecipeResult:
    """
    Function to parse, render and optionally build or test a conda package recipe using the py-rattler-build API.

    Workflow:
        - Load and parse the recipe via `Stage0Recipe.from_file()`
        - Render the recipe variants according to the provided variant and render configuration objects
        - Build each rendered variant using `variant.run_build()`
        - If testing is enabled, run tests on the built package with `Package.run_tests()`
    """
    result = RecipeResult(recipe_path=recipe_path)

    try:
        recipe = Stage0Recipe.from_file(Path(recipe_path))
    except RecipeParseError as e:
        result.error = f"Failed to process recipe file {recipe_path}: {e}"
        return result

    try:
        rendered = recipe.render(variant_config, render_config)
    except RattlerBuildError as e:
        result.error = f"Failed to render recipe {recipe_path}: {e}"
        return result

    if command == "render":
        for item in rendered:
            data = item.recipe.to_dict()
            print(yaml.safe_dump(data, indent=2, sort_keys=False))
        return result

    for i, variant in enumerate(rendered, 1):
        print(
            f"\nBuilding variant {i}/{len(rendered)} for recipe {Path(recipe_path).resolve()}"
        )

        recipe_dict = variant.recipe.to_dict()
        package_section = recipe_dict.get("package", {})
        output_name = package_section.get("name")

        try:
            build_result = variant.run_build(
                tool_config=tool_config,
                output_dir=output_dir,
                channels=channels,
                progress_callback=CondaProgressCallback(show_logs=show_logs),
                no_build_id=no_build_id,
                package_format=package_format,
                no_include_recipe=no_include_recipe,
            )
        except RattlerBuildError as e:
            result.outputs.append(
                OutputResult(
                    name=output_name,
                    success=False,
                    error=str(e),
                )
            )
            continue

        built_packages = list(build_result.packages)

        for pkg_path in built_packages:
            if parsed_args.notest:
                result.outputs.append(
                    OutputResult(
                        name=output_name,
                        success=True,
                    )
                )
                continue

            try:
                pkg = Package.from_file(pkg_path)
            except RattlerBuildError as e:
                result.outputs.append(
                    OutputResult(
                        name=output_name,
                        success=False,
                        error=str(e),
                    )
                )
                continue

            try:
                # tests are ran in a different directory than build, so we need to add the build
                # directory manually as a file:// channel
                test_channels = [Path(output_dir).resolve().as_uri(), *channels]

                test_results = pkg.run_tests(
                    progress_callback=CondaProgressCallback(show_logs=show_logs),
                    channel=test_channels,
                )
            except RattlerBuildError as e:
                result.outputs.append(
                    OutputResult(
                        name=output_name,
                        success=False,
                        error=str(e),
                    )
                )
                continue

            test_failed = [r for r in test_results if not r.success]

            if test_failed:
                result.outputs.append(
                    OutputResult(
                        name=output_name,
                        success=False,
                        error="Package tests failed",
                    )
                )
                continue

            result.outputs.append(
                OutputResult(
                    name=output_name,
                    success=True,
                )
            )

    return result


def run_rattler(command: str, parsed_args: argparse.Namespace, config: Config) -> int:
    """Run rattler-build for v1 recipes"""
    if command not in ("build", "render"):
        raise ValueError(f"Unrecognized subcommand: {command}")

    # Initialize configuration defaults
    skip_existing: bool | None = None
    channel_priority: str | None = None
    output_dir: str = config.croot
    no_include_recipe: bool = False
    no_build_id: bool = False
    package_format: str | None = None
    channels: list[str] = []
    extra_context: dict[str, str] = {}
    show_logs: bool = getattr(parsed_args, "quiet", False) is False
    target_platform: str = config.variant.get("host_platform", config.subdir)
    build_platform: str = config.variant.get("build_platform", config.subdir)
    host_platform: str = config.variant.get("target_platform", config.subdir)
    noarch_build_platform: str = config.variant.get(
        "noarch_build_platform", config.subdir
    )
    variant_config: VariantConfig = VariantConfig()

    if parsed_args.override_channels:
        if not parsed_args.channel:
            raise CondaBuildUserError(
                "Channels must be specified using -c/--channel argument when --override-channels is used."
            )
        channels = list(parsed_args.channel)
    else:
        channels = list(context.channels)

    # Local and multichannel not supported yet, xref https://github.com/conda/rattler/issues/1327
    channels = list(dict.fromkeys(c for c in channels if c != "local"))

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
                # single-recipe case: include recipe config files if any exist
                config_files = find_config_files(
                    None, config, recipe_config_filenames=None
                )
        else:
            config_files = find_config_files(
                Path(parsed_args.recipe[0]),
                config,
                recipe_config_filenames=CONFIG_FILES,
            )

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
        # test execution is handled manually in process_recipe()
        test_strategy=None,
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
        if command == "render":
            recipes = [str(Path(parsed_args.recipe) / "recipe.yaml")]
        else:
            recipes = [
                str(Path(recipe_dir) / "recipe.yaml")
                for recipe_dir in parsed_args.recipe
            ]

        # configure variant
        # merge config files in the order they are stacked
        if config_files:
            for variant in config_files:
                variant_config = variant_config.merge(VariantConfig.from_file(variant))

        recipe_results: list[RecipeResult] = []

        for recipe_path in recipes:
            recipe_results.append(
                process_recipe(
                    recipe_path=recipe_path,
                    variant_config=variant_config,
                    command=command,
                    output_dir=output_dir,
                    channels=channels,
                    show_logs=show_logs,
                    no_build_id=no_build_id,
                    package_format=package_format,
                    no_include_recipe=no_include_recipe,
                    tool_config=tool_config,
                    render_config=render_config,
                    parsed_args=parsed_args,
                )
            )

        if command == "render":
            failed = [r for r in recipe_results if r.failed]
            if failed:
                msg = "\n".join(
                    [
                        "Recipe render failures:",
                        *[
                            f"  - {Path(r.recipe_path).resolve()}: {r.error or 'Unknown error'}"
                            for r in failed
                        ],
                    ]
                )
                raise CondaBuildUserError(msg)
            return 0

        recipe_count = len(recipe_results)
        total_outputs = sum(len(r.outputs) for r in recipe_results)
        succeeded_outputs = sum(
            1 for r in recipe_results for output in r.outputs if output.success
        )
        failed_outputs = total_outputs - succeeded_outputs

        print("\n=== Build summary ===")
        print(
            f"Tried to build {recipe_count} recipe file{'s' if recipe_count != 1 else ''}, "
            f"resulting in {total_outputs} output{'s' if total_outputs != 1 else ''}."
        )
        print(f"{succeeded_outputs} succeeded, {failed_outputs} failed.\n")
        print("Details:")

        for recipe in recipe_results:
            recipe_icon = "❌" if recipe.failed else "✅"
            print(f"- {recipe_icon} {Path(recipe.recipe_path).resolve()}")

            if recipe.outputs:
                for output in recipe.outputs:
                    if output.success:
                        print(f"  - ✅ {output.name}: Succeeded")
                    else:
                        print(f"  - ❌ {output.name}: {output.error}")
            elif recipe.error:
                print(f"  - ❌ recipe: {recipe.error}")

        failed = [r for r in recipe_results if r.failed]
        if failed:
            msg_lines = ["Recipe build failures:"]
            for recipe in failed:
                msg_lines.append(f"  - {Path(recipe.recipe_path).resolve()}")
                if recipe.outputs:
                    for output in recipe.outputs:
                        if not output.success:
                            reason = output.error
                            msg_lines.append(f"      - {output.name}: {reason}")
                elif recipe.error:
                    msg_lines.append(f"      - recipe: {recipe.error}")

            if parsed_args.debug:
                raise CondaBuildUserError("\n".join(msg_lines))
            else:
                return 1

        return 0
