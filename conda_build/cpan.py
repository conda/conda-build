"""
Tools for converting CPAN packages to conda recipes.
"""

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import json
import sys
from io import open
from os import makedirs
from os.path import basename, dirname, join, exists

from conda.fetch import download, TmpDownload
from conda.utils import human_bytes, hashsum_file
from conda.install import rm_rf
from conda_build.utils import tar_xf, unzip
from conda_build.source import SRC_CACHE
from conda.compat import input, configparser, StringIO


CPAN_META = """\
package:
  name: {packagename}
  version: !!str {version}

source:
  fn: {filename}
  url: {cpanurl}
  {usemd5}md5: {md5}
#  patches:
   # List any patch files here
   # - fix.patch

{build_comment}build:
  # If this is a new build for the same version, increment the build
  # number. If you do not include this key, it defaults to 0.
  # number: 1

requirements:
  build:
    - perl{build_depends}

  run:
    - perl{run_depends}

# test:
  # By default CPAN tests will be run while "building" (which just uses cpanm
  # to install)

  # You can also put a file called run_test.py in the recipe that will be run
  # at test time.

  # requires:
    # Put any additional test requirements here.  For example
    # - nose

about:
  home: {homeurl}
  license: {license}
  summary: {summary}

# See
# http://docs.continuum.io/conda/build.html for
# more information about meta.yaml
"""

CPAN_BUILD_SH = """\
#!/bin/bash

cpanm .

# Add more build steps here, if they are necessary.

# See
# http://docs.continuum.io/conda/build.html
# for a list of environment variables that are set during the build process.
"""

CPAN_BLD_BAT = """\
cpanm .
if errorlevel 1 exit 1

:: Add more build steps here, if they are necessary.

:: See
:: http://docs.continuum.io/conda/build.html
:: for a list of environment variables that are set during the build process.
"""

def main(args, parser):
    '''
    Creates a bunch of CPAN conda recipes.
    '''

    package_dicts = {}
    [output_dir] = args.output_dir
    indent = '\n    - '

    if len(args.packages) > 1 and args.download:
        print("WARNING: building more than one recipe at once without " +
              "--no-download is not recommended")
    for package in args.packages:
        dir_path = join(output_dir, package.lower())
        packagename = perl_to_conda(package)
        if exists(dir_path):
            raise RuntimeError("directory already exists: %s" % dir_path)
        d = package_dicts.setdefault(package, {'packagename': packagename,
                                               'run_depends':'',
                                               'build_depends':'',
                                               'build_comment':'# ',
                                               'test_commands':'',
                                               'usemd5':''})

        # Fetch all metadata from CPAN
        release_data = get_release_info(args.meta_cpan_url, package,
                                        args.version)

        d['cpanurl'] = release_data['download_url']
        d['md5'], size = get_checksum_and_size(release_data['download_url'])
        d['filename'] = release_data['archive']

        print("Using url %s (%s) for %s." % (d['cpanurl'], size, package))

        try:
            d['homeurl'] = release_data['resources']['homepage']
        except KeyError:
            d['homeurl'] = 'http://metacpan.org/pod/' + package
        d['summary'] = repr(release_data['abstract']).lstrip('u')
        d['license'] = release_data['license'][0]
        d['version'] = release_data['version']

        # Create lists of dependencies
        build_deps = set()
        run_deps = set()
        for dep_dict in release_data['dependency']:
            # Only care about requirements
            if dep_dict['relationship'] == 'requires':
                # Handle runtime deps
                if dep_dict['phase'] == 'runtime':
                    dep_entry = perl_to_conda(dep_dict['module'])
                    if dep_dict['version_numified']:
                        dep_entry += ' ' + dep_dict['version']
                    run_deps.add(dep_entry)

                # Handle build deps
                else:
                    dep_entry = perl_to_conda(dep_dict['module'])
                    if dep_dict['version_numified']:
                        dep_entry += ' ' + dep_dict['version']
                    build_deps.add(dep_entry)

        # Add dependencies to d
        d['build_depends'] = indent.join([''] + list(build_deps))
        d['run_depends'] = indent.join([''] + list(run_deps))


    # Write recipes
    for package in package_dicts:
        d = package_dicts[package]
        package_dir = join(output_dir, packagename)
        if not exists(package_dir):
            makedirs(package_dir)
        print("Writing recipe for %s" % packagename)
        with open(join(package_dir, 'meta.yaml'), 'w') as f:
            f.write(CPAN_META.format(**d))
        with open(join(package_dir, 'build.sh'), 'w') as f:
            f.write(CPAN_BUILD_SH.format(**d))
        with open(join(package_dir, 'bld.bat'), 'w') as f:
            f.write(CPAN_BLD_BAT.format(**d))

    print("Done")


def get_release_info(cpan_url, package, version):
    '''
    Return a dictionary of the JSON information stored at cpan.metacpan.org
    corresponding to the given package/dist/module.
    '''
    # Transform module name to dist name if necessary
    orig_package = package
    package = package.replace('::', '-')

    # Get latest info to find author, which is necessary for retrieving a
    # specific version
    with TmpDownload('{}/v0/release/{}'.format(cpan_url, package)) as json_path:
        with open(json_path, encoding='utf-8-sig') as dist_json_file:
            rel_dict = json.load(dist_json_file)

    # Make sure the dictionary doesn't contain an error code
    if 'code' in rel_dict:
        sys.exit(("Error: Could not find any versions of package %s on " +
                  "MetaCPAN. (%s)") % (orig_package, rel_dict['code']))

    # If the latest isn't the version we're looking for, we have to do another
    # request
    if version is not None and rel_dict['version'] != version:
        author = rel_dict['author']
        with TmpDownload('{}/v0/release/{}/{}-{}'.format(cpan_url,
                                                         author,
                                                         package,
                                                         version)) as json_path:
            with open(json_path, encoding='utf-8-sig') as dist_json_file:
                new_rel_dict = json.load(dist_json_file)
            if 'code' in new_rel_dict:
                sys.exit(("Error: Version %s of %s is not available on " +
                          "MetaCPAN. (%s)") % (version, orig_package,
                                               new_rel_dict['code']))
            else:
                rel_dict = new_rel_dict

    return rel_dict


def get_checksum_and_size(download_url):
    '''
    Looks in the CHECKSUMS file in the same directory as the file specified
    at download_url and returns the md5 hash and file size.
    '''
    base_url = dirname(download_url)
    filename = basename(download_url)
    with TmpDownload(base_url + '/CHECKSUMS') as checksum_path:
        with open(checksum_path) as checksum_file:
            found_file = False
            md5 = None
            size = None
            for line in checksum_file:
                line = line.strip()
                if line.startswith("'" + filename):
                    found_file = True
                elif found_file:
                    if line.startswith("'md5'"):
                        md5 = line.split("=>")[1].strip("', ")
                    elif line.startswith("'size"):
                        size = line.split("=>")[1].strip("', ")
                        break
                    # This should never happen, but just in case
                    elif line.startswith('}'):
                        break
    return md5, size


def perl_to_conda(name):
    ''' Sanitizes a Perl package name for use as a conda package name. '''
    return 'perl-' + name.replace('::', '-').lower()


