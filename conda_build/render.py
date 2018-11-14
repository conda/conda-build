# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

from collections import OrderedDict, defaultdict
from locale import getpreferredencoding
import json
import os
from os.path import isdir, isfile, abspath
import random
import re
import shutil
import string
import subprocess
import sys
import tarfile
import tempfile

import yaml

from .conda_interface import (PY3, UnsatisfiableError, ProgressiveFetchExtract,
                              TemporaryDirectory)
from .conda_interface import execute_actions
from .conda_interface import pkgs_dirs
from .conda_interface import conda_43
from .conda_interface import specs_from_url
from .conda_interface import memoized

from conda_build import exceptions, utils, environ
from conda_build.metadata import MetaData, combine_top_level_metadata_with_output
import conda_build.source as source
from conda_build.variants import (get_package_variants, list_of_dicts_to_dict_of_lists,
                                  filter_by_key_value)
from conda_build.exceptions import DependencyNeedsBuildingError
from conda_build.index import get_build_index
# from conda_build.jinja_context import pin_subpackage_against_outputs

try:
    from conda.base.constants import CONDA_TARBALL_EXTENSIONS
except Exception:
    from conda.base.constants import CONDA_TARBALL_EXTENSION
    CONDA_TARBALL_EXTENSIONS = (CONDA_TARBALL_EXTENSION,)


def odict_representer(dumper, data):
    return dumper.represent_dict(data.items())


yaml.add_representer(set, yaml.representer.SafeRepresenter.represent_list)
yaml.add_representer(tuple, yaml.representer.SafeRepresenter.represent_list)
yaml.add_representer(OrderedDict, odict_representer)


def bldpkg_path(m):
    '''
    Returns path to built package's tarball given its ``Metadata``.
    '''
    subdir = 'noarch' if m.noarch or m.noarch_python else m.config.host_subdir

    if not hasattr(m, 'type') or m.type == "conda":
        path = os.path.join(m.config.output_folder, subdir, '%s%s' % (m.dist(), CONDA_TARBALL_EXTENSIONS[0]))
    else:
        path = '{} file for {} in: {}'.format(m.type, m.name(), os.path.join(m.config.output_folder, subdir))
    return path


def actions_to_pins(actions):
    specs = []
    if conda_43:
        spec_name = lambda x: x.dist_name
    else:
        spec_name = lambda x: x
    if 'LINK' in actions:
        specs = [' '.join(spec_name(spec).split()[0].rsplit('-', 2)) for spec in actions['LINK']]
    return specs


def get_env_dependencies(m, env, variant, exclude_pattern=None,
                         permit_unsatisfiable_variants=False,
                         merge_build_host_on_same_platform=True):
    dash_or_under = re.compile("[-_]")
    specs = m.get_depends_top_and_out(env)
    # replace x.x with our variant's numpy version, or else conda tries to literally go get x.x
    if env in ('build', 'host'):
        no_xx_specs = []
        for spec in specs:
            if ' x.x' in spec:
                pkg_name = spec.split()[0]
                no_xx_specs.append(' '.join((pkg_name, variant.get(pkg_name, ""))))
            else:
                no_xx_specs.append(spec)
        specs = no_xx_specs
    subpackages = []
    dependencies = []
    pass_through_deps = []
    # ones that get filtered from actual versioning, to exclude them from the hash calculation
    for spec in specs:
        if not exclude_pattern or not exclude_pattern.match(spec):
            is_subpackage = False
            spec_name = spec.split()[0]
            for entry in m.get_section('outputs'):
                name = entry.get('name')
                if name == spec_name:
                    subpackages.append(' '.join((name, m.version())))
                    is_subpackage = True
            if not is_subpackage:
                dependencies.append(spec)
            # fill in variant version iff no version at all is provided
            for key, value in variant.items():
                # for sake of comparison, ignore dashes and underscores
                if (dash_or_under.sub("", key) == dash_or_under.sub("", spec_name) and
                        not re.search(r'%s\s+[0-9a-zA-Z\_\.\<\>\=\*]' % spec_name, spec)):
                    dependencies.append(" ".join((spec_name, value)))
        elif exclude_pattern.match(spec):
            pass_through_deps.append(spec)
    random_string = ''.join(random.choice(string.ascii_uppercase + string.digits)
                            for _ in range(10))
    dependencies = set(dependencies)
    unsat = None
    with TemporaryDirectory(prefix="_", suffix=random_string) as tmpdir:
        try:
            actions = environ.get_install_actions(tmpdir, tuple(dependencies), env,
                                                  subdir=getattr(m.config, '{}_subdir'.format(env)),
                                                  debug=m.config.debug,
                                                  verbose=m.config.verbose,
                                                  locking=m.config.locking,
                                                  bldpkgs_dirs=tuple(m.config.bldpkgs_dirs),
                                                  timeout=m.config.timeout,
                                                  disable_pip=m.config.disable_pip,
                                                  max_env_retry=m.config.max_env_retry,
                                                  output_folder=m.config.output_folder,
                                                  channel_urls=tuple(m.config.channel_urls))
        except (UnsatisfiableError, DependencyNeedsBuildingError) as e:
            # we'll get here if the environment is unsatisfiable
            if hasattr(e, 'packages'):
                unsat = ', '.join(e.packages)
            else:
                unsat = e.message
            if permit_unsatisfiable_variants:
                actions = {}
            else:
                raise

    specs = actions_to_pins(actions)
    return (utils.ensure_list((specs + subpackages + pass_through_deps) or
                  m.meta.get('requirements', {}).get(env, [])),
            actions, unsat)


