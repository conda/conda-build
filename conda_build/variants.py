"""This file handles the parsing of feature specifications from files,
ending up with a configuration matrix"""

from collections import OrderedDict
from copy import copy
from itertools import product
import os.path
from pkg_resources import parse_version
import re
import sys

import yaml

from conda_build.conda_interface import string_types
from conda_build.conda_interface import subdir
from conda_build.conda_interface import cc_conda_build
from conda_build.conda_interface import memoized
from conda_build.utils import ensure_list, get_logger, islist, on_win, trim_empty_keys

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
    'extend_keys': ['pin_run_as_build', 'ignore_version', 'ignore_build_only_deps'],
    'cran_mirror': "https://cran.r-project.org",
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


def validate_spec(src, spec, log_output=True):
    return combine_specs({src: spec}, log_output)


def find_config_files(metadata_or_path, config):
    """
    Find config files to load. Config files are stacked in the following order:
        1. exclusive config files (see config.exclusive_config_files)
        2. user config files
           (see context.conda_build["config_file"] or ~/conda_build_config.yaml)
        3. cwd config files (see ./conda_build_config.yaml)
        4. recipe config files (see ${RECIPE_DIR}/conda_build_config.yaml)
        5. additional config files (see config.variant_config_files)

    .. note::
        Order determines clobbering with later files clobbering earlier ones.

    :param metadata_or_path: the metadata or path within which to find recipe config files
    :type metadata_or_path:
    :param config: config object specifying config file settings
                   (see exclusive_config_files, ignore_system_variants, and variant_config_files)
    :type config: :class:`Config`
    :return: List of config files
    :rtype: `list` of paths (`str`)
    """
    resolve = lambda p: os.path.abspath(os.path.expanduser(os.path.expandvars(p)))

    # exclusive configs
    files = [resolve(f) for f in ensure_list(config.exclusive_config_files)]

    if not files and not config.ignore_system_variants:
        # user config
        if cc_conda_build.get('config_file'):
            cfg = resolve(cc_conda_build['config_file'])
        else:
            cfg = resolve(os.path.join('~', "conda_build_config.yaml"))
        if os.path.isfile(cfg):
            files.append(cfg)

        cfg = resolve('conda_build_config.yaml')
        if os.path.isfile(cfg):
            files.append(cfg)

    path = getattr(metadata_or_path, "path", metadata_or_path)
    cfg = resolve(os.path.join(path, "conda_build_config.yaml"))
    if os.path.isfile(cfg):
        files.append(cfg)

    files.extend([resolve(f) for f in ensure_list(config.variant_config_files)])

    return files


