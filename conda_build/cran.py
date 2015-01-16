"""
Tools for converting Cran packages to conda recipes.
"""

from __future__ import absolute_import, division, print_function

import requests

import keyword
import os
import re
import subprocess
import sys
from collections import defaultdict
from os import makedirs, listdir, getcwd, chdir
from os.path import join, isdir, exists, isfile
from tempfile import mkdtemp
from shutil import copy2

from conda.fetch import (download, handle_proxy_407)
from conda.connection import CondaSession
from conda.utils import human_bytes, hashsum_file
from conda.install import rm_rf
from conda.compat import input, configparser, StringIO, string_types, PY3
from conda.config import get_proxy_servers
from conda.cli.common import spec_from_line
from conda_build.utils import tar_xf, unzip
from conda_build.source import SRC_CACHE, apply_patch
from conda_build.build import create_env
from conda_build.config import config

from requests.packages.urllib3.util.url import parse_url

CRAN_META = """\
package:
  name: {packagename}
  version: !!str {version}

source:
  fn: {filename}
  url: {cranurl}
  {usemd5}md5: {md5}
#  patches:
   # List any patch files here
   # - fix.patch

{build_comment}build:
  {egg_comment}preserve_egg_dir: True
  {entry_comment}entry_points:
    # Put any entry points (scripts to be generated automatically) here. The
    # syntax is module:function.  For example
    #
    # - {packagename} = {packagename}:main
    #
    # Would create an entry point called {packagename} that calls {packagename}.main()
{entry_points}

  # If this is a new build for the same version, increment the build
  # number. If you do not include this key, it defaults to 0.
  # number: 1

requirements:
  build:
    - python{build_depends}

  run:
    - python{run_depends}

{test_comment}test:
  # Python imports
  {import_comment}imports:{import_tests}

  {entry_comment}commands:
    # You can put test commands to be run here.  Use this to test that the
    # entry points work.
{test_commands}

  # You can also put a file called run_test.py in the recipe that will be run
  # at test time.

  # requires:
    # Put any additional test requirements here.  For example
    # - nose

about:
  {home_comment}home: {homeurl}
  license: {license}
  {summary_comment}summary: {summary}

# See
# http://docs.continuum.io/conda/build.html for
# more information about meta.yaml
"""

CRAN_BUILD_SH = """\
#!/bin/bash

# R refuses to build packages that mark themselves as Priority: Recommended
mv DESCRIPTION DESCRIPTION.old
grep -v '^Priority: ' DESCRIPTION.old > DESCRIPTION

# On OS X, the only way to build packages currently is by having
# DYLD_LIBRARY_PATH set.
export DYLD_LIBRARY_PATH=$PREFIX/lib

R CMD INSTALL --build .

# Add more build steps here, if they are necessary.

# See
# http://docs.continuum.io/conda/build.html
# for a list of environment variables that are set during the build process.
"""

CRAN_BLD_BAT = """\
R CMD INSTALL --build .
if errorlevel 1 exit 1

@rem Add more build steps here, if they are necessary.

@rem See
@rem http://docs.continuum.io/conda/build.html
@rem for a list of environment variables that are set during the build process.
"""

INDENT = '\n    - '

