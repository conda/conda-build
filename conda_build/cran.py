"""
Tools for converting Cran packages to conda recipes.
"""

from __future__ import absolute_import, division, print_function

import requests
import yaml

import re
import sys
from os import makedirs, listdir
from os.path import join, exists, isfile, basename, isdir
from itertools import chain
import subprocess

from conda.install import rm_rf

from conda_build import source, metadata

CRAN_META = """\
package:
  name: {packagename}
  # Note that conda versions cannot contain -, so any -'s in the version have
  # been replaced with _'s.
  version: "{conda_version}"

source:
  {fn_key} {filename}
  {url_key} {cranurl}
  {git_url_key} {git_url}
  {git_tag_key} {git_tag}
  # You can add a hash for the file here, like md5 or sha1
  # md5: 49448ba4863157652311cc5ea4fea3ea
  # sha1: 3bcfbee008276084cbb37a2b453963c61176a322
  # patches:
   # List any patch files here
   # - fix.patch

build:
  # If this is a new build for the same version, increment the build
  # number. If you do not include this key, it defaults to 0.
  # number: 1

  # This is required to make R link correctly on Linux.
  rpaths:
    - lib/R/lib/
    - lib/

{suggests}
requirements:
  build:{build_depends}

  run:{run_depends}

test:
  commands:
    # You can put additional test commands to be run here.
    - $R -e "library('{cran_packagename}')" # [not win]
    - "\\"%R%\\" -e \\"library('{cran_packagename}')\\"" # [win]

  # You can also put a file called run_test.py, run_test.sh, or run_test.bat
  # in the recipe that will be run at test time.

  # requires:
    # Put any additional test requirements here.

about:
  {home_comment}home:{homeurl}
  license: {license}
  {summary_comment}summary:{summary}

# The original CRAN metadata for this package was:

{cran_metadata}

# See
# http://docs.continuum.io/conda/build.html for
# more information about meta.yaml

"""

CRAN_BUILD_SH = """\
#!/bin/bash

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
if errorlevel 1 exit 1

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
    'tools',
    'utils',
    'grDevices',
    'graphics',
    'stats',
    'datasets',
    'methods',
    'grid',
    'splines',
    'stats4',
    'tcltk',
    'compiler',
    'parallel',
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

def dict_from_cran_lines(lines):
    d = {}
    for line in lines:
        if not line:
            continue
        try:
            (k, v) = line.split(': ', 1)
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
    """
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
                continued_ix = i-1
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
        chunk = [ c for c in chunk if c ]

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
    return yaml.dump(string).replace('\n...\n', '').replace('\n', '\n  ')

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