def combine_specs(specs, log_output=True):
    """
    With arbitrary sets of sources, combine into a single aggregate spec. Later
    specs in the input set have higher priority and overwrite duplicate entries.

    A number of combination techniques are performed:
        1. a unique set of 'zip_keys' is extracted from all specs
        2. a unique set of 'extend_keys' is extracted from all specs
        3. all keys defined in 'extend_keys' are extended or updated depending on
           whether the values are lists (`list`) or mappings (`dict`)
        4. all non-'extend_keys' are clobbered based on the order of `specs`

    A number of checks are done in the process of combining specs:
        1. invalid characters in keys
        2. valid 'zip_keys' format
        3. no duplicate keys in 'zip_keys'
        4. 'zip_keys' are not also defined as 'extend_keys'
        5. each key's field within a 'zip_keys' group has the same length
        6. ensure every key in 'zip_keys' is defined

    :param specs: mapping of source (e.g. command line, config file) to spec
    :type specs: `collections.OrderedDict`
    :param log_output: whether to enable logging, defaults to True
    :type log_output: `bool`, optional
    :return: the combined spec
    :rtype: `dict`
    :raises ValueError: one or more of the checks failed
    """
    if log_output:
        logger = get_logger(__name__)
        logshim = lambda m: logger.info(m)
    else:
        logshim = lambda m: None

    errors = []
    combined = {}

    # check for invalid characters
    errors.extend(
        "  - (src:{}) {!r} key contains an invalid character '-'".format(src, k)
        for src, spec in specs.items()
        for k in spec
        if "-" in k
    )

    # extract extend_keys from all specs
    extend_keys = {}  # maps extend_keys to first source
    extend_keys.update({
        k: src
        for src, spec in reversed(list(specs.items()))
        for k in _get_extend_keys(spec, include_defaults=False)
    })
    extend_keys.update({k: None for k in DEFAULT_VARIANTS['extend_keys']})
    combined["extend_keys"] = [k for k, v in extend_keys.items() if v]

    # extract zip_keys from all specs
    zip_keys = {}  # maps zip_keys group to first source
    for src, spec in reversed(list(specs.items())):
        try:
            zk = _get_zip_keys(spec)
        except ValueError as e:
            errors.append("  - (src:{}) {}".format(src, e))
        else:
            zip_keys.update({zg: src for zg in zk})
    combined["zip_keys"] = [tuple(zg) for zg in zip_keys]

    # ensure that no zip_keys key is duplicated
    keys = {}  # maps keys to their zip_keys group
    errors.extend(
        "  - key {!r} has been used multiple times in zip_keys, keys can only occur in one group:\n"
        "      (src:{}) {}\n"
        "      (src:{}) {}".format(k, zip_keys[keys[k]], tuple(keys[k]), src, tuple(zg))
        if k in keys else keys.__setitem__(k, zg)  # remember the first zip_keys group this key was seen in
        for zg, src in zip_keys.items()
        for k in zg
    )

    # ensure that no zip_keys key is also an extend_keys
    errors.extend(
        "  - a key cannot be defined in both extend_keys and zip_keys:\n"
        "      (src:{}) extend_keys={!r}\n"
        "      (src:{}) zip_keys={}".format(extend_keys[k], k, src, tuple(zg))
        for zg, src in zip_keys.items()
        for k in zg
        if k in extend_keys
    )

    # extend_keys: keys are updated/extended based on whether prior value was a dict/set
    for src, spec in specs.items():
        for key in set(spec).intersection(extend_keys) - {"zip_keys", "extend_keys"}:
            if isinstance(spec[key], dict):
                prior = combined.setdefault(key, {})
                if isinstance(prior, dict):
                    prior.update(spec[key])
                else:
                    logshim("(src:{}) {!r} clobbering a {} with dict".format(src, key, type(prior).__name__))
                    combined[key] = copy(spec[key])
            else:
                prior = combined.setdefault(key, set())
                if isinstance(prior, set):
                    prior.update(ensure_list(spec[key]))
                else:
                    logshim("(src:{}) {!r} clobbering a {} with set".format(src, key, type(prior).__name__))
                    combined[key] = set(ensure_list(spec[key]))

    # clobber keys: keys that override prior values
    for src, spec in specs.items():
        logshim("(src:{}) adding variants".format(src))

        for key in set(spec).difference(extend_keys) - {"zip_keys", "extend_keys"}:
            zg = keys.get(key, {key})
            sizes = {
                k: len(ensure_list(spec.get(k, combined.get(k)), include_dict=False))
                for k in zg
                if k in spec or k in combined
            }

            # clobbering occurs if all fields are the same size, this covers two cases:
            #   1) the new field has the same length as the old field it is clobbering
            #   2) all fields in a zip_group are defined in this source and all have the same length
            if len(set(sizes.values())) == 1:
                combined[key] = ensure_list(spec[key], include_dict=False)
                continue

            # all of the fields in this zip_group are defined in this source (so clobbering was attempted)
            # but the field lengths did not match
            if all(k in spec for k in zg):
                errors.append(
                    "  - (src:{}) key fields within a zip_keys group {} must "
                    "specify the same number of values:\n".format(src, tuple(zg)) +
                    "\n".join("      {!r}: {}".format(k, v) for k, v in sizes.items())
                )
                continue

            # since clobbering was not successful assume we are looking at a filter instead, ensuring
            # that all of the values defined in our filter are valid

            missing = set(ensure_list(spec[key], include_dict=False)).difference(combined.get(key, []))
            if missing:
                errors.append(
                    "  - (src:{}) {}filtering for unimplemented subspace(s) {}".format(
                        src,
                        "did not fully implement all fields for zip_keys group {} or ".format(tuple(zg))
                        if len(zg) > 1
                        else "",
                        tuple(missing),
                    )
                )

    # check if every zip field is defined
    errors.extend(
        "  - (src:{}) key {!r} in zip_keys group {} is not defined in the combined spec".format(src, k, tuple(zg))
        for zg, src in zip_keys.items()
        for k in zg.difference(combined)
    )

    errors = "\n".join(filter(None, errors))
    if errors:
        raise ValueError("Variant configuration errors:\n{}".format(errors))

    return combined


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


