"""
Tools for converting CPAN packages to conda recipes.
"""

from __future__ import absolute_import, division, print_function

import codecs
from pkg_resources import parse_version
from glob import glob
import gzip
import json
import os
from os import makedirs
from os.path import basename, dirname, join, exists
import subprocess
import sys
import tempfile

from conda_build.conda_interface import get_index
from conda_build.conda_interface import TmpDownload, download
from conda_build.conda_interface import MatchSpec, Resolve
from conda_build.conda_interface import memoized
from conda_build.conda_interface import CondaHTTPError, CondaError

from conda_build.config import get_or_merge_config
from conda_build.utils import on_win, check_call_env
from conda_build.variants import get_default_variant

import requests

CPAN_META = """\
{{% set name = "{packagename}" %}}
{{% set version = "{version}" %}}
{{% set sha256 = "{sha256}" %}}

package:
  name: {{{{ name }}}}
  version: {{{{ version }}}}

{source_comment}source:
  {useurl}fn: {filename}
  {useurl}url: {cpanurl}
  {usesha256}sha256: {{{{ sha256 }}}}

# If this is a new build for the same version, increment the build
# number. If you do not include this key, it defaults to 0.
build:
  number: 0

requirements:
  build:
    - perl{build_depends}

  run:
    - perl{run_depends}

{import_comment}test:
  # Perl 'use' tests
  {import_comment}imports:{import_tests}

  # You can also put a file called run_test.pl (or run_test.py) in the recipe
  # that will be run at test time.

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

# If it has Build.PL use that, otherwise use Makefile.PL
if [ -f Build.PL ]; then
    perl Build.PL
    perl ./Build
    perl ./Build test
    # Make sure this goes in site
    perl ./Build install --installdirs site
elif [ -f Makefile.PL ]; then
    # Make sure this goes in site
    perl Makefile.PL INSTALLDIRS=site
    make
    make test
    make install
else
    echo 'Unable to find Build.PL or Makefile.PL. You need to modify build.sh.'
    exit 1
fi

# Add more build steps here, if they are necessary.

# See
# http://docs.continuum.io/conda/build.html
# for a list of environment variables that are set during the build process.
"""

CPAN_BLD_BAT = """\
:: If it has Build.PL use that, otherwise use Makefile.PL
IF exist Build.PL (
    perl Build.PL
    IF %ERRORLEVEL% NEQ 0 exit 1
    Build
    IF %ERRORLEVEL% NEQ 0 exit 1
    Build test
    :: Make sure this goes in site
    Build install --installdirs site
    IF %ERRORLEVEL% NEQ 0 exit 1
) ELSE IF exist Makefile.PL (
    :: Make sure this goes in site
    perl Makefile.PL INSTALLDIRS=site
    IF %ERRORLEVEL% NEQ 0 exit 1
    make
    IF %ERRORLEVEL% NEQ 0 exit 1
    make test
    IF %ERRORLEVEL% NEQ 0 exit 1
    make install
) ELSE (
    ECHO 'Unable to find Build.PL or Makefile.PL. You need to modify bld.bat.'
    exit 1
)

:: Add more build steps here, if they are necessary.

:: See
:: http://docs.continuum.io/conda/build.html
:: for a list of environment variables that are set during the build process.
"""

perl_core = []


class InvalidReleaseError(RuntimeError):

    '''
    An exception that is raised when a release is not available on MetaCPAN.
    '''
    pass


class PerlTmpDownload(TmpDownload):

    '''
    Subclass Conda's TmpDownload to replace : in download filenames.
    Critical on win.
    '''

    def __enter__(self):
        if '://' not in self.url:
            # if we provide the file itself, no tmp dir is created
            self.tmp_dir = None
            return self.url
        else:
            if 'CHECKSUMS' in self.url:
                turl = self.url.split('id/')
                filename = turl[1]
            else:
                filename = basename(self.url)

            filename.replace('::', '-')

            self.tmp_dir = tempfile.mkdtemp()

            home = os.path.expanduser('~')
            base_dir = join(home, '.conda-build', 'cpan',
                            basename(self.url).replace('::', '-'))
            dst = join(base_dir, filename)
            dst = dst.replace('::', '-')
            base_dir = dirname(dst)

            if not exists(base_dir):
                makedirs(base_dir)
            if not exists(dst):
                download(self.url, dst)

            return dst


