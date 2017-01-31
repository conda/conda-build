"""This file handles the parsing of feature specifications from files,
ending up with a configuration matrix"""

from itertools import product
import os
import sys

import six
import yaml

from conda_build.utils import ensure_list
from conda_build.conda_interface import cc

DEFAULT_EXTEND_KEYS = ['pin_run_as_build']
DEFAULT_VARIANTS = {
    'python': ['{0}.{1}.*'.format(sys.version_info.major, sys.version_info.minor)],
    'numpy': ['1.11.*'],
    'perl': ['5.22.2.*'],
    'lua': ['5.2.*'],
    'r_base': ['3.3.2.*'],
    'pin_run_as_build': ['python']
}


SUFFIX_MAP = {'PY': 'python',
              'NPY': 'numpy',
              'LUA': 'lua',
              'PERL': 'perl',
              'R': 'r_base'}


def parse_config_file(path):
    with open(path) as f:
        content = yaml.load(f)
    return content


def validate_variant(variant):
    errors = []
    for key in variant:
        if '-' in key:
            errors.append('"-" is a disallowed character in variant keys.  Key was: {}'.format(key))
    if errors:
        raise ValueError("Variant configuration errors: \n{}".format(errors))


def find_config_files(metadata_or_path, additional_files=None, ignore_system_config=False):
    """Find files to load variables from.  Note that order here determines clobbering.

    Later files clobber earlier ones.  Preference is system-wide, then """
    files = []

    if hasattr(metadata_or_path, 'path'):
        recipe_config = os.path.join(metadata_or_path.path, ".conda_build_config.yaml")
    else:
        recipe_config = os.path.join(metadata_or_path, ".conda_build_config.yaml")

    if not ignore_system_config:
        if hasattr(cc, "conda_build_config") and getattr(cc, "conda_build_config"):
            system_path = cc.conda_build_config
        else:
            system_path = os.path.join(os.path.expanduser('~'), ".conda_build_config.yaml")
        if os.path.isfile(system_path):
            files.append(system_path)
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
    extend_keys = DEFAULT_EXTEND_KEYS
    extend_keys.extend([key for spec in specs if spec
                        for key in ensure_list(spec.get('extend_keys'))])

    values = {}
    # each spec is a dictionary.  Each subsequent spec replaces the previous one.
    #     Only the last one with the key stays.
    for spec in specs:
        if spec:
            for k, v in spec.items():
                if k in extend_keys:
                    # update dictionaries, extend lists
                    if hasattr(v, 'keys'):
                        if k in values and hasattr(values[k], 'keys'):
                            values[k].update(v)
                        else:
                            values[k] = v
                    else:
                        values[k] = ensure_list(values.get(k, []))
                        values[k].extend(ensure_list(v))
                        # uniquify
                        values[k] = list(set(values[k]))
                else:
                    if hasattr(v, 'keys'):
                        values[k] = v
                    else:
                        values[k] = ensure_list(v)
    return values, set(extend_keys)


def combine_variants(*variants):
    """Difference between this and combine_specs is that specs have lists of versions, whereas a
    single variant has only one version per key.

    The purpose of this function is to clobber earlier variant values with later ones, while merging
    any values from 'extended' columns.

    Many variants can be passed in, but only one unified variant is returned
    """
    combined_specs, extend_keys = combine_specs(variants)
    return dict_of_lists_to_list_of_dicts(combined_specs)[0]


def set_language_env_vars(variant):
    """Given args passed into conda command, set language env vars to be made available"""
    inverse_map = {v: k for k, v in SUFFIX_MAP.items()}
    env = {}
    for variant_name, env_var_name in inverse_map.items():
        if variant_name in variant:
            env['CONDA_' + env_var_name] = str(variant[variant_name])
    return env


def dict_of_lists_to_list_of_dicts(dict_or_list_of_dicts):
    # http://stackoverflow.com/a/5228294/1170370
    # end result is a collection of dicts, like [{'python': 2.7, 'numpy': 1.11},
    #                                            {'python': 3.5, 'numpy': 1.11}]
    if hasattr(dict_or_list_of_dicts, 'keys'):
        specs = [DEFAULT_VARIANTS, dict_or_list_of_dicts]
    else:
        specs = [DEFAULT_VARIANTS] + list(dict_or_list_of_dicts or [])

    combined, extend_keys = combine_specs(specs)
    if 'extend_keys' in combined:
        del combined['extend_keys']

    dicts = []
    dimensions = {k: v for k, v in combined.items() if k not in ['extend_keys'] + list(extend_keys)}
    for x in product(*dimensions.values()):
        remapped = dict(six.moves.zip(dimensions, x))
        for col in list(extend_keys):
            v = combined.get(col)
            if v:
                remapped[col] = v if hasattr(v, 'keys') else list(set(v))
        dicts.append(remapped)
    return dicts


def get_package_variants(recipedir_or_metadata, config=None):
    if hasattr(recipedir_or_metadata, 'config'):
        config = recipedir_or_metadata.config
    files = find_config_files(recipedir_or_metadata, ensure_list(config.variant_config_files),
                              ignore_system_config=config.ignore_system_variants)

    specs = get_default_variants() + [parse_config_file(f) for f in files]

    # this is the override of the variants from files and args with values from CLI or env vars
    if config.variant:
        combined_spec, extend_keys = combine_specs(specs + [config.variant])
    else:
        # this tweaks behavior from clobbering to appending/extending
        combined_spec, extend_keys = combine_specs(specs)

    # clobber the variant with anything in the config (stuff set via CLI flags or env vars)
    for k, v in config.variant.items():
        if k in extend_keys:
            combined_spec[k].extend(v)
        else:
            combined_spec[k] = [v]

    validate_variant(combined_spec)
    return dict_of_lists_to_list_of_dicts(combined_spec)


def get_default_variants():
    return dict_of_lists_to_list_of_dicts(DEFAULT_VARIANTS)
