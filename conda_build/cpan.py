"""
Tools for converting CPAN packages to conda recipes.
"""

from __future__ import absolute_import, division, print_function

import json
import subprocess
import sys
from distutils.version import LooseVersion
from glob import glob
from os import makedirs
from os.path import basename, dirname, join, exists
import io

from conda.api import get_index
from conda.fetch import TmpDownload
from conda.resolve import MatchSpec, Resolve
from conda.utils import memoized

from conda_build.config import config


CPAN_META = """\
package:
  name: {packagename}
  version: "{version}"

source:
  {useurl}fn: {filename}
  {useurl}url: {cpanurl}
  {usemd5}md5: {md5}
#  patches:
   # List any patch files here
   # - fix.patch

{build_comment}build:
  # If this is a new build for the same version, increment the build
  # number. If you do not include this key, it defaults to 0.
  {build_comment}number: 1

requirements:
  build:
    - perl{build_depends}

  run:
    - perl{run_depends}

test:
  # Perl 'use' tests
  {import_comment}imports:{import_tests}

  # You can also put a file called run_test.pl (or run_test.py) in the recipe
  # that will be run at test time.

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

# If it has Build.PL use that, otherwise use Makefile.PL
if [ -f Build.PL ]; then
    perl Build.PL
    ./Build
    ./Build test
    # Make sure this goes in site
    ./Build install --installdirs site
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
    IF errorlevel 1 exit 1
    Build
    IF errorlevel 1 exit 1
    Build test
    :: Make sure this goes in site
    Build install --installdirs site
    IF errorlevel 1 exit 1
) ELSE IF exist Makefile.PL (
    :: Make sure this goes in site
    perl Makefile.PL INSTALLDIRS=site
    IF errorlevel 1 exit 1
    make
    IF errorlevel 1 exit 1
    make test
    IF errorlevel 1 exit 1
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


class InvalidReleaseError(RuntimeError):
    '''
    An exception that is raised when a release is not available on MetaCPAN.
    '''
    pass


def main(args, parser):
    '''
    Creates a bunch of CPAN conda recipes.
    '''
    perl_version = config.CONDA_PERL
    package_dicts = {}
    [output_dir] = args.output_dir
    indent = '\n    - '
    args.packages = list(reversed(args.packages))
    processed_packages = set()
    orig_version = args.version
    while args.packages:
        package = args.packages.pop()
        # If we're passed version in the same format as `PACKAGE=VERSION`
        # update version
        if '=' in package:
            package, __, args.version = package.partition('=')
        else:
            args.version = orig_version

        # Skip duplicates
        if package in processed_packages:
            continue
        processed_packages.add(package)

        # Convert modules into distributions
        orig_package = package
        package = dist_for_module(args.meta_cpan_url, package, perl_version)
        if package == 'perl':
            print(("WARNING: {0} is a Perl core module that is not developed " +
                   "outside of Perl, so we are skipping creating a recipe " +
                   "for it.").format(orig_package))
            continue
        elif package not in {orig_package, orig_package.replace('::', '-')}:
            print(("WARNING: {0} was part of the {1} distribution, so we are " +
                   "making a recipe for {1} instead.").format(orig_package,
                                                              package))

        latest_release_data = get_release_info(args.meta_cpan_url, package,
                                               None, perl_version)
        packagename = perl_to_conda(package)

        # Skip duplicates
        if ((args.version is not None and ((packagename + '-' + args.version) in
                                           processed_packages)) or
                ((packagename + '-' + latest_release_data['version']) in
                 processed_packages)):
            continue

        d = package_dicts.setdefault(package, {'packagename': packagename,
                                               'run_depends': '',
                                               'build_depends': '',
                                               'build_comment': '# ',
                                               'test_commands': '',
                                               'usemd5': '',
                                               'useurl': '',
                                               'summary': "''",
                                               'import_tests': ''})

        # Fetch all metadata from CPAN
        core_version = core_module_version(package, perl_version)
        release_data = get_release_info(args.meta_cpan_url, package,
                                        (LooseVersion(args.version) if
                                         args.version is not None else
                                         core_version),
                                        perl_version)
        # Check if versioned recipe directory already exists
        dir_path = join(output_dir, '-'.join((packagename,
                                              release_data['version'])))
        if exists(dir_path):
            raise RuntimeError("directory already exists: %s" % dir_path)

        # If this is something we're downloading, get MD5
        if release_data['download_url']:
            d['cpanurl'] = release_data['download_url']
            d['md5'], size = get_checksum_and_size(release_data['download_url'])
            d['filename'] = basename(release_data['archive'])
            print("Using url %s (%s) for %s." % (d['cpanurl'], size, package))
        else:
            d['useurl'] = '#'
            d['usemd5'] = '#'
            d['cpanurl'] = ''
            d['filename'] = ''
            d['md5'] = ''

        try:
            d['homeurl'] = release_data['resources']['homepage']
        except KeyError:
            d['homeurl'] = 'http://metacpan.org/pod/' + package
        if 'abstract' in release_data:
            d['summary'] = repr(release_data['abstract']).lstrip('u')
        d['license'] = (release_data['license'][0] if
                        isinstance(release_data['license'], list) else
                        release_data['license'])
        d['version'] = release_data['version']

        processed_packages.add(packagename + '-' + d['version'])

        # Add Perl version to core module requirements, since these are empty
        # packages, unless we're newer than what's in core
        if core_version is not None and ((args.version is None) or
                                         (core_version >=
                                          LooseVersion(args.version))):
            d['useurl'] = '#'
            d['usemd5'] = '#'
            empty_recipe = True
        # Add dependencies to d if not in core, or newer than what's in core
        else:
            build_deps, run_deps, packages_to_append = deps_for_package(
                package, release_data, perl_version, args, output_dir,
                processed_packages)
            d['build_depends'] += indent.join([''] + list(build_deps |
                                                          run_deps))
            d['run_depends'] += indent.join([''] + list(run_deps))
            args.packages.extend(packages_to_append)
            empty_recipe = False

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

        # Write recipe files to a versioned directory
        makedirs(dir_path)
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

    print("Done")


@memoized
def latest_pkg_version(pkg):
    '''
    :returns: the latest version of the specified conda package available
    '''
    r = Resolve(get_index())
    try:
        pkg_list = sorted(r.get_pkgs(MatchSpec(pkg)))
    except RuntimeError:
        pkg_list = None
    if pkg_list:
        pkg_version = LooseVersion(pkg_list[-1].version)
    else:
        pkg_version = None
    return pkg_version


@memoized
def core_module_version(module, version):
    '''
    :param module: Name of a Perl core module
    :type module: str

    :returns: The version of the specified module that is currently available
              in the specified version of Perl. If the version is `undef`, but
              the module is actually part of the Perl core, the version of Perl
              passed in will be used as the module version.
    '''
    # In case we were given a dist, convert to module
    module = module.replace('-', '::')
    if version is None:
        version = LooseVersion(config.CONDA_PERL)
    else:
        version = LooseVersion(version)
    cmd = ['corelist', '-v', str(version), module]
    try:
        output = subprocess.check_output(cmd).decode('utf-8')
    except subprocess.CalledProcessError:
        sys.exit(('Error: command failed: %s\nPlease make sure you have ' +
                  'the perl conda package installed in your default ' +
                  'environment.') % ' '.join(cmd))
    mod_version = output.split()[1]
    # If undefined, that could either mean it's versionless or not in core
    if mod_version == 'undef':
        # Check if it's actually in core
        cmd = ['corelist', module]
        output = subprocess.check_output(cmd).decode('utf-8')
        # If it's in core...
        if 'perl v' in output:
            first_version = output.partition('perl v')[2].strip()
            first_version = LooseVersion(first_version)
            # If it's newer than the specified version, return None
            if LooseVersion(first_version) > LooseVersion(version):
                mod_version = None
            else:
                mod_version = version
        # If it's not, return None
        else:
            mod_version = None
    else:
        mod_version = LooseVersion(mod_version)

    return mod_version


def deps_for_package(package, release_data, perl_version, args, output_dir,
                     processed_packages):
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
    :param args: The command-line arguments passed to the skeleton command.
    :type args: Namespace
    :param output_dir: The output directory to write recipes to
    :type output_dir: str
    :param processed_packages: The set of packages we have built recipes for
                               already.
    :type processed_packages: set of str

    :returns: Build dependencies, runtime dependencies, and set of packages to
              add to list of recipes to create.
    :rtype: 3-tuple of sets
    '''

    # Create lists of dependencies
    build_deps = set()
    run_deps = set()
    packages_to_append = set()
    print('Processing dependencies for %s...' % package, end='')
    sys.stdout.flush()
    for dep_dict in release_data['dependency']:
        # Only care about requirements
        if dep_dict['relationship'] == 'requires':
            print('.', end='')
            sys.stdout.flush()
            # Format dependency string (with Perl trailing dist comment)
            orig_dist = dist_for_module(args.meta_cpan_url, dep_dict['module'],
                                        perl_version)
            dep_entry = perl_to_conda(orig_dist)
            # Skip perl as a dependency, since it's already in list
            if orig_dist.lower() == 'perl':
                continue

            # See if version is specified
            if dep_dict['version'] in {'', 'undef'}:
                dep_dict['version'] = '0'
            dep_version = LooseVersion(dep_dict['version'])

            # Make sure specified version is valid
            try:
                get_release_info(args.meta_cpan_url, dep_dict['module'],
                                 dep_version, perl_version, dependency=True)
            except InvalidReleaseError:
                print(('WARNING: The version of %s listed as a ' +
                       'dependency for %s, %s, is not available on MetaCPAN, ' +
                       'so we are just assuming the latest version is ' +
                       'okay.') % (orig_dist, package, str(dep_version)))
                dep_version = LooseVersion('0')

            # Add version number to dependency, if it's newer than latest
            # we have package for.
            if dep_version > LooseVersion('0'):
                pkg_version = latest_pkg_version(dep_entry)
                # If we don't have a package, use core version as version
                if pkg_version is None:
                    pkg_version = core_module_version(dep_entry,
                                                      perl_version)
                # If no package is available at all, it's in the core, or
                # the latest is already good enough, don't specify version.
                # This is because conda doesn't support > in version
                # requirements.
                if pkg_version is not None and (dep_version > pkg_version):
                    dep_entry += ' ' + dep_dict['version']

            # If recursive, check if we have a recipe for this dependency
            if args.recursive:
                # If dependency entry is versioned, make sure this is too
                if ' ' in dep_entry:
                    if not exists(join(output_dir, dep_entry.replace('::',
                                                                     '-'))):
                        packages_to_append.add('='.join((orig_dist,
                                                         dep_dict['version'])))
                elif not glob(join(output_dir, (dep_entry + '-[v0-9][0-9.]*'))):
                    packages_to_append.add(orig_dist)

            # Add to appropriate dependency list
            if dep_dict['phase'] == 'runtime':
                run_deps.add(dep_entry)
            # Handle build deps
            elif dep_dict['phase'] != 'develop':
                build_deps.add(dep_entry)
    print('done')
    sys.stdout.flush()

    return build_deps, run_deps, packages_to_append

@memoized
def dist_for_module(cpan_url, module, perl_version):
    '''
    Given a name that could be a module or a distribution, return the
    distribution.
    '''
    # First check if its already a distribution
    try:
        with TmpDownload('{}/v0/release/{}'.format(cpan_url,
                                                   module)) as json_path:
            with io.open(json_path, encoding='utf-8-sig') as dist_json_file:
                rel_dict = json.load(dist_json_file)
    # If there was an error, module may actually be a module
    except RuntimeError:
        rel_dict = None
    else:
        distribution = module

    # Check if
    if rel_dict is None:
        try:
            with TmpDownload('{}/v0/module/{}'.format(cpan_url,
                                                      module)) as json_path:
                with io.open(json_path, encoding='utf-8-sig') as dist_json_file:
                    mod_dict = json.load(dist_json_file)
        # If there was an error, report it
        except RuntimeError:
            core_version = core_module_version(module, perl_version)
            if core_version is None:
                sys.exit(('Error: Could not find module or distribution named' +
                          ' %s on MetaCPAN') % module)
            else:
                distribution = 'perl'
        else:
            distribution = mod_dict['distribution']

    return distribution


def get_release_info(cpan_url, package, version, perl_version,
                     dependency=False):
    '''
    Return a dictionary of the JSON information stored at cpan.metacpan.org
    corresponding to the given package/dist/module.
    '''
    # Transform module name to dist name if necessary
    orig_package = package
    package = dist_for_module(cpan_url, package, perl_version)
    package = package.replace('::', '-')

    # Get latest info to find author, which is necessary for retrieving a
    # specific version
    try:
        with TmpDownload('{}/v0/release/{}'.format(cpan_url, package)) as json_path:
            with io.open(json_path, encoding='utf-8-sig') as dist_json_file:
                rel_dict = json.load(dist_json_file)
                rel_dict['version'] = rel_dict['version'].lstrip('v')
    except RuntimeError as e:
        core_version = core_module_version(orig_package, perl_version)
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

    # If the latest isn't the version we're looking for, we have to do another
    # request
    version_str = str(version)
    if (version is not None) and (version != LooseVersion('0') and
            (rel_dict['version'] != version_str)):
        author = rel_dict['author']
        try:
            with TmpDownload('{}/v0/release/{}/{}-{}'.format(cpan_url,
                                                             author,
                                                             package,
                                                             version_str)) as json_path:
                with io.open(json_path, encoding='utf-8-sig') as dist_json_file:
                    new_rel_dict = json.load(dist_json_file)
                    new_rel_dict['version'] = new_rel_dict['version'].lstrip()
        # Check if this is a core module, and don't die if it is
        except RuntimeError:
            core_version = core_module_version(orig_package, perl_version)
            if core_version is not None and (version == core_version):
                print(("WARNING: Version {0} of {1} is not available on " +
                       "MetaCPAN, but it's a core module, so we do not " +
                       "actually need the source file, and are omitting the " +
                       "URL and MD5 from the recipe " +
                       "entirely.").format(version_str, orig_package))
                rel_dict['version'] = version_str
                rel_dict['download_url'] = ''
            elif LooseVersion(rel_dict['version']) > version:
                if not dependency:
                    print(("WARNING: Version {0} of {1} is not available on " +
                           "MetaCPAN, but a newer version ({2}) is, so we " +
                           "will use that " +
                           "instead.").format(version_str, orig_package,
                                              rel_dict['version']))
            else:
                raise InvalidReleaseError(("Version %s of %s is not available" +
                                           " on MetaCPAN. You may want to use" +
                                           " the latest version, %s, instead.")
                                          % (version_str, orig_package,
                                             rel_dict['version']))
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
