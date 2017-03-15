# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

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

from .conda_interface import (PY3, UnsatisfiableError, plan, cc, ProgressiveFetchExtract,
                              memoized, TemporaryDirectory)

from conda_build import exceptions, utils, environ
from conda_build.metadata import MetaData
import conda_build.source as source
from conda_build.variants import (get_package_variants, dict_of_lists_to_list_of_dicts,
                                  combine_variants)
from conda_build.exceptions import DependencyNeedsBuildingError
from conda_build.index import get_build_index


def bldpkg_path(m):
    '''
    Returns path to built package's tarball given its ``Metadata``.
    '''
    output_dir = m.info_index()['subdir']
    return os.path.join(os.path.dirname(m.config.bldpkgs_dir), output_dir, '%s.tar.bz2' % m.dist())


def actions_to_pins(actions):
    if utils.conda_43():
        spec_name = lambda x: x.dist_name
    else:
        spec_name = lambda x: x
    return [' '.join(spec_name(spec).split()[0].rsplit('-', 2)) for spec in actions['LINK']]


@memoized
def get_env_dependencies(m, env, variant, index=None, exclude_pattern=None):
    dash_or_under = re.compile("[-_]")
    if not index:
        index = get_build_index(m.config, getattr(m.config, "{}_subdir".format(env)))
    specs = [ms.spec for ms in m.ms_depends(env)]
    # replace x.x with our variant's numpy version, or else conda tries to literally go get x.x
    if env == 'build':
        specs = [spec.replace(' x.x', ' {}'.format(variant.get('numpy', ""))) for spec in specs]
    subpackages = []
    dependencies = []
    # ones that get filtered from actual versioning, to exclude them from the hash calculation
    append_specs = []
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
            for key, value in variant.items():
                if dash_or_under.sub("", key) == dash_or_under.sub("", spec_name):
                    dependencies.append(" ".join((spec_name, value)))
        else:
            append_specs.append(spec)
    random_string = ''.join(random.choice(string.ascii_uppercase + string.digits)
                            for _ in range(10))
    with TemporaryDirectory(suffix=random_string) as tmpdir:
        try:
            actions = environ.get_install_actions(tmpdir, index, dependencies, m.config)
        except UnsatisfiableError as e:
            # we'll get here if the environment is unsatisfiable
            raise DependencyNeedsBuildingError(e)

    specs = actions_to_pins(actions)
    return specs + subpackages + append_specs


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
            not (dep_name == 'python' and m.noarch)):
        pin = utils.apply_pin_expressions(version.split()[0],
                                            **m.config.variant['pin_run_as_build'][dep_name])
    elif dep.startswith('numpy') and 'x.x' in dep:
        if not build_dep_versions.get(dep_name):
            raise ValueError("numpy x.x specified, but numpy not in build requirements.")
        pin = utils.apply_pin_expressions(version.split()[0], min_pin='p.p', max_pin='p.p')
    if pin:
        dep = " ".join((dep_name, pin))
    return dep


def get_upstream_pins(m, dependencies, index):
    """Download packages from specs, then inspect each downloaded package for additional
    downstream dependency specs.  Return these additional specs."""
    dependencies = [strip_channel(dep) for dep in dependencies]
    random_string = ''.join(random.choice(string.ascii_uppercase + string.digits)
                            for _ in range(10))
    with TemporaryDirectory(suffix=random_string) as tmpdir:
        actions = environ.get_install_actions(tmpdir, index, dependencies,
                                            m.config)
        additional_specs = []
        linked_packages = actions['LINK']
        # edit the plan to download all necessary packages
        for key in ('LINK', 'EXTRACT', 'UNLINK'):
            if key in actions:
                del actions[key]
        # this should be just downloading packages.  We don't need to extract them -
        #    we read contents directly
        if actions:
            plan.execute_actions(actions, index, verbose=m.config.debug)

            pkgs_dirs = cc.pkgs_dirs + list(m.config.bldpkgs_dirs)
            for pkg in linked_packages:
                for pkgs_dir in pkgs_dirs:
                    if hasattr(pkg, 'dist_name'):
                        pkg_dist = pkg.dist_name
                    else:
                        pkg = strip_channel(pkg)
                        pkg_dist = pkg.split(' ')[0]

                    pkg_dir = os.path.join(pkgs_dir, pkg_dist)
                    pkg_file = os.path.join(pkgs_dir, pkg_dist + '.tar.bz2')
                    if os.path.isdir(pkg_dir):
                        downstream_file = os.path.join(pkg_dir, 'info/pin_downstream')
                        if os.path.isfile(downstream_file):
                            additional_specs.extend(open(downstream_file).read().splitlines())
                        break
                    elif os.path.isfile(pkg_file):
                        extra_specs = utils.package_has_file(pkg_file, 'info/pin_downstream')
                        if extra_specs:
                            additional_specs.extend(extra_specs.splitlines())
                        break
                    elif utils.conda_43():
                        # TODO: this is a vile hack reaching into conda's internals. Replace with
                        #    proper conda API when available.
                        try:
                            pfe = ProgressiveFetchExtract(link_dists=[pkg],
                                                        index=index)
                            pfe.execute()
                            for pkgs_dir in pkgs_dirs:
                                pkg_file = os.path.join(pkgs_dir, pkg.dist_name + '.tar.bz2')
                                if os.path.isfile(pkg_file):
                                    extra_specs = utils.package_has_file(pkg_file,
                                                                        'info/pin_downstream')
                                    if extra_specs:
                                        additional_specs.extend(extra_specs.splitlines())
                                    break
                            break
                        except KeyError:
                            raise DependencyNeedsBuildingError(packages=[pkg.name])
                else:
                    raise RuntimeError("Didn't find expected package {} in package cache ({})"
                                        .format(pkg_dist, pkgs_dirs))

    return additional_specs


