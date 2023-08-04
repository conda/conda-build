# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import argparse
import logging
import sys
from pprint import pprint

import yaml
from yaml.parser import ParserError

from .. import __version__, api
from ..conda_interface import ArgumentParser, add_parser_channels, cc_conda_build
from ..config import get_channel_urls, get_or_merge_config
from ..deprecations import deprecated
from ..utils import LoggingContext
from ..variants import get_package_variants, set_language_env_vars

on_win = sys.platform == "win32"
log = logging.getLogger(__name__)


# see: https://stackoverflow.com/questions/29986185/python-argparse-dict-arg
class ParseYAMLArgument(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if len(values) != 1:
            raise RuntimeError("This switch requires exactly one argument")

        try:
            my_dict = yaml.load(values[0], Loader=yaml.BaseLoader)
            if not isinstance(my_dict, dict):
                raise RuntimeError(
                    f"The argument of {option_string} is not a YAML dictionary."
                )

            setattr(namespace, self.dest, my_dict)
        except ParserError as e:
            raise RuntimeError(
                f"The argument of {option_string} is not a valid YAML. The parser error was: \n\n{str(e)}"
            )


def get_render_parser():
    p = ArgumentParser(
        prog="conda render",
        description="""
Tool for expanding the template meta.yml file (containing Jinja syntax and
selectors) into the rendered meta.yml files. The template meta.yml file is
combined with user-specified configurations, static recipe files, and
environment information to generate the rendered meta.yml files.""",
        conflict_handler="resolve",
    )
    p.add_argument(
        "-V",
        "--version",
        action="version",
        help="Show the conda-build version number and exit.",
        version="conda-build %s" % __version__,
    )
    p.add_argument(
        "-n",
        "--no-source",
        action="store_true",
        help="When templating can't be completed, do not obtain the \
source to try fill in related template variables.",
    )
    p.add_argument(
        "--output",
        action="store_true",
        help="Output the conda package filename which would have been " "created",
    )
    p.add_argument(
        "--python",
        action="append",
        help="Set the Python version used by conda build.",
    )
    p.add_argument(
        "--perl",
        action="append",
        help="Set the Perl version used by conda build.",
    )
    p.add_argument(
        "--numpy",
        action="append",
        help="Set the NumPy version used by conda build.",
    )
    p.add_argument(
        "--R",
        action="append",
        help="""Set the R version used by conda build.""",
        dest="r_base",
    )
    p.add_argument(
        "--lua",
        action="append",
        help="Set the Lua version used by conda build.",
    )
    p.add_argument(
        "--bootstrap",
        help="""Provide initial configuration in addition to recipe.
        Can be a path to or name of an environment, which will be emulated
        in the package.""",
    )
    p.add_argument(
        "--append-file",
        help="""Append data in meta.yaml with fields from this file.  Jinja2 is not done
        on appended fields""",
        dest="append_sections_file",
    )
    p.add_argument(
        "--clobber-file",
        help="""Clobber data in meta.yaml with fields from this file.  Jinja2 is not done
        on clobbered fields.""",
        dest="clobber_sections_file",
    )
    p.add_argument(
        "-m",
        "--variant-config-files",
        action="append",
        help="""Additional variant config files to add.  These yaml files can contain
        keys such as `c_compiler` and `target_platform` to form a build matrix.""",
    )
    p.add_argument(
        "-e",
        "--exclusive-config-files",
        "--exclusive-config-file",
        action="append",
        help="""Exclusive variant config files to add. Providing files here disables
        searching in your home directory and in cwd.  The files specified here come at the
        start of the order, as opposed to the end with --variant-config-files.  Any config
        files in recipes and any config files specified with --variant-config-files will
        override values from these files.""",
    )
    p.add_argument(
        "--old-build-string",
        dest="filename_hashing",
        action="store_false",
        default=cc_conda_build.get("filename_hashing", "true").lower() == "true",
        help=(
            "Disable hash additions to filenames to distinguish package "
            "variants from one another. NOTE: any filename collisions are "
            "yours to handle. Any variants with overlapping names within a "
            "build will clobber each other."
        ),
    )
    p.add_argument(
        "--use-channeldata",
        action="store_true",
        dest="use_channeldata",
        help=(
            "Use channeldata, if available, to determine run_exports. Otherwise packages "
            "are downloaded to determine this information"
        ),
    )
    p.add_argument(
        "--variants",
        nargs=1,
        action=ParseYAMLArgument,
        help=(
            "Variants to extend the build matrix. Must be a valid YAML instance, "
            'such as "{python: [3.8, 3.9]}"'
        ),
    )
    add_parser_channels(p)
    return p


def parse_args(args):
    p = get_render_parser()
    p.add_argument(
        "-f",
        "--file",
        help="write YAML to file, given as argument here.\
              Overwrites existing files.",
    )
    # we do this one separately because we only allow one entry to conda render
    p.add_argument(
        "recipe",
        metavar="RECIPE_PATH",
        help="Path to recipe directory.",
    )
    # this is here because we have a different default than build
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output from download tools and progress updates",
    )
    args, _ = p.parse_known_args(args)
    return p, args


def execute(args, print_results=True):
    p, args = parse_args(args)

    config = get_or_merge_config(None, **args.__dict__)

    variants = get_package_variants(args.recipe, config, variants=args.variants)
    from conda_build.build import get_all_replacements

    get_all_replacements(variants)
    set_language_env_vars(variants)

    config.channel_urls = get_channel_urls(args.__dict__)

    config.override_channels = args.override_channels

    if args.output:
        config.verbose = False
        config.debug = False

    metadata_tuples = api.render(
        args.recipe,
        config=config,
        no_download_source=args.no_source,
        variants=args.variants,
    )

    if args.file and len(metadata_tuples) > 1:
        log.warning(
            "Multiple variants rendered. "
            "Only one will be written to the file you specified ({}).".format(args.file)
        )

    if print_results:
        if args.output:
            with LoggingContext(logging.CRITICAL + 1):
                paths = api.get_output_file_paths(metadata_tuples, config=config)
                print("\n".join(sorted(paths)))
            if args.file:
                m = metadata_tuples[-1][0]
                api.output_yaml(m, args.file, suppress_outputs=True)
        else:
            logging.basicConfig(level=logging.INFO)
            for m, _, _ in metadata_tuples:
                print("--------------")
                print("Hash contents:")
                print("--------------")
                pprint(m.get_hash_contents())
                print("----------")
                print("meta.yaml:")
                print("----------")
                print(api.output_yaml(m, args.file, suppress_outputs=True))
    else:
        return metadata_tuples


@deprecated("3.26.0", "4.0.0", addendum="Use `conda render` instead.")
def main():
    return execute(sys.argv[1:])


if __name__ == "__main__":
    main()
