"""This file handles the parsing of feature specifications from files,
ending up with a configuration matrix"""

from collections import OrderedDict
from itertools import product
import os
from os.path import abspath, expanduser, expandvars
from pkg_resources import parse_version
import re
import sys

import six
import yaml

from conda_build.utils import ensure_list, trim_empty_keys, get_logger
from conda_build.conda_interface import string_types
from conda_build.conda_interface import subdir
from conda_build.conda_interface import cc_conda_build
from conda_build.conda_interface import memoized
from conda_build.utils import on_win

DEFAULT_VARIANTS = {
    'python': '{0}.{1}'.format(sys.version_info.major, sys.version_info.minor),
    'numpy': '1.11',
    # this one actually needs to be pretty specific.  The reason is that cpan skeleton uses the
    #    version to say what's in their standard library.
    'perl': '5.26.2',
    'lua': '5',
    'r_base': '3.4' if on_win else '3.5',
    'cpu_optimization_target': 'nocona',
    'pin_run_as_build': OrderedDict(python=OrderedDict(min_pin='x.x', max_pin='x.x')),
    'ignore_version': [],
    'ignore_build_only_deps': ['python', 'numpy'],
    'extend_keys': ['pin_run_as_build', 'ignore_version', 'ignore_build_only_deps', 'extend_keys'],
    'cran_mirror': "https://cran.r-project.org",
    'CONDA_BUILD_SYSROOT': '/opt/MacOSX10.10.sdk',
}

# set this outside the initialization because of the dash in the key
DEFAULT_VARIANTS['pin_run_as_build']['r-base'] = OrderedDict(min_pin='x.x', max_pin='x.x')

# map python version to default compiler on windows, to match upstream python
#    This mapping only sets the "native" compiler, and can be overridden by specifying a compiler
#    in the conda-build variant configuration
DEFAULT_COMPILERS = {
    'win': {
        'c': {
            '2.7': 'vs2008',
            '3.3': 'vs2010',
            '3.4': 'vs2010',
            '3.5': 'vs2017',
        },
        'cxx': {
            '2.7': 'vs2008',
            '3.3': 'vs2010',
            '3.4': 'vs2010',
            '3.5': 'vs2017',
        },
        'vc': {
            '2.7': '9',
            '3.3': '10',
            '3.4': '10',
            '3.5': '14',
        },
        'fortran': 'gfortran',
    },
    'linux': {
        'c': 'gcc',
        'cxx': 'gxx',
        'fortran': 'gfortran',
    },
    'osx': {
        'c': 'clang',
        'cxx': 'clangxx',
        'fortran': 'gfortran',
    },
}

arch_name = subdir.rsplit('-', 1)[-1]

SUFFIX_MAP = {'PY': 'python',
              'NPY': 'numpy',
              'LUA': 'lua',
              'PERL': 'perl',
              'R': 'r_base'}


@memoized
def _get_default_compilers(platform, py_ver):
    compilers = DEFAULT_COMPILERS[platform].copy()
    if platform == 'win':
        if parse_version(py_ver) >= parse_version('3.5'):
            py_ver = '3.5'
        elif parse_version(py_ver) <= parse_version('3.2'):
            py_ver = '2.7'
        compilers['c'] = compilers['c'][py_ver]
        compilers['cxx'] = compilers['cxx'][py_ver]
    compilers = {lang + '_compiler': pkg_name
                 for lang, pkg_name in compilers.items() if lang != 'vc'}
    # this one comes after, because it's not a _compiler key
    if platform == 'win':
        compilers['vc'] = DEFAULT_COMPILERS[platform]['vc'][py_ver]
    return compilers


def get_default_variant(config):
    base = DEFAULT_VARIANTS.copy()
    base['target_platform'] = config.subdir
    python = base['python'] if (not hasattr(config, 'variant') or
                                not config.variant.get('python')) else config.variant['python']
    base.update(_get_default_compilers(config.platform, python))
    return base


def parse_config_file(path, config):
    from conda_build.metadata import select_lines, ns_cfg
    with open(path) as f:
        contents = f.read()
    contents = select_lines(contents, ns_cfg(config), variants_in_place=False)
    content = yaml.load(contents, Loader=yaml.loader.BaseLoader) or {}
    trim_empty_keys(content)
    return content