def finalize_metadata(m, index=None):
    """Fully render a recipe.  Fill in versions for build dependencies."""
    if not index:
        index = get_build_index(m.config, m.config.build_subdir)

    exclude_pattern = None
    excludes = m.config.variant.get('exclude_from_build_hash', [])
    if excludes:
        exclude_pattern = re.compile('|'.join('(?:^{}(?:\s|$|\Z))'.format(exc) for exc in excludes))

    # these are obtained from a sort of dry-run of conda.  These are the actual packages that would
    #     be installed in the environment.

    build_deps = get_env_dependencies(m, 'build', m.config.variant, index, exclude_pattern)
    # optimization: we don't need the index after here, and copying them takes a lot of time.
    rendered_metadata = m.copy()
    build_dep_versions = {dep.split()[0]: " ".join(dep.split()[1:]) for dep in build_deps}

    extra_run_specs = get_upstream_pins(m, build_deps, index)

    reset_index = False
    if m.config.build_subdir != m.config.host_subdir:
        index = get_build_index(m.config, m.config.host_subdir)
        reset_index = True

    # IMPORTANT: due to the statefulness of conda's index, this index invalidates the earlier one!
    #    To avoid confusion, any index passed around is always the native build platform.
    if reset_index:
        index = None

    # here's where we pin run dependencies to their build time versions.  This happens based
    #     on the keys in the 'pin_run_as_build' key in the variant, which is a list of package
    #     names to have this behavior.
    requirements = rendered_metadata.meta.get('requirements', {})
    run_deps = requirements.get('run', [])
    versioned_run_deps = [get_pin_from_build(m, dep, build_dep_versions) for dep in run_deps]
    versioned_run_deps.extend(extra_run_specs)

    rendered_metadata.meta['requirements'] = rendered_metadata.meta.get('requirements', {})
    for env, values in (('build', build_deps), ('run', versioned_run_deps)):
        if values:
            requirements[env] = list({strip_channel(dep) for dep in values})
    rendered_metadata.meta['requirements'] = requirements

    test_deps = rendered_metadata.get_value('test/requires')
    if test_deps:
        versioned_test_deps = list({get_pin_from_build(m, dep, build_dep_versions)
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

    rendered_metadata.final = True
    rendered_metadata.config.index = index
    return rendered_metadata


def try_download(metadata, no_download_source, force_download=False):
    need_source_download = True
    if (force_download or (not no_download_source and metadata.needs_source_for_render)):
        # this try/catch is for when the tool to download source is actually in
        #    meta.yaml, and not previously installed in builder env.
        try:
            if not metadata.config.dirty or len(os.listdir(metadata.config.work_dir)) == 0:
                source.provide(metadata)
            if not metadata.get_section('source') or len(os.listdir(metadata.config.work_dir)) > 0:
                need_source_download = False
        except subprocess.CalledProcessError as error:
            print("Warning: failed to download source.  If building, will try "
                "again after downloading recipe dependencies.")
            print("Error was: ")
            print(error)

    elif not metadata.get_section('source'):
        need_source_download = False
    if need_source_download and no_download_source:
        raise ValueError("no_download_source specified, but can't fully render recipe without"
                         " downloading source.  Please fix the recipe, or don't use "
                         "no_download_source.")


def reparse(metadata, index):
    """Some things need to be parsed again after the build environment has been created
    and activated."""
    metadata.final = False
    sys.path.insert(0, metadata.config.build_prefix)
    py_ver = '.'.join(metadata.config.variant['python'].split('.')[:2])
    sys.path.insert(0, utils.get_site_packages(metadata.config.build_prefix, py_ver))
    metadata.parse_until_resolved()
    metadata = finalize_metadata(metadata, index)
    return metadata


def distribute_variants(metadata, variants, index, permit_unsatisfiable_variants=False):
    rendered_metadata = {}
    need_reparse_in_env = False
    unsatisfiable_variants = []
    packages_needing_building = set()

    for variant in variants:
        mv = metadata.copy()
        # deep copy the sensitive parts to decouple metadata objects
        mv.config = metadata.config.copy()
        mv.config.variant = combine_variants(variant, mv.config.variant)
        mv.final = False

        # TODO: may need to compute new build id, or at least remove any envs before building
        #    another variant

        if 'target_platform' in variant:
            mv.config.host_subdir = variant['target_platform']
        if not need_reparse_in_env:
            try:
                mv.parse_until_resolved()
                need_source_download = (bool(mv.meta.get('source')) and
                                        not mv.needs_source_for_render and
                                        not os.listdir(mv.config.work_dir))
                # this is a bit wasteful.  We don't store the output here - we'll have to recompute
                #    it later.  We don't store it, so that we can have per-subpackage exclusions
                #    from the hash.  Since finalizing brings in *all* build-time packages, notest
                #    just the ones from the recipe, it is impossible to remove them in the general
                #    case.  Instead, we just leave the recipe unfinalized until then, so that by
                #    excluding one higher-level package (e.g. python), we also won't include its
                #    deps in the hash
                finalize_metadata(mv, index)
            except DependencyNeedsBuildingError as e:
                unsatisfiable_variants.append(variant)
                packages_needing_building.update(set(e.packages))
                if permit_unsatisfiable_variants:
                    rendered_metadata[mv.dist()] = (mv, need_source_download,
                                                        need_reparse_in_env)
                continue
            except exceptions.UnableToParseMissingSetuptoolsDependencies:
                need_reparse_in_env = True
            except:
                raise

        # computes hashes based on whatever the current specs are - not the final specs
        #    This is a deduplication step.  Any variants that end up identical because a
        #    given variant is not used in a recipe are effectively ignored, though we still pay
        #    the price to parse for that variant.
        rendered_metadata[mv.build_id()] = (mv, need_source_download, need_reparse_in_env)
    # list of tuples.
    # each tuple item is a tuple of 3 items:
    #    metadata, need_download, need_reparse_in_env
    if unsatisfiable_variants and not permit_unsatisfiable_variants:
        raise DependencyNeedsBuildingError(packages=packages_needing_building)
    return list(rendered_metadata.values())


def expand_outputs(metadata_tuples, index):
    """Obtain all metadata objects for all outputs from recipe.  Useful for ouptutting paths."""
    expanded_outputs = {}
    for (_m, download, reparse) in metadata_tuples:
        for (output_dict, m) in _m.get_output_metadata_set():
            if output_dict.get('type') != 'wheel':
                try:
                    m = finalize_metadata(m, index)
                except DependencyNeedsBuildingError:
                    log = utils.get_logger(__name__)
                    log.warn("Could not finalize metadata due to missing dependencies.  "
                                "If building, these should get built in order and it's OK to "
                                "ignore this message..")
                expanded_outputs[m.dist()] = (m, download, reparse)
    return list(expanded_outputs.values())


def render_recipe(recipe_path, config, no_download_source=False, variants=None,
                  permit_unsatisfiable_variants=True, reset_build_id=True, expand_output=False):
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

    if config.set_build_id:
        m.config.compute_build_id(m.name(), reset=reset_build_id)

    if m.needs_source_for_render and (not os.path.isdir(m.config.work_dir) or
                                      len(os.listdir(m.config.work_dir)) == 0):
        try_download(m, no_download_source=no_download_source)

    rendered_metadata = {}

    if m.final:
        rendered_metadata = [(m, False, False), ]
        index = None
    else:
        variants = (dict_of_lists_to_list_of_dicts(variants, m.config.platform)
                    if variants else get_package_variants(m, m.config))
        index = get_build_index(m.config, m.config.build_subdir)
        rendered_metadata = distribute_variants(m, variants, index,
                                        permit_unsatisfiable_variants=permit_unsatisfiable_variants)
        if not rendered_metadata:
            raise ValueError("No variants were satisfiable - no valid recipes could be rendered.")

    if expand_output:
        rendered_metadata = expand_outputs(rendered_metadata, index)

    if need_cleanup:
        utils.rm_rf(recipe_dir)

    return rendered_metadata, index


# Next bit of stuff is to support YAML output in the order we expect.
# http://stackoverflow.com/a/17310199/1170370
class _MetaYaml(dict):
    fields = ["package", "source", "build", "requirements", "test", "outputs", "about", "extra"]

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
