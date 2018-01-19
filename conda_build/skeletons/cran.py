"""
Tools for converting Cran packages to conda recipes.
"""

from __future__ import absolute_import, division, print_function

from itertools import chain
from os import makedirs, listdir, sep
from os.path import (basename, commonprefix, exists, isabs,
                     isdir, isfile, join, normpath, realpath)
import re
import subprocess
import sys
import hashlib

import requests
import tarfile
import unicodedata
import yaml

# try to import C dumper
try:
    from yaml import CSafeDumper as SafeDumper
except ImportError:
    from yaml import SafeDumper

from conda_build import source, metadata
from conda_build.config import Config
from conda_build.conda_interface import text_type, iteritems
from conda_build.license_family import allowed_license_families, guess_license_family
from conda_build.utils import rm_rf

CRAN_META = """\
{{% set version = '{cran_version}' %}}

{{% set posix = 'm2-' if win else '' %}}
{{% set native = 'm2w64-' if win else '' %}}

package:
  name: {packagename}
  version: {{{{ version|replace("-", "_") }}}}

source:
  {fn_key} {filename}
  {url_key} {cranurl}
  {hash_entry}
  {git_url_key} {git_url}
  {git_tag_key} {git_tag}
  {patches}

build:
  merge_build_host: True  # [win]
  # If this is a new build for the same version, increment the build number.
  number: {build_number}
  {noarch_generic}

  # This is required to make R link correctly on Linux.
  rpaths:
    - lib/R/lib/
    - lib/
  {script_env}
{suggests}
requirements:
  build:{build_depends}

  host:{host_depends}

  run:{run_depends}

test:
  commands:
    # You can put additional test commands to be run here.
    - $R -e "library('{cran_packagename}')"           # [not win]
    - "\\"%R%\\" -e \\"library('{cran_packagename}')\\""  # [win]

  # You can also put a file called run_test.py, run_test.sh, or run_test.bat
  # in the recipe that will be run at test time.

  # requires:
    # Put any additional test requirements here.

about:
  {home_comment}home:{homeurl}
  license: {license}
  {summary_comment}summary:{summary}
  license_family: {license_family}

{extra_recipe_maintainers}

# The original CRAN metadata for this package was:

{cran_metadata}

# See
# http://docs.continuum.io/conda/build.html for
# more information about meta.yaml

"""

CRAN_BUILD_SH = """\
#!/bin/bash

# 'Autobrew' is being used by more and more packages these days
# to grab static libraries from Homebrew bottles. These bottles
# are fetched via Homebrew's --force-bottle option which grabs
# a bottle for the build machine which may not be macOS 10.9.
# Also, we want to use conda packages (and shared libraries) for
# these 'system' dependencies. See:
# https://github.com/jeroen/autobrew/issues/3
export DISABLE_AUTOBREW=1

# R refuses to build packages that mark themselves as Priority: Recommended
mv DESCRIPTION DESCRIPTION.old
grep -v '^Priority: ' DESCRIPTION.old > DESCRIPTION
$R CMD INSTALL --build .

# Add more build steps here, if they are necessary.

# See
# http://docs.continuum.io/conda/build.html
# for a list of environment variables that are set during the build process.
"""

CRAN_BLD_BAT = """\
"%R%" CMD INSTALL --build .
IF %ERRORLEVEL% NEQ 0 exit 1

@rem Add more build steps here, if they are necessary.

@rem See
@rem http://docs.continuum.io/conda/build.html
@rem for a list of environment variables that are set during the build process.
"""

INDENT = '\n    - '

CRAN_KEYS = [
    'Site',
    'Archs',
    'Depends',
    'Enhances',
    'Imports',
    'License',
    'License_is_FOSS',
    'License_restricts_use',
    'LinkingTo',
    'MD5sum',
    'NeedsCompilation',
    'OS_type',
    'Package',
    'Path',
    'Priority',
    'Suggests',
    'Version',

    'Title',
    'Author',
    'Maintainer',
]

# The following base/recommended package names are derived from R's source
# tree (R-3.0.2/share/make/vars.mk).  Hopefully they don't change too much
# between versions.
R_BASE_PACKAGE_NAMES = (
    'base',
    'compiler',
    'datasets',
    'graphics',
    'grDevices',
    'grid',
    'methods',
    'parallel',
    'splines',
    'stats',
    'stats4',
    'tcltk',
    'tools',
    'utils',
)