def validate_spec(spec):
    errors = []
    for key in spec:
        if '-' in key:
            errors.append('"-" is a disallowed character in variant keys.  Key was: {}'.format(key))
    zip_groups = _get_zip_groups(spec)
    # each group looks like {key1#key2: [val1_1#val2_1, val1_2#val2_2]
    for group in zip_groups:
        for group_key in group:
            for variant_key in group_key.split('#'):
                if variant_key not in spec:
                    errors.append('zip_key entry {} in group {} does not have any settings'.format(
                        variant_key, group_key.split('#')))
    if errors:
        raise ValueError("Variant configuration errors: \n{}".format(errors))


def find_config_files(metadata_or_path, additional_files=None, ignore_system_config=False,
                      exclusive_config_files=None):
    """Find files to load variables from.  Note that order here determines clobbering.

    Later files clobber earlier ones.  order is user-wide < cwd < recipe dir < additional files"""
    files = [
        os.path.abspath(os.path.expanduser(config_file))
        for config_file in (exclusive_config_files or [])
    ]

    if not ignore_system_config and not exclusive_config_files:
        if cc_conda_build.get('config_file'):
            system_path = abspath(expanduser(expandvars(cc_conda_build['config_file'])))
        else:
            system_path = os.path.join(expanduser('~'), "conda_build_config.yaml")
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


def _combine_spec_dictionaries(specs, extend_keys=None, filter_keys=None, zip_keys=None,
                               log_output=True):
    # each spec is a dictionary.  Each subsequent spec replaces the previous one.
    #     Only the last one with the key stays.
    values = {}
    keys = ensure_list(filter_keys)
    extend_keys = ensure_list(extend_keys)

    for spec_source, spec in specs.items():
        if spec:
            if log_output:
                log = get_logger(__name__)
                log.info("Adding in variants from {}".format(spec_source))
            for k, v in spec.items():
                if not keys or k in keys:
                    if k in extend_keys:
                        # update dictionaries, extend lists
                        if hasattr(v, 'keys'):
                            if k in values and hasattr(values[k], 'keys'):
                                values[k].update(v)
                            else:
                                values[k] = v.copy()
                        else:
                            values[k] = ensure_list(values.get(k, []))
                            values[k].extend(ensure_list(v))
                            # uniquify
                            values[k] = list(set(values[k]))
                    elif k == 'zip_keys':
                        v = [subval for subval in v if subval]
                        if not isinstance(v[0], list) and not isinstance(v[0], tuple):
                            v = [v]
                        # should always be a list of lists, but users may specify as just a list
                        values[k] = values.get(k, [])
                        values[k].extend(v)
                        values[k] = list(list(set_group) for set_group in set(tuple(group)
                                                                        for group in values[k]))
                    else:
                        if hasattr(v, 'keys'):
                            values[k] = v.copy()
                        else:
                            # default "group" is just this one key.  We latch onto other groups if
                            #     they exist
                            keys_in_group = [k]
                            if zip_keys:
                                for group in zip_keys:
                                    if k in group:
                                        keys_in_group = group
                                        break
                            # in order to clobber, one must replace ALL of the zipped keys.
                            # or the length must match with the other items in the group
                            #    Otherwise, we filter later.
                            if all(group_item in spec for group_item in keys_in_group):
                                for group_item in keys_in_group:
                                    if len(ensure_list(spec[group_item])) != len(ensure_list(v)):
                                        raise ValueError("All entries associated by a zip_key "
                                    "field must be the same length.  In {}, {} and {} are "
                                    "different ({} and {})".format(spec_source, k, group_item,
                                                                len(ensure_list(v)),
                                                                len(ensure_list(spec[group_item]))))
                                    values[group_item] = ensure_list(spec[group_item])
                            elif k in values:
                                for group_item in keys_in_group:
                                    if group_item in spec and \
                                            len(ensure_list(spec[group_item])) != len(ensure_list(v)):
                                        break
                                    if group_item in values and \
                                            len(ensure_list(values[group_item])) != len(ensure_list(v)):
                                        break
                                else:
                                    values[k] = v.copy()
                                if any(subvalue not in values[k]
                                                    for subvalue in ensure_list(v)):

                                    raise ValueError("variant config in {} is ambiguous because it "
                                        "does not fully implement all zipped keys, or specifies "
                                        "a subspace that is not fully implemented.".format(
                                            spec_source))

    return values


