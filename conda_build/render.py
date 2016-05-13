# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

import shutil
import sys
import tarfile
import tempfile
import os
from os.path import isdir, isfile, abspath
from locale import getpreferredencoding
import subprocess

from conda.compat import PY3
from conda.lock import Locked

from conda_build import exceptions
from conda_build.config import config
from conda_build.metadata import MetaData
import conda_build.source as source
from conda_build.completers import all_versions, conda_version


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
        if hasattr(config, var):
            # Set the env variable.
            os.environ[var] = str(getattr(config, var))


def parse_or_try_download(metadata, no_download_source):
    if not no_download_source:
        # this try/catch is for when the tool to download source is actually in
        #    meta.yaml, and not previously installed in builder env.
        try:
            source.provide(metadata.path, metadata.get_section('source'))
            metadata.parse_again(permit_undefined_jinja=False)
            need_source_download = False
        except subprocess.CalledProcessError:
            print("Warning: failed to download source.  If building, will try "
                  "again after downloading recipe dependencies.")
            need_source_download = True
    else:
        metadata.parse_again(permit_undefined_jinja=False)
        need_source_download = no_download_source
    return metadata, need_source_download


def render_recipe(recipe_path, no_download_source):
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

        m = parse_or_try_download(m, no_download_source=no_download_source)

        if need_cleanup:
            shutil.rmtree(recipe_dir)

    return m