def _get_zip_keys(spec):
    """
    Extracts 'zip_keys' from `spec` and standardizes value into a list of zip_groups
    (tuples of keys (string)).

    :param spec: Variants specification
    :type spec: dict
    :return: Standardized 'zip_keys' value
    :rtype: set
    :raise ValueError: 'zip_keys' cannot be standardized
    """
    zip_keys = spec.get('zip_keys')
    if not zip_keys:
        return set()
    elif islist(zip_keys, uniform=lambda e: isinstance(e, string_types)):
        return {frozenset(zip_keys)}
    elif islist(zip_keys, uniform=lambda e: islist(e, uniform=lambda e: isinstance(e, string_types))):
        return {frozenset(zg) for zg in zip_keys}

    raise ValueError("'zip_keys' expect list of string or list of lists of string")


def _get_extend_keys(spec, include_defaults=True):
    """
    Extracts 'extend_keys' from `spec`.

    :param spec: Variants specification
    :type spec: dict
    :param include_defaults: Whether to include default 'extend_keys'
    :type include_defaults: bool, optional
    :return: Standardized 'extend_keys' value
    :rtype: set
    """
    extend_keys = {'zip_keys', 'extend_keys'}
    if include_defaults:
        extend_keys.update(DEFAULT_VARIANTS['extend_keys'])
    return extend_keys.union(ensure_list(spec.get('extend_keys')))


def _get_passthru_keys(spec, zip_keys=None, extend_keys=None):
    """
    Keys in `spec` that are not exploded and are simply carried over from the `spec`
    into the variants without modification.

    :param spec: Variants specification
    :type spec: dict
    :param zip_keys: Keys defined as 'zip_keys' (see :func:`_get_zip_keys`)
    :type zip_keys: set, optional
    :param extend_keys: Keys defined as 'extend_keys' (see :func:`_get_extend_keys`)
    :type extend_keys: set, optional
    :return: Passthru (not exploded) keys defined in `spec`
    :rtype: set
    """
    if zip_keys is None:
        zip_keys = _get_zip_keys(spec)
    if extend_keys is None:
        extend_keys = _get_extend_keys(spec)
    passthru_keys = {'replacements', 'extend_keys', 'zip_keys'}
    return passthru_keys.union(extend_keys).difference(*zip_keys).intersection(spec)


def _get_explode_keys(spec, passthru_keys=None, zip_keys=None, extend_keys=None):
    """
    Keys in `spec` that are that are exploding into the variants.

    :param spec: Variants specification
    :type spec: dict
    :param passthru_keys: Passthru (not exploded) keys (see :func:`_get_passthru_keys`)
    :type passthru_keys: set, optional
    :param zip_keys: Keys defined as 'zip_keys' (see :func:`_get_zip_keys`) and is passed
                     to :func:`_get_passthru_keys` if `passthru_keys` is undefined
    :type zip_keys: set, optional
    :param extend_keys: Keys defined as 'extend_keys' (see :func:`_get_extend_keys`) and
                        is passed to :func:`_get_passthru_keys` if `passthru_keys` is
                        undefined
    :type extend_keys: set, optional
    :return: Exploded keys defined in `spec`
    :rtype: set
    """
    if passthru_keys is None:
        passthru_keys = _get_passthru_keys(spec, zip_keys, extend_keys)
    return set(spec).difference(passthru_keys)


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