def combine_specs(specs, log_output=True):
    """With arbitrary sets of sources, combine into a single aggregate spec.

    Later specs in the input set have priority and overwrite duplicate entries.

    specs: list of dictionaries.  Keys are arbitrary, but correspond to variable
           names used in Jinja2 templated recipes.  Values can be either single
           values (strings or integers), or collections (lists, tuples, sets).
    """
    extend_keys = DEFAULT_VARIANTS['extend_keys'][:]
    extend_keys.extend([key for spec in specs.values() if spec
                        for key in ensure_list(spec.get('extend_keys'))])

    # first pass gets zip_keys entries from each and merges them.  We treat these specially
    #   below, keeping the size of related fields identical, or else the zipping makes no sense

    zip_keys = _combine_spec_dictionaries(specs, extend_keys=extend_keys,
                                          filter_keys=['zip_keys'],
                                          log_output=log_output).get('zip_keys', [])
    values = _combine_spec_dictionaries(specs, extend_keys=extend_keys, zip_keys=zip_keys,
                                        log_output=log_output)
    return values


def set_language_env_vars(variant):
    """Given args passed into conda command, set language env vars to be made available.

    Search terms: CONDA_PY, CONDA_R, CONDA_PERL, CONDA_LUA, CONDA_NPY
    """
    inverse_map = {v: k for k, v in SUFFIX_MAP.items()}
    env = {}
    for variant_name, env_var_name in inverse_map.items():
        if variant_name in variant:
            value = str(variant[variant_name])
            # legacy compatibility: python should be just first
            if env_var_name == 'PY':
                value = ''.join(value.split('.')[:2])
            env['CONDA_' + env_var_name] = value
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
        key_set = set()
        if is_strings and len(zip_keys) > 1:
            key_set.update(zip_keys)
        else:
            # make sure that each key only occurs in one set
            _all_unique = all_unique(zip_keys)
            if _all_unique is not True:
                raise ValueError("All packages in zip keys must belong to only one group.  "
                                "'{}' is in more than one group.".format(_all_unique))
            for ks in zip_keys:
                # sets with only a single member aren't actually zipped.  Ignore them.
                if len(ks) > 1:
                    key_set.update(set(ks))
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
                raise ValueError("zip field {} ({}) length does not match zip field {} ({}) "
                                 "length.  All zip fields within a group must be the same length."
                                 .format(used_keys[0], combined_variant[used_keys[0]],
                                         key, combined_variant[key]))
        values = list(zip(*[ensure_list(combined_variant[key]) for key in used_keys]))
        values = ['#'.join(value) for value in values]
        out = {dict_key: values}
    return out


def _get_zip_groups(combined_variant):
    """returns a list of dictionaries - each one is a concatenated collection of """
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


def filter_by_key_value(variants, key, values, source_name):
    """variants is the exploded out list of dicts, with one value per key in each dict.
    key and values come from subsequent variants before they are exploded out."""
    reduced_variants = []
    if hasattr(values, 'keys'):
        reduced_variants = variants
    else:
        # break this out into a full loop so that we can show filtering output
        for variant in variants:
            if variant.get(key) is not None and variant.get(key) in values:
                reduced_variants.append(variant)
            else:
                log = get_logger(__name__)
                log.debug('Filtering variant with key {key} not matching target value(s) '
                          '({tgt_vals}) from {source_name}, actual {actual_val}'.format(
                              key=key, tgt_vals=values, source_name=source_name,
                              actual_val=variant.get(key)))
    return reduced_variants


@memoized
def _split_str(string, char):
    return string.split(char)