def strip_channel(spec_str):
    if hasattr(spec_str, 'decode'):
        spec_str = spec_str.decode()
    if ':' in spec_str:
        spec_str = spec_str.split("::")[-1]
    return spec_str


def get_pin_from_build(m, dep, build_dep_versions):
    dep_name = dep.split()[0]
    pin = None
    version = build_dep_versions.get(dep_name) or m.config.variant.get(dep_name)
    if (version and dep_name in m.config.variant.get('pin_run_as_build', {}) and
            not (dep_name == 'python' and (m.noarch or m.noarch_python)) and
            dep_name in build_dep_versions):
        pin_cfg = m.config.variant['pin_run_as_build'][dep_name]
        if isinstance(pin_cfg, str):
            # if pin arg is a single 'x.x', use the same value for min and max
            pin_cfg = dict(min_pin=pin_cfg, max_pin=pin_cfg)
        pin = utils.apply_pin_expressions(version.split()[0], **pin_cfg)
    elif dep.startswith('numpy') and 'x.x' in dep:
        if not build_dep_versions.get(dep_name):
            raise ValueError("numpy x.x specified, but numpy not in build requirements.")
        pin = utils.apply_pin_expressions(version.split()[0], min_pin='x.x', max_pin='x.x')
    if pin:
        dep = " ".join((dep_name, pin))
    return dep


def _filter_run_exports(specs, ignore_list):
    filtered_specs = {}
    for agent, specs_list in specs.items():
        for spec in specs_list:
            if hasattr(spec, 'decode'):
                spec = spec.decode()
            if not any((ignore_spec == '*' or spec == ignore_spec or
                        spec.startswith(ignore_spec + ' ')) for ignore_spec in ignore_list):
                filtered_specs[agent] = filtered_specs.get(agent, []) + [spec]
    return filtered_specs


def find_pkg_dir_or_file_in_pkgs_dirs(pkg_dist, m, files_only=False):
    _pkgs_dirs = pkgs_dirs + list(m.config.bldpkgs_dirs)
    pkg_loc = None
    for pkgs_dir in _pkgs_dirs:
        pkg_dir = os.path.join(pkgs_dir, pkg_dist)
        pkg_file = os.path.join(pkgs_dir, pkg_dist + CONDA_TARBALL_EXTENSIONS[0])
        if not files_only and os.path.isdir(pkg_dir):
            pkg_loc = pkg_dir
            break
        elif os.path.isfile(pkg_file):
            pkg_loc = pkg_file
            break
        elif files_only and os.path.isdir(pkg_dir):
            pkg_loc = pkg_file
            # create the tarball on demand.  This is so that testing on archives works.
            with tarfile.open(pkg_file, 'w:bz2') as archive:
                for entry in os.listdir(pkg_dir):
                    archive.add(os.path.join(pkg_dir, entry), arcname=entry)
            pkg_subdir = os.path.join(m.config.croot, m.config.host_subdir)
            pkg_loc = os.path.join(pkg_subdir, os.path.basename(pkg_file))
            shutil.move(pkg_file, pkg_loc)
    return pkg_loc


