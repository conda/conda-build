# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

from collections import OrderedDict
from locale import getpreferredencoding
import os
from os.path import isdir, isfile, abspath
import random
import re
import subprocess
import string
import sys
import tarfile
import tempfile

import yaml

from .conda_interface import (PY3, UnsatisfiableError, ProgressiveFetchExtract,
                              TemporaryDirectory)
from .conda_interface import execute_actions
from .conda_interface import pkgs_dirs

from conda_build import exceptions, utils, environ
from conda_build.metadata import MetaData
import conda_build.source as source
from conda_build.variants import (get_package_variants, dict_of_lists_to_list_of_dicts,
                                  conform_variants_to_value)
from conda_build.exceptions import DependencyNeedsBuildingError
from conda_build.index import get_build_index
# from conda_build.jinja_context import pin_subpackage_against_outputs


def bldpkg_path(m):
    '''
    Returns path to built package's tarball given its ``Metadata``.
    '''
    output_dir = 'noarch' if m.noarch or m.noarch_python else m.config.host_subdir
    return os.path.join(os.path.dirname(m.config.bldpkgs_dir), output_dir, '%s.tar.bz2' % m.dist())


def actions_to_pins(actions):
    specs = []
    if utils.conda_43():
        spec_name = lambda x: x.dist_name
    else:
        spec_name = lambda x: x
    if 'LINK' in actions:
        specs = [' '.join(spec_name(spec).split()[0].rsplit('-', 2)) for spec in actions['LINK']]
    return specs


def get_env_dependencies(m, env, variant, exclude_pattern=None,
                         permit_unsatisfiable_variants=False):
    dash_or_under = re.compile("[-_]")
    specs = [ms.spec for ms in m.ms_depends(env)]
    if env == 'build' and m.is_cross and m.config.build_subdir == m.config.host_subdir:
        specs.extend([ms.spec for ms in m.ms_depends('host')])
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
                        not re.search(r'%s\s+[0-9a-zA-Z\_\.]' % spec_name, spec)):
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
    return specs + subpackages + pass_through_deps, actions, unsat


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
            not (dep_name == 'python' and m.noarch) and
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
    filtered_specs = []
    for spec in specs:
        if hasattr(spec, 'decode'):
            spec = spec.decode()
        if not any((spec == ignore_spec or spec.startswith(ignore_spec + ' '))
                   for ignore_spec in ignore_list):
            filtered_specs.append(spec)
    return filtered_specs


def get_upstream_pins(m, actions, env):
    """Download packages from specs, then inspect each downloaded package for additional
    downstream dependency specs.  Return these additional specs."""
    additional_specs = []
    linked_packages = actions.get('LINK', [])
    # edit the plan to download all necessary packages
    for key in ('LINK', 'EXTRACT', 'UNLINK'):
        if key in actions:
            del actions[key]
    # this should be just downloading packages.  We don't need to extract them -
    #    we read contents directly

    index, index_ts = get_build_index(getattr(m.config, '{}_subdir'.format(env)),
                                      bldpkgs_dir=m.config.bldpkgs_dir,
                                      output_folder=m.config.output_folder,
                                      channel_urls=m.config.channel_urls,
                                      debug=m.config.debug, verbose=m.config.verbose,
                                      locking=m.config.locking, timeout=m.config.timeout)

    if actions:
        execute_actions(actions, index, verbose=m.config.debug)
        ignore_list = utils.ensure_list(m.get_value('build/ignore_run_exports'))

        _pkgs_dirs = pkgs_dirs + list(m.config.bldpkgs_dirs)
        for pkg in linked_packages:
            for pkgs_dir in _pkgs_dirs:
                if hasattr(pkg, 'dist_name'):
                    pkg_dist = pkg.dist_name
                else:
                    pkg = strip_channel(pkg)
                    pkg_dist = pkg.split(' ')[0]

                pkg_dir = os.path.join(pkgs_dir, pkg_dist)
                pkg_file = os.path.join(pkgs_dir, pkg_dist + '.tar.bz2')
                if os.path.isdir(pkg_dir):
                    downstream_file = os.path.join(pkg_dir, 'info/run_exports')
                    if os.path.isfile(downstream_file):
                        specs = open(downstream_file).read().splitlines()
                        additional_specs.extend(_filter_run_exports(specs, ignore_list))
                    break
                elif os.path.isfile(pkg_file):
                    extra_specs = utils.package_has_file(pkg_file, 'info/run_exports')
                    if extra_specs:
                        # exclude packages pinning themselves (makes no sense)
                        extra_specs = [spec for spec in extra_specs.splitlines()
                            if not spec.startswith(pkg_dist.rsplit('-', 2)[0])]
                        additional_specs.extend(_filter_run_exports(extra_specs, ignore_list))
                    break
                elif utils.conda_43():
                    # TODO: this is a vile hack reaching into conda's internals. Replace with
                    #    proper conda API when available.
                    try:
                        pfe = ProgressiveFetchExtract(link_dists=[pkg],
                                                    index=index)
                        with utils.LoggingContext():
                            pfe.execute()
                        for pkgs_dir in _pkgs_dirs:
                            pkg_file = os.path.join(pkgs_dir, pkg.dist_name + '.tar.bz2')
                            if os.path.isfile(pkg_file):
                                extra_specs = utils.package_has_file(pkg_file,
                                                                    'info/run_exports')
                                if extra_specs:
                                    specs = extra_specs.splitlines()
                                    additional_specs.extend(_filter_run_exports(specs, ignore_list))
                                break
                        break
                    except KeyError:
                        raise DependencyNeedsBuildingError(packages=[pkg.name])
            else:
                raise RuntimeError("Didn't find expected package {} in package cache ({})"
                                    .format(pkg_dist, _pkgs_dirs))

    return additional_specs


