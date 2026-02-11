# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import argparse
import shlex
import shutil
import subprocess
import sys
from os.path import join
from pathlib import Path

from conda.base.context import context

from ..config import CondaPkgFormat, Config
from ..utils import on_win

CONFIG_FILES = {"conda_build_config.yaml", "variants.yaml"}


def find_rattler_build() -> str:
    """Find rattler-build executable."""
    executable_dir = Path(sys.executable).parent
    resolved_dir = Path(sys.executable).resolve().parent

    if on_win:
        # on Windows: rattler-build can be in $PREFIX/Library/bin or $PREFIX/Scripts
        candidate_dirs = [
            executable_dir / "Library" / "bin",
            executable_dir / "Scripts",
            resolved_dir / "Library" / "bin",
            resolved_dir / "Scripts",
            executable_dir,
            resolved_dir,
        ]
        executable_name = "rattler-build.exe"
    else:
        # On Unix: both python and rattler-build are in $PREFIX/bin
        candidate_dirs = [
            executable_dir,
            resolved_dir,
        ]
        executable_name = "rattler-build"

    # Check candidate directories
    for directory in candidate_dirs:
        rattler_path = directory / executable_name
        if rattler_path.exists():
            return str(rattler_path)

    # Fallback to PATH
    return shutil.which("rattler-build") or "rattler-build"


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
    if command == "build":
        cmd = ["rattler-build", "build"] + [
            f"--recipe={join(recipe_dir, 'recipe.yaml')}"
            for recipe_dir in parsed_args.recipe
        ]
    elif command == "render":
        cmd = [
            "rattler-build",
            "build",
            "--render-only",
            f"--recipe={join(parsed_args.recipe, 'recipe.yaml')}",
        ]
    elif command == "debug":
        cmd = [
            "rattler-build",
            "debug",
            "--recipe",
            parsed_args.recipe_or_package_file_path,
        ]
    else:
        raise ValueError(f"Unrecognized subcommand: {command}")

    # common configuration
    if config.channel_urls:
        for url in config.channel_urls:
            if url in context.custom_multichannels:
                cmd.extend(
                    [
                        f"--channel={local_url}"
                        for local_url in context.custom_multichannels[url]
                    ]
                )
            else:
                cmd.append(f"--channel={url}")
    cmd.extend(
        ["--build-platform", config.variant.get("build_platform", config.subdir)]
    )
    cmd.extend(
        [
            "--host-platform",
            config.variant.get(
                "host_platform", config.variant.get("target_platform", config.subdir)
            ),
        ]
    )
    cmd.extend(
        [
            "--target-platform",
            config.variant.get(
                "target_platform", config.variant.get("host_platform", config.subdir)
            ),
        ]
    )
    if context.channel_priority == "strict":
        cmd.extend(["--channel-priority", "strict"])
    else:
        cmd.extend(["--channel-priority", "disabled"])

    if command in ("build", "render"):
        # Ignore rattler's variant auto-discovery
        cmd.append("--ignore-recipe-variants")

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
                    metadata_or_path=None, config=config, recipe_config_filenames=None
                )
        else:
            # single-recipe case: include recipe config files if any exist
            config_files = find_config_files(
                config,
                Path(parsed_args.recipe[0]),
                recipe_config_filenames=CONFIG_FILES,
            )

        cmd.extend([f"-m={variant}" for variant in config_files])

        if config.verbose:
            cmd.append("--verbose")

    if command == "debug":
        if parsed_args.output_id:
            cmd.extend(["--output-name", parsed_args.output_id])
    elif command == "build":
        cmd.extend(
            [
                "--noarch-build-platform",
                config.variant.get("noarch_build_platform", config.subdir),
            ]
        )
        if parsed_args.extra_meta:
            for k, v in parsed_args.extra_meta.items():
                cmd.append(f"--extra-meta={k}={v}")
        if parsed_args.output_folder:
            cmd.extend(["--output-dir", parsed_args.output_folder])
        else:
            cmd.extend(["--output-dir", config.croot])
        if not parsed_args.set_build_id:
            cmd.append("--no-build-id")
        if parsed_args.debug:
            cmd.append("--debug")
        if parsed_args.notest:
            cmd.extend(["--test", "skip"])
        if parsed_args.quiet:
            cmd.append("-q")
        if parsed_args.skip_existing != "none":
            if parsed_args.skip_existing == "local":
                cmd.append("--skip-existing=local")
            elif parsed_args.skip_existing == "all":
                cmd.append("--skip-existing=all")
        if not parsed_args.include_recipe:
            cmd.append("--no-include-recipe")
        if parsed_args.conda_pkg_format == CondaPkgFormat.V2:
            cmd.extend(
                ["--package-format", f".conda:{parsed_args.zstd_compression_level}"]
            )
        else:
            cmd.extend(["--package-format", ".tar.bz2"])

    try:
        rattler_cmd = find_rattler_build()
        cmd = [rattler_cmd, *cmd[1:]]
        print("Running rattler:", shlex.join(cmd))
        subprocess.run(cmd, check=True)
        return 0
    except subprocess.CalledProcessError as e:
        print(f"rattler failed: {e}", file=sys.stderr)
        return e.returncode