def loose_version(ver):
    return str(parse_version(str(ver)))


def get_cpan_api_url(url, colons):
    if not colons:
        url = url.replace("::", "-")
    with PerlTmpDownload(url) as json_path:
        try:
            with gzip.open(json_path) as dist_json_file:
                output = dist_json_file.read()
            if hasattr(output, "decode"):
                output = output.decode('utf-8-sig')
            rel_dict = json.loads(output)
        except IOError:
            rel_dict = json.loads(codecs.open(
                json_path, encoding='utf-8').read())
        except CondaHTTPError:
            rel_dict = None
    return rel_dict


def package_exists(package_name):
    try:
        cmd = ['cpan', '-D', package_name]
        if on_win:
            cmd.insert(0, '/c')
            cmd.insert(0, 'cmd.exe')
        check_call_env(cmd)
        in_repo = True
    except subprocess.CalledProcessError:
        in_repo = False
    return in_repo


# meta_cpan_url="http://api.metacpan.org",
def skeletonize(packages, output_dir=".", version=None,
                meta_cpan_url="http://fastapi.metacpan.org/v1",
                recursive=False, force=False, config=None, write_core=False):
    '''
    Loops over packages, outputting conda recipes converted from CPAN metata.
    '''

    config = get_or_merge_config(config)
    # TODO: load/use variants?

    perl_version = config.variant.get('perl', get_default_variant(config)['perl'])
    # wildcards are not valid for perl
    perl_version = perl_version.replace(".*", "")
    package_dicts = {}
    indent = '\n    - '
    indent_core = '\n    #- '
    processed_packages = set()
    orig_version = version
    while packages:
        package = packages.pop()
        # If we're passed version in the same format as `PACKAGE=VERSION`
        # update version
        if '=' in package:
            package, _, version = package.partition('=')
        else:
            version = orig_version

        # Skip duplicates
        if package in processed_packages:
            continue
        processed_packages.add(package)

        # Convert modules into distributions
        orig_package = package
        package = dist_for_module(
            meta_cpan_url, package, perl_version, config=config)
        if package == 'perl':
            print(("WARNING: {0} is a Perl core module that is not developed " +
                   "outside of Perl, so we are skipping creating a recipe " +
                   "for it.").format(orig_package))
            continue
        elif package not in {orig_package, orig_package.replace('::', '-')}:
            print(
                ("WARNING: {0} was part of the {1} distribution, so we are " +
                 "making a recipe for {1} instead.").format(orig_package,
                                                            package)
            )

        latest_release_data = get_release_info(meta_cpan_url, package,
                                               None, perl_version,
                                               config=config)
        packagename = perl_to_conda(package)

        # Skip duplicates
        if ((version is not None and ((packagename + '-' + version) in
                                      processed_packages)) or
                ((packagename + '-' + latest_release_data['version']) in
                    processed_packages)):
            continue

        d = package_dicts.setdefault(package, {'packagename': packagename,
                                               'run_depends': '',
                                               'build_depends': '',
                                               'build_comment': '# ',
                                               'test_commands': '',
                                               'usesha256': '',
                                               'useurl': '',
                                               'source_comment': '',
                                               'summary': "''",
                                               'import_tests': ''})

        # Fetch all metadata from CPAN
        if version is None:
            release_data = latest_release_data
        else:
            release_data = get_release_info(meta_cpan_url, package,
                                            parse_version(version),
                                            perl_version,
                                            config=config)

        # Check if recipe directory already exists
        dir_path = join(output_dir, packagename, release_data['version'])

        # Add Perl version to core module requirements, since these are empty
        # packages, unless we're newer than what's in core
        if metacpan_api_is_core_version(meta_cpan_url, package):

            if not write_core:
                print('We found core module %s. Skipping recipe creation.' %
                      packagename)
                continue

            d['useurl'] = '#'
            d['usesha256'] = '#'
            d['source_comment'] = '#'
            empty_recipe = True
        # Add dependencies to d if not in core, or newer than what's in core
        else:
            build_deps, build_core_deps, run_deps, run_core_deps, packages_to_append = \
                deps_for_package(package, release_data=release_data, perl_version=perl_version,
                                 output_dir=output_dir, meta_cpan_url=meta_cpan_url,
                                 recursive=recursive, config=config)

            # Get which deps are in perl_core

            d['build_depends'] += indent.join([''] + list(build_deps |
                                                          run_deps))
            d['build_depends'] += indent_core.join([''] + list(build_core_deps |
                                                               run_core_deps))

            d['run_depends'] += indent.join([''] + list(run_deps))
            d['run_depends'] += indent_core.join([''] + list(run_core_deps))
            # Make sure we append any packages before continuing
            packages.extend(packages_to_append)
            empty_recipe = False

        # If we are recursively getting packages for a particular version
        # we need to make sure this is reset on the loop
        version = None
        if exists(dir_path) and not force:
            print(
                'Directory %s already exists and you have not specified --force ' % dir_path)
            continue
        elif exists(dir_path) and force:
            print('Directory %s already exists, but forcing recipe creation' % dir_path)

        # If this is something we're downloading, get MD5
        d['cpanurl'] = ''
        # Conda build will guess the filename
        d['filename'] = repr('')
        d['sha256'] = ''
        if release_data.get('archive'):
            d['filename'] = basename(release_data['archive'])
        if release_data.get('download_url'):
            d['cpanurl'] = release_data['download_url']
            d['sha256'], size = get_checksum_and_size(
                release_data['download_url'])
            d['filename'] = basename(release_data['download_url'])
            print("Using url %s (%s) for %s." % (d['cpanurl'], size, package))
        else:
            d['useurl'] = '#'
            d['usesha256'] = '#'
            d['source_comment'] = '#'

        try:
            d['homeurl'] = release_data['resources']['homepage']
        except KeyError:
            d['homeurl'] = 'http://metacpan.org/pod/' + package
        if 'abstract' in release_data:
            # TODO this does not escape quotes in a YAML friendly manner
            summary = repr(release_data['abstract']).lstrip('u')
            d['summary'] = summary
            # d['summary'] = repr(release_data['abstract']).lstrip('u')
        try:
            d['license'] = (release_data['license'][0] if
                            isinstance(release_data['license'], list) else
                            release_data['license'])
        except KeyError:
            d['license'] = 'perl_5'
        d['version'] = release_data['version']

        processed_packages.add(packagename + '-' + d['version'])

        # Create import tests
        module_prefix = package.replace('::', '-').split('-')[0]
        if 'provides' in release_data:
            for provided_mod in sorted(set(release_data['provides'])):
                # Filter out weird modules that don't belong
                if (provided_mod.startswith(module_prefix) and
                        '::_' not in provided_mod):
                    d['import_tests'] += indent + provided_mod
        if d['import_tests']:
            d['import_comment'] = ''
        else:
            d['import_comment'] = '# '

        if not exists(dir_path):
            makedirs(dir_path)

        # Write recipe files to a directory
        # TODO def write_recipe
        print("Writing recipe for %s-%s" % (packagename, d['version']))
        with open(join(dir_path, 'meta.yaml'), 'w') as f:
            f.write(CPAN_META.format(**d))
        with open(join(dir_path, 'build.sh'), 'w') as f:
            if empty_recipe:
                f.write('#!/bin/bash\necho "Nothing to do."\n')
            else:
                f.write(CPAN_BUILD_SH.format(**d))
        with open(join(dir_path, 'bld.bat'), 'w') as f:
            if empty_recipe:
                f.write('echo "Nothing to do."\n')
            else:
                f.write(CPAN_BLD_BAT.format(**d))