def finalize_metadata(m, permit_unsatisfiable_variants=False):
    """Fully render a recipe.  Fill in versions for build/host dependencies."""
    exclude_pattern = None
    excludes = set(m.config.variant.get('ignore_version', []))

    for key in m.config.variant.get('pin_run_as_build', {}).keys():
        if key in excludes:
            excludes.remove(key)

    output_excludes = set()
    if hasattr(m, 'other_outputs'):
        output_excludes = set(name for (name, variant) in m.other_outputs.keys())

    if excludes or output_excludes:
        exclude_pattern = re.compile('|'.join('(?:^{}(?:\s|$|\Z))'.format(exc)
                                          for exc in excludes | output_excludes))

    build_reqs = m.meta.get('requirements', {}).get('build', [])
    # if python is in the build specs, but doesn't have a specific associated
    #    version, make sure to add one
    if build_reqs and 'python' in build_reqs:
        build_reqs.append('python {}'.format(m.config.variant['python']))
        m.meta['requirements']['build'] = build_reqs

    # if we have host deps, they're more important than the build deps.
    build_deps, build_actions, build_unsat = get_env_dependencies(m, 'build', m.config.variant,
                                        exclude_pattern,
                                        permit_unsatisfiable_variants=permit_unsatisfiable_variants)
    # optimization: we don't need the index after here, and copying them takes a lot of time.
    rendered_metadata = m.copy()

    extra_run_specs = get_upstream_pins(m, build_actions, 'build')

    if m.is_cross and m.config.host_subdir != m.config.build_subdir:
        host_reqs = m.get_value('requirements/host')
        # if python is in the build specs, but doesn't have a specific associated
        #    version, make sure to add one
        if host_reqs and 'python' in host_reqs:
            host_reqs.append('python {}'.format(m.config.variant['python']))
            m.meta['requirements']['host'] = host_reqs
        host_deps, host_actions, host_unsat = get_env_dependencies(m, 'host', m.config.variant,
                                        exclude_pattern,
                                        permit_unsatisfiable_variants=permit_unsatisfiable_variants)
        extra_run_specs += get_upstream_pins(m, host_actions, 'host')
    else:
        host_deps = []
        host_unsat = None

    # here's where we pin run dependencies to their build time versions.  This happens based
    #     on the keys in the 'pin_run_as_build' key in the variant, which is a list of package
    #     names to have this behavior.
    requirements = rendered_metadata.meta.get('requirements', {})
    run_deps = requirements.get('run', [])
    if output_excludes:
        exclude_pattern = re.compile('|'.join('(?:^{}(?:\s|$|\Z))'.format(exc)
                                          for exc in output_excludes))
    pinning_env = 'host' if m.is_cross else 'build'
    full_build_deps, _, _ = get_env_dependencies(m, pinning_env, m.config.variant,
                                        exclude_pattern=exclude_pattern,
                                        permit_unsatisfiable_variants=permit_unsatisfiable_variants)
    full_build_dep_versions = {dep.split()[0]: " ".join(dep.split()[1:]) for dep in full_build_deps}
    versioned_run_deps = [get_pin_from_build(m, dep, full_build_dep_versions) for dep in run_deps]
    versioned_run_deps.extend(extra_run_specs)

    for _env, values in (('build', build_deps), ('host', host_deps), ('run', versioned_run_deps)):
        if values:
            requirements[_env] = list({strip_channel(dep) for dep in values})
    rendered_metadata.meta['requirements'] = requirements

    test_deps = rendered_metadata.get_value('test/requires')
    if test_deps:
        versioned_test_deps = list({get_pin_from_build(m, dep, full_build_dep_versions)
                                    for dep in test_deps})
        rendered_metadata.meta['test']['requires'] = versioned_test_deps

    # if source/path is relative, then the output package makes no sense at all.  The next
    #   best thing is to hard-code the absolute path.  This probably won't exist on any
    #   system other than the original build machine, but at least it will work there.
    if m.meta.get('source'):
        if 'path' in m.meta['source'] and not os.path.isabs(m.meta['source']['path']):
            rendered_metadata.meta['source']['path'] = os.path.normpath(
                os.path.join(m.path, m.meta['source']['path']))
        elif ('git_url' in m.meta['source'] and not (
                # absolute paths are not relative paths
                os.path.isabs(m.meta['source']['git_url']) or
                # real urls are not relative paths
                ":" in m.meta['source']['git_url'])):
            rendered_metadata.meta['source']['git_url'] = os.path.normpath(
                os.path.join(m.path, m.meta['source']['git_url']))

    if not rendered_metadata.meta.get('build'):
        rendered_metadata.meta['build'] = {}
    # hard-code build string so that any future "renderings" can't go wrong based on user env
    rendered_metadata.meta['build']['string'] = rendered_metadata.build_id()

    if build_unsat or host_unsat:
        rendered_metadata.final = False
        log = utils.get_logger(__name__)
        log.warn("Returning non-final recipe for {}; one or more dependencies "
                 "was unsatisfiable:\nBuild: {}\nHost: {}".format(rendered_metadata.dist(),
                                                                  build_unsat, host_unsat))
    else:
        rendered_metadata.final = True
    return rendered_metadata