R_RECOMMENDED_PACKAGE_NAMES = (
    'MASS',
    'lattice',
    'Matrix',
    'nlme',
    'survival',
    'boot',
    'cluster',
    'codetools',
    'foreign',
    'KernSmooth',
    'rpart',
    'class',
    'nnet',
    'spatial',
    'mgcv',
)

# Stolen then tweaked from debian.deb822.PkgRelation.__dep_RE.
VERSION_DEPENDENCY_REGEX = re.compile(
    r'^\s*(?P<name>[a-zA-Z0-9.+\-]{1,})'
    r'(\s*\(\s*(?P<relop>[>=<]+)\s*'
    r'(?P<version>[0-9a-zA-Z:\-+~.]+)\s*\))'
    r'?(\s*\[(?P<archs>[\s!\w\-]+)\])?\s*$'
)


def package_exists(package_name):
    # TODO: how can we get cran to spit out package presence?
    # available.packages() is probably a start, but no channels are working on mac right now?
    return True
    # install_output = subprocess.check_output([join(sys.prefix, "r"), "-e",
    #                     # ind=2 arbitrarily chooses some CRAN mirror to try.
    #                     "chooseCRANmirror(ind=2);install.packages('{}')".format(package_name)])


def add_parser(repos):
    cran = repos.add_parser(
        "cran",
        help="""
    Create recipe skeleton for packages hosted on the Comprehensive R Archive
    Network (CRAN) (cran.r-project.org).
        """,
    )
    cran.add_argument(
        "packages",
        nargs='+',
        help="""CRAN packages to create recipe skeletons for.""",
    )
    cran.add_argument(
        "--output-dir",
        help="Directory to write recipes to (default: %(default)s).",
        default=".",
    )
    cran.add_argument(
        "--output-suffix",
        help="Suffix to add to recipe dir, can contain other dirs (eg: -feedstock/recipe).",
        default="",
    )
    cran.add_argument(
        "--add-maintainer",
        help="Add this github username as a maintainer if not already present.",
        default=None,
    )
    cran.add_argument(
        "--version",
        help="Version to use. Applies to all packages.",
    )
    cran.add_argument(
        "--git-tag",
        help="Git tag to use for GitHub recipes.",
    )
    cran.add_argument(
        "--all-urls",
        action="store_true",
        help="""Look at all URLs, not just source URLs. Use this if it can't
                find the right URL.""",
    )
    cran.add_argument(
        "--cran-url",
        default='https://cran.r-project.org/',
        help="URL to use for CRAN (default: %(default)s).",
    )
    cran.add_argument(
        "--recursive",
        action='store_true',
        dest='recursive',
        help='Create recipes for dependencies if they do not already exist.',
    )
    cran.add_argument(
        "--no-recursive",
        action='store_false',
        dest='recursive',
        help="Don't create recipes for dependencies if they do not already exist.",
    )
    cran.add_argument(
        '--no-archive',
        action='store_false',
        dest='archive',
        help="Don't include an Archive download url.",
    )
    cran.add_argument(
        "--version-compare",
        action='store_true',
        help="""Compare the package version of the recipe with the one available
        on CRAN. Exits 1 if a newer version is available and 0 otherwise."""
    )
    cran.add_argument(
        "--update-policy",
        action='store',
        choices=('error',
                 'skip-up-to-date',
                 'skip-existing',
                 'overwrite',
                 'merge-keep-build-num',
                 'merge-incr-build-num'),
        default='error',
        help="""Dictates what to do when existing packages are encountered in the
        output directory (set by --output-dir). In the present implementation, the
        merge options avoid overwriting bld.bat and build.sh and only manage copying
        across patches, and the `build/{number,script_env}` fields. When the version
        changes, both merge options reset `build/number` to 0. When the version does
        not change they either keep the old `build/number` or else increase it by one."""
    )


def dict_from_cran_lines(lines):
    d = {}
    for line in lines:
        if not line:
            continue
        try:
            if ': ' in line:
                (k, v) = line.split(': ', 1)
            else:
                # Sometimes fields are included but left blank, e.g.:
                #   - Enhances in data.tree
                #   - Suggests in corpcor
                (k, v) = line.split(':', 1)
        except ValueError:
            sys.exit("Error: Could not parse metadata (%s)" % line)
        d[k] = v
        # if k not in CRAN_KEYS:
        #     print("Warning: Unknown key %s" % k)
    d['orig_lines'] = lines
    return d