def dict_of_lists_to_list_of_dicts(dict_of_lists, extend_keys=None):
    # http://stackoverflow.com/a/5228294/1170370
    # end result is a collection of dicts, like [{'python': 2.7, 'numpy': 1.11},
    #                                            {'python': 3.5, 'numpy': 1.11}]
    dicts = []
    if not extend_keys:
        extend_keys = set(ensure_list(dict_of_lists.get('extend_keys')))
    pass_through_keys = set(['extend_keys', 'zip_keys', 'pin_run_as_build', 'replacements'] +
                            list(ensure_list(extend_keys)) +
                            list(_get_zip_key_set(dict_of_lists)))
    dimensions = {k: v for k, v in dict_of_lists.items() if k not in pass_through_keys}
    # here's where we add in the zipped dimensions.  Zipped stuff is concatenated strings, to avoid
    #      being distributed in the product.
    for group in _get_zip_groups(dict_of_lists):
        dimensions.update(group)

    # in case selectors nullify any groups - or else zip reduces whole set to nil
    trim_empty_keys(dimensions)

    for x in product(*dimensions.values()):
        remapped = dict(six.moves.zip(dimensions, x))
        for col in pass_through_keys:
            v = dict_of_lists.get(col)
            if v or v == '':
                if isinstance(v, (OrderedDict, dict)):
                    remapped[col] = v.copy()
                else:
                    remapped[col] = v
        # split out zipped keys
        to_del = set()
        for k, v in remapped.items():
            if isinstance(k, string_types) and isinstance(v, string_types):
                keys = _split_str(k, '#')
                values = _split_str(v, '#')
                for (_k, _v) in zip(keys, values):
                    # I am unclear if I should be doing something else here!
                    if not isinstance(remapped[_k], (OrderedDict, dict)):
                        remapped[_k] = _v
                if '#' in k:
                    to_del.add(k)
        for key in to_del:
            del remapped[key]
        dicts.append(remapped)
    return dicts


def list_of_dicts_to_dict_of_lists(list_of_dicts):
    """Opposite of dict_of_lists_to_list_of_dicts function.

    Take broken out collection of variants, and squish it into a dict, where each value is a list.
    Only squishes string/int values; does "update" for dict keys
    """
    if not list_of_dicts:
        return
    squished = OrderedDict()
    all_zip_keys = set()
    groups = None
    zip_key_groups = (list_of_dicts[0]['zip_keys'] if 'zip_keys' in list_of_dicts[0] and
                      list_of_dicts[0]['zip_keys'] else [])
    if zip_key_groups:
        if (isinstance(list_of_dicts[0]['zip_keys'][0], list) or
                  isinstance(list_of_dicts[0]['zip_keys'][0], tuple)):
            groups = list_of_dicts[0]['zip_keys']
        else:
            groups = [list_of_dicts[0]['zip_keys']]
        for group in groups:
            for item in group:
                all_zip_keys.add(item)
    for variant in list_of_dicts:
        for k, v in variant.items():
            if k == 'zip_keys':
                continue
            if hasattr(v, 'keys'):
                existing_value = squished.get(k, OrderedDict())
                existing_value.update(v)
                squished[k] = existing_value
            elif isinstance(v, list):
                squished[k] = set(squished.get(k, set())) | set(v)
            else:
                squished[k] = list(squished.get(k, [])) + ensure_list(v)
                if k not in all_zip_keys:
                    squished[k] = list(set(squished[k]))
    # reduce the combinatoric space of the zipped keys, too:
    if groups:
        for group in groups:
            values = list(zip(*set(zip(*(squished[key] for key in group)))))
            for idx, key in enumerate(group):
                squished[key] = values[idx]
    squished['zip_keys'] = zip_key_groups
    return squished


def get_package_combined_spec(recipedir_or_metadata, config=None, variants=None):
    # outputs a tuple of (combined_spec_dict_of_lists, used_spec_file_dict)
    #
    # The output of this function is order preserving, unlike get_package_variants
    if hasattr(recipedir_or_metadata, 'config'):
        config = recipedir_or_metadata.config
    if not config:
        from conda_build.config import Config
        config = Config()
    files = find_config_files(recipedir_or_metadata, ensure_list(config.variant_config_files),
                              ignore_system_config=config.ignore_system_variants,
                              exclusive_config_files=config.exclusive_config_files)

    specs = OrderedDict(internal_defaults=get_default_variant(config))

    for f in files:
        specs[f] = parse_config_file(f, config)

    # this is the override of the variants from files and args with values from CLI or env vars
    if hasattr(config, 'variant') and config.variant:
        specs['config.variant'] = config.variant
    if variants:
        specs['argument_variants'] = variants

    for f, spec in specs.items():
        try:
            validate_spec(spec)
        except ValueError as e:
            raise ValueError("Error in config {}: {}".format(f, str(e)))

    # this merges each of the specs, providing a debug message when a given setting is overridden
    #      by a later spec
    combined_spec = combine_specs(specs, log_output=config.verbose)
    return combined_spec, specs