def try_download(metadata, no_download_source):
    need_source_download = (metadata.get_section('source') and
                            len(os.listdir(metadata.config.work_dir)) == 0)
    if need_source_download and not no_download_source:
        # this try/catch is for when the tool to download source is actually in
        #    meta.yaml, and not previously installed in builder env.
        try:
            source.provide(metadata)
            need_source_download = len(os.listdir(metadata.config.work_dir)) > 0
        except subprocess.CalledProcessError as error:
            print("Warning: failed to download source.  If building, will try "
                "again after downloading recipe dependencies.")
            print("Error was: ")
            print(error)

    if need_source_download and no_download_source:
        raise ValueError("no_download_source specified, but can't fully render recipe without"
                         " downloading source.  Please fix the recipe, or don't use "
                         "no_download_source.")


def reparse(metadata):
    """Some things need to be parsed again after the build environment has been created
    and activated."""
    metadata.final = False
    sys.path.insert(0, metadata.config.build_prefix)
    py_ver = '.'.join(metadata.config.variant['python'].split('.')[:2])
    sys.path.insert(0, utils.get_site_packages(metadata.config.build_prefix, py_ver))
    metadata.parse_until_resolved()
    metadata = finalize_metadata(metadata)
    return metadata


def insert_variant_versions(metadata, env):
    reqs = metadata.get_value('requirements/' + env)
    for key, val in metadata.config.variant.items():
        regex = re.compile(r'^%s(?:\s*$|(?=(?:\s*[#\[])))' % key)
        matches = [regex.match(pkg) for pkg in reqs]
        if any(matches):
            for i, x in enumerate(matches):
                if x:
                    del reqs[i]
                    reqs.insert(i, ' '.join((key, val)))

    xx_re = re.compile("([0-9a-zA-Z\.\-\_]+)\s+x\.x")

    matches = [xx_re.match(pkg) for pkg in reqs]
    if any(matches):
        for i, x in enumerate(matches):
            if x:
                del reqs[i]
                reqs.insert(i, ' '.join((x.group(1), metadata.config.variant.get(x.group(1)))))
    metadata.meta['requirements'][env] = reqs