@memoized
def _read_specs_from_package(pkg_loc, pkg_dist):
    specs = {}
    if pkg_loc and os.path.isdir(pkg_loc):
        downstream_file = os.path.join(pkg_loc, 'info/run_exports')
        if os.path.isfile(downstream_file):
            with open(downstream_file) as f:
                specs = {'weak': [spec.rstrip() for spec in f.readlines()]}
        # a later attempt: record more info in the yaml file, to support "strong" run exports
        elif os.path.isfile(downstream_file + '.yaml'):
            with open(downstream_file + '.yaml') as f:
                specs = yaml.safe_load(f)
        elif os.path.isfile(downstream_file + '.json'):
            with open(downstream_file + '.json') as f:
                specs = json.load(f)
    if not specs and os.path.isfile(pkg_loc):
        # switching to json for consistency in conda-build 4
        specs_yaml = utils.package_has_file(pkg_loc, 'info/run_exports.yaml')
        specs_json = utils.package_has_file(pkg_loc, 'info/run_exports.json')
        if hasattr(specs_json, "decode"):
            specs_json = specs_json.decode("utf-8")

        if specs_json:
            specs = json.loads(specs_json)
        elif specs_yaml:
            specs = yaml.safe_load(specs_yaml)
        else:
            legacy_specs = utils.package_has_file(pkg_loc, 'info/run_exports')
            # exclude packages pinning themselves (makes no sense)
            if legacy_specs:
                weak_specs = set()
                if hasattr(pkg_dist, "decode"):
                    pkg_dist = pkg_dist.decode("utf-8")
                for spec in legacy_specs.splitlines():
                    if hasattr(spec, "decode"):
                        spec = spec.decode("utf-8")
                    if not spec.startswith(pkg_dist.rsplit('-', 2)[0]):
                        weak_specs.add(spec.rstrip())
                specs = {'weak': sorted(list(weak_specs))}
    return specs


def execute_download_actions(m, actions, env, package_subset=None, require_files=False):
    index, index_ts = get_build_index(getattr(m.config, '{}_subdir'.format(env)),
                                      bldpkgs_dir=m.config.bldpkgs_dir,
                                      output_folder=m.config.output_folder,
                                      channel_urls=m.config.channel_urls,
                                      debug=m.config.debug, verbose=m.config.verbose,
                                      locking=m.config.locking, timeout=m.config.timeout)

    # this should be just downloading packages.  We don't need to extract them -
    #    we read contents directly
    if 'FETCH' in actions or 'EXTRACT' in actions:
        # this is to force the download
        execute_actions(actions, index, verbose=m.config.debug)

    pkg_files = {}

    packages = actions.get('LINK', [])
    package_subset = utils.ensure_list(package_subset)
    selected_packages = set()
    if package_subset:
        for pkg in package_subset:
            if hasattr(pkg, 'name'):
                if pkg in packages:
                    selected_packages.add(pkg)
            else:
                pkg_name = pkg.split()[0]
                for link_pkg in packages:
                    if pkg_name == link_pkg.name:
                        selected_packages.add(link_pkg)
                        break
        packages = selected_packages

    for pkg in packages:
        if hasattr(pkg, 'dist_name'):
            pkg_dist = pkg.dist_name
        else:
            pkg = strip_channel(pkg)
            pkg_dist = pkg.split(' ')[0]
        pkg_loc = find_pkg_dir_or_file_in_pkgs_dirs(pkg_dist, m, files_only=require_files)

        # ran through all pkgs_dirs, and did not find package or folder.  Download it.
        # TODO: this is a vile hack reaching into conda's internals. Replace with
        #    proper conda API when available.
        if not pkg_loc and conda_43:
            try:
                pkg_record = [_ for _ in index if _.dist_name == pkg_dist][0]
                # the conda 4.4 API uses a single `link_prefs` kwarg
                # whereas conda 4.3 used `index` and `link_dists` kwargs
                pfe = ProgressiveFetchExtract(link_prefs=(index[pkg_record],))
            except TypeError:
                # TypeError: __init__() got an unexpected keyword argument 'link_prefs'
                pfe = ProgressiveFetchExtract(link_dists=[pkg], index=index)
            with utils.LoggingContext():
                pfe.execute()
            for pkg_dir in pkgs_dirs:
                _loc = os.path.join(pkg_dir, index[pkg].fn)
                if os.path.isfile(_loc):
                    pkg_loc = _loc
                    break
        pkg_files[pkg] = pkg_loc, pkg_dist

    return pkg_files