def get_latest_git_tag():
    p = subprocess.Popen(['git', 'tag'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=source.WORK_DIR)
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

def get_session(output_dir, verbose=True, cache=[]):
    if cache:
        return cache[0]
    session = requests.Session()
    try:
        import cachecontrol
        import cachecontrol.caches
    except ImportError:
        if verbose:
            print("Tip: install CacheControl to cache the CRAN metadata")
    else:
        session = cachecontrol.CacheControl(session,
            cache=cachecontrol.caches.FileCache(join(output_dir,
                '.web_cache')))

    cache.append(session)
    return session

def get_cran_metadata(cran_url, output_dir, verbose=True):
    session = get_session(output_dir, verbose=verbose)
    if verbose:
        print("Fetching metadata from %s" % cran_url)
    r = session.get(cran_url + "src/contrib/PACKAGES")
    r.raise_for_status()
    PACKAGES = r.text
    package_list =  [remove_package_line_continuations(i.splitlines()) for i in PACKAGES.split('\n\n')]
    return {d['Package'].lower(): d for d in map(dict_from_cran_lines,
        package_list)}

def main(args, parser):
    if len(args.packages) > 1 and args.version_compare:
        parser.error("--version-compare only works with one package at a time")
    if not args.update_outdated and not args.packages:
        parser.error("At least one package must be supplied")

    package_dicts = {}

    [output_dir] = args.output_dir

    cran_metadata = get_cran_metadata(args.cran_url, output_dir)

    if args.update_outdated:
        args.packages = get_outdated(output_dir, cran_metadata, args.packages)
        for pkg in args.packages:
            rm_rf(join(args.output_dir, 'r-' + pkg))


    while args.packages:
        package = args.packages.pop()

        is_github_url = 'github.com' in package
        url = package


        if is_github_url:
            rm_rf(source.WORK_DIR)
            source.git_source({'git_url': package}, '.')
            git_tag = args.git_tag[0] if args.git_tag else get_latest_git_tag()
            p = subprocess.Popen(['git', 'checkout', git_tag], stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=source.WORK_DIR)
            stdout, stderr = p.communicate()
            stdout = stdout.decode('utf-8')
            stderr = stderr.decode('utf-8')
            if p.returncode:
                sys.exit("Error: 'git checkout %s' failed (%s).\nInvalid tag?" % (git_tag, stderr.strip()))
            if stdout:
                print(stdout, file=sys.stdout)
            if stderr:
                print(stderr, file=sys.stderr)

            DESCRIPTION = join(source.WORK_DIR, "DESCRIPTION")
            if not isfile(DESCRIPTION):
                sub_description_pkg = join(source.WORK_DIR, 'pkg', "DESCRIPTION")
                sub_description_name = join(source.WORK_DIR, package.split('/')[-1], "DESCRIPTION")
                if isfile(sub_description_pkg):
                    DESCRIPTION = sub_description_pkg
                elif isfile(sub_description_name):
                    DESCRIPTION = sub_description_name
                else:
                    sys.exit("%s does not appear to be a valid R package (no DESCRIPTION file)" % package)

            with open(DESCRIPTION) as f:
                description_text = clear_trailing_whitespace(f.read())

            d = dict_from_cran_lines(remove_package_line_continuations(description_text.splitlines()))
            d['orig_description'] = description_text
            package = d['Package'].lower()
            cran_metadata[package] = d

        if package.startswith('r-'):
            package = package[2:]
        if package.endswith('/'):
            package = package[:-1]
        if package.lower() not in cran_metadata:
            sys.exit("Package %s not found" % package)

        # Make sure package is always uses the CRAN capitalization
        package = cran_metadata[package.lower()]['Package']

        if not is_github_url:
            session = get_session(output_dir)
            cran_metadata[package.lower()].update(get_package_metadata(args.cran_url,
            package, session))

        dir_path = join(output_dir, 'r-' + package.lower())
        if exists(dir_path) and not args.version_compare:
            raise RuntimeError("directory already exists: %s" % dir_path)

        cran_package = cran_metadata[package.lower()]

        d = package_dicts.setdefault(package,
            {
                'cran_packagename': package,
                'packagename': 'r-' + package.lower(),
                'build_depends': '',
                'run_depends': '',
                # CRAN doesn't seem to have this metadata :(
                'home_comment': '#',
                'homeurl': '',
                'summary_comment': '#',
                'summary': '',
            })

        if is_github_url:
            d['url_key'] = ''
            d['fn_key'] = ''
            d['git_url_key'] = 'git_url:'
            d['git_tag_key'] = 'git_tag:'
            d['filename'] = ''
            d['cranurl'] = ''
            d['git_url'] = url
            d['git_tag'] = git_tag
        else:
            d['url_key'] = 'url:'
            d['fn_key'] = 'fn:'
            d['git_url_key'] = ''
            d['git_tag_key'] = ''
            d['git_url'] = ''
            d['git_tag'] = ''

        if args.version:
            raise NotImplementedError("Package versions from CRAN are not yet implemented")
            [version] = args.version
            d['version'] = version

        d['cran_version'] = cran_package['Version']
        # Conda versions cannot have -. Conda (verlib) will treat _ as a .
        d['conda_version'] = d['cran_version'].replace('-', '_')
        if args.version_compare:
            sys.exit(not version_compare(dir_path, d['conda_version']))

        if not is_github_url:
            d['filename'] = "{cran_packagename}_{cran_version}.tar.gz".format(**d)
            if args.archive:
                d['cranurl'] = (INDENT + args.cran_url + 'src/contrib/' +
                    d['filename'] + INDENT + args.cran_url + 'src/contrib/' +
                    'Archive/' + d['cran_packagename'] + '/' + d['filename'])
            else:
                d['cranurl'] = ' ' + args.cran_url + 'src/contrib/' + d['filename']

        d['cran_metadata'] = '\n'.join(['# %s' % l for l in
            cran_package['orig_lines'] if l])

        # XXX: We should maybe normalize these
        d['license'] = cran_package.get("License", "None")
        if 'License_is_FOSS' in cran_package:
            d['license'] += ' (FOSS)'
        if cran_package.get('License_restricts_use', None) == 'yes':
            d['license'] += ' (Restricts use)'

        if "URL" in cran_package:
            d['home_comment'] = ''
            d['homeurl'] = ' ' + yaml_quote_string(cran_package['URL'])

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

        for s in set(chain(depends, imports, links)):
            match = VERSION_DEPENDENCY_REGEX.match(s)
            if not match:
                sys.exit("Could not parse version from dependency of %s: %s" %
                    (package, s))
            name = match.group('name')
            archs = match.group('archs')
            relop = match.group('relop') or ''
            version = match.group('version') or ''
            version = version.replace('-', '_')
            # If there is a relop there should be a version
            assert not relop or version

            if archs:
                sys.exit("Don't know how to handle archs from dependency of "
                "package %s: %s" % (package, s))

            dep_dict[name] = '{relop}{version}'.format(relop=relop, version=version)

        if 'R' not in dep_dict:
            dep_dict['R'] = ''

        for dep_type in ['build', 'run']:
            deps = []
            for name in sorted(dep_dict):
                if name in R_BASE_PACKAGE_NAMES:
                    continue
                if name == 'R':
                    # Put R first
                    if d['cran_packagename'] in R_RECOMMENDED_PACKAGE_NAMES and dep_type == 'build':
                        # On Linux and OS X, r is a metapackage depending on
                        # r-base and r-recommended. Recommended packages cannot
                        # build depend on r as they would then build depend on
                        # themselves and the built package would end up being
                        # empty (because conda would find no new files)
                        r_name = 'r-base'
                    else:
                        r_name = 'r'
                    # We don't include any R version restrictions because we
                    # always build R packages against an exact R version
                    deps.insert(0, '{indent}{r_name}'.format(indent=INDENT, r_name=r_name))
                else:
                    conda_name = 'r-' + name.lower()

                    # The r package on Windows includes the recommended packages
                    if name in R_RECOMMENDED_PACKAGE_NAMES:
                        end = ' # [not win]'
                    else:
                        end = ''
                    if dep_dict[name]:
                        deps.append('{indent}{name} {version}{end}'.format(name=conda_name,
                            version=dep_dict[name], end=end, indent=INDENT))
                    else:
                        deps.append('{indent}{name}{end}'.format(name=conda_name,
                            indent=INDENT, end=end))
                    if args.recursive:
                        if not exists(join(output_dir, conda_name)):
                            args.packages.append(name)

            if cran_package.get("NeedsCompilation", 'no') == 'yes':
                if dep_type == 'build':
                    deps.append('{indent}gcc # [not win]'.format(indent=INDENT))
                else:
                    deps.append('{indent}libgcc # [not win]'.format(indent=INDENT))
            d['%s_depends' % dep_type] = ''.join(deps)

    for package in package_dicts:
        d = package_dicts[package]
        name = d['packagename']
        makedirs(join(output_dir, name))
        print("Writing recipe for %s" % package.lower())
        with open(join(output_dir, name, 'meta.yaml'), 'w') as f:
            f.write(clear_trailing_whitespace(CRAN_META.format(**d)))
        with open(join(output_dir, name, 'build.sh'), 'w') as f:
            f.write(CRAN_BUILD_SH.format(**d))
        with open(join(output_dir, name, 'bld.bat'), 'w') as f:
            f.write(CRAN_BLD_BAT.format(**d))

    print("Done")

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

        for i, package in enumerate(packages):
            if package.endswith('/'):
                packages[i] = package[:-1]

        if packages and not (recipe_name in packages or recipe in packages):
            continue

        if recipe_name not in cran_metadata:
            print("Skipping %s, not found on CRAN" % recipe)
            continue

        up_to_date = version_compare(join(output_dir, recipe),
            cran_metadata[recipe_name]['Version'].replace('-', '_'))

        if up_to_date:
            print("%s is up-to-date." % recipe)
            continue

        print("Updating %s" % recipe)
        to_update.append(recipe_name)

    return to_update