def distribute_variants(metadata, variants, permit_unsatisfiable_variants=False,
                        allow_no_other_outputs=False, bypass_env_check=False):
    rendered_metadata = {}
    need_reparse_in_env = False
    need_source_download = True

    # don't bother distributing python if it's a noarch package
    if metadata.noarch or metadata.noarch_python:
        conform_dict = {'python': variants[0]['python']}
        variants = conform_variants_to_value(variants, conform_dict)

    # store these for reference later
    metadata.config.variants = variants
    # These are always the full set.  just 'variants' is the one that gets
    #     used mostly, and can be reduced
    metadata.config.input_variants = variants

    recipe_requirements = metadata.extract_requirements_text()

    for variant in variants:
        mv = metadata.copy()

        # this determines which variants were used, and thus which ones should be locked for
        #     future rendering
        mv.final = False
        mv.config.variant = {}
        mv.parse_again(permit_undefined_jinja=True, allow_no_other_outputs=True,
                        bypass_env_check=True)
        vars_in_recipe = set(mv.undefined_jinja_vars)

        mv.config.variant = variant
        conform_dict = {}
        for key in vars_in_recipe:
            if PY3 and hasattr(recipe_requirements, 'decode'):
                recipe_requirements = recipe_requirements.decode()
            elif not PY3 and hasattr(recipe_requirements, 'encode'):
                recipe_requirements = recipe_requirements.encode()
            # We use this variant in the top-level recipe.
            # constrain the stored variants to only this version in the output
            #     variant mapping
            if re.search(r"\s+\{\{\s*%s\s*(?:.*?)?\}\}" % key, recipe_requirements):
                conform_dict[key] = variant[key]

        compiler_matches = re.findall(r"compiler\([\'\"](.*)[\'\"].*\)",
                                        recipe_requirements)
        if compiler_matches:
            from conda_build.jinja_context import native_compiler
            for match in compiler_matches:
                compiler_key = '{}_compiler'.format(match)
                conform_dict[compiler_key] = variant.get(compiler_key,
                                        native_compiler(match, mv.config))
                conform_dict['target_platform'] = variant['target_platform']

        build_reqs = mv.meta.get('requirements', {}).get('build', [])
        host_reqs = mv.meta.get('requirements', {}).get('host', [])
        if 'python' in build_reqs or 'python' in host_reqs:
            conform_dict['python'] = variant['python']

        pin_run_as_build = variant.get('pin_run_as_build', {})
        if mv.numpy_xx and 'numpy' not in pin_run_as_build:
            pin_run_as_build['numpy'] = {'min_pin': 'x.x', 'max_pin': 'x.x'}

        mv.config.variants = conform_variants_to_value(mv.config.variants, conform_dict)
        numpy_pinned_variants = []
        for _variant in mv.config.variants:
            _variant['pin_run_as_build'] = pin_run_as_build
            numpy_pinned_variants.append(_variant)
        mv.config.variants = numpy_pinned_variants

        if not need_reparse_in_env:
            mv.parse_until_resolved(allow_no_other_outputs=allow_no_other_outputs,
                                    bypass_env_check=bypass_env_check)
            need_source_download = (bool(mv.meta.get('source')) and
                                    not mv.needs_source_for_render and
                                    not os.listdir(mv.config.work_dir))
            # if python is in the build specs, but doesn't have a specific associated
            #    version, make sure to add one to newly parsed 'requirements/build'.
            for env in ('build', 'host', 'run'):
                insert_variant_versions(mv, env)
            fm = mv.copy()
            # HACK: trick conda-build into thinking this is final, and computing a hash based
            #     on the current meta.yaml.  The accuracy doesn't matter, all that matters is
            #     our ability to differentiate configurations
            fm.final = True
            rendered_metadata[fm.dist()] = (mv, need_source_download, need_reparse_in_env)

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
    if m.needs_source_for_render and (not os.path.isdir(m.config.work_dir) or
                                      len(os.listdir(m.config.work_dir)) == 0):
        try_download(m, no_download_source=no_download_source)

    if m.final:
        if not hasattr(m.config, 'variants'):
            m.config.variants = [m.config.variant]
        rendered_metadata = [(m, False, False), ]
    else:
        index, index_ts = get_build_index(m.config.build_subdir,
                                        bldpkgs_dir=m.config.bldpkgs_dir,
                                        output_folder=m.config.output_folder,
                                        channel_urls=m.config.channel_urls,
                                        debug=m.config.debug, verbose=m.config.verbose,
                                        locking=m.config.locking, timeout=m.config.timeout)
        # when building, we don't want to fully expand all outputs into metadata, only expand
        #    whatever variants we have.
        variants = (dict_of_lists_to_list_of_dicts(variants) if variants else
                    get_package_variants(m))
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


yaml.add_representer(_MetaYaml, _represent_omap)
if PY3:
    yaml.add_representer(str, _unicode_representer)
    unicode = None  # silence pyflakes about unicode not existing in py3
else:
    yaml.add_representer(unicode, _unicode_representer)


def output_yaml(metadata, filename=None):
    utils.trim_empty_keys(metadata.meta)
    if metadata.meta.get('outputs'):
        del metadata.meta['outputs']
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