def main(args, parser):
    package_dicts = {}

    while args.packages:
        [output_dir] = args.output_dir

        package = args.packages.pop()

        d = package_dicts.setdefault(package,
            {
                'packagename': package.lower(),
                'run_depends': '',
                'build_depends': '',
                'entry_points': '',
                'build_comment': '# ',
                'test_commands': '',
                'usemd5': '',
                'test_comment': '',
                'entry_comment': '# ',
                'egg_comment': '# ',
                'summary_comment': '',
                'home_comment': '',
            })

        if args.version:
            raise NotImplementedError("Package versions from CRAN are not yet implemented")
            [version] = args.version
            d['version'] = version
        else:
            versions = client.package_releases(package)
            if not versions:
                # The xmlrpc interface is case sensitive, but the index itself
                # is apparently not (the last time I checked,
                # len(set(all_packages_lower)) == len(set(all_packages)))
                if package.lower() in all_packages_lower:
                    print("%s not found, trying %s" % (package, package.capitalize()))
                    args.packages.append(all_packages[all_packages_lower.index(package.lower())])
                    del package_dicts[package]
                    continue
                sys.exit("Error: Could not find any versions of package %s" %
                         package)
            if len(versions) > 1:
                print("Warning, the following versions were found for %s" %
                      package)
                for ver in versions:
                    print(ver)
                print("Using %s" % versions[0])
                print("Use --version to specify a different version.")
            d['version'] = versions[0]

        data = client.release_data(package, d['version']) if not is_url else None
        urls = client.release_urls(package, d['version']) if not is_url else [package]
        if not is_url and not args.all_urls:
            # Try to find source urls
            urls = [url for url in urls if url['python_version'] == 'source']
        if not urls:
            if 'download_url' in data:
                urls = [defaultdict(str, {'url': data['download_url']})]
                U = parse_url(urls[0]['url'])
                urls[0]['filename'] = U.path.rsplit('/')[-1]
                fragment = U.fragment or ''
                if fragment.startswith('md5='):
                    d['usemd5'] = ''
                    d['md5'] = fragment[len('md5='):]
                else:
                    d['usemd5'] = '#'
            else:
                sys.exit("Error: No source urls found for %s" % package)
        if len(urls) > 1 and not args.noprompt:
            print("More than one source version is available for %s:" %
                  package)
            for i, url in enumerate(urls):
                print("%d: %s (%s) %s" % (i, url['url'],
                                          human_bytes(url['size']),
                                          url['comment_text']))
            n = int(input("Which version should I use? "))
        else:
            n = 0

        if not is_url:
            print("Using url %s (%s) for %s." % (urls[n]['url'],
                human_bytes(urls[n]['size'] or 0), package))
            d['cranurl'] = urls[n]['url']
            d['md5'] = urls[n]['md5_digest']
            d['filename'] = urls[n]['filename']
        else:
            print("Using url %s" % package)
            d['cranurl'] = package
            U = parse_url(package)
            if U.fragment.startswith('md5='):
                d['usemd5'] = ''
                d['md5'] = U.fragment[len('md5='):]
            else:
                d['usemd5'] = '#'
                d['md5'] = ''
            # TODO: 'package' won't work with unpack()
            d['filename'] = U.path.rsplit('/', 1)[-1] or 'package'

        if is_url:
            d['import_tests'] = 'PLACEHOLDER'
        else:
            d['import_tests'] = valid(package).lower()

        get_package_metadata(args, package, d, data)

        if d['import_tests'] == '':
            d['import_comment'] = '# '
        else:
            d['import_comment'] = ''
            d['import_tests'] = INDENT + d['import_tests']

        if d['entry_comment'] == d['import_comment'] == '# ':
            d['test_comment'] = '# '

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

def dict_from_cran_lines(lines):
    d = {}
    for line in lines:
        if not line:
            continue
        (k, v) = line.split(': ')
        d[k] = v
        if k not in CRAN_KEYS:
            print("Warning: Unknown key %s" % k)
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
    continuation = ' ' * 8
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

def get_package_metadata(args, package, d, data):
    [output_dir] = args.output_dir


def valid(name):
    if (re.match("[_A-Za-z][_a-zA-Z0-9]*$", name)
            and not keyword.iskeyword(name)):
        return name
    else:
        return ''


def unpack(src_path, tempdir):
    if src_path.endswith(('.tar.gz', '.tar.bz2', '.tgz', '.tar.xz', '.tar')):
        tar_xf(src_path, tempdir)
    elif src_path.endswith('.zip'):
        unzip(src_path, tempdir)
    else:
        raise Exception("not a valid source")


def get_dir(tempdir):
    lst = [fn for fn in listdir(tempdir) if not fn.startswith('.') and
           isdir(join(tempdir, fn))]
    if len(lst) == 1:
        dir_path = join(tempdir, lst[0])
        if isdir(dir_path):
            return dir_path
    raise Exception("could not find unpacked source dir")


def make_entry_tests(entry_list):
    tests = []
    for entry_point in entry_list:
        entry = entry_point.partition('=')[0].strip()
        tests.append(entry + " --help")
    return tests
