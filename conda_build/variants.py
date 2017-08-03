"""This file handles the parsing of feature specifications from files,
ending up with a configuration matrix"""

from itertools import product
import os
import sys

import six
import yaml

from conda_build.utils import ensure_list, HashableDict, trim_empty_keys
from conda_build.conda_interface import string_types
from conda_build.conda_interface import subdir
from conda_build.conda_interface import cc_conda_build
from conda_build.conda_interface import cc_platform

DEFAULT_EXTEND_KEYS = ['pin_run_as_build', 'ignore_version']
DEFAULT_VARIANTS = {
    'python': ['{0}.{1}'.format(sys.version_info.major, sys.version_info.minor)],
    'numpy': ['1.11'],
    # this one actually needs to be pretty specific.  The reason is that cpan skeleton uses the
    #    version to say what's in their standard library.
    'perl': ['5.22.2'],
    'lua': ['5'],
    'r_base': ['3'],
    'cpu_optimization_target': ['nocona'],
    'pin_run_as_build': {'python': {'min_pin': 'x.x', 'max_pin': 'x.x'}},
    'ignore_version': [],
}

arch_name = subdir.rsplit('-', 1)[-1]

DEFAULT_PLATFORMS = {
    'linux': 'linux-' + arch_name,
    'osx': 'osx-' + arch_name,
    'win': 'win-' + arch_name,
}


SUFFIX_MAP = {'PY': 'python',
              'NPY': 'numpy',
              'LUA': 'lua',
              'PERL': 'perl',
              'R': 'r_base'}