def remove_package_line_continuations(chunk):
    """
    >>> chunk = [
        'Package: A3',
        'Version: 0.9.2',
        'Depends: R (>= 2.15.0), xtable, pbapply',
        'Suggests: randomForest, e1071',
        'Imports: MASS, R.methodsS3 (>= 1.5.2), R.oo (>= 1.15.8), R.utils (>=',
        '        1.27.1), matrixStats (>= 0.8.12), R.filesets (>= 2.3.0), ',
        '        sampleSelection, scatterplot3d, strucchange, systemfit',
        'License: GPL (>= 2)',
        'NeedsCompilation: no']
    >>> remove_package_line_continuations(chunk)
    ['Package: A3',
     'Version: 0.9.2',
     'Depends: R (>= 2.15.0), xtable, pbapply',
     'Suggests: randomForest, e1071',
     'Imports: MASS, R.methodsS3 (>= 1.5.2), R.oo (>= 1.15.8), R.utils (>= 1.27.1), matrixStats (>= 0.8.12), R.filesets (>= 2.3.0), sampleSelection, scatterplot3d, strucchange, systemfit, rgl,'
     'License: GPL (>= 2)',
     'NeedsCompilation: no']
    """  # NOQA
    continuation = (' ', '\t')
    continued_ix = None
    continued_line = None
    had_continuation = False
    accumulating_continuations = False

    chunk.append('')

    for (i, line) in enumerate(chunk):
        if line.startswith(continuation):
            line = ' ' + line.lstrip()
            if accumulating_continuations:
                assert had_continuation
                continued_line += line
                chunk[i] = None
            else:
                accumulating_continuations = True
                continued_ix = i - 1
                continued_line = chunk[continued_ix] + line
                had_continuation = True
                chunk[i] = None
        else:
            if accumulating_continuations:
                assert had_continuation
                chunk[continued_ix] = continued_line
                accumulating_continuations = False
                continued_line = None
                continued_ix = None

    if had_continuation:
        # Remove the None(s).
        chunk = [c for c in chunk if c]

    chunk.append('')

    return chunk


def yaml_quote_string(string):
    """
    Quote a string for use in YAML.

    We can't just use yaml.dump because it adds ellipses to the end of the
    string, and it in general doesn't handle being placed inside an existing
    document very well.

    Note that this function is NOT general.
    """
    return yaml.dump(string, Dumper=SafeDumper).replace('\n...\n', '').replace('\n', '\n  ')


def clear_trailing_whitespace(string):
    lines = []
    for line in string.splitlines():
        lines.append(line.rstrip())
    return '\n'.join(lines)


def get_package_metadata(cran_url, package, session):
    url = cran_url + 'web/packages/' + package + '/DESCRIPTION'
    r = session.get(url)
    try:
        r.raise_for_status()
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            sys.exit("ERROR: %s (404 Not Found)" % url)
        raise
    DESCRIPTION = r.text
    d = dict_from_cran_lines(remove_package_line_continuations(DESCRIPTION.splitlines()))
    d['orig_description'] = DESCRIPTION
    return d


def get_latest_git_tag(config):
    # SO says to use taggerdate instead of committerdate, but that is invalid for lightweight tags.
    p = subprocess.Popen(['git', 'for-each-ref',
                                 'refs/tags',
                                 '--sort=-committerdate',
                                 '--format=%(refname:short)',
                                 '--count=1'], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         cwd=config.work_dir)

    stdout, stderr = p.communicate()
    stdout = stdout.decode('utf-8')
    stderr = stderr.decode('utf-8')
    if stderr or p.returncode:
        sys.exit("Error: git tag failed (%s)" % stderr)
    tags = stdout.strip().splitlines()
    if not tags:
        sys.exit("Error: no tags found")

    print("Using tag %s" % tags[-1])
    return tags[-1]


def get_session(output_dir, verbose=True):
    session = requests.Session()
    try:
        import cachecontrol
        import cachecontrol.caches
    except ImportError:
        if verbose:
            print("Tip: install CacheControl and lockfile (conda packages) to cache the "
                  "CRAN metadata")
    else:
        session = cachecontrol.CacheControl(session,
            cache=cachecontrol.caches.FileCache(join(output_dir,
                '.web_cache')))
    return session


def get_cran_metadata(cran_url, output_dir, verbose=True):
    session = get_session(output_dir, verbose=verbose)
    if verbose:
        print("Fetching metadata from %s" % cran_url)
    r = session.get(cran_url + "src/contrib/PACKAGES")
    r.raise_for_status()
    PACKAGES = r.text
    package_list = [remove_package_line_continuations(i.splitlines())
                    for i in PACKAGES.split('\n\n')]
    return {d['Package'].lower(): d for d in map(dict_from_cran_lines,
        package_list)}


