# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import copy
from locale import getpreferredencoding
import logging
import os
from os.path import isdir, isfile, abspath
import re
import subprocess
import sys
import tarfile
import tempfile

import yaml

from .conda_interface import PY3, memoized, NoPackagesFoundError

from conda_build import exceptions, utils, environ
from conda_build.metadata import MetaData
import conda_build.source as source
from conda_build.variants import get_package_variants, dict_of_lists_to_list_of_dicts
from conda_build.exceptions import UnsatisfiableVariantError


def bldpkg_path(m):
    '''
    Returns path to built package's tarball given its ``Metadata``.
    '''
    output_dir = m.info_index()['subdir']
    return os.path.join(os.path.dirname(m.config.bldpkgs_dir), output_dir, '%s.tar.bz2' % m.dist())


def actions_to_pins(actions):
    return [' '.join(spec.split()[0].rsplit('-', 2)) for spec in actions['LINK']]


def get_env_dependencies(m, env, variant, index=None):
    dash_or_under = re.compile("[-_]")
    if not index:
        index = utils.get_build_index(m.config, getattr(m.config, "{}_subdir".format(env)))
    specs = [ms.spec for ms in m.ms_depends(env)]
    for spec in specs[:]:
        spec_name = spec.split()[0]
        for key, value in variant.items():
            if dash_or_under.sub("", key) == dash_or_under.sub("", spec_name):
                specs.append(" ".join((spec_name, value)))
    prefix = m.config.host_prefix if env == 'host' else m.config.build_prefix
    try:
        actions = environ.get_install_actions(prefix, index, specs, m.config)
    except NoPackagesFoundError as e:
        # we'll get here if the environment is unsatisfiable
        raise UnsatisfiableVariantError("Invalid variant: {}.  Led to unsatisfiable environment.\n"
                                        "Error was: {}".format(variant, str(e)))
    return actions_to_pins(actions)


@memoized
def finalize_metadata(m, variant, indexes):
    """Fully render a recipe.  Fill in versions for build dependencies."""
    rendered_metadata = copy.deepcopy(m)
    # these are obtained from a sort of dry-run of conda.  These are the actual packages that would
    #     be installed in the environment.
    deps = {env: get_env_dependencies(m, env, variant, indexes[env]) for env in ('build', 'host')}
    build_dep_versions = {dep.split()[0]: " ".join(dep.split()[1:]) for dep in deps['build']}
    if not rendered_metadata.meta.get('build'):
        rendered_metadata.meta['build'] = {}
    # hard-code build string so that any future "renderings" can't go wrong based on user env
    rendered_metadata.meta['build']['string'] = m.build_id()

    rendered_metadata.meta['requirements'] = rendered_metadata.meta.get('requirements', {})
    for env, values in deps.items():
        if values:
            rendered_metadata.meta['requirements'][env] = values

    # here's where we pin run dependencies to their build time versions.  This happens based
    #     on the keys in the 'pin_run_as_build' key in the variant, which is a list of package
    #     names to have this behavior.
    run_deps = rendered_metadata.meta['requirements'].get('run', [])
    for dep in run_deps[:]:
        dep_name = dep.split()[0]
        if dep_name in variant['pin_run_as_build'] and dep_name in build_dep_versions:
            run_deps.append(" ".join((dep_name, build_dep_versions[dep_name])))

    rendered_metadata.meta['requirements']['run'] = run_deps

    if not rendered_metadata.meta.get('test'):
        rendered_metadata.meta['test'] = {}
    rendered_metadata.meta['test']['requires'] = rendered_metadata.get_value('test/requires') + run_deps

    # if source/path is relative, then the output package makes no sense at all.  The next
    #   best thing is to hard-code the absolute path.  This probably won't exist on any
    #   system other than the original build machine, but at least it will work there.
    if m.meta.get('source'):
        if 'path' in m.meta['source'] and not os.path.isabs(m.meta['source']['path']):
            rendered_metadata.meta['source']['path'] = os.path.normpath(
                os.path.join(m.path, m.meta['source']['path']))
        elif ('git_url' in m.meta['source'] and not os.path.isabs(m.meta['source']['git_url'])):
            rendered_metadata.meta['source']['git_url'] = os.path.normpath(
                os.path.join(m.path, m.meta['source']['git_url']))
    return rendered_metadata


