"""
Tools for converting Cran packages to conda recipes.
"""

from __future__ import absolute_import, division, print_function

import argparse
import copy
from itertools import chain
from os import makedirs, listdir, sep, environ
from os.path import (basename, commonprefix, exists, isabs, isdir,
                     isfile, join, normpath, realpath, relpath)
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
from conda_build.config import get_or_merge_config
from conda_build.conda_interface import text_type, iteritems, TemporaryDirectory, cc_conda_build
from conda_build.license_family import allowed_license_families, guess_license_family
from conda_build.utils import rm_rf, ensure_list
from conda_build.variants import get_package_variants, DEFAULT_VARIANTS

SOURCE_META = """\
  {archive_keys}
  {git_url_key} {git_url}
  {git_tag_key} {git_tag}
  {patches}
"""

BINARY_META = """\
  url: {cranurl}{sel}
  {hash_entry}{sel}
"""

VERSION_META = """\
{{% set version = '{cran_version}' %}}{sel}"""

CRAN_META = """\
{version_source}
{version_binary1}
{version_binary2}

{{% set posix = 'm2-' if win else '' %}}
{{% set native = 'm2w64-' if win else '' %}}

package:
  name: {packagename}
  version: {{{{ version|replace("-", "_") }}}}

source:
{source}
{binary1}
{binary2}

build:
  merge_build_host: True{sel_src_and_win}
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
  {license_file}

{extra_recipe_maintainers}

# The original CRAN metadata for this package was:

{cran_metadata}

# See
# https://docs.conda.io/projects/conda-build for
# more information about meta.yaml

"""

CRAN_BUILD_SH_SOURCE = """\
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
grep -va '^Priority: ' DESCRIPTION.old > DESCRIPTION
$R CMD INSTALL --build .

# Add more build steps here, if they are necessary.

# See
# https://docs.conda.io/projects/conda-build
# for a list of environment variables that are set during the build process.
"""

CRAN_BUILD_SH_MIXED = """\
#!/bin/bash

if {source_pf_bash}; then
  export DISABLE_AUTOBREW=1
  mv DESCRIPTION DESCRIPTION.old
  grep -v '^Priority: ' DESCRIPTION.old > DESCRIPTION
  $R CMD INSTALL --build .
else
  mkdir -p $PREFIX/lib/R/library/{cran_packagename}
  mv * $PREFIX/lib/R/library/{cran_packagename}

  if [[ $target_platform == osx-64 ]]; then
    pushd $PREFIX
      for libdir in lib/R/lib lib/R/modules lib/R/library lib/R/bin/exec sysroot/usr/lib; do
        pushd $libdir || exit 1
          for SHARED_LIB in $(find . -type f -iname "*.dylib" -or -iname "*.so" -or -iname "R"); do
            echo "fixing SHARED_LIB $SHARED_LIB"
            install_name_tool -change /Library/Frameworks/R.framework/Versions/3.5.0-MRO/Resources/lib/libR.dylib "$PREFIX"/lib/R/lib/libR.dylib $SHARED_LIB || true
            install_name_tool -change /Library/Frameworks/R.framework/Versions/3.5/Resources/lib/libR.dylib "$PREFIX"/lib/R/lib/libR.dylib $SHARED_LIB || true
            install_name_tool -change /usr/local/clang4/lib/libomp.dylib "$PREFIX"/lib/libomp.dylib $SHARED_LIB || true
            install_name_tool -change /usr/local/gfortran/lib/libgfortran.3.dylib "$PREFIX"/lib/libgfortran.3.dylib $SHARED_LIB || true
            install_name_tool -change /Library/Frameworks/R.framework/Versions/3.5/Resources/lib/libquadmath.0.dylib "$PREFIX"/lib/libquadmath.0.dylib $SHARED_LIB || true
            install_name_tool -change /usr/local/gfortran/lib/libquadmath.0.dylib "$PREFIX"/lib/libquadmath.0.dylib $SHARED_LIB || true
            install_name_tool -change /Library/Frameworks/R.framework/Versions/3.5/Resources/lib/libgfortran.3.dylib "$PREFIX"/lib/libgfortran.3.dylib $SHARED_LIB || true
            install_name_tool -change /usr/lib/libgcc_s.1.dylib "$PREFIX"/lib/libgcc_s.1.dylib $SHARED_LIB || true
            install_name_tool -change /usr/lib/libiconv.2.dylib "$PREFIX"/sysroot/usr/lib/libiconv.2.dylib $SHARED_LIB || true
            install_name_tool -change /usr/lib/libncurses.5.4.dylib "$PREFIX"/sysroot/usr/lib/libncurses.5.4.dylib $SHARED_LIB || true
            install_name_tool -change /usr/lib/libicucore.A.dylib "$PREFIX"/sysroot/usr/lib/libicucore.A.dylib $SHARED_LIB || true
            install_name_tool -change /usr/lib/libexpat.1.dylib "$PREFIX"/lib/libexpat.1.dylib $SHARED_LIB || true
            install_name_tool -change /usr/lib/libcurl.4.dylib "$PREFIX"/lib/libcurl.4.dylib $SHARED_LIB || true
            install_name_tool -change /usr/lib/libc++.1.dylib "$PREFIX"/lib/libc++.1.dylib $SHARED_LIB || true
            install_name_tool -change /Library/Frameworks/R.framework/Versions/3.5/Resources/lib/libc++.1.dylib "$PREFIX"/lib/libc++.1.dylib $SHARED_LIB || true
          done
        popd
      done
    popd
  fi
fi
"""