def get_upstream_pins(m, actions, env):
    """Download packages from specs, then inspect each downloaded package for additional
    downstream dependency specs.  Return these additional specs."""

    env_specs = m.meta.get('requirements', {}).get(env, [])
    explicit_specs = [req.split(' ')[0] for req in env_specs] if env_specs else []
    linked_packages = actions.get('LINK', [])
    linked_packages = [pkg for pkg in linked_packages if pkg.name in explicit_specs]

    pkg_locs_and_dists = execute_download_actions(m, actions, env=env,
                                                  package_subset=linked_packages)

    ignore_list = utils.ensure_list(m.get_value('build/ignore_run_exports'))

    additional_specs = {}
    for (loc, dist) in pkg_locs_and_dists.values():
        specs = _read_specs_from_package(loc, dist)
        additional_specs = utils.merge_dicts_of_lists(additional_specs,
                                                      _filter_run_exports(specs, ignore_list))
    return additional_specs


def _read_upstream_pin_files(m, env, permit_unsatisfiable_variants, exclude_pattern):
    deps, actions, unsat = get_env_dependencies(m, env, m.config.variant,
                                exclude_pattern,
                                permit_unsatisfiable_variants=permit_unsatisfiable_variants)
    # extend host deps with strong build run exports.  This is important for things like
    #    vc feature activation to work correctly in the host env.
    extra_run_specs = get_upstream_pins(m, actions, env)
    return list(set(deps)) or m.meta.get('requirements', {}).get(env, []), unsat, extra_run_specs


def add_upstream_pins(m, permit_unsatisfiable_variants, exclude_pattern):
    """Applies run_exports from any build deps to host and run sections"""
    # if we have host deps, they're more important than the build deps.
    requirements = m.meta.get('requirements', {})
    build_deps, build_unsat, extra_run_specs_from_build = _read_upstream_pin_files(m, 'build',
                                                    permit_unsatisfiable_variants, exclude_pattern)

    # is there a 'host' section?
    if m.is_cross:
        # this must come before we read upstream pins, because it will enforce things
        #      like vc version from the compiler.
        host_reqs = utils.ensure_list(m.get_value('requirements/host'))
        # ensure host_reqs is present, so in-place modification below is actually in-place
        requirements = m.meta.setdefault('requirements', {})
        requirements['host'] = host_reqs

        if not host_reqs:
            matching_output = [out for out in m.meta.get('outputs', []) if
                               out.get('name') == m.name()]
            if matching_output:
                requirements = utils.expand_reqs(matching_output[0].get('requirements', {}))
                matching_output[0]['requirements'] = requirements
                host_reqs = requirements.setdefault('host', [])
        # in-place modification of above thingie
        host_reqs.extend(extra_run_specs_from_build.get('strong', []))

        host_deps, host_unsat, extra_run_specs_from_host = _read_upstream_pin_files(m, 'host',
                                                    permit_unsatisfiable_variants, exclude_pattern)
        extra_run_specs = set(extra_run_specs_from_host.get('strong', []) +
                              extra_run_specs_from_host.get('weak', []) +
                              extra_run_specs_from_build.get('strong', []))
    else:
        host_deps = []
        host_unsat = []
        extra_run_specs = set(extra_run_specs_from_build.get('strong', []))
        if not m.uses_new_style_compiler_activation and not m.build_is_host:
            extra_run_specs.update(extra_run_specs_from_build.get('weak', []))
        else:
            host_deps = set(extra_run_specs_from_build.get('strong', []))

    run_deps = extra_run_specs | set(utils.ensure_list(requirements.get('run')))

    for section, deps in (('build', build_deps), ('host', host_deps), ('run', run_deps)):
        if deps:
            requirements[section] = list(deps)

    m.meta['requirements'] = requirements
    return build_unsat, host_unsat