def explode_variants(spec):
    """
    Helper function to explode spec into all of the variants.

    .. code-block:: python
        >>> spec = {
            # normal expansions
            "foo": [2.7, 3.7, 3.8],
            # zip_keys are the values that need to be exploded as a set
            "zip_keys": [["bar", "baz"], ["qux", "quux", "quuz"]],
            "bar": [1, 2, 3],
            "baz": [2, 4, 6],
            "qux": [4, 5],
            "quux": [8, 10],
            "quuz": [12, 15],
            # extend_keys are those values which we do not explode
            "extend_keys": ["corge"],
            "corge": 42,
        }
        >>> explode_variants(spec)
        [{
            "foo": 2.7,
            "bar": 1, "baz": 2,
            "qux": 4, "quux": 8, "quuz": 12,
            "corge": 42,
            "zip_keys": ..., "extend_keys": ...,
        },
        {
            "foo": 2.7,
            "bar": 1, "baz": 2,
            "qux": 5, "quux": 10, "quuz": 15,
            "corge": 42,
            ...,
        }, ...]

    :param spec: Specification to explode
    :type spec: `dict`
    :return: Exploded specification
    :rtype: `list` of `dict`
    """
    zip_keys = _get_zip_keys(spec)

    # key/values from spec that do not explode
    passthru_keys = _get_passthru_keys(spec, zip_keys)
    passthru = {k: spec[k] for k in passthru_keys if spec[k] or spec[k] == ""}

    # key/values from spec that do explode
    explode_keys = _get_explode_keys(spec, passthru_keys)
    explode = {
        (k,): [ensure_list(v, include_dict=False) for v in ensure_list(spec[k])]
        for k in explode_keys.difference(*zip_keys)
    }
    explode.update({zg: list(zip(*(ensure_list(spec[k]) for k in zg))) for zg in zip_keys})
    trim_empty_keys(explode)

    # Cartesian Product of dict of lists
    # http://stackoverflow.com/a/5228294/1170370
    # dict.keys() and dict.values() orders are the same even prior to Python 3.6
    variants = []
    for values in product(*explode.values()):
        variant = {k: copy(v) for k, v in passthru.items()}
        variant.update({k: v for zg, zv in zip(explode, values) for k, v in zip(zg, zv)})
        variants.append(variant)
    return variants


# temporary backport for other places in cond_build
dict_of_lists_to_list_of_dicts = explode_variants


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
    files = find_config_files(recipedir_or_metadata, config)

    specs = OrderedDict(internal_defaults=get_default_variant(config))

    for f in files:
        specs[f] = parse_config_file(f, config)

    # this is the override of the variants from files and args with values from CLI or env vars
    if hasattr(config, 'variant') and config.variant:
        specs['config.variant'] = config.variant
    if variants:
        specs['argument_variants'] = variants

    return combine_specs(specs, config.verbose), specs


def filter_combined_spec_to_used_keys(combined_spec, specs):
    extend_keys = _get_extend_keys(combined_spec)

    # delete the default specs, so that they don't unnecessarily limit the matrix
    specs = specs.copy()
    del specs['internal_defaults']

    # TODO: act here?
    combined_spec = explode_variants(combined_spec)
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
def find_used_variables_in_text(variant, recipe_text, selectors_only=False):
    used_variables = set()
    recipe_lines = recipe_text.splitlines()
    for v in variant:
        all_res = []
        compiler_match = re.match(r'(.*?)_compiler(_version)?$', v)
        if compiler_match and not selectors_only:
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
        conditional_regex = r"(?:^|[^\{])\{%\s*(?:el)?if\s*.*" + v_regex + r"\s*(?:[^%]*?)?%\}"
        # plain req name, no version spec.  Look for end of line after name, or comment or selector
        requirement_regex = r"^\s+\-\s+%s\s*(?:\s[\[#]|$)" % v_req_regex
        if selectors_only:
            all_res.insert(0, selector_regex)
        else:
            all_res.extend([variant_regex, requirement_regex, conditional_regex])
        # consolidate all re's into one big one for speedup
        all_res = r"|".join(all_res)
        if any(re.search(all_res, line) for line in variant_lines):
            used_variables.add(v)
            if v in ('c_compiler', 'cxx_compiler'):
                if 'CONDA_BUILD_SYSROOT' in variant:
                    used_variables.add('CONDA_BUILD_SYSROOT')
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