def make_array(m, key, allow_empty=False):
    result = []
    try:
        old_vals = m.get_value(key, [])
    except:
        old_vals = []
    if old_vals or allow_empty:
        result.append(key.split('/')[-1] + ":")
    for old_val in old_vals:
        result.append("{indent}{old_val}".format(indent=INDENT, old_val=old_val))
    return result


def existing_recipe_dir(output_dir, output_suffix, package):
    result = None
    if exists(join(output_dir, package)):
        result = normpath(join(output_dir, package))
    elif exists(join(output_dir, package + output_suffix)):
        result = normpath(join(output_dir, package + output_suffix))
    elif exists(join(output_dir, 'r-' + package + output_suffix)):
        result = normpath(join(output_dir, 'r-' + package + output_suffix))
    return result


def strip_end(string, end):
    if string.endswith(end):
        return string[:-len(end)]
    return string


def package_to_inputs_dict(output_dir, output_suffix, git_tag, package):
    """
    Converts `package` (*) into a tuple of:

    pkg_name (without leading 'r-')
    location (in a subdir of output_dir - may not exist - or at GitHub)
    old_git_rev (from existing metadata, so corresponds to the *old* version)
    metadata or None (if a recipe does *not* already exist)

    (*) `package` could be:
    1. A package name beginning (or not) with 'r-'
    2. A GitHub URL
    3. A relative path to a recipe from output_dir
    4. An absolute path to a recipe (fatal unless in the output_dir hierarchy)
    5. Any of the above ending (or not) in sep or '/'

    So this function cleans all that up:

    Some packages may be from GitHub but we'd like the user not to have to worry
    about that on the command-line (for pre-existing recipes). Also, we may want
    to get version information from them (or existing metadata to merge) so lets
    load *all* existing recipes (later we will add or replace this metadata with
    any that we create).
    """
    if isfile(package):
        return None
    print("Parsing input package %s:" % package)
    package = strip_end(package, '/')
    package = strip_end(package, sep)
    if 'github.com' in package:
        package = strip_end(package, '.git')
    pkg_name = basename(package).lower()
    pkg_name = strip_end(pkg_name, '-feedstock')
    if output_suffix:
        pkg_name = strip_end(pkg_name, output_suffix)
    if pkg_name.startswith('r-'):
        pkg_name = pkg_name[2:]
    if isabs(package):
        commp = commonprefix((package, output_dir))
        if commp != output_dir:
            raise RuntimeError("package %s specified with abs path outside of output-dir %s" % (
                package, output_dir))
        location = package
        existing_location = existing_recipe_dir(output_dir, output_suffix, 'r-' + pkg_name)
    elif 'github.com' in package:
        location = package
        existing_location = existing_recipe_dir(output_dir, output_suffix, 'r-' + pkg_name)
    else:
        location = existing_location = existing_recipe_dir(output_dir, output_suffix, package)
    if existing_location:
        try:
            m = metadata.MetaData(existing_location)
        except:
            # Happens when the folder exists but contains no recipe.
            m = None
    else:
        m = None

    # It can still be the case that a package without 'github.com' in the location does really
    # come from there, for that we need to inspect the existing metadata's source/git_url.
    old_git_rev = git_tag
    if location and m and 'github.com' not in location:
        git_url = m.get_value('source/git_url', '')
        if 'github.com' in git_url:
            location = git_url
            old_git_rev = m.get_value('source/git_rev', None)

    new_location = join(output_dir, 'r-' + pkg_name + output_suffix)
    print(".. name: %s location: %s new_location: %s" % (pkg_name, location, new_location))

    return dict({'pkg-name': pkg_name,
                 'location': location,
                 'old-git-rev': old_git_rev,
                 'old-metadata': m,
                 'new-location': new_location})