def _simplify_to_exact_constraints(metadata):
    """
    For metapackages that are pinned exactly, we want to bypass all dependencies that may
    be less exact.
    """
    requirements = metadata.meta.get('requirements', {})
    # collect deps on a per-section basis
    for section in 'build', 'host', 'run':
        deps = utils.ensure_list(requirements.get(section, []))
        deps_dict = defaultdict(list)
        for dep in deps:
            spec_parts = utils.ensure_valid_spec(dep).split()
            name = spec_parts[0]
            if len(spec_parts) > 1:
                deps_dict[name].append(spec_parts[1:])
            else:
                deps_dict[name].append([])

        deps_list = []
        for name, values in deps_dict.items():
            exact_pins = [dep for dep in values if len(dep) > 1]
            if len(values) == 1 and not any(values):
                deps_list.append(name)
            elif exact_pins:
                if not all(pin == exact_pins[0] for pin in exact_pins):
                    raise ValueError("Conflicting exact pins: {}".format(exact_pins))
                else:
                    deps_list.append(' '.join([name] + exact_pins[0]))
            else:
                deps_list.extend(' '.join([name] + dep) for dep in values if dep)
        if section in requirements and deps_list:
            requirements[section] = deps_list
    metadata.meta['requirements'] = requirements


def finalize_metadata(m, permit_unsatisfiable_variants=False):
    """Fully render a recipe.  Fill in versions for build/host dependencies."""
    if m.skip():
        rendered_metadata = m.copy()
        rendered_metadata.final = True
    else:
        exclude_pattern = None
        excludes = set(m.config.variant.get('ignore_version', []))

        for key in m.config.variant.get('pin_run_as_build', {}).keys():
            if key in excludes:
                excludes.remove(key)

        output_excludes = set()
        if hasattr(m, 'other_outputs'):
            output_excludes = set(name for (name, variant) in m.other_outputs.keys())

        if excludes or output_excludes:
            exclude_pattern = re.compile(r'|'.join(r'(?:^{}(?:\s|$|\Z))'.format(exc)
                                            for exc in excludes | output_excludes))

        parent_recipe = m.meta.get('extra', {}).get('parent_recipe', {})

        # extract the topmost section where variables are defined, and put it on top of the
        #     requirements for a particular output
        # Re-parse the output from the original recipe, so that we re-consider any jinja2 stuff
        output = m.get_rendered_output(m.name())
        rendered_metadata = m.get_output_metadata(output)

        if output:
            if 'package' in output or 'name' not in output:
                # it's just a top-level recipe
                output = {'name': m.name()}

            if not parent_recipe or parent_recipe['name'] == m.name():
                combine_top_level_metadata_with_output(rendered_metadata, output)
            requirements = utils.expand_reqs(output.get('requirements', {}))
            rendered_metadata.meta['requirements'] = requirements

        if rendered_metadata.meta.get('requirements'):
            utils.insert_variant_versions(rendered_metadata.meta['requirements'],
                                          rendered_metadata.config.variant, 'build')
            utils.insert_variant_versions(rendered_metadata.meta['requirements'],
                                        rendered_metadata.config.variant, 'host')

        build_unsat, host_unsat = add_upstream_pins(rendered_metadata,
                                                    permit_unsatisfiable_variants,
                                                    exclude_pattern)
        # getting this AFTER add_upstream_pins is important, because that function adds deps
        #     to the metadata.
        requirements = rendered_metadata.meta.get('requirements', {})

        # here's where we pin run dependencies to their build time versions.  This happens based
        #     on the keys in the 'pin_run_as_build' key in the variant, which is a list of package
        #     names to have this behavior.
        if output_excludes:
            exclude_pattern = re.compile(r'|'.join(r'(?:^{}(?:\s|$|\Z))'.format(exc)
                                            for exc in output_excludes))
        pinning_env = 'host' if rendered_metadata.is_cross else 'build'

        build_reqs = requirements.get(pinning_env, [])
        # if python is in the build specs, but doesn't have a specific associated
        #    version, make sure to add one
        if build_reqs and 'python' in build_reqs:
            build_reqs.append('python {}'.format(m.config.variant['python']))
            rendered_metadata.meta['requirements'][pinning_env] = build_reqs

        full_build_deps, _, _ = get_env_dependencies(rendered_metadata, pinning_env,
                                        rendered_metadata.config.variant,
                                        exclude_pattern=exclude_pattern,
                                        permit_unsatisfiable_variants=permit_unsatisfiable_variants)
        full_build_dep_versions = {dep.split()[0]: " ".join(dep.split()[1:])
                                   for dep in full_build_deps}

        if isfile(m.requirements_path) and not requirements.get('run'):
            requirements['run'] = specs_from_url(m.requirements_path)
        run_deps = requirements.get('run', [])

        versioned_run_deps = [get_pin_from_build(rendered_metadata, dep, full_build_dep_versions)
                            for dep in run_deps]
        versioned_run_deps = [utils.ensure_valid_spec(spec, warn=True)
                              for spec in versioned_run_deps]
        requirements[pinning_env] = full_build_deps
        requirements['run'] = versioned_run_deps

        rendered_metadata.meta['requirements'] = requirements

        # append other requirements, such as python.app, appropriately
        rendered_metadata.append_requirements()

        if rendered_metadata.pin_depends == 'strict':
            rendered_metadata.meta['requirements']['run'] = environ.get_pinned_deps(
                rendered_metadata, 'run')
        test_deps = rendered_metadata.get_value('test/requires')
        if test_deps:
            versioned_test_deps = list({get_pin_from_build(m, dep, full_build_dep_versions)
                                        for dep in test_deps})
            versioned_test_deps = [utils.ensure_valid_spec(spec, warn=True)
                                for spec in versioned_test_deps]
            rendered_metadata.meta['test']['requires'] = versioned_test_deps
        extra = rendered_metadata.meta.get('extra', {})
        extra['copy_test_source_files'] = m.config.copy_test_source_files
        rendered_metadata.meta['extra'] = extra

        # if source/path is relative, then the output package makes no sense at all.  The next
        #   best thing is to hard-code the absolute path.  This probably won't exist on any
        #   system other than the original build machine, but at least it will work there.
        if m.meta.get('source'):
            if 'path' in m.meta['source']:
                source_path = m.meta['source']['path']
                os.path.expanduser(source_path)
                if not os.path.isabs(source_path):
                    rendered_metadata.meta['source']['path'] = os.path.normpath(
                        os.path.join(m.path, source_path))
                elif ('git_url' in m.meta['source'] and not (
                        # absolute paths are not relative paths
                        os.path.isabs(m.meta['source']['git_url']) or
                        # real urls are not relative paths
                        ":" in m.meta['source']['git_url'])):
                    rendered_metadata.meta['source']['git_url'] = os.path.normpath(
                        os.path.join(m.path, m.meta['source']['git_url']))

        if not rendered_metadata.meta.get('build'):
            rendered_metadata.meta['build'] = {}

        _simplify_to_exact_constraints(rendered_metadata)

        if build_unsat or host_unsat:
            rendered_metadata.final = False
            log = utils.get_logger(__name__)
            log.warn("Returning non-final recipe for {}; one or more dependencies "
                    "was unsatisfiable:".format(rendered_metadata.dist()))
            if build_unsat:
                log.warn("Build: {}".format(build_unsat))
            if host_unsat:
                log.warn("Host: {}".format(host_unsat))
        else:
            rendered_metadata.final = True
    return rendered_metadata


