"""This file handles the parsing of feature specifications from files,
ending up with a configuration matrix"""

from itertools import product
import os
import sys

import six
import yaml

from conda_build.utils import ensure_list
from conda_build.conda_interface import cc
from conda_build import jinja_context


DEFAULT_VARIANTS = {
    'python': ['{0}.{1}'.format(sys.version_info.major, sys.version_info.minor)],
    'numpy': ['1.11'],
    'perl': ['5.20'],
    'lua': ['5.2'],
    'r': ['3.3'],
}


def parse_config_file(path):
    with open(path) as f:
        content = yaml.load(f)
    return content


def find_config_files(metadata, additional_files=None, ignore_system_config=False):
    """Find files to load variables from.  Note that order here determines clobbering.

    Later files clobber earlier ones.  Preference is system-wide, then """
    files = []
    if not ignore_system_config:
        if hasattr(cc, "conda_build_config") and getattr(cc, "conda_build_config"):
            system_path = cc.conda_build_config
        else:
            system_path = os.path.join(os.path.expanduser('~'), ".conda_build_config.yaml")
        if os.path.isfile(system_path):
            files.append(system_path)
    recipe_config = os.path.join(metadata.path, ".conda_build_config.yaml")
    if os.path.isfile(recipe_config):
        files.append(recipe_config)
    if additional_files:
        files.extend([os.path.expanduser(additional_file) for additional_file in additional_files])
    return files


def combine_specs(specs):
    """With arbitrary sets of sources, combine into a single aggregate spec.

    Later specs in the input set have priority and overwrite duplicate entries.

    specs: list of dictionaries.  Keys are arbitrary, but correspond to variable
           names used in Jinja2 templated recipes.  Values can be either single
           values (strings or integers), or collections (lists, tuples, sets).
    """
    values = {}
    # each spec replaces the previous one.  Only the last one with the key stays.
    for spec in specs:
        values.update(spec)
    return values


def get_package_variants(recipe_metadata, config_files=None, ignore_system_config=False):
    files = find_config_files(recipe_metadata, ensure_list(config_files),
                              ignore_system_config=ignore_system_config)
    specs = [parse_config_file(f) for f in files]
    if not specs:
        specs = [DEFAULT_VARIANTS]
    combined_spec = combine_specs(specs)
    matching_subset = (set(recipe_metadata.undefined_jinja_vars) |
                       jinja_context.get_used_variants(recipe_metadata)) & \
    set(combined_spec.keys())
    matching_subset = {key: ensure_list(combined_spec[key]) for key in matching_subset}

    # http://stackoverflow.com/a/5228294/1170370
    # end result is a collection of dicts, like [{'CONDA_PY': 2.7, 'CONDA_NPY': 1.11},
    #                                            {'CONDA_PY': 3.5, 'CONDA_NPY': 1.11}]
    return (dict(six.moves.zip(matching_subset, x)) for x in product(*matching_subset.values()))