def filter_combined_spec_to_used_keys(combined_spec, specs):

    extend_keys = set(ensure_list(combined_spec.get('extend_keys')))
    extend_keys.update({'zip_keys', 'extend_keys'})

    # delete the default specs, so that they don't unnecessarily limit the matrix
    specs = specs.copy()
    del specs['internal_defaults']

    # TODO: act here?
    combined_spec = dict_of_lists_to_list_of_dicts(combined_spec, extend_keys=extend_keys)
    for source, source_specs in reversed(specs.items()):
        for k, vs in source_specs.items():
            if k not in extend_keys:
                # when filtering ends up killing off all variants, we just ignore that.  Generally,
                #    this arises when a later variant config overrides, rather than selects a
                #    subspace of earlier configs
                combined_spec = (filter_by_key_value(combined_spec, k, vs, source_name=source) or
                                 combined_spec)
    return combined_spec


def get_package_variants(recipedir_or_metadata, config=None, variants=None):
    combined_spec, specs = get_package_combined_spec(recipedir_or_metadata, config=config, variants=variants)
    return filter_combined_spec_to_used_keys(combined_spec, specs=specs)


def get_vars(variants, loop_only=False):
    """For purposes of naming/identifying, provide a way of identifying which variables contribute
    to the matrix dimensionality"""
    special_keys = {'pin_run_as_build', 'zip_keys', 'ignore_version'}
    special_keys.update(set(ensure_list(variants[0].get('extend_keys'))))
    loop_vars = [k for k in variants[0] if k not in special_keys and
                (not loop_only or
                any(variant[k] != variants[0][k] for variant in variants[1:]))]
    return loop_vars


@memoized
def find_used_variables_in_text(variant, recipe_text, selectors=False):
    used_variables = set()
    recipe_lines = recipe_text.splitlines()
    for v in variant:
        all_res = []
        compiler_match = re.match(r'(.*?)_compiler(_version)?$', v)
        if compiler_match and not selectors:
            compiler_lang = compiler_match.group(1)
            compiler_regex = (
                r"\{\s*compiler\([\'\"]%s[\"\'][^\{]*?\}" % re.escape(compiler_lang)
            )
            all_res.append(compiler_regex)
            variant_lines = [line for line in recipe_lines if v in line or compiler_lang in line]
        else:
            variant_lines = [line for line in recipe_lines if v in line.replace('-', '_')]
        if not variant_lines:
            continue
        v_regex = re.escape(v)
        v_req_regex = '[-_]'.join(map(re.escape, v.split('_')))
        variant_regex = r"\{\s*(?:pin_[a-z]+\(\s*?['\"])?%s[^'\"]*?\}\}" % v_regex
        selector_regex = r"^[^#\[]*?\#?\s\[[^\]]*?(?<![_\w\d])%s[=\s<>!\]]" % v_regex
        conditional_regex = r"(?:^|[^\{])\{%\s*(?:el)?if\s*" + v_regex + r"\s*(?:[^%]*?)?%\}"
        # plain req name, no version spec.  Look for end of line after name, or comment or selector
        requirement_regex = r"^\s+\-\s+%s\s*(?:\s[\[#]|$)" % v_req_regex
        if selectors:
            all_res.extend([selector_regex])
        else:
            all_res.extend([variant_regex, requirement_regex, conditional_regex])
        # consolidate all re's into one big one for speedup
        all_res = r"|".join(all_res)
        if any(re.search(all_res, line) for line in variant_lines):
            used_variables.add(v)
    return used_variables


def find_used_variables_in_shell_script(variant, file_path):
    with open(file_path) as f:
        text = f.read()
    used_variables = set()
    for v in variant:
        variant_regex = r"(^[^$]*?\$\{?\s*%s\s*[\s|\}])" % v
        if re.search(variant_regex, text, flags=re.MULTILINE | re.DOTALL):
            used_variables.add(v)
    return used_variables


def find_used_variables_in_batch_script(variant, file_path):
    with open(file_path) as f:
        text = f.read()
    used_variables = set()
    for v in variant:
        variant_regex = r"\%" + v + r"\%"
        if re.search(variant_regex, text, flags=re.MULTILINE | re.DOTALL):
            used_variables.add(v)
    return used_variables