def skeletonize(in_packages, output_dir=".", output_suffix="", add_maintainer=None, version=None,
                git_tag=None, cran_url="https://cran.r-project.org/", recursive=False, archive=True,
                version_compare=False, update_policy='', config=None):

    output_dir = realpath(output_dir)

    if not config:
        config = Config()

    if len(in_packages) > 1 and version_compare:
        raise ValueError("--version-compare only works with one package at a time")
    if update_policy == 'error' and not in_packages:
        raise ValueError("At least one package must be supplied")

    package_dicts = {}
    package_list = []

    cran_metadata = get_cran_metadata(cran_url, output_dir)

    # r_recipes_in_output_dir = []
    # recipes = listdir(output_dir)
    # for recipe in recipes:
    #     if not recipe.startswith('r-') or not isdir(recipe):
    #         continue
    #     r_recipes_in_output_dir.append(recipe)

    for package in in_packages:
        inputs_dict = package_to_inputs_dict(output_dir, output_suffix, git_tag, package)
        if inputs_dict:
            package_dicts.update({inputs_dict['pkg-name']: {'inputs': inputs_dict}})

    for package_name, package_dict in package_dicts.items():
        package_list.append(package_name)

    while package_list:
        inputs = package_dicts[package_list.pop()]['inputs']
        location = inputs['location']
        pkg_name = inputs['pkg-name']
        is_github_url = location and 'github.com' in location
        url = inputs['location']

        dir_path = inputs['new-location']
        print("Making/refreshing recipe for {}".format(pkg_name))

        # Bodges GitHub packages into cran_metadata
        if is_github_url:
            rm_rf(config.work_dir)
            m = metadata.MetaData.fromdict({'source': {'git_url': location}}, config=config)
            source.git_source(m.get_section('source'), m.config.git_cache, m.config.work_dir)
            new_git_tag = git_tag if git_tag else get_latest_git_tag(config)
            p = subprocess.Popen(['git', 'checkout', new_git_tag], stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, cwd=config.work_dir)
            stdout, stderr = p.communicate()
            stdout = stdout.decode('utf-8')
            stderr = stderr.decode('utf-8')
            if p.returncode:
                sys.exit("Error: 'git checkout %s' failed (%s).\nInvalid tag?" %
                         (new_git_tag, stderr.strip()))
            if stdout:
                print(stdout, file=sys.stdout)
            if stderr:
                print(stderr, file=sys.stderr)

            DESCRIPTION = join(config.work_dir, "DESCRIPTION")
            if not isfile(DESCRIPTION):
                sub_description_pkg = join(config.work_dir, 'pkg', "DESCRIPTION")
                sub_description_name = join(config.work_dir, location.split('/')[-1], "DESCRIPTION")
                if isfile(sub_description_pkg):
                    DESCRIPTION = sub_description_pkg
                elif isfile(sub_description_name):
                    DESCRIPTION = sub_description_name
                else:
                    sys.exit("%s does not appear to be a valid R package "
                             "(no DESCRIPTION file in %s, %s)"
                                 % (location, sub_description_pkg, sub_description_name))

            with open(DESCRIPTION) as f:
                description_text = clear_trailing_whitespace(f.read())

            d = dict_from_cran_lines(remove_package_line_continuations(
                description_text.splitlines()))
            d['orig_description'] = description_text
            package = d['Package'].lower()
            cran_metadata[package] = d
        else:
            package = pkg_name

        if pkg_name not in cran_metadata:
            sys.exit("Package %s not found" % pkg_name)

        # Make sure package always uses the CRAN capitalization
        package = cran_metadata[package.lower()]['Package']

        if not is_github_url:
            session = get_session(output_dir)
            cran_metadata[package.lower()].update(get_package_metadata(cran_url,
            package, session))

        cran_package = cran_metadata[package.lower()]

        package_dicts[package.lower()].update(
            {
                'cran_packagename': package,
                'packagename': 'r-' + package.lower(),
                'patches': '',
                'build_number': 0,
                'build_depends': '',
                'host_depends': '',
                'run_depends': '',
                # CRAN doesn't seem to have this metadata :(
                'home_comment': '#',
                'homeurl': '',
                'summary_comment': '#',
                'summary': '',
            })
        d = package_dicts[package.lower()]
        if is_github_url:
            d['url_key'] = ''
            d['fn_key'] = ''
            d['git_url_key'] = 'git_url:'
            d['git_tag_key'] = 'git_tag:'
            d['hash_entry'] = '# You can add a hash for the file here, like md5, sha1 or sha256'
            d['filename'] = ''
            d['cranurl'] = ''
            d['git_url'] = url
            d['git_tag'] = new_git_tag
        else:
            d['url_key'] = 'url:'
            d['fn_key'] = 'fn:'
            d['git_url_key'] = ''
            d['git_tag_key'] = ''
            d['git_url'] = ''
            d['git_tag'] = ''
            d['hash_entry'] = ''

        if version:
            d['version'] = version
            raise NotImplementedError("Package versions from CRAN are not yet implemented")

        d['cran_version'] = cran_package['Version']
        # Conda versions cannot have -. Conda (verlib) will treat _ as a .
        d['conda_version'] = d['cran_version'].replace('-', '_')
        if version_compare:
            sys.exit(not version_compare(dir_path, d['conda_version']))

        patches = []
        script_env = []
        extra_recipe_maintainers = []
        build_number = 0
        if update_policy.startswith('merge') and inputs['old-metadata']:
            m = inputs['old-metadata']
            patches = make_array(m, 'source/patches')
            script_env = make_array(m, 'build/script_env')
            extra_recipe_maintainers = make_array(m, 'extra/recipe-maintainers', add_maintainer)
            if m.version() == d['conda_version']:
                build_number = int(m.get_value('build/number', 0))
                build_number += 1 if update_policy == 'merge-incr-build-num' else 0
        if not len(patches):
            patches.append("# patches:\n")
            patches.append("   # List any patch files here\n")
            patches.append("   # - fix.patch")
        if add_maintainer:
            new_maintainer = "{indent}{add_maintainer}".format(indent=INDENT,
                                                               add_maintainer=add_maintainer)
            if new_maintainer not in extra_recipe_maintainers:
                if not len(extra_recipe_maintainers):
                    # We hit this case when there is no existing recipe.
                    extra_recipe_maintainers = make_array({}, 'extra/recipe-maintainers', True)
                extra_recipe_maintainers.append(new_maintainer)
        if len(extra_recipe_maintainers):
            extra_recipe_maintainers[1:].sort()
            extra_recipe_maintainers.insert(0, "extra:\n  ")
        d['extra_recipe_maintainers'] = ''.join(extra_recipe_maintainers)
        d['patches'] = ''.join(patches)
        d['script_env'] = ''.join(script_env)
        d['build_number'] = build_number

        cached_path = None
        if not is_github_url:
            filename = '{}_{}.tar.gz'
            contrib_url = cran_url + 'src/contrib/'
            package_url = contrib_url + filename.format(package, d['cran_version'])

            # calculate sha256 by downloading source
            sha256 = hashlib.sha256()
            print("Downloading source from {}".format(package_url))
            # We may need to inspect the file later to determine which compilers are needed.
            cached_path, _ = source.download_to_cache(config.src_cache, '',
                                                      dict({'url': package_url}))
            sha256.update(open(cached_path, 'rb').read())
            d['hash_entry'] = 'sha256: {}'.format(sha256.hexdigest())

            d['filename'] = filename.format(package, '{{ version }}')
            if archive:
                d['cranurl'] = (INDENT + contrib_url +
                    d['filename'] + INDENT + contrib_url +
                    'Archive/{}/'.format(package) + d['filename'])
            else:
                d['cranurl'] = ' ' + cran_url + 'src/contrib/' + d['filename']

        d['cran_metadata'] = '\n'.join(['# %s' % l for l in
            cran_package['orig_lines'] if l])

        # XXX: We should maybe normalize these
        d['license'] = cran_package.get("License", "None")
        d['license_family'] = guess_license_family(d['license'], allowed_license_families)

        if 'License_is_FOSS' in cran_package:
            d['license'] += ' (FOSS)'
        if cran_package.get('License_restricts_use') == 'yes':
            d['license'] += ' (Restricts use)'

        if "URL" in cran_package:
            d['home_comment'] = ''
            d['homeurl'] = ' ' + yaml_quote_string(cran_package['URL'])
        else:
            # use CRAN page as homepage if nothing has been specified
            d['home_comment'] = ''
            if is_github_url:
                d['homeurl'] = ' {}'.format(location)
            else:
                d['homeurl'] = ' https://CRAN.R-project.org/package={}'.format(package)

        if cran_package.get("NeedsCompilation", 'no') == 'yes':
            d['noarch_generic'] = ''
        else:
            d['noarch_generic'] = 'noarch: generic'

        if 'Description' in cran_package:
            d['summary_comment'] = ''
            d['summary'] = ' ' + yaml_quote_string(cran_package['Description'])

        if "Suggests" in cran_package:
            d['suggests'] = "# Suggests: %s" % cran_package['Suggests']
        else:
            d['suggests'] = ''

        # Every package depends on at least R.
        # I'm not sure what the difference between depends and imports is.
        depends = [s.strip() for s in cran_package.get('Depends',
            '').split(',') if s.strip()]
        imports = [s.strip() for s in cran_package.get('Imports',
            '').split(',') if s.strip()]
        links = [s.strip() for s in cran_package.get("LinkingTo",
            '').split(',') if s.strip()]

        dep_dict = {}

        seen = set()
        for s in list(chain(imports, depends, links)):
            match = VERSION_DEPENDENCY_REGEX.match(s)
            if not match:
                sys.exit("Could not parse version from dependency of %s: %s" %
                    (package, s))
            name = match.group('name')
            if name in seen:
                continue
            seen.add(name)
            archs = match.group('archs')
            relop = match.group('relop') or ''
            ver = match.group('version') or ''
            ver = ver.replace('-', '_')
            # If there is a relop there should be a version
            assert not relop or ver

            if archs:
                sys.exit("Don't know how to handle archs from dependency of "
                "package %s: %s" % (package, s))

            dep_dict[name] = '{relop}{version}'.format(relop=relop, version=ver)

        if 'R' not in dep_dict:
            dep_dict['R'] = ''

        need_git = is_github_url
        if cran_package.get("NeedsCompilation", 'no') == 'yes':
            with tarfile.open(cached_path) as tf:
                need_f = any([f.name.lower().endswith(('.f', '.f90', '.f77')) for f in tf])
                # Fortran builds use CC to perform the link (they do not call the linker directly).
                need_c = True if need_f else \
                    any([f.name.lower().endswith('.c') for f in tf])
                need_cxx = any([f.name.lower().endswith(('.cxx', '.cpp', '.cc', '.c++'))
                                         for f in tf])
                need_autotools = any([f.name.lower().endswith('/configure') for f in tf])
                need_make = True if any((need_autotools, need_f, need_cxx, need_c)) else \
                    any([f.name.lower().endswith(('/makefile', '/makevars'))
                        for f in tf])
        else:
            need_c = need_cxx = need_f = need_autotools = need_make = False

        if 'Rcpp' in dep_dict or 'RcppArmadillo' in dep_dict:
            need_cxx = True

        if need_cxx:
            need_c = True

        for dep_type in ['build', 'host', 'run']:

            deps = []
            # Put non-R dependencies first.
            if dep_type == 'build':
                if need_c:
                    deps.append("{indent}{{{{ compiler('c') }}}}        # [not win]".format(
                        indent=INDENT))
                if need_cxx:
                    deps.append("{indent}{{{{ compiler('cxx') }}}}      # [not win]".format(
                        indent=INDENT))
                if need_f:
                    deps.append("{indent}{{{{ compiler('fortran') }}}}  # [not win]".format(
                        indent=INDENT))
                if need_c or need_cxx or need_f:
                    deps.append("{indent}{{{{native}}}}toolchain        # [win]".format(
                        indent=INDENT))
                if need_autotools or need_make or need_git:
                    deps.append("{indent}{{{{posix}}}}filesystem        # [win]".format(
                        indent=INDENT))
                if need_git:
                    deps.append("{indent}{{{{posix}}}}git".format(indent=INDENT))
                if need_autotools:
                    deps.append("{indent}{{{{posix}}}}sed               # [win]".format(
                        indent=INDENT))
                    deps.append("{indent}{{{{posix}}}}grep              # [win]".format(
                        indent=INDENT))
                    deps.append("{indent}{{{{posix}}}}autoconf".format(indent=INDENT))
                    deps.append("{indent}{{{{posix}}}}automake-wrapper  # [win]".format(
                        indent=INDENT))
                    deps.append("{indent}{{{{posix}}}}automake          # [not win]".format(
                        indent=INDENT))
                    deps.append("{indent}{{{{posix}}}}pkg-config".format(indent=INDENT))
                if need_make:
                    deps.append("{indent}{{{{posix}}}}make".format(indent=INDENT))
            elif dep_type == 'run':
                if need_c or need_cxx or need_f:
                    deps.append("{indent}{{{{native}}}}gcc-libs         # [win]".format(
                        indent=INDENT))

            if dep_type == 'host' or dep_type == 'run':
                for name in sorted(dep_dict):
                    if name in R_BASE_PACKAGE_NAMES:
                        continue
                    if name == 'R':
                        # Put R first
                        # Regarless of build or run, and whether this is a
                        # recommended package or not, it can only depend on
                        # 'r-base' since anything else can and will cause
                        # cycles in the dependency graph. The cran metadata
                        # lists all dependencies anyway, even those packages
                        # that are in the recommended group.
                        r_name = 'r-base'
                        # We don't include any R version restrictions because we
                        # always build R packages against an exact R version
                        deps.insert(0, '{indent}{r_name}'.format(indent=INDENT, r_name=r_name))
                    else:
                        conda_name = 'r-' + name.lower()

                        if dep_dict[name]:
                            deps.append('{indent}{name} {version}'.format(name=conda_name,
                                version=dep_dict[name], indent=INDENT))
                        else:
                            deps.append('{indent}{name}'.format(name=conda_name,
                                indent=INDENT))
                        if recursive:
                            lower_name = name.lower()
                            if lower_name not in package_dicts:
                                inputs_dict = package_to_inputs_dict(output_dir, output_suffix,
                                                                     git_tag, lower_name)
                                assert lower_name == inputs_dict['pkg-name'], \
                                    "name %s != inputs_dict['pkg-name'] %s" % (
                                        name, inputs_dict['pkg-name'])
                                assert lower_name not in package_list
                                package_dicts.update({lower_name: {'inputs': inputs_dict}})
                                package_list.append(lower_name)

            d['%s_depends' % dep_type] = ''.join(deps)

    for package in package_dicts:
        d = package_dicts[package]
        dir_path = d['inputs']['new-location']
        if exists(dir_path) and not version_compare:
            if update_policy == 'error':
                raise RuntimeError("directory already exists "
                                   "(and --update-policy is 'error'): %s" % dir_path)
            elif update_policy == 'overwrite':
                rm_rf(dir_path)
        elif update_policy == 'skip-up-to-date' and up_to_date(cran_metadata,
                                                               d['inputs']['old-metadata']):
            continue
        elif update_policy == 'skip-existing' and d['inputs']['old-metadata']:
            continue

        # Normalize the metadata values
        d = {k: unicodedata.normalize("NFKD", text_type(v)).encode('ascii', 'ignore')
             .decode() for k, v in iteritems(d)}
        try:
            makedirs(join(dir_path))
        except:
            pass
        print("Writing recipe for %s" % package.lower())
        with open(join(dir_path, 'meta.yaml'), 'w') as f:
            f.write(clear_trailing_whitespace(CRAN_META.format(**d)))
        if not exists(join(dir_path, 'build.sh')) or update_policy == 'overwrite':
            with open(join(dir_path, 'build.sh'), 'w') as f:
                f.write(CRAN_BUILD_SH.format(**d))
        if not exists(join(dir_path, 'bld.bat')) or update_policy == 'overwrite':
            with open(join(dir_path, 'bld.bat'), 'w') as f:
                f.write(CRAN_BLD_BAT.format(**d))