@memoized
def is_core_version(core_version, version):
    if core_version is None:
        return False
    elif core_version is not None and ((version in [None, '']) or
                                       (core_version >= parse_version(version))):
        return True
    else:
        return False


def add_parser(repos):
    cpan = repos.add_parser(
        "cpan",
        help="""
    Create recipe skeleton for packages hosted on the Comprehensive Perl Archive
    Network (CPAN) (cpan.org).
        """,)
    cpan.add_argument(
        "packages",
        nargs='+',
        help="CPAN packages to create recipe skeletons for.",)
    cpan.add_argument(
        "--output-dir",
        help="Directory to write recipes to (default: %(default)s).",
        default=".",)
    cpan.add_argument(
        "--version",
        help="Version to use. Applies to all packages.",)
    cpan.add_argument(
        "--meta-cpan-url",
        default='http://fastapi.metacpan.org/v1',
        help="URL to use for MetaCPAN API. It must include a version, such as v1",)
    cpan.add_argument(
        "--recursive",
        action='store_true',
        help='Create recipes for dependencies if they do not already exist (default: %(default)s).')
    cpan.add_argument(
        "--force",
        action='store_true',
        help='Force overwrite of existing recipes (default: %(default)s).')
    cpan.add_argument(
        "--write_core",
        action='store_true',
        help='Write recipes for perl core modules (default: %(default)s). ')