def parse_or_try_download(metadata, no_download_source, config, variants, force_download=False):
    log = logging.getLogger(__name__)
    need_reparse_in_env = True
    need_source_download = True
    if (force_download or (not no_download_source and metadata.needs_source_for_render)):
        # this try/catch is for when the tool to download source is actually in
        #    meta.yaml, and not previously installed in builder env.
        try:
            if not config.dirty or len(os.listdir(metadata.config.work_dir)) == 0:
                source.provide(metadata)
            if not metadata.get_section('source') or len(os.listdir(metadata.config.work_dir)) > 0:
                need_source_download = False
            try:
                metadata.parse_again(permit_undefined_jinja=False)
                need_reparse_in_env = False
            except (ImportError, exceptions.UnableToParseMissingSetuptoolsDependencies):
                pass  # we just don't alter the need_reparse_in_env variable
        except subprocess.CalledProcessError as error:
            print("Warning: failed to download source.  If building, will try "
                "again after downloading recipe dependencies.")
            print("Error was: ")
            print(error)

    elif not metadata.get_section('source'):
        need_source_download = False
        need_reparse_in_env = False

    if need_source_download and no_download_source:
        raise ValueError("no_download_source specified, but can't fully render recipe without"
                         " downloading source.  Please fix the recipe, or don't use "
                         "no_download_source.")

    if metadata.get_value('build/noarch'):
        config.noarch = True

    if 'host' in metadata.get_section('requirements'):
        metadata.config.has_separate_host_prefix = True

    # this additional parse ensures that jinja2 stuff is evaluated
    metadata.parse_again(permit_undefined_jinja=True)

    outputs = {}
    indexes = {env: utils.get_build_index(metadata.config,
                                          getattr(metadata.config, '{}_subdir'.format(env)))
                                          for env in ('build', 'host')}
    for variant in variants:
        varmeta = copy.deepcopy(metadata)
        varmeta.config.variant = variant
        if 'target_platform' in variant:
            varmeta.config.host_subdir = variant['target_platform']
        try:
            varmeta.parse_until_resolved(config=varmeta.config)
        except (RuntimeError, exceptions.UnableToParseMissingSetuptoolsDependencies):
            log.warn("Need to create build environment to fully render this recipe.  Doing so.")
            specs = [ms.spec for ms in metadata.ms_depends('build')]
            environ.create_env(config.build_prefix, specs, config=config,
                               subdir=config.build_subdir)
            reparse(metadata)
            need_reparse_in_env = False

        metadata.config.noarch = bool((metadata.get_value('build/noarch') or
                                       metadata.get_value('build/noarch_python')))
        try:
            # keys in variant are named after package, but config is still used for some things.
            #    This overrides the config with the variant settings.  The initial config
            #    overrides the variant, though, so the variant is only clobbering in the case
            #    where no CONDA_PY variables are set, or no version args passed to config object.
            # computes hashes based on whatever the current specs are - not the final specs
            #    This is a deduplication step.  Any variants that end up identical because a given
            #    variant is not used in a recipe are effectively ignored.
            reparse(varmeta)
            final = finalize_metadata(varmeta, variant, indexes=indexes)
        except UnsatisfiableVariantError as e:
            log.warn("Unsatisfiable variant: {}"
                     "Error was {}".format(variant, e))
            continue
        outputs[final.build_id()] = (final, need_source_download, need_reparse_in_env)
    return outputs.values()


def reparse(metadata):
    """Some things need to be parsed again after the build environment has been created
    and activated."""
    sys.path.insert(0, metadata.config.build_prefix)
    sys.path.insert(0, utils.get_site_packages(metadata.config.build_prefix))
    metadata.parse_again(permit_undefined_jinja=False)


def render_recipe(recipe_path, config, no_download_source=False, variants=None):
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
            return
    else:
        recipe_dir = abspath(arg)
        need_cleanup = False

    if not isdir(recipe_dir):
        sys.exit("Error: no such directory: %s" % recipe_dir)

    if config.set_build_id:
        # updates a unique build id if not already computed
        config.compute_build_id(os.path.basename(recipe_dir))
    try:
        m = MetaData(recipe_dir, config=config)
    except exceptions.YamlParsingError as e:
        sys.stderr.write(e.error_msg())
        sys.exit(1)

    variants = dict_of_lists_to_list_of_dicts(variants) if variants else get_package_variants(m, config)

    # list of tuples.
    # each tuple item is a tuple of 3 items:
    #    metadata, need_download, need_reparse_in_env
    rendered_metadata = parse_or_try_download(m,
                                              no_download_source=no_download_source,
                                              config=config, variants=variants)
    if need_cleanup:
        utils.rm_rf(recipe_dir)

    return rendered_metadata


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
        with open(filename, "w") as f:
            f.write(output)
        return "Wrote yaml to %s" % filename
    else:
        return output