def try_download(metadata, no_download_source, raise_error=False):
    if not metadata.source_provided and not no_download_source:
        # this try/catch is for when the tool to download source is actually in
        #    meta.yaml, and not previously installed in builder env.
        try:
            source.provide(metadata)
        except subprocess.CalledProcessError as error:
            print("Warning: failed to download source.  If building, will try "
                "again after downloading recipe dependencies.")
            print("Error was: ")
            print(error)

    if not metadata.source_provided:
        if no_download_source:
            raise ValueError("no_download_source specified, but can't fully render recipe without"
                             " downloading source.  Please fix the recipe, or don't use "
                             "no_download_source.")
        elif raise_error:
            raise RuntimeError("Failed to download or patch source. Please see build log for info.")


def reparse(metadata):
    """Some things need to be parsed again after the build environment has been created
    and activated."""
    metadata.final = False
    sys.path.insert(0, metadata.config.build_prefix)
    sys.path.insert(0, metadata.config.host_prefix)
    py_ver = '.'.join(metadata.config.variant['python'].split('.')[:2])
    sys.path.insert(0, utils.get_site_packages(metadata.config.host_prefix, py_ver))
    metadata.parse_until_resolved()
    metadata = finalize_metadata(metadata)
    return metadata


def distribute_variants(metadata, variants, permit_unsatisfiable_variants=False,
                        allow_no_other_outputs=False, bypass_env_check=False):
    rendered_metadata = {}
    need_source_download = True

    # don't bother distributing python if it's a noarch package
    if metadata.noarch or metadata.noarch_python:
        variants = filter_by_key_value(variants, 'python', variants[0]['python'],
                                       'noarch_reduction')

    # store these for reference later
    metadata.config.variants = variants
    # These are always the full set.  just 'variants' is the one that gets
    #     used mostly, and can be reduced
    metadata.config.input_variants = variants

    recipe_requirements = metadata.extract_requirements_text()
    recipe_package_and_build_text = metadata.extract_package_and_build_text()
    recipe_text = recipe_package_and_build_text + recipe_requirements
    if PY3 and hasattr(recipe_text, 'decode'):
        recipe_text = recipe_text.decode()
    elif not PY3 and hasattr(recipe_text, 'encode'):
        recipe_text = recipe_text.encode()

    metadata.config.variant = variants[0]
    used_variables = metadata.get_used_loop_vars(force_global=False)
    top_loop = metadata.get_reduced_variant_set(used_variables)

    for variant in top_loop:
        mv = metadata.copy()
        mv.config.variant = variant

        pin_run_as_build = variant.get('pin_run_as_build', {})
        if mv.numpy_xx and 'numpy' not in pin_run_as_build:
            pin_run_as_build['numpy'] = {'min_pin': 'x.x', 'max_pin': 'x.x'}

        conform_dict = {}
        for key in used_variables:
            # We use this variant in the top-level recipe.
            # constrain the stored variants to only this version in the output
            #     variant mapping
            conform_dict[key] = variant[key]

        for key, values in conform_dict.items():
            mv.config.variants = (filter_by_key_value(mv.config.variants, key, values,
                                                      'distribute_variants_reduction') or
                                  mv.config.variants)

        pin_run_as_build = variant.get('pin_run_as_build', {})
        if mv.numpy_xx and 'numpy' not in pin_run_as_build:
            pin_run_as_build['numpy'] = {'min_pin': 'x.x', 'max_pin': 'x.x'}

        numpy_pinned_variants = []
        for _variant in mv.config.variants:
            _variant['pin_run_as_build'] = pin_run_as_build
            numpy_pinned_variants.append(_variant)
        mv.config.variants = numpy_pinned_variants

        mv.config.squished_variants = list_of_dicts_to_dict_of_lists(mv.config.variants)

        if mv.needs_source_for_render and mv.variant_in_source:
            mv.parse_again()
            utils.rm_rf(mv.config.work_dir)
            source.provide(mv)
            mv.parse_again()

        try:
            mv.parse_until_resolved(allow_no_other_outputs=allow_no_other_outputs,
                                    bypass_env_check=bypass_env_check)
        except SystemExit:
            pass
        need_source_download = (not mv.needs_source_for_render or not mv.source_provided)

        rendered_metadata[(mv.dist(),
                           mv.config.variant.get('target_platform', mv.config.subdir),
                           tuple((var, mv.config.variant.get(var))
                                 for var in mv.get_used_vars()))] = \
                                    (mv, need_source_download, None)
    # list of tuples.
    # each tuple item is a tuple of 3 items:
    #    metadata, need_download, need_reparse_in_env
    return list(rendered_metadata.values())


