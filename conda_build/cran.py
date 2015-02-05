"""
Tools for converting Cran packages to conda recipes.
"""

from __future__ import absolute_import, division, print_function

import requests
import yaml

import re
import sys
from os import makedirs
from os.path import join, exists
from itertools import chain


CRAN_META = """\
package:
  name: {packagename}
  # Note that conda versions cannot contain -, so any -'s in the version have
  # been replaced with _'s.
  version: "{conda_version}"

source:
  fn: {filename}
  url:{cranurl}
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
  build:{depends}

  run:{depends}

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
        (k, v) = line.split(': ', 1)
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
    continuation = ' '
    continued_ix = None
    continued_line = None
    had_continuation = False
    accumulating_continuations = False

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

def get_package_metadata(cran_url, package, session):
    r = session.get(cran_url + 'web/packages/' + package + '/DESCRIPTION')
    DESCRIPTION = r.text
    d = dict_from_cran_lines(remove_package_line_continuations(DESCRIPTION.splitlines()))
    d['orig_description'] = DESCRIPTION
    return d

def main(args, parser):
    package_dicts = {}

    [output_dir] = args.output_dir

    session = requests.Session()
    try:
        import cachecontrol
        import cachecontrol.caches
    except ImportError:
        print("Tip: install CacheControl to cache the CRAN metadata")
    else:
        session = cachecontrol.CacheControl(session,
            cache=cachecontrol.caches.FileCache(join(output_dir,
                '.web_cache')))

    print("Fetching metadata from %s" % args.cran_url)
    r = session.get(args.cran_url + "src/contrib/PACKAGES")
    PACKAGES = r.text
    package_list = [remove_package_line_continuations(i.splitlines()) for i in PACKAGES.split('\n\n')]

    cran_metadata = {d['Package'].lower(): d for d in map(dict_from_cran_lines,
        package_list)}

    while args.packages:
        package = args.packages.pop()

        if package.lower() not in cran_metadata:
            sys.exit("Package %s not found" % package)

        cran_metadata[package.lower()].update(get_package_metadata(args.cran_url,
            package, session))

        dir_path = join(output_dir, 'r-' + package.lower())
        if exists(dir_path):
            raise RuntimeError("directory already exists: %s" % dir_path)

        package = cran_metadata[package.lower()]['Package']

        cran_package = cran_metadata[package.lower()]

        d = package_dicts.setdefault(package,
            {
                'cran_packagename': package,
                'packagename': 'r-' + package.lower(),
                'depends': '',
                # CRAN doesn't seem to have this metadata :(
                'home_comment': '#',
                'homeurl': '',
                'summary_comment': '#',
                'summary': '',
            })

        if args.version:
            raise NotImplementedError("Package versions from CRAN are not yet implemented")
            [version] = args.version
            d['version'] = version

        d['cran_version'] = cran_package['Version']
        # Conda versions cannot have -. Conda (verlib) will treat _ as a .
        d['conda_version'] = d['cran_version'].replace('-', '_')
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
            d['homeurl'] = ' ' + yaml.dump(cran_package['URL'])

        if 'Description' in cran_package:
            d['summary_comment'] = ''
            d['summary'] = ' ' + yaml.dump(cran_package['Description'])

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

        deps = []
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

        for name in sorted(dep_dict):
            if name in R_BASE_PACKAGE_NAMES:
                continue
            if name == 'R':
                # Put R first
                if dep_dict[name]:
                    deps.insert(0, '{indent}r {version}'.format(version=dep_dict[name],
                        indent=INDENT))
                else:
                    deps.insert(0, '{indent}r'.format(indent=INDENT))
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

        d['depends'] = ''.join(deps)

    for package in package_dicts:
        d = package_dicts[package]
        name = d['packagename']
        makedirs(join(output_dir, name))
        print("Writing recipe for %s" % package.lower())
        with open(join(output_dir, name, 'meta.yaml'), 'w') as f:
            f.write(CRAN_META.format(**d))
        with open(join(output_dir, name, 'build.sh'), 'w') as f:
            f.write(CRAN_BUILD_SH.format(**d))
        with open(join(output_dir, name, 'bld.bat'), 'w') as f:
            f.write(CRAN_BLD_BAT.format(**d))

    print("Done")