CRAN_BUILD_SH_BINARY = """\
#!/bin/bash
mkdir -p $PREFIX/lib/R/library/{cran_packagename}
mv * $PREFIX/lib/R/library/{cran_packagename}
fi
"""

CRAN_BLD_BAT_SOURCE = """\
"%R%" CMD INSTALL --build .
IF %ERRORLEVEL% NEQ 0 exit 1
"""

# We hardcode the fact that CRAN does not provide win32 binaries here.
CRAN_BLD_BAT_MIXED = """\
if "%target_platform%" == "win-64" goto skip_source_build
"%R%" CMD INSTALL --build .
IF %ERRORLEVEL% NEQ 0 exit 1
exit 0
:skip_source_build
mkdir %PREFIX%\lib\R\library
robocopy /E . "%PREFIX%\lib\R\library\{cran_packagename}"
if %ERRORLEVEL% NEQ 1 exit 1
exit 0
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

target_platform_bash_test_by_sel = {'linux': '=~ linux.*',
                                    'linux32': '== linux-32',
                                    'linux64': '== linux-64',
                                    'win32': '== win-32',
                                    'win64': '== win-64',
                                    'osx': '== osx-64'}


def package_exists(package_name):
    # TODO: how can we get cran to spit out package presence?
    # available.packages() is probably a start, but no channels are working on mac right now?
    return True
    # install_output = subprocess.check_output([join(sys.prefix, "r"), "-e",
    #                     # ind=2 arbitrarily chooses some CRAN mirror to try.
    #                     "chooseCRANmirror(ind=2);install.packages('{}')".format(package_name)])


def add_parser(repos):
    # for loading default variant info
    cran = repos.add_parser(
        "cran",
        help="""
    Create recipe skeleton for packages hosted on the Comprehensive R Archive
    Network (CRAN) (cran.r-project.org).
        """,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
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
        help="URL to use for as source package repository",
    )
    cran.add_argument(
        "--r-interp",
        default='r-base',
        help="Declare R interpreter package",
    )
    cran.add_argument(
        "--use-binaries-ver",
        help=("Repackage binaries from version provided by argument instead of building "
              "from source."),
    )
    cran.add_argument(
        "--use-when-no-binary",
        choices=('src',
                 'old',
                 'src-old',
                 'old-src',
                 'error'),
        default='src',
        help="""Sometimes binaries are not available at the correct version for
                a given platform (macOS). You can use this flag to specify what
                fallback to take, either compiling from source or using an older
                binary or trying one then the other."""
    )
    cran.add_argument(
        "--use-noarch-generic",
        action='store_true',
        dest='use_noarch_generic',
        help=("Mark packages that do not need compilation as `noarch: generic`"),
    )
    cran.add_argument(
        "--use-rtools-win",
        action='store_true',
        help="Use Rtools when building from source on Windows",
    )
    cran.add_argument(
        "--recursive",
        action='store_true',
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
    cran.add_argument(
        '-m', '--variant-config-files',
        default=cc_conda_build.get('skeleton_config_yaml', None),
        help="""Variant config file to add.  These yaml files can contain
        keys such as `cran_mirror`.  Only one can be provided here."""
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


# Due to how we render the metadata there can be significant areas of repeated newlines.
# This collapses them and also strips any trailing spaces.
def clear_whitespace(string):
    lines = []
    last_line = ''
    for line in string.splitlines():
        line = line.rstrip()
        if not (line == '' and last_line == ''):
            lines.append(line)
        last_line = line
    return '\n'.join(lines)


def get_package_metadata(cran_url, package, session):
    url = cran_url + '/web/packages/' + package + '/DESCRIPTION'
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


def _ssl_no_verify():
    """Gets whether the SSL_NO_VERIFY environment variable is set to 1 or True.

    This provides a workaround for users in some corporate environments where
    MITM style proxies make it difficult to fetch data over HTTPS.
    """
    return environ.get('SSL_NO_VERIFY', '').strip().lower() in ('1', 'true')


def get_session(output_dir, verbose=True):
    session = requests.Session()
    session.verify = _ssl_no_verify()
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
    r = session.get(cran_url + "/src/contrib/PACKAGES")
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
    3. A file:// URL to a tarball
    4. A relative path to a recipe from output_dir
    5. An absolute path to a recipe (fatal unless in the output_dir hierarchy)
    6. Any of the above ending (or not) in sep or '/'

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
    if package.startswith('file://'):
        location = package.replace('file://', '')
        pkg_filename = basename(location)
        pkg_name = re.match(r'(.*)_(.*)', pkg_filename).group(1).lower()
        existing_location = existing_recipe_dir(output_dir, output_suffix, 'r-' + pkg_name)
    elif isabs(package):
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

    return {'pkg-name': pkg_name,
            'location': location,
            'old-git-rev': old_git_rev,
            'old-metadata': m,
            'new-location': new_location}


def get_available_binaries(cran_url, details):
    import requests
    from bs4 import BeautifulSoup

    def get_url_paths(url, ext='', params={}):
        response = requests.get(url, params=params)
        if response.ok:
            response_text = response.text
        else:
            return response.raise_for_status()
        soup = BeautifulSoup(response_text, 'html.parser')
        parent = [url + node.get('href') for node in soup.find_all('a') if node.get('href').endswith(ext)]
        return parent

    url = cran_url + '/' + details['dir']
    ext = details['ext']
    result = get_url_paths(url, ext)
    for p in result:
        filename = basename(p)
        pkg, _, ver = filename.rpartition('_')
        ver, _, _ = ver.rpartition(ext)
        if pkg in details['binaries']:
            details['binaries'][pkg.lower()].extend((ver, p))
        else:
            details['binaries'][pkg.lower()] = [(ver, p)]


def skeletonize(in_packages, output_dir=".", output_suffix="", add_maintainer=None, version=None,
                git_tag=None, cran_url=None, recursive=False, archive=True,
                version_compare=False, update_policy='', r_interp='r-base', use_binaries_ver=None,
                use_noarch_generic=False, use_when_no_binary='src', use_rtools_win=False, config=None,
                variant_config_files=None):

    if use_when_no_binary != 'error' and \
       use_when_no_binary != 'src' and \
       use_when_no_binary != 'old' and \
       use_when_no_binary != 'old-src':
        print("ERROR: --use_when_no_binary={} not yet implemented".format(use_when_no_binary))
        sys.exit(1)
    output_dir = realpath(output_dir)
    config = get_or_merge_config(config, variant_config_files=variant_config_files)

    if not cran_url:
        with TemporaryDirectory() as t:
            _variant = get_package_variants(t, config)[0]
        cran_url = ensure_list(_variant.get('cran_mirror', DEFAULT_VARIANTS['cran_mirror']))[0]

    if len(in_packages) > 1 and version_compare:
        raise ValueError("--version-compare only works with one package at a time")
    if update_policy == 'error' and not in_packages:
        raise ValueError("At least one package must be supplied")

    package_dicts = {}
    package_list = []

    cran_url = cran_url.rstrip('/')
    cran_metadata = get_cran_metadata(cran_url, output_dir)

    cran_layout_template = \
                  {'source': {'selector': '{others}',
                              'dir': 'src/contrib/',
                              'ext': '.tar.gz',
                              # If we had platform filters we would change this to:
                              # build_for_linux or is_github_url or is_tarfile
                              'use_this': True},
                   'win-64': {'selector': 'win64',
                              'dir': 'bin/windows/contrib/{}/'.format(use_binaries_ver),
                              'ext': '.zip',
                              'use_this': True if use_binaries_ver else False},
                   'osx-64': {'selector': 'osx',
                              'dir': 'bin/macosx/el-capitan/contrib/{}/'.format(
                                  use_binaries_ver),
                              'ext': '.tgz',
                              'use_this': True if use_binaries_ver else False}}

    # Figure out what binaries are available once:
    for archive_type, archive_details in iteritems(cran_layout_template):
        archive_details['binaries'] = dict()
        if archive_type != 'source' and archive_details['use_this']:
            get_available_binaries(cran_url, archive_details)

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
        is_tarfile = location and isfile(location) and tarfile.is_tarfile(location)
        url = inputs['location']

        dir_path = inputs['new-location']
        print("Making/refreshing recipe for {}".format(pkg_name))

        # Bodges GitHub packages into cran_metadata
        if is_github_url or is_tarfile:
            rm_rf(config.work_dir)
            if is_github_url:
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
            else:
                m = metadata.MetaData.fromdict({'source': {'url': location}}, config=config)
                source.unpack(m.get_section('source'), m.config.work_dir, m.config.src_cache,
                              output_dir, m.config.work_dir)
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
                description_text = clear_whitespace(f.read())

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

        if not is_github_url and not is_tarfile:
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
        d['binary1'] = ''
        d['binary2'] = ''

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
        cran_layout = copy.deepcopy(cran_layout_template)
        available = {}

        for archive_type, archive_details in iteritems(cran_layout):
            contrib_url = ''
            archive_details['cran_version'] = d['cran_version']
            archive_details['conda_version'] = d['conda_version']
            avaliable_artefact = True if archive_type == 'source' else \
                package in archive_details['binaries'] and \
                d['cran_version'] in archive_details['binaries'][package][0]
            if not avaliable_artefact:
                if use_when_no_binary == 'error':
                    print("ERROR: --use-when-no-binary is error (and there is no binary)")
                    sys.exit(1)
                elif use_when_no_binary.startswith('old'):
                    if package not in archive_details['binaries']:
                        if use_when_no_binary.endswith('src'):
                            avaliable_artefact = False
                            archive_details['use_this'] = False
                            continue
                        else:
                            print("ERROR: No binary nor old binary found "
                                  "(maybe pass --use-when-no-binary=old-src to fallback to source?)")
                            sys.exit(1)
                    # Version needs to be stored in archive_details.
                    archive_details['cranurl'] = archive_details['binaries'][package][-1][1]
                    archive_details['conda_version'] = archive_details['binaries'][package][-1][0]
                    archive_details['cran_version'] = archive_details['conda_version'].replace('_', '-')
                    avaliable_artefact = True
            # We may need to inspect the file later to determine which compilers are needed.
            cached_path = None
            sha256 = hashlib.sha256()
            if archive_details['use_this'] and avaliable_artefact:
                if is_tarfile:
                    filename = basename(location)
                    contrib_url = relpath(location, dir_path)
                    contrib_url_rendered = package_url = contrib_url
                    cached_path = location
                elif not is_github_url or archive_type != 'source':
                    filename_rendered = '{}_{}{}'.format(
                        package, archive_details['cran_version'], archive_details['ext'])
                    filename = '{}_{{{{ version }}}}'.format(package) + archive_details['ext']
                    contrib_url = '{{{{ cran_mirror }}}}/{}'.format(archive_details['dir'])
                    contrib_url_rendered = cran_url + '/{}'.format(archive_details['dir'])
                    package_url = contrib_url_rendered + filename_rendered
                    print("Downloading {} from {}".format(archive_type, package_url))
                    try:
                        cached_path, _ = source.download_to_cache(
                            config.src_cache, '',
                            {'url': package_url, 'fn': archive_type + '-' + filename_rendered})
                    except:
                        print("logic error, file {} should exist, we found it in a dir listing earlier."
                              .format(package_url))
                        sys.exit(1)
                available_details = {}
                available_details['selector'] = archive_details['selector']
                available_details['cran_version'] = archive_details['cran_version']
                available_details['conda_version'] = archive_details['conda_version']
                if cached_path:
                    sha256.update(open(cached_path, 'rb').read())
                    archive_details['cranurl'] = package_url
                    available_details['filename'] = filename
                    available_details['contrib_url'] = contrib_url
                    available_details['contrib_url_rendered'] = contrib_url_rendered
                    available_details['hash_entry'] = 'sha256: {}'.format(sha256.hexdigest())
                    available_details['cached_path'] = cached_path
                # This is rubbish; d[] should be renamed global[] and should be
                #      merged into source and binaryN.
                if archive_type == 'source':
                    if is_github_url:
                        available_details['url_key'] = ''
                        available_details['git_url_key'] = 'git_url:'
                        available_details['git_tag_key'] = 'git_tag:'
                        hash_msg = '# You can add a hash for the file here, (md5, sha1 or sha256)'
                        available_details['hash_entry'] = hash_msg
                        available_details['filename'] = ''
                        available_details['cranurl'] = ''
                        available_details['git_url'] = url
                        available_details['git_tag'] = new_git_tag
                        available_details['archive_keys'] = ''
                    else:
                        available_details['url_key'] = 'url:'
                        available_details['git_url_key'] = ''
                        available_details['git_tag_key'] = ''
                        available_details['cranurl'] = ' ' + contrib_url + filename
                        available_details['git_url'] = ''
                        available_details['git_tag'] = ''
                else:
                    available_details['cranurl'] = archive_details['cranurl']

                available_details['patches'] = d['patches']
                available[archive_type] = available_details

        # Figure out the selectors according to what is available.
        _all = ['linux', 'win32', 'win64', 'osx']
        from_source = _all[:]
        binary_id = 1
        for archive_type, archive_details in iteritems(available):
            if archive_type == 'source':
                for k, v in iteritems(archive_details):
                    d[k] = v
            else:
                sel = archive_details['selector']
                # Does the file exist? If not we need to build from source.
                from_source.remove(sel)
                binary_id += 1
        if from_source == _all:
            sel_src = ""
            sel_src_and_win = '  # [win]'
            sel_src_not_win = '  # [not win]'
        else:
            sel_src = '  # [' + ' or '.join(from_source) + ']'
            sel_src_and_win = '  # [' + ' or '.join(fs for fs in from_source if
                                                    fs.startswith('win')) + ']'
            sel_src_not_win = '  # [' + ' or '.join(fs for fs in from_source if not
                                                    fs.startswith('win')) + ']'
        d['sel_src'] = sel_src
        d['sel_src_and_win'] = sel_src_and_win
        d['sel_src_not_win'] = sel_src_not_win
        d['from_source'] = from_source

        if 'source' in available:
            available_details = available['source']
            available_details['sel'] = sel_src
            filename = available_details['filename']
            if 'contrib_url' in available_details:
                contrib_url = available_details['contrib_url']
                if archive:
                    if is_tarfile:
                        available_details['cranurl'] = (INDENT + contrib_url)
                    else:
                        available_details['cranurl'] = (INDENT + contrib_url +
                            filename + sel_src + INDENT + contrib_url +
                            'Archive/{}/'.format(package) + filename + sel_src)
                else:
                    available_details['cranurl'] = ' ' + contrib_url + filename + sel_src
            if not is_github_url:
                available_details['archive_keys'] = '{url_key}{sel}' \
                                                    '    {cranurl}\n' \
                                                    '  {hash_entry}{sel}'.format(
                    **available_details)

        d['cran_metadata'] = '\n'.join(['# %s' % l for l in
            cran_package['orig_lines'] if l])

        # Render the source and binaryN keys
        binary_id = 1
        d['version_binary1'] = d['version_binary2'] = ""
        for archive_type, archive_details in iteritems(available):
            if archive_type == 'source':
                d['source'] = SOURCE_META.format(**archive_details)
                d['version_source'] = VERSION_META.format(**archive_details)
            else:
                archive_details['sel'] = '  # [' + archive_details['selector'] + ']'
                d['binary' + str(binary_id)] = BINARY_META.format(**archive_details)
                d['version_binary' + str(binary_id)] = VERSION_META.format(**archive_details)
                binary_id += 1

        license_info = get_license_info(cran_package.get("License", "None"), allowed_license_families)
        d['license'], d['license_file'], d['license_family'] = license_info

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

        if not use_noarch_generic or cran_package.get("NeedsCompilation", 'no') == 'yes':
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
            with tarfile.open(available['source']['cached_path']) as tf:
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
                    deps.append("{indent}{{{{ compiler('c') }}}}            {sel}".format(
                        indent=INDENT, sel=sel_src_not_win))
                    deps.append("{indent}{{{{ compiler('m2w64_c') }}}}      {sel}".format(
                        indent=INDENT, sel=sel_src_and_win))
                if need_cxx:
                    deps.append("{indent}{{{{ compiler('cxx') }}}}          {sel}".format(
                        indent=INDENT, sel=sel_src_not_win))
                    deps.append("{indent}{{{{ compiler('m2w64_cxx') }}}}    {sel}".format(
                        indent=INDENT, sel=sel_src_and_win))
                if need_f:
                    deps.append("{indent}{{{{ compiler('fortran') }}}}      {sel}".format(
                        indent=INDENT, sel=sel_src_not_win))
                    deps.append("{indent}{{{{ compiler('m2w64_fortran') }}}}{sel}".format(
                        indent=INDENT, sel=sel_src_and_win))
                if use_rtools_win:
                    need_c = need_cxx = need_f = need_autotools = need_make = False
                    deps.append("{indent}rtools                   {sel}".format(
                        indent=INDENT, sel=sel_src_and_win))
                    # extsoft is legacy. R packages will download rwinlib subprojects
                    # as necessary according to Jeroen Ooms. (may need to disable that
                    # for non-MRO builds or maybe switch to Jeroen's toolchain?)
                    # deps.append("{indent}{{{{native}}}}extsoft     {sel}".format(
                    #     indent=INDENT, sel=sel_src_and_win))
                if need_autotools or need_make or need_git:
                    deps.append("{indent}{{{{posix}}}}filesystem      {sel}".format(
                        indent=INDENT, sel=sel_src_and_win))
                if need_git:
                    deps.append("{indent}{{{{posix}}}}git".format(indent=INDENT))
                if need_autotools:
                    deps.append("{indent}{{{{posix}}}}sed             {sel}".format(
                        indent=INDENT, sel=sel_src_and_win))
                    deps.append("{indent}{{{{posix}}}}grep            {sel}".format(
                        indent=INDENT, sel=sel_src_and_win))
                    deps.append("{indent}{{{{posix}}}}autoconf        {sel}".format(
                        indent=INDENT, sel=sel_src))
                    deps.append("{indent}{{{{posix}}}}automake        {sel}".format(
                        indent=INDENT, sel=sel_src_not_win))
                    deps.append("{indent}{{{{posix}}}}automake-wrapper{sel}".format(
                        indent=INDENT, sel=sel_src_and_win))
                    deps.append("{indent}{{{{posix}}}}pkg-config".format(indent=INDENT))
                if need_make:
                    deps.append("{indent}{{{{posix}}}}make            {sel}".format(
                        indent=INDENT, sel=sel_src))
                    if not need_autotools:
                        deps.append("{indent}{{{{posix}}}}sed             {sel}".format(
                            indent=INDENT, sel=sel_src_and_win))
                    deps.append("{indent}{{{{posix}}}}coreutils       {sel}".format(
                        indent=INDENT, sel=sel_src_and_win))
                deps.append("{indent}{{{{posix}}}}zip             {sel}".format(
                    indent=INDENT, sel=sel_src_and_win))
            elif dep_type == 'run':
                if need_c or need_cxx or need_f:
                    deps.append("{indent}{{{{native}}}}gcc-libs       {sel}".format(
                        indent=INDENT, sel=sel_src_and_win))

            if dep_type == 'host' or dep_type == 'run':
                for name in sorted(dep_dict):
                    if name in R_BASE_PACKAGE_NAMES:
                        continue
                    if name == 'R':
                        # Put R first
                        # Regarless of build or run, and whether this is a
                        # recommended package or not, it can only depend on
                        # r_interp since anything else can and will cause
                        # cycles in the dependency graph. The cran metadata
                        # lists all dependencies anyway, even those packages
                        # that are in the recommended group.
                        # We don't include any R version restrictions because
                        # conda-build always pins r-base and mro-base version.
                        deps.insert(0, '{indent}{r_name}'.format(indent=INDENT, r_name=r_interp))
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

        from_sources = d['from_source']
        # Normalize the metadata values
        d = {k: unicodedata.normalize("NFKD", text_type(v)).encode('ascii', 'ignore')
             .decode() for k, v in iteritems(d)}
        try:
            makedirs(join(dir_path))
        except:
            pass
        print("Writing recipe for %s" % package.lower())
        with open(join(dir_path, 'meta.yaml'), 'w') as f:
            f.write(clear_whitespace(CRAN_META.format(**d)))
        if not exists(join(dir_path, 'build.sh')) or update_policy == 'overwrite':
            with open(join(dir_path, 'build.sh'), 'w') as f:
                if from_sources == all:
                    f.write(CRAN_BUILD_SH_SOURCE.format(**d))
                elif from_sources == []:
                    f.write(CRAN_BUILD_SH_BINARY.format(**d))
                else:
                    tpbt = [target_platform_bash_test_by_sel[t] for t in from_sources]
                    d['source_pf_bash'] = ' || '.join(['[[ $target_platform ' + s + ' ]]'
                                                  for s in tpbt])
                    f.write(CRAN_BUILD_SH_MIXED.format(**d))

        if not exists(join(dir_path, 'bld.bat')) or update_policy == 'overwrite':
            with open(join(dir_path, 'bld.bat'), 'w') as f:
                if len([fs for fs in from_sources if fs.startswith('win')]) == 2:
                    f.write(CRAN_BLD_BAT_SOURCE.format(**d))
                else:
                    f.write(CRAN_BLD_BAT_MIXED.format(**d))


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


def get_license_info(license_text, allowed_license_families):
    """
    Most R packages on CRAN do not include a license file. Instead, to avoid
    duplication, R base ships with common software licenses:

    complete: AGPL-3, Artistic-2.0, GPL-2, GPL-3, LGPL-2, LGPL-2.1, LGPL-3
    template: BSD_2_clause BSD_3_clause, MIT

    The complete licenses can be included in conda binaries by pointing to the
    license file shipped with R base. The template files are more complicated
    because they would need to be combined with the license information provided
    by the package authors. In this case, the template file and the license
    information file are both packaged. All optional ('|' seperated) licenses
    are included, if they are matching.

    This function returns the path to the license file for the unambiguous
    cases.
    """

    # The list order matters. The first element should be the name of the
    # license file shipped with r-base.
    d_license = {'agpl3': ['AGPL-3', 'AGPL (>= 3)', 'AGPL',
                           'GNU Affero General Public License'],
                 'artistic2': ['Artistic-2.0', 'Artistic License 2.0'],
                 'gpl2': ['GPL-2', 'GPL (>= 2)', 'GNU General Public License (>= 2)'],
                 'gpl3': ['GPL-3', 'GPL (>= 3)', 'GNU General Public License (>= 3)',
                          'GPL', 'GNU General Public License'],
                 'lgpl2': ['LGPL-2', 'LGPL (>= 2)'],
                 'lgpl21': ['LGPL-2.1', 'LGPL (>= 2.1)'],
                 'lgpl3': ['LGPL-3', 'LGPL (>= 3)', 'LGPL',
                           'GNU Lesser General Public License'],
                 'bsd2': ['BSD_2_clause', 'BSD_2_Clause', 'BSD 2-clause License'],
                 'bsd3': ['BSD_3_clause', 'BSD_3_Clause', 'BSD 3-clause License'],
                 'mit': ['MIT'],
                 }

    license_file_template = '\'{{{{ environ["PREFIX"] }}}}/lib/R/share/licenses/{license_id}\''

    license_texts = []
    license_files = []

    # split license_text by "|" and "+" into parts for further matching
    license_text_parts = [l_opt.strip() for l_opt in re.split('\||\+', license_text)]
    for l_opt in license_text_parts:
        # the file case
        if l_opt.startswith("file "):
            license_files.append(l_opt[5:])
            continue

        # license id string to match
        for license_id in d_license.keys():
            if l_opt in d_license[license_id]:
                l_opt_text = d_license[license_id][0]

                license_texts.append(l_opt_text)
                license_files.append(license_file_template.format(license_id=l_opt_text))
                break

    # Join or fallback to original license_text if matched license_texts is empty
    license_text = " | ".join(license_texts) or license_text

    # Build the license_file entry and ensure it is empty if no license file
    license_file = "license_file:\n    - " + "\n    - ".join(license_files) if license_files else ""

    # Only one family is allowed, so guessing it once
    license_family = guess_license_family(license_text, allowed_license_families)

    return license_text, license_file, license_family