def expand_outputs(metadata_tuples):
    """Obtain all metadata objects for all outputs from recipe.  Useful for outputting paths."""
    expanded_outputs = OrderedDict()

    for (_m, download, reparse) in metadata_tuples:
        for (output_dict, m) in _m.get_output_metadata_set(permit_unsatisfiable_variants=False):
            expanded_outputs[m.dist()] = (output_dict, m)
    return list(expanded_outputs.values())


def render_recipe(recipe_path, config, no_download_source=False, variants=None,
                  permit_unsatisfiable_variants=True, reset_build_id=True, bypass_env_check=False):
    """Returns a list of tuples, each consisting of

    (metadata-object, needs_download, needs_render_in_env)

    You get one tuple per variant.  Outputs are not factored in here (subpackages won't affect these
    results returned here.)
    """
    arg = recipe_path
    # Don't use byte literals for paths in Python 2
    if not PY3:
        arg = arg.decode(getpreferredencoding() or 'utf-8')
    if isfile(arg):
        if arg.endswith(('.tar', '.tar.gz', '.tgz', '.tar.bz2')):
            recipe_dir = tempfile.mkdtemp()
            t = tarfile.open(arg, 'r:*')
            t.extractall(path=recipe_dir)
            t.close()
            need_cleanup = True
        elif arg.endswith('.yaml'):
            recipe_dir = os.path.dirname(arg)
            need_cleanup = False
        else:
            print("Ignoring non-recipe: %s" % arg)
            return None, None
    else:
        recipe_dir = abspath(arg)
        need_cleanup = False

    if not isdir(recipe_dir):
        sys.exit("Error: no such directory: %s" % recipe_dir)

    try:
        m = MetaData(recipe_dir, config=config)
    except exceptions.YamlParsingError as e:
        sys.stderr.write(e.error_msg())
        sys.exit(1)

    rendered_metadata = {}

    # important: set build id *before* downloading source.  Otherwise source goes into a different
    #    build folder.
    if config.set_build_id:
        m.config.compute_build_id(m.name(), reset=reset_build_id)

    # this source may go into a folder that doesn't match the eventual build folder.
    #   There's no way around it AFAICT.  We must download the source to be able to render
    #   the recipe (from anything like GIT_FULL_HASH), but we can't know the final build
    #   folder until rendering is complete, because package names can have variant jinja2 in them.
    if m.needs_source_for_render and not m.source_provided:
        try_download(m, no_download_source=no_download_source)

    if m.final:
        if not hasattr(m.config, 'variants') or not m.config.variant:
            m.config.ignore_system_variants = True
            if os.path.isfile(os.path.join(m.path, 'conda_build_config.yaml')):
                m.config.variant_config_files = [os.path.join(m.path, 'conda_build_config.yaml')]
            m.config.variants = get_package_variants(m, variants=variants)
            m.config.variant = m.config.variants[0]
        rendered_metadata = [(m, False, False), ]
    else:
        # merge any passed-in variants with any files found
        variants = get_package_variants(m, variants=variants)

        # when building, we don't want to fully expand all outputs into metadata, only expand
        #    whatever variants we have (i.e. expand top-level variants, not output-only variants)
        rendered_metadata = distribute_variants(m, variants,
                                    permit_unsatisfiable_variants=permit_unsatisfiable_variants,
                                    allow_no_other_outputs=True, bypass_env_check=bypass_env_check)
    if need_cleanup:
        utils.rm_rf(recipe_dir)
    return rendered_metadata