@memoized
def latest_pkg_version(pkg):
    '''
    :returns: the latest version of the specified conda package available
    '''
    r = Resolve(get_index())
    try:
        pkg_list = sorted(r.get_pkgs(MatchSpec(pkg)))
    except:
        pkg_list = None
    if pkg_list:
        pkg_version = parse_version(pkg_list[-1].version)
    else:
        pkg_version = None
    return pkg_version


def deps_for_package(package, release_data, perl_version, output_dir,
                     meta_cpan_url, recursive, config):
    '''
    Build the sets of dependencies and packages we need recipes for. This should
    only be called for non-core modules/distributions, as dependencies are
    ignored for core modules.

    :param package: Perl distribution we're checking dependencies of.
    :type package: str
    :param release_data: The metadata about the current release of the package.
    :type release_data: dict
    :param perl_version: The target version of Perl we're building this for.
                         This only really matters for core modules.
    :type perl_version: str
    :param output_dir: The output directory to write recipes to
    :type output_dir: str
    :param processed_packages: The set of packages we have built recipes for
                               already.

    :returns: Build dependencies, runtime dependencies, and set of packages to
              add to list of recipes to create.
    :rtype: 3-tuple of sets
    '''

    # Create lists of dependencies
    build_deps = set()
    build_core_deps = set()
    run_deps = set()
    run_core_deps = set()
    packages_to_append = set()

    print('Processing dependencies for %s...' % package, end='')
    sys.stdout.flush()

    if not release_data.get('dependency'):
        return build_deps, build_core_deps, run_deps, run_core_deps, packages_to_append

    for dep_dict in release_data['dependency']:
        # Only care about requirements
        try:
            if dep_dict['relationship'] == 'requires':
                print('.', end='')
                sys.stdout.flush()
                # Format dependency string (with Perl trailing dist comment)
                orig_dist = dist_for_module(meta_cpan_url, dep_dict['module'],
                                            perl_version, config=config)
                # core_version = core_module_version(
                #     orig_dist, perl_version, config=config)

                dep_entry = perl_to_conda(orig_dist)
                # Skip perl as a dependency, since it's already in list
                if orig_dist.lower() == 'perl':
                    continue

                # See if version is specified
                # There is a dep version and a pkg_version ... why?
                if dep_dict['version'] in {'', 'undef'}:
                    dep_dict['version'] = '0'
                dep_version = parse_version(dep_dict['version'])

                # Make sure specified version is valid
                # TODO def valid_release_info
                try:
                    get_release_info(meta_cpan_url, dep_dict['module'],
                                     dep_version, perl_version, dependency=True, config=config)
                except InvalidReleaseError:
                    print(('WARNING: The version of %s listed as a ' +
                           'dependency for %s, %s, is not available on MetaCPAN, ' +
                           'so we are just assuming the latest version is ' +
                           'okay.') % (orig_dist, package, str(dep_version)))
                    dep_version = parse_version('0')

                # Add version number to dependency, if it's newer than latest
                # we have package for.
                if loose_version(dep_version) > loose_version('0'):

                    pkg_version = latest_pkg_version(dep_entry)
                    # If we don't have a package, use core version as version
                    if pkg_version is None:
                        # pkg_version = core_module_version(dep_entry,
                        #                                   perl_version,
                        #                                   config=config)
                        # print('dep entry is {}'.format(dep_entry))
                        pkg_version = metacpan_api_get_core_version(
                            meta_cpan_url, dep_dict['module'])
                    # If no package is available at all, it's in the core, or
                    # the latest is already good enough, don't specify version.
                    # This is because conda doesn't support > in version
                    # requirements.
                    # J = Conda does support >= ?
                    try:
                        if pkg_version is not None and (
                                loose_version(dep_version) > loose_version(pkg_version)):
                            dep_entry += ' ' + dep_dict['version']
                    except Exception:
                        print(
                            'We have got an expected error with dependency versions')
                        print('Module {}'.format(dep_dict['module']))
                        print('Pkg_version {}'.format(pkg_version))
                        print('Dep Version {}'.format(dep_version))

                # If recursive, check if we have a recipe for this dependency
                if recursive:
                    # If dependency entry is versioned, make sure this is too
                    if ' ' in dep_entry:
                        if not exists(join(output_dir, dep_entry.replace('::',
                                                                         '-'))):
                            packages_to_append.add('='.join((orig_dist,
                                                             dep_dict['version'])))
                    elif not glob(join(output_dir, (dep_entry + '-[v1-9][0-9.]*'))):
                        packages_to_append.add(orig_dist)

                # Add to appropriate dependency list
                core = metacpan_api_is_core_version(
                    meta_cpan_url, dep_dict['module'])

                if dep_dict['phase'] == 'runtime':
                    if core:
                        run_core_deps.add(dep_entry)
                    else:
                        run_deps.add(dep_entry)
                # Handle build deps
                elif dep_dict['phase'] != 'develop':
                    if core:
                        build_core_deps.add(dep_entry)
                    else:
                        build_deps.add(dep_entry)
        # seemingly new in conda 4.3: HTTPErrors arise when we ask for
        # something that is a
        # perl module, but not a package.
        # See https://github.com/conda/conda-build/issues/1675
        except (CondaError, CondaHTTPError):
            continue

    return build_deps, build_core_deps, run_deps, run_core_deps, packages_to_append