def parse_config_file(path, config):
    from conda_build.metadata import select_lines, ns_cfg
    with open(path) as f:
        contents = f.read()
    contents = select_lines(contents, ns_cfg(config))
    content = yaml.load(contents, Loader=yaml.loader.BaseLoader)
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

    Later files clobber earlier ones.  order is user-wide < cwd < recipe dir < additional files"""
    files = []

    if not ignore_system_config:
        if cc_conda_build.get('config_file'):
            system_path = cc_conda_build['config_file']
        else:
            system_path = os.path.join(os.path.expanduser('~'), "conda_build_config.yaml")
        if os.path.isfile(system_path):
            files.append(system_path)

    cwd = os.path.join(os.getcwd(), 'conda_build_config.yaml')
    if os.path.isfile(cwd):
        files.append(cwd)

    if hasattr(metadata_or_path, 'path'):
        recipe_config = os.path.join(metadata_or_path.path, "conda_build_config.yaml")
    else:
        recipe_config = os.path.join(metadata_or_path, "conda_build_config.yaml")
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


def all_unique(_list):
    seen = set()
    item = None
    unique = not any(item in seen or seen.add(item) for _set in _list for item in _set)
    return unique or item


def _get_zip_key_type(zip_keys):
    is_strings = all(isinstance(key, string_types) for key in zip_keys)
    is_list_of_strings = all(hasattr(key, '__iter__') and not isinstance(key, string_types)
                            for key in zip_keys)
    return is_strings, is_list_of_strings


def _get_zip_key_set(combined_variant):
    """Used to exclude particular keys from the matrix"""
    zip_keys = combined_variant.get('zip_keys')
    key_set = set()
    if zip_keys:
        # zip keys can be either a collection of strings, or a collection of collections of strings
        assert hasattr(zip_keys, '__iter__') and not isinstance(zip_keys, string_types), (
                    "zip_keys must be uniformly a list of strings, or a list of lists of strings")
        is_strings, is_list_of_strings = _get_zip_key_type(zip_keys)
        assert is_strings or is_list_of_strings, ("zip_keys must be uniformly a list of strings, "
                                                "or a list of lists of strings")
        if is_strings:
            key_set = set(zip_keys)
        else:
            # make sure that each key only occurs in one set
            key_sets = [set(group) for group in zip_keys]
            _all_unique = all_unique(key_sets)
            if _all_unique is not True:
                raise ValueError("All package in zip keys must belong to only one group.  "
                                "'{}' is in more than one group.".format(_all_unique))
            for ks in key_sets:
                key_set.update(ks)
    # omit
    key_set = {key for key in key_set if key in combined_variant}
    return key_set


def _get_zip_dict_of_lists(combined_variant, list_of_strings):
    used_keys = [key for key in list_of_strings if key in combined_variant]
    out = {}

    if used_keys:
        # The join value needs to be selected as something
        # that will not likely appear in any key or value.
        dict_key = "#".join(list_of_strings)
        length = len(ensure_list(combined_variant[used_keys[0]]))
        for key in used_keys:
            if not len(ensure_list(combined_variant[key])) == length:
                raise ValueError("zip field {} length does not match zip field {} length.  All zip "
                                 "fields within a group must be the same length."
                                 .format(used_keys[0], key))
        values = list(zip(*[ensure_list(combined_variant[key]) for key in used_keys]))
        values = ['#'.join(value) for value in values]
        out = {dict_key: values}
    return out


def _get_zip_groups(combined_variant):
    """returns a dictionary of dictionaries - each one is """
    zip_keys = combined_variant.get('zip_keys')
    groups = []
    if zip_keys:
        is_strings, is_list_of_strings = _get_zip_key_type(zip_keys)
        if is_strings:
            groups.append(_get_zip_dict_of_lists(combined_variant, zip_keys))
        elif is_list_of_strings:
            for group in zip_keys:
                groups.append(_get_zip_dict_of_lists(combined_variant, group))
    return groups


def dict_of_lists_to_list_of_dicts(dict_or_list_of_dicts, platform=cc_platform):
    # http://stackoverflow.com/a/5228294/1170370
    # end result is a collection of dicts, like [{'python': 2.7, 'numpy': 1.11},
    #                                            {'python': 3.5, 'numpy': 1.11}]
    if hasattr(dict_or_list_of_dicts, 'keys'):
        specs = [DEFAULT_VARIANTS, dict_or_list_of_dicts]
    else:
        specs = [DEFAULT_VARIANTS] + list(dict_or_list_of_dicts or [])

    combined, extend_keys = combine_specs(specs)

    if 'target_platform' not in combined or not combined['target_platform']:
        try:
            combined['target_platform'] = [DEFAULT_PLATFORMS[platform]]
        except KeyError:
            combined['target_platform'] = [DEFAULT_PLATFORMS[platform.split('-')[0]]]

    if 'extend_keys' in combined:
        del combined['extend_keys']

    dicts = []
    dimensions = {k: v for k, v in combined.items() if k not in (['extend_keys'] +
                                                                 list(extend_keys) +
                                                                 list(_get_zip_key_set(combined)))}
    # here's where we add in the zipped dimensions
    for group in _get_zip_groups(combined):
        dimensions.update(group)

    # in case selectors nullify any groups - or else zip reduces whole set to nil
    trim_empty_keys(dimensions)

    for x in product(*dimensions.values()):
        remapped = dict(six.moves.zip(dimensions, x))
        for col in list(extend_keys):
            v = combined.get(col)
            if v:
                remapped[col] = v if hasattr(v, 'keys') else list(set(v))
        # split out zipped keys
        for k, v in remapped.copy().items():
            if isinstance(k, string_types) and isinstance(v, string_types):
                keys = k.split('#')
                values = v.split('#')
                for (_k, _v) in zip(keys, values):
                    remapped[_k] = _v
                if '#' in k:
                    del remapped[k]
        dicts.append(remapped)
    return dicts


def conform_variants_to_value(list_of_dicts, dict_of_values):
    """We want to remove some variability sometimes.  For example, when Python is used by the
    top-level recipe, we do not want a further matrix for the outputs.  This function reduces
    the variability of the variant set."""
    for d in list_of_dicts:
        for k, v in dict_of_values.items():
            d[k] = v
    return list(set([HashableDict(d) for d in list_of_dicts]))


def get_package_variants(recipedir_or_metadata, config=None):
    if hasattr(recipedir_or_metadata, 'config'):
        config = recipedir_or_metadata.config
    if not config:
        from conda_build.config import Config
        config = Config()
    files = find_config_files(recipedir_or_metadata, ensure_list(config.variant_config_files),
                              ignore_system_config=config.ignore_system_variants)

    specs = get_default_variants(config.platform) + [parse_config_file(f, config) for f in files]

    # this is the override of the variants from files and args with values from CLI or env vars
    if config.variant:
        combined_spec, extend_keys = combine_specs(specs + [config.variant])
    else:
        # this tweaks behavior from clobbering to appending/extending
        combined_spec, extend_keys = combine_specs(specs)

    # clobber the variant with anything in the config (stuff set via CLI flags or env vars)
    for k, v in config.variant.items():
        if k in extend_keys:
            if hasattr(combined_spec[k], 'keys'):
                combined_spec[k].update(v)
            else:
                combined_spec[k].extend(v)
        else:
            combined_spec[k] = [v]

    validate_variant(combined_spec)
    return dict_of_lists_to_list_of_dicts(combined_spec, config.platform)


def get_default_variants(platform=cc_platform):
    return dict_of_lists_to_list_of_dicts(DEFAULT_VARIANTS, platform)


def get_loop_vars(variants):
    """For purposes of naming/identifying, provide a way of identifying which variables contribute
    to the matrix dimensionality"""
    special_keys = ('pin_run_as_build', 'zip_keys', 'ignore_version')
    return [k for k in variants[0] if k not in special_keys and
            any(variant[k] != variants[0][k] for variant in variants[1:])]
