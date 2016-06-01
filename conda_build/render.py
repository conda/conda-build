# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import copy
import glob
import json
from locale import getpreferredencoding
import os
from os.path import isdir, isfile, abspath
import shutil
import subprocess
import sys
import tarfile
import tempfile

import yaml

from conda.compat import PY3
import conda.config as cc
from conda.lock import Locked

from conda_build import exceptions
from conda_build.completers import all_versions, conda_version
from conda_build.config import config
from conda_build.metadata import MetaData, parse
import conda_build.source as source


def set_language_env_vars(args, parser, execute=None):
    """Given args passed into conda command, set language env vars"""
    for lang in all_versions:
        versions = getattr(args, lang)
        if not versions:
            continue
        if versions == ['all']:
            if all_versions[lang]:
                versions = all_versions[lang]
            else:
                parser.error("'all' is not supported for --%s" % lang)
        if len(versions) > 1:
            for ver in versions[:]:
                setattr(args, lang, [str(ver)])
                if execute:
                    execute(args, parser)
                # This is necessary to make all combinations build.
                setattr(args, lang, versions)
            return
        else:
            version = versions[0]
            if lang in ('python', 'numpy'):
                version = int(version.replace('.', ''))
            setattr(config, conda_version[lang], version)
        if not len(str(version)) in (2, 3) and lang in ['python', 'numpy']:
            if all_versions[lang]:
                raise RuntimeError("%s must be major.minor, like %s, not %s" %
                    (conda_version[lang], all_versions[lang][-1] / 10, version))
            else:
                raise RuntimeError("%s must be major.minor, not %s" %
                    (conda_version[lang], version))

    # Using --python, --numpy etc. is equivalent to using CONDA_PY, CONDA_NPY, etc.
    # Auto-set those env variables
    for var in conda_version.values():
        if hasattr(config, var) and getattr(config, var):
            # Set the env variable.
            os.environ[var] = str(getattr(config, var))


def bldpkg_path(m):
    '''
    Returns path to built package's tarball given its ``Metadata``.
    '''
    return os.path.join(config.bldpkgs_dir, '%s.tar.bz2' % m.dist())


# This really belongs in conda, and it is int conda.cli.common,
#   but we don't presently have an API there.
def _get_env_path(env_name):
    if os.path.isdir(env_name):
        return env_name
    for envs_dir in cc.envs_dirs + [os.getcwd()]:
        path = os.path.join(envs_dir, env_name)
        if os.path.isdir(path):
            return path
    return None


def _scan_metadata(path):
    '''
    Scan all json files in 'path' and return a dictionary with their contents.
    Files are assumed to be in 'index.json' format.
    '''
    installed = dict()
    for filename in glob.glob(os.path.join(path, '*.json')):
        with open(filename) as file:
            data = json.load(file)
            installed[data['name']] = data
    return installed


def add_build_config(metadata, build_config_or_bootstrap):
    if not build_config_or_bootstrap:
        return metadata
    # don't modify it in place.
    metadata = copy.deepcopy(metadata)
    path = _get_env_path(build_config_or_bootstrap)
    # concatenate build requirements from the build config file to the build
    # requirements from the recipe
    if os.path.isfile(build_config_or_bootstrap):
        try:
            with open(build_config_or_bootstrap) as configfile:
                build_config = parse(configfile.read())
            metadata.meta['requirements']['build'] += build_config['requirements']['build']
        except Exception as e:
            print("Unable to read config file '%s':" % build_config_or_bootstrap)
            print(e)
            sys.exit(1)
    elif path:
        # construct build requirements that replicate the given bootstrap environment
        # and concatenate them to the build requirements from the recipe
        bootstrap_metadir = os.path.join(path, 'conda-meta')
        if not isdir(bootstrap_metadir):
            print("Bootstrap environment '%s' not found" % build_config_or_bootstrap)
            sys.exit(1)
        bootstrap_metadata = _scan_metadata(bootstrap_metadir)
        bootstrap_requirements = []
        for package, data in bootstrap_metadata.items():
            bootstrap_requirements.append("%s %s %s" % (package, data['version'], data['build']))
        metadata.meta['requirements']['build'] += bootstrap_requirements
    return metadata


def _jinja_config(jinja_env):
    # make all metadata from build_prefix/conda-meta/*.json available to
    # jinja in a dictionary 'installed'
    jinja_env.globals['installed'] = _scan_metadata(os.path.join(config.build_prefix, 'conda-meta'))


def parse_or_try_download(metadata, no_download_source, verbose,
                          force_download=False, dirty=False, permit_undefined_jinja=False):
    if (force_download or (not no_download_source and
                           any(var.startswith('GIT_') for var in metadata.undefined_jinja_vars))):
        try:
            source.provide(metadata.path, metadata.get_section('source'),
                           verbose=verbose, dirty=dirty)
            metadata.parse_again(permit_undefined_jinja=False, jinja_config=_jinja_config)
            need_source_download = False
        except subprocess.CalledProcessError:
            print("Warning: failed to download source.  If building, will try "
                "again after downloading recipe dependencies.")
            need_source_download = True
        else:
            need_source_download = no_download_source
    else:
        # we have not downloaded source in the render phase.  Download it in
        #     the build phase
        need_source_download = True
    metadata.parse_again(permit_undefined_jinja=permit_undefined_jinja)
    return metadata, need_source_download


def render_recipe(recipe_path, no_download_source, verbose, dirty=False,
                  build_config_or_bootstrap=None, permit_undefined_jinja=False):
    with Locked(config.croot):
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
            else:
                print("Ignoring non-recipe: %s" % arg)
                return
        else:
            recipe_dir = abspath(arg)
            need_cleanup = False

        if not isdir(recipe_dir):
            sys.exit("Error: no such directory: %s" % recipe_dir)

        try:
            m = MetaData(recipe_dir)
        except exceptions.YamlParsingError as e:
            sys.stderr.write(e.error_msg())
            sys.exit(1)

        m, need_download = parse_or_try_download(m, no_download_source=no_download_source,
                                                 verbose=verbose, dirty=dirty,
                                                 permit_undefined_jinja=permit_undefined_jinja)
        m = add_build_config(m, build_config_or_bootstrap)

        if need_cleanup:
            shutil.rmtree(recipe_dir)

    return m, need_download


# Next bit of stuff is to support YAML output in the order we expect.
# http://stackoverflow.com/a/17310199/1170370
class _MetaYaml(dict):
    fields = ["package", "source", "build", "requirements", "test", "about", "extra"]

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
        return("Wrote yaml to %s" % filename)
    else:
        return(output)