@memoized
def dist_for_module(cpan_url, module, perl_version, config):
    '''
    Given a name that could be a module or a distribution, return the
    distribution.
    '''
    # First check if its already a distribution
    rel_dict = release_module_dict(cpan_url, module)
    if rel_dict is not None:
        distribution = module
    else:
        # Check if it's a module instead
        mod_dict = core_module_dict(cpan_url, module)
        distribution = mod_dict['distribution']

    return distribution


def release_module_dict(cpan_url, module):
    try:
        rel_dict = get_cpan_api_url(
            '{0}/release/{1}'.format(cpan_url, module), colons=False)
    # If there was an error, module may actually be a module
    except RuntimeError:
        rel_dict = None
    except CondaHTTPError:
        rel_dict = None

    return rel_dict


def core_module_dict(cpan_url, module):
    try:
        mod_dict = get_cpan_api_url(
            '{0}/module/{1}'.format(cpan_url, module), colons=True)
        # If there was an error, report it
    except CondaHTTPError:
        sys.exit(('Error: Could not find module or distribution named'
                  ' %s on MetaCPAN. Error was: %s') % (module))
    else:
        mod_dict = {}
        mod_dict['distribution'] = 'perl'

    return mod_dict


@memoized
def metacpan_api_is_core_version(cpan_url, module):

    url = '{0}/release/{1}'.format(cpan_url, module)
    url = url.replace("::", "-")
    req = requests.get(url)

    if req.status_code == 200:
        return False
    else:
        url = '{0}/module/{1}'.format(cpan_url, module)
        req = requests.get(url)
        if req.status_code == 200:
            return True
        else:
            sys.exit(('Error: Could not find module or distribution named'
                      ' %s on MetaCPAN.')
                     % (module))