# Keep this out of the function below so it can be imported by other modules.
FIELDS = ["package", "source", "build", "requirements", "test", "app", "outputs", "about", "extra"]


# Next bit of stuff is to support YAML output in the order we expect.
# http://stackoverflow.com/a/17310199/1170370
class _MetaYaml(dict):
    fields = FIELDS

    def to_omap(self):
        return [(field, self[field]) for field in _MetaYaml.fields if field in self]


def _represent_omap(dumper, data):
    return dumper.represent_mapping(u'tag:yaml.org,2002:map', data.to_omap())


def _unicode_representer(dumper, uni):
    node = yaml.ScalarNode(tag=u'tag:yaml.org,2002:str', value=uni)
    return node


class _IndentDumper(yaml.Dumper):
    def increase_indent(self, flow=False, indentless=False):
        return super(_IndentDumper, self).increase_indent(flow, False)

    def ignore_aliases(self, data):
        return True


yaml.add_representer(_MetaYaml, _represent_omap)
if PY3:
    yaml.add_representer(str, _unicode_representer)
    unicode = None  # silence pyflakes about unicode not existing in py3
else:
    yaml.add_representer(unicode, _unicode_representer)


def output_yaml(metadata, filename=None):
    utils.trim_empty_keys(metadata.meta)
    output = yaml.dump(_MetaYaml(metadata.meta), Dumper=_IndentDumper,
                       default_flow_style=False, indent=4)
    if filename:
        if any(sep in filename for sep in ('\\', '/')):
            try:
                os.makedirs(os.path.dirname(filename))
            except OSError:
                pass
        with open(filename, "w") as f:
            f.write(output)
        return "Wrote yaml to %s" % filename
    else:
        return output