def version_compare(recipe_dir, newest_conda_version):
    m = metadata.MetaData(recipe_dir)
    local_version = m.version()
    package = basename(recipe_dir)

    print("Local recipe for %s has version %s." % (package, local_version))

    print("The version on CRAN for %s is %s." % (package, newest_conda_version))

    return local_version == newest_conda_version


def get_outdated(output_dir, cran_metadata, packages=()):
    to_update = []
    recipes = listdir(output_dir)
    for recipe in recipes:
        if not recipe.startswith('r-') or not isdir(recipe):
            continue

        recipe_name = recipe[2:]

        if packages and not (recipe_name in packages or recipe in packages):
            continue

        if recipe_name not in cran_metadata:
            print("Skipping %s, not found on CRAN" % recipe)
            continue

        version_compare(join(output_dir, recipe),
            cran_metadata[recipe_name]['Version'].replace('-', '_'))

        print("Updating %s" % recipe)
        to_update.append(recipe_name)

    return to_update


def get_existing(output_dir, cran_metadata, packages=()):

    existing = []
    recipes = listdir(output_dir)
    for recipe in recipes:
        if not recipe.startswith('r-') or not isdir(recipe):
            continue

        recipe_name = recipe[2:]

        if packages and not (recipe_name in packages or recipe in packages):
            continue

        existing.append(recipe_name)

    return existing


def up_to_date(cran_metadata, package):
    r_pkg_name, location, old_git_rev, m = package
    cran_pkg_name = r_pkg_name[2:]

    # Does not exist, so is not up to date.
    if not m:
        return False

    # For now. We can do better; need to collect *all* information upfront.
    if 'github.com' in location:
        return False
    else:
        if cran_pkg_name not in cran_metadata:
            return False

    if m.version() != cran_metadata[cran_pkg_name]['Version'].replace('-', '_'):
        return False

    return True