def metacpan_api_get_core_version(cpan_url, module):

    module_dict = core_module_dict(cpan_url, module)
    try:
        version = module_dict['module'][-1]['version']
    except Exception:
        version = None

    return version


def get_release_info(cpan_url, package, version, perl_version, config,
                     dependency=False):
    '''
    Return a dictionary of the JSON information stored at cpan.metacpan.org
    corresponding to the given package/dist/module.
    '''
    # Transform module name to dist name if necessary
    orig_package = package
    package = dist_for_module(cpan_url, package, perl_version, config=config)

    # Get latest info to find author, which is necessary for retrieving a
    # specific version
    try:
        rel_dict = get_cpan_api_url(
            '{0}/release/{1}'.format(cpan_url, package), colons=False)
        rel_dict['version'] = str(rel_dict['version']).lstrip('v')
    except CondaHTTPError:
        core_version = metacpan_api_is_core_version(cpan_url, package)
        if core_version is not None and (version is None or
                                         (version == core_version)):
            print(("WARNING: {0} is not available on MetaCPAN, but it's a " +
                   "core module, so we do not actually need the source file, " +
                   "and are omitting the URL and MD5 from the recipe " +
                   "entirely.").format(orig_package))
            rel_dict = {'version': str(core_version), 'download_url': '',
                        'license': ['perl_5'], 'dependency': {}}
        else:
            sys.exit(("Error: Could not find any versions of package %s on " +
                      "MetaCPAN.") % (orig_package))

    version_mismatch = False

    if version is not None:
        version_str = str(version)
        rel_version = str(rel_dict['version'])
        loose_str = str(parse_version(version_str))

        try:
            version_mismatch = (version is not None) and (
                loose_version('0') != loose_version(version_str) and
                parse_version(rel_version) != loose_version(version_str))
            # print(version_mismatch)
        except Exception as e:
            print('We have some strange version mismatches. Please investigate.')
            print(e)
            print('Package {}'.format(package))
            print('Version {}'.format(version))
            print('Pkg Version {}'.format(rel_dict['version']))
            print('Loose Version {}'.format(loose_str))

    # TODO  - check for major/minor version mismatches
    # Allow for minor
    if version_mismatch:
        print('We have a version mismatch!')
        print('Version: {}, RelVersion: {}'.format(version_str, rel_version))

    return rel_dict


def get_checksum_and_size(download_url):
    '''
    Looks in the CHECKSUMS file in the same directory as the file specified
    at download_url and returns the sha256 hash and file size.
    '''
    base_url = dirname(download_url)
    filename = basename(download_url)
    with PerlTmpDownload(base_url + '/CHECKSUMS') as checksum_path:
        with open(checksum_path) as checksum_file:
            found_file = False
            sha256 = None
            size = None
            for line in checksum_file:
                line = line.strip()
                if line.startswith("'" + filename):
                    found_file = True
                elif found_file:
                    if line.startswith("'sha256'"):
                        sha256 = line.split("=>")[1].strip("', ")
                    elif line.startswith("'size"):
                        size = line.split("=>")[1].strip("', ")
                        break
                    # This should never happen, but just in case
                    elif line.startswith('}'):
                        break
    return sha256, size


def perl_to_conda(name):
    ''' Sanitizes a Perl package name for use as a conda package name. '''
    return 'perl-' + name.replace('::', '-').lower()
