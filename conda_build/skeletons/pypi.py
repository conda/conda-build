"""
Tools for converting PyPI packages to conda recipes.
"""

from __future__ import absolute_import, division, print_function

from collections import defaultdict
import keyword
import os
from os import makedirs, listdir, getcwd, chdir
from os.path import join, isdir, exists, isfile, abspath
from pkg_resources import parse_version
import re
from shutil import copy2
import subprocess
import sys
from tempfile import mkdtemp

import pkginfo
import requests
from requests.packages.urllib3.util.url import parse_url
import yaml

from conda_build.conda_interface import spec_from_line, Completer
from conda_build.conda_interface import input, configparser, StringIO, string_types, PY3
from conda_build.conda_interface import CondaSession
from conda_build.conda_interface import download, handle_proxy_407
from conda_build.conda_interface import normalized_version
from conda_build.conda_interface import human_bytes, hashsum_file
from conda_build.conda_interface import default_python

from conda_build.utils import tar_xf, unzip, rm_rf, check_call_env
from conda_build.source import apply_patch
from conda_build.build import create_env
from conda_build.config import Config
from conda_build.metadata import MetaData
from conda_build.license_family import allowed_license_families, guess_license_family

if PY3:
    try:
        from xmlrpc.client import ServerProxy, Transport, ProtocolError
    except ImportError:
        print(sys.path)
        raise
else:
    try:
        from xmlrpclib import ServerProxy, Transport, ProtocolError
    except ImportError:
        print(sys.path)
        raise


# https://gist.github.com/chrisguitarguy/2354951


class RequestsTransport(Transport):
    """
    Drop in Transport for xmlrpclib that uses Requests instead of httplib
    """
    # change our user agent to reflect Requests
    user_agent = "Python XMLRPC with Requests (python-requests.org)"

    # override this if you'd like to https
    use_https = True

    session = CondaSession()

    def request(self, host, handler, request_body, verbose):
        """
        Make an xmlrpc request.
        """
        headers = {
            'User-Agent': self.user_agent,
            'Content-Type': 'text/xml',
        }
        url = self._build_url(host, handler)

        try:
            resp = self.session.post(url,
                                     data=request_body,
                                     headers=headers,
                                     proxies=self.session.proxies)
            resp.raise_for_status()

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 407:  # Proxy Authentication Required
                handle_proxy_407(url, self.session)
                # Try again
                return self.request(host, handler, request_body, verbose)
            else:
                raise

        except requests.exceptions.ConnectionError as e:
            # requests isn't so nice here. For whatever reason, https gives this
            # error and http gives the above error. Also, there is no status_code
            # attribute here. We have to just check if it looks like 407.  See
            # https://github.com/kennethreitz/requests/issues/2061.
            if "407" in str(e):  # Proxy Authentication Required
                handle_proxy_407(url, self.session)
                # Try again
                return self.request(host, handler, request_body, verbose)
            else:
                raise

        except requests.RequestException as e:
            raise ProtocolError(url, resp.status_code, str(e), resp.headers)

        else:
            return self.parse_response(resp)

    def parse_response(self, resp):
        """
        Parse the xmlrpc response.
        """
        p, u = self.getparser()
        p.feed(resp.text.encode("utf-8"))
        p.close()
        ret = u.close()
        return ret

    def _build_url(self, host, handler):
        """
        Build a url for our request based on the host, handler and use_http
        property
        """
        scheme = 'https' if self.use_https else 'http'
        return '%s://%s/%s' % (scheme, host, handler)


class PyPIPackagesCompleter(Completer):
    def __init__(self, prefix, parsed_args, **kwargs):
        self.prefix = prefix
        self.parsed_args = parsed_args

    def _get_items(self):
        from conda_build.pypi import get_xmlrpc_client
        args = self.parsed_args
        client = get_xmlrpc_client(getattr(args, 'pypi_url'))
        return [i.lower() for i in client.list_packages()]


pypi_example = """
Examples:

Create a recipe for the sympy package:

    conda skeleton pypi sympy

Create a recipes for the flake8 package and all its dependencies:

    conda skeleton pypi --recursive flake8

Use the --pypi-url flag to point to a PyPI mirror url:

    conda skeleton pypi --pypi-url <mirror-url> package_name
"""

PYPI_META = """\
package:
  name: {packagename}
  version: "{version}"

source:
  fn: {filename}
  url: {pypiurl}
  {usemd5}md5: {md5}
#  patches:
   # List any patch files here
   # - fix.patch

{build_comment}build:
  {noarch_python_comment}noarch_python: True
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

  {requires_comment}requires:{tests_require}
    # Put any additional test requirements here.  For example
    # - nose

about:
  {home_comment}home: {homeurl}
  license: {license}
  {summary_comment}summary: {summary}
  license_family: {license_family}

# See
# http://docs.continuum.io/conda/build.html for
# more information about meta.yaml
"""

PYPI_BUILD_SH = """\
#!/bin/bash

$PYTHON setup.py install {recipe_setup_options}

# Add more build steps here, if they are necessary.

# See
# http://docs.continuum.io/conda/build.html
# for a list of environment variables that are set during the build process.
"""

PYPI_BLD_BAT = """\
"%PYTHON%" setup.py install {recipe_setup_options}
if errorlevel 1 exit 1

:: Add more build steps here, if they are necessary.

:: See
:: http://docs.continuum.io/conda/build.html
:: for a list of environment variables that are set during the build process.
"""

# Note the {} formatting bits here
DISTUTILS_PATCH = '''\
diff core.py core.py
--- core.py
+++ core.py
@@ -166,5 +167,40 @@ def setup (**attrs):
 \n
+# ====== BEGIN CONDA SKELETON PYPI PATCH ======
+
+import distutils.core
+import io
+import os.path
+import sys
+import yaml
+from yaml import Loader, SafeLoader
+
+# Override the default string handling function to always return unicode
+# objects (taken from StackOverflow)
+def construct_yaml_str(self, node):
+    return self.construct_scalar(node)
+Loader.add_constructor(u'tag:yaml.org,2002:str', construct_yaml_str)
+SafeLoader.add_constructor(u'tag:yaml.org,2002:str', construct_yaml_str)
+
+def setup(*args, **kwargs):
+    data = {{}}
+    data['tests_require'] = kwargs.get('tests_require', [])
+    data['install_requires'] = kwargs.get('install_requires', [])
+    data['extras_require'] = kwargs.get('extras_require', {{}})
+    data['entry_points'] = kwargs.get('entry_points', [])
+    data['packages'] = kwargs.get('packages', [])
+    data['setuptools'] = 'setuptools' in sys.modules
+    data['summary'] = kwargs.get('description', None)
+    data['homeurl'] = kwargs.get('url', None)
+    data['license'] = kwargs.get('license', None)
+    data['name'] = kwargs.get('name', '??PACKAGE-NAME-UNKNOWN??')
+    data['classifiers'] = kwargs.get('classifiers', None)
+    data['version'] = kwargs.get('version', '??PACKAGE-VERSION-UNKNOWN??')
+    with io.open(os.path.join("{}", "pkginfo.yaml"), 'w', encoding='utf-8') as fn:
+        fn.write(yaml.safe_dump(data, encoding=None))
+
+
+# ======= END CONDA SKELETON PYPI PATCH ======
 \n
 def run_setup (script_name, script_args=None, stop_after="run"):
     """Run a setup script in a somewhat controlled environment, and
'''

INDENT = '\n    - '


def package_exists(package_name, pypi_url=None):
    if not pypi_url:
        pypi_url = 'https://pypi.python.org/pypi'
    # request code will be 404 if the package does not exist.  Requires exact match.
    r = requests.get(pypi_url + '/' + package_name)
    return r.status_code != 404


def skeletonize(packages, output_dir=".", version=None, recursive=False,
                all_urls=False, pypi_url='https://pypi.python.org/pypi', noprompt=False,
                version_compare=False, python_version=default_python, manual_url=False,
                all_extras=False, noarch_python=False, config=None, setup_options=None,
                extra_specs=[],
                pin_numpy=False):
    client = get_xmlrpc_client(pypi_url)
    package_dicts = {}

    if not setup_options:
        setup_options = []

    if isinstance(setup_options, string_types):
        setup_options = [setup_options]

    if not config:
        config = Config()

    # all_packages = client.list_packages()
    # searching is faster than listing all packages, but we need to separate URLs from names
    all_packages = []

    urls = [package for package in packages if ':' in package]
    names = [package for package in packages if package not in urls]
    all_packages = urls + [match["name"] for match in client.search({"name": names}, "or")]
    all_packages_lower = [i.lower() for i in all_packages]

    created_recipes = []
    while packages:
        package = packages.pop()
        created_recipes.append(package)

        is_url = ':' in package

        if not is_url:
            dir_path = join(output_dir, package.lower())
            if exists(dir_path) and not version_compare:
                raise RuntimeError("directory already exists: %s" % dir_path)
        d = package_dicts.setdefault(package,
            {
                'packagename': package.lower(),
                'run_depends': '',
                'build_depends': '',
                'entry_points': '',
                'build_comment': '# ',
                'noarch_python_comment': '# ',
                'test_commands': '',
                'requires_comment': '#',
                'tests_require': '',
                'usemd5': '',
                'test_comment': '',
                'entry_comment': '# ',
                'egg_comment': '# ',
                'summary_comment': '',
                'home_comment': '',
            })
        if is_url:
            del d['packagename']

        if is_url:
            d['version'] = 'UNKNOWN'
        else:
            # need to treat hidden and visible packages separately.
            # the behavior of PyPI XML API differs from the documentation in certain
            # cases. See
            # https://github.com/pypa/pypi-legacy/issues/189#issuecomment-275515861

            sort_by_version = lambda l: sorted(l, key=parse_version)

            hidden_versions = sort_by_version(client.package_releases(package, True))
            visible_versions = sort_by_version(client.package_releases(package, False))

            # this list of available versions is the union of hidden and visible ones.
            versions = sort_by_version(set(hidden_versions + visible_versions))

            if version_compare:
                version_compare(versions)
            if version:
                if version not in versions:
                    sys.exit("Error: Version %s of %s is not available on PyPI."
                             % (version, package))
                d['version'] = version
            else:
                # select the most visible version from PyPI.
                if not visible_versions:
                    # The xmlrpc interface is case sensitive, but the index itself
                    # is apparently not (the last time I checked,
                    # len(set(all_packages_lower)) == len(set(all_packages)))
                    if package.lower() in all_packages_lower:
                        cased_package = all_packages[all_packages_lower.index(package.lower())]
                        if cased_package != package:
                            print("%s not found, trying %s" % (package, cased_package))
                            packages.append(cased_package)
                            del package_dicts[package]
                            continue
                    sys.exit("Error: Could not find any versions of package %s" % package)
                if len(visible_versions) > 1:
                    print("Warning, the following versions were found for %s" %
                          package)
                    for ver in visible_versions:
                        print(ver)
                    print("Using %s" % visible_versions[-1])
                    print("Use --version to specify a different version.")
                d['version'] = visible_versions[-1]

        data, d['pypiurl'], d['filename'], d['md5'] = get_download_data(client,
                                                                        package,
                                                                        d['version'],
                                                                        is_url, all_urls,
                                                                        noprompt, manual_url)

        if d['md5'] == '':
            d['usemd5'] = '# '
        else:
            d['usemd5'] = ''

        d['import_tests'] = ''

        get_package_metadata(package, d, data, output_dir, python_version,
                             all_extras, recursive, created_recipes, noarch_python,
                             noprompt, packages, extra_specs, config=config,
                             setup_options=setup_options)

        if d['import_tests'] == '':
            d['import_comment'] = '# '
        else:
            d['import_comment'] = ''
            d['import_tests'] = INDENT + d['import_tests']

        if d['tests_require'] == '':
            d['requires_comment'] = '# '
        else:
            d['requires_comment'] = ''
            d['tests_require'] = INDENT + d['tests_require']

        if d['entry_comment'] == d['import_comment'] == '# ':
            d['test_comment'] = '# '

        d['recipe_setup_options'] = ' '.join(setup_options)

        # Change requirements to use format that guarantees the numpy
        # version will be pinned when the recipe is built and that
        # the version is included in the build string.
        if pin_numpy:
            for depends in ['build_depends', 'run_depends']:
                deps = d[depends].split(INDENT)
                numpy_dep = [idx for idx, dep in enumerate(deps)
                             if 'numpy' in dep]
                if numpy_dep:
                    # Turns out this needs to be inserted before the rest
                    # of the numpy spec.
                    deps.insert(numpy_dep[0], 'numpy x.x')
                    d[depends] = INDENT.join(deps)

    for package in package_dicts:
        d = package_dicts[package]
        name = d['packagename']
        makedirs(join(output_dir, name))
        print("Writing recipe for %s" % package.lower())
        with open(join(output_dir, name, 'meta.yaml'), 'w') as f:
            f.write(PYPI_META.format(**d))
        with open(join(output_dir, name, 'build.sh'), 'w') as f:
            f.write(PYPI_BUILD_SH.format(**d))
        with open(join(output_dir, name, 'bld.bat'), 'w') as f:
            f.write(PYPI_BLD_BAT.format(**d))


def add_parser(repos):
    """Modify repos in place, adding the PyPI option"""
    pypi = repos.add_parser(
        "pypi",
        help="""
    Create recipe skeleton for packages hosted on the Python Packaging Index
    (PyPI) (pypi.python.org).
        """,
        epilog=pypi_example,
    )
    pypi.add_argument(
        "packages",
        nargs='+',
        help="""PyPi packages to create recipe skeletons for.
                You can also specify package[extra,...] features.""",
    ).completer = PyPIPackagesCompleter
    pypi.add_argument(
        "--output-dir",
        help="Directory to write recipes to (default: %(default)s).",
        default=".",
    )
    pypi.add_argument(
        "--version",
        help="""Version to use. Applies to all packages. If not specified the
              lastest visible version on PyPI is used.""",
    )
    pypi.add_argument(
        "--all-urls",
        action="store_true",
        help="""Look at all URLs, not just source URLs. Use this if it can't
                find the right URL.""",
    )
    pypi.add_argument(
        "--pypi-url",
        default='https://pypi.python.org/pypi',
        help="URL to use for PyPI (default: %(default)s).",
    )
    pypi.add_argument(
        "--no-prompt",
        action="store_true",
        default=False,
        dest="noprompt",
        help="""Don't prompt the user on ambiguous choices.  Instead, make the
        best possible choice and continue."""
    )
    pypi.add_argument(
        "--all-extras",
        action="store_true",
        default=False,
        help="Add all extra feature requirements. Applies to all packages.",
    )
    pypi.add_argument(
        "--recursive",
        action='store_true',
        help='Create recipes for dependencies if they do not already exist.'
    )
    pypi.add_argument(
        "--version-compare",
        action='store_true',
        help="""Compare the package version of the recipe with all available
        versions on PyPI."""
    )
    pypi.add_argument(
        "--python-version",
        action='store',
        default=default_python,
        help="""Version of Python to use to run setup.py. Default is %(default)s.""",
        choices=['2.7', '3.4', '3.5'],
    )

    pypi.add_argument(
        "--manual-url",
        action='store_true',
        default=False,
        help=("Manually choose source url when more than one urls are present."
              "Default is the one with least source size.")
    )

    pypi.add_argument(
        "--noarch-python",
        action='store_true',
        default=False,
        help="Creates recipe as noarch python"
    )

    pypi.add_argument(
        "--setup-options",
        action='append',
        default=[],
        help='Options to be added to setup.py install in the recipe. '
             'The same options are passed to setup.py install in both '
             'the construction of the recipe and in the recipe itself.'
             'For options that include a double-hypen or to pass multiple '
             'options, use the syntax '
             '--setup-options="--option1 --option-with-arg arg"'
    )

    pypi.add_argument(
        "--pin-numpy",
        action='store_true',
        help="Ensure that the generated recipe pins the version of numpy"
             "to CONDA_NPY."
    )

    pypi.add_argument(
        "--extra-specs",
        action='append',
        default=[],
        help="Extra specs for the build environment to extract the skeleton.",
    )


def get_xmlrpc_client(pypi_url):
    return ServerProxy(pypi_url, transport=RequestsTransport())


def get_download_data(client, package, version, is_url, all_urls, noprompt, manual_url):
    data = client.release_data(package, version) if not is_url else None
    urls = client.release_urls(package, version) if not is_url else [package]
    if not is_url and not all_urls:
        # Try to find source urls
        urls = [url for url in urls if url['python_version'] == 'source']
    if not urls:
        if 'download_url' in data:
            urls = [defaultdict(str, {'url': data['download_url']})]
            if not urls[0]['url']:
                # The package doesn't have a url, or maybe it only has a wheel.
                sys.exit("Error: Could not build recipe for %s. "
                    "Could not find any valid urls." % package)
            U = parse_url(urls[0]['url'])
            if not U.path:
                sys.exit("Error: Could not parse url for %s: %s" %
                    (package, U))
            urls[0]['filename'] = U.path.rsplit('/')[-1]
            fragment = U.fragment or ''
            if fragment.startswith('md5='):
                md5 = fragment[len('md5='):]
            else:
                md5 = ''
        else:
            sys.exit("Error: No source urls found for %s" % package)
    if len(urls) > 1 and not noprompt:
        print("More than one source version is available for %s:" %
                package)
        if manual_url:
            for i, url in enumerate(urls):
                print("%d: %s (%s) %s" % (i, url['url'],
                        human_bytes(url['size']), url['comment_text']))
            n = int(input("which version should i use? "))
        else:
            print("Using the one with the least source size")
            print("use --manual-url to override this behavior")
            _, n = min([(url['size'], i)
                                for (i, url) in enumerate(urls)])
    else:
        n = 0

    if not is_url:
        print("Using url %s (%s) for %s." % (urls[n]['url'],
            human_bytes(urls[n]['size'] or 0), package))
        pypiurl = urls[n]['url']
        md5 = urls[n]['md5_digest']
        filename = urls[n]['filename'] or 'package'
    else:
        print("Using url %s" % package)
        pypiurl = package
        U = parse_url(package)
        if U.fragment and U.fragment.startswith('md5='):
            md5 = U.fragment[len('md5='):]
        else:
            md5 = ''
        # TODO: 'package' won't work with unpack()
        filename = U.path.rsplit('/', 1)[-1] or 'package'

    return (data, pypiurl, filename, md5)


def version_compare(package, versions):
    if not versions:
        # PyPI is case sensitive, this will pass control
        # to a method in main() to take care of that.
        return

    nv = normalized_version

    norm_versions = [nv(ver) for ver in versions]

    recipe_dir = abspath(package.lower())
    if not isdir(recipe_dir):
        sys.exit("Error: no such directory: %s" % recipe_dir)
    m = MetaData(recipe_dir)
    local_version = nv(m.version())
    print("Local recipe for %s has version %s" % (package, local_version))
    if local_version not in versions:
        sys.exit("Error: %s %s is not available on PyPI."
                 % (package, local_version))
    else:
        # Comparing normalized versions, displaying non normalized ones
        new_versions = versions[:norm_versions.index(local_version)]
        if len(new_versions) > 0:
            print("Following new versions of %s are avaliable" % (package))
            for ver in new_versions:
                print(ver)
        else:
            print("No new version for %s is available" % (package))
        sys.exit()


def get_package_metadata(package, d, data, output_dir, python_version, all_extras,
                         recursive, created_recipes, noarch_python, noprompt, packages,
                         extra_specs, config, setup_options):

    print("Downloading %s" % package)

    pkginfo = get_pkginfo(package,
                          filename=d['filename'],
                          pypiurl=d['pypiurl'],
                          md5=d['md5'],
                          python_version=python_version,
                          extra_specs=extra_specs,
                          setup_options=setup_options,
                          config=config)

    setuptools_build = pkginfo.get('setuptools', False)
    setuptools_run = False

    # Look at the entry_points and construct console_script and
    #  gui_scripts entry_points for conda
    entry_points = pkginfo.get('entry_points', [])
    if entry_points:
        if isinstance(entry_points, str):
            # makes sure it is left-shifted
            newstr = "\n".join(x.strip()
                                for x in entry_points.splitlines())
            _config = configparser.ConfigParser()
            entry_points = {}
            try:
                _config.readfp(StringIO(newstr))
            except Exception as err:
                print("WARNING: entry-points not understood: ",
                        err)
                print("The string was", newstr)
                entry_points = pkginfo['entry_points']
            else:
                setuptools_run = True
                for section in _config.sections():
                    if section in ['console_scripts', 'gui_scripts']:
                        value = ['%s=%s' % (option, _config.get(section, option))
                                    for option in _config.options(section)]
                        entry_points[section] = value
        if not isinstance(entry_points, dict):
            print("WARNING: Could not add entry points. They were:")
            print(entry_points)
        else:
            cs = entry_points.get('console_scripts', [])
            gs = entry_points.get('gui_scripts', [])
            if isinstance(cs, string_types):
                cs = [cs]
            if isinstance(gs, string_types):
                gs = [gs]
            # We have *other* kinds of entry-points so we need
            # setuptools at run-time
            if set(entry_points.keys()) - {'console_scripts', 'gui_scripts'}:
                setuptools_build = True
                setuptools_run = True
            # TODO: Use pythonw for gui scripts
            entry_list = (cs + gs)
            if len(cs + gs) != 0:
                d['entry_points'] = INDENT.join([''] + entry_list)
                d['entry_comment'] = ''
                d['build_comment'] = ''
                d['test_commands'] = INDENT.join([''] + make_entry_tests(entry_list))

    requires = get_requirements(package, pkginfo, all_extras=all_extras)

    if requires or setuptools_build or setuptools_run:
        deps = []
        if setuptools_run:
            deps.append('setuptools')
        for deptext in requires:
            if isinstance(deptext, string_types):
                deptext = deptext.splitlines()
            # Every item may be a single requirement
            #  or a multiline requirements string...
            for dep in deptext:
                # ... and may also contain comments...
                dep = dep.split('#')[0].strip()
                if dep:  # ... and empty (or comment only) lines
                    spec = spec_from_line(dep)
                    if spec is None:
                        sys.exit("Error: Could not parse: %s" % dep)
                    deps.append(spec)

        if 'setuptools' in deps:
            setuptools_build = False
            setuptools_run = False
            d['egg_comment'] = ''
            d['build_comment'] = ''
        d['build_depends'] = INDENT.join([''] +
                                            ['setuptools'] * setuptools_build +
                                            deps)
        d['run_depends'] = INDENT.join([''] +
                                        ['setuptools'] * setuptools_run +
                                        deps)

        if recursive:
            for dep in deps:
                dep = dep.split()[0]
                if not exists(join(output_dir, dep)):
                    if dep not in created_recipes:
                        packages.append(dep)

    if noarch_python:
        d['build_comment'] = ''
        d['noarch_python_comment'] = ''

    if 'packagename' not in d:
        d['packagename'] = pkginfo['name'].lower()
    if d['version'] == 'UNKNOWN':
        d['version'] = pkginfo['version']

    if pkginfo.get('packages'):
        deps = set(pkginfo['packages'])
        if d['import_tests']:
            if not d['import_tests'] or d['import_tests'] == 'PLACEHOLDER':
                olddeps = []
            else:
                olddeps = [x for x in d['import_tests'].split()
                        if x != '-']
            deps = set(olddeps) | deps
        d['import_tests'] = INDENT.join(sorted(deps))
        d['import_comment'] = ''

        d['tests_require'] = INDENT.join(sorted([spec_from_line(pkg) for pkg
                                                    in pkginfo['tests_require']]))

    if pkginfo.get('homeurl'):
        d['homeurl'] = pkginfo['homeurl']
    else:
        if data and 'homeurl' in data:
            d['homeurl'] = data['homeurl']
        else:
            d['homeurl'] = "The package home page"
            d['home_comment'] = '#'

    if pkginfo.get('summary'):
        d['summary'] = repr(pkginfo['summary'])
    else:
        if data:
            d['summary'] = repr(data['summary'])
        else:
            d['summary'] = "Summary of the package"
            d['summary_comment'] = '#'
    if d['summary'].startswith("u'") or d['summary'].startswith('u"'):
        d['summary'] = d['summary'][1:]

    license_classifier = "License :: OSI Approved :: "
    if pkginfo.get('classifiers'):
        licenses = [classifier.split(license_classifier, 1)[1] for
            classifier in pkginfo['classifiers'] if classifier.startswith(license_classifier)]
    elif data and 'classifiers' in data:
        licenses = [classifier.split(license_classifier, 1)[1] for classifier in
                data['classifiers'] if classifier.startswith(license_classifier)]
    else:
        licenses = []
    if not licenses:
        if pkginfo.get('license'):
            license_name = pkginfo['license']
        elif data and 'license' in data:
            license_name = data['license']
        else:
            license_name = None
        if license_name:
            if noprompt:
                pass
            elif '\n' not in license_name:
                print('Using "%s" for the license' % license_name)
            else:
                # Some projects put the whole license text in this field
                print("This is the license for %s" % package)
                print()
                print(license_name)
                print()
                license_name = input("What license string should I use? ")
        else:
            if noprompt:
                license_name = "UNKNOWN"
            else:
                license_name = input(("No license could be found for %s on " +
                                    "PyPI or in the source. What license should I use? ") %
                                package)
    else:
        license_name = ' or '.join(licenses)
    d['license'] = license_name
    d['license_family'] = guess_license_family(license_name, allowed_license_families)


def valid(name):
    if (re.match("[_A-Za-z][_a-zA-Z0-9]*$", name) and not keyword.iskeyword(name)):
        return name
    else:
        return ''


def unpack(src_path, tempdir):
    if src_path.endswith(('.tar.gz', '.tar.bz2', '.tgz', '.tar.xz', '.tar')):
        tar_xf(src_path, tempdir)
    elif src_path.endswith('.zip'):
        unzip(src_path, tempdir)
    else:
        raise Exception("not a valid source: %s" % src_path)


def get_dir(tempdir):
    lst = [fn for fn in listdir(tempdir) if not fn.startswith('.') and
           isdir(join(tempdir, fn))]
    if len(lst) == 1:
        dir_path = join(tempdir, lst[0])
        if isdir(dir_path):
            return dir_path
    if not lst:
        return tempdir
    raise Exception("could not find unpacked source dir")


def get_requirements(package, pkginfo, all_extras=True):
    # Look for package[extra,...] features spec:
    match_extras = re.match(r'^([^[]+)\[([^]]+)\]$', package)
    if match_extras:
        package, extras = match_extras.groups()
        extras = extras.split(',')
    else:
        extras = []

    # Extract requested extra feature requirements...
    if all_extras:
        extras_require = list(pkginfo['extras_require'].values())
    else:
        try:
            extras_require = [pkginfo['extras_require'][x] for x in extras]
        except KeyError:
            sys.exit("Error: Invalid extra features: [%s]" % ','.join(extras))

    # ... and collect all needed requirement specs in a single list:
    requires = []
    for specs in [pkginfo.get('install_requires', "")] + extras_require:
        if isinstance(specs, string_types):
            requires.append(specs)
        else:
            requires.extend(specs)

    return requires


def get_pkginfo(package, filename, pypiurl, md5, python_version, extra_specs, config,
                setup_options):
    # Unfortunately, two important pieces of metadata are only stored in
    # the package itself: the dependencies, and the entry points (if the
    # package uses distribute).  Our strategy is to download the package
    # and "fake" distribute/setuptools's setup() function to get this
    # information from setup.py. If this sounds evil, keep in mind that
    # distribute itself already works by monkeypatching distutils.
    tempdir = mkdtemp('conda_skeleton_' + filename)

    if not isdir(config.src_cache):
        makedirs(config.src_cache)

    try:
        # Download it to the build source cache. That way, you have
        # it.
        download_path = join(config.src_cache, filename)
        if not isfile(download_path) or \
                hashsum_file(download_path, 'md5') != md5:
            download(pypiurl, join(config.src_cache, filename))
        else:
            print("Using cached download")
        print("Unpacking %s..." % package)
        unpack(join(config.src_cache, filename), tempdir)
        print("done")
        print("working in %s" % tempdir)
        src_dir = get_dir(tempdir)
        # TODO: find args parameters needed by run_setuppy
        run_setuppy(src_dir, tempdir, python_version, extra_specs=extra_specs, config=config,
                    setup_options=setup_options)
        try:
            with open(join(tempdir, 'pkginfo.yaml')) as fn:
                pkg_info = yaml.load(fn)
        except IOError:
            pkg_info = pkginfo.SDist(download_path).__dict__
    finally:
        rm_rf(tempdir)

    return pkg_info


def run_setuppy(src_dir, temp_dir, python_version, extra_specs, config, setup_options):
    '''
    Patch distutils and then run setup.py in a subprocess.

    :param src_dir: Directory containing the source code
    :type src_dir: str
    :param temp_dir: Temporary directory for doing for storing pkginfo.yaml
    :type temp_dir: str
    '''
    specs = ['python %s*' % python_version, 'pyyaml', 'setuptools']
    with open(os.path.join(src_dir, "setup.py")) as setup:
        text = setup.read()
        if 'import numpy' in text or 'from numpy' in text:
            specs.append('numpy')

    specs.extend(extra_specs)

    # Do everything in the build env in case the setup.py install goes
    # haywire.
    # TODO: Try with another version of Python if this one fails. Some
    # packages are Python 2 or Python 3 only.

    create_env(config.build_prefix, specs=specs,
               clear_cache=False,
               config=config)
    stdlib_dir = join(config.build_prefix,
                      'Lib' if sys.platform == 'win32'
                      else 'lib/python%s' % python_version)

    patch = join(temp_dir, 'pypi-distutils.patch')
    with open(patch, 'w') as f:
        f.write(DISTUTILS_PATCH.format(temp_dir.replace('\\', '\\\\')))

    if exists(join(stdlib_dir, 'distutils', 'core.py-copy')):
        rm_rf(join(stdlib_dir, 'distutils', 'core.py'))
        copy2(join(stdlib_dir, 'distutils', 'core.py-copy'),
              join(stdlib_dir, 'distutils', 'core.py'))
        # Avoid race conditions. Invalidate the cache.
        if PY3:
            rm_rf(join(stdlib_dir, 'distutils', '__pycache__',
                'core.cpython-%s%s.pyc' % sys.version_info[:2]))
            rm_rf(join(stdlib_dir, 'distutils', '__pycache__',
                'core.cpython-%s%s.pyo' % sys.version_info[:2]))
        else:
            rm_rf(join(stdlib_dir, 'distutils', 'core.pyc'))
            rm_rf(join(stdlib_dir, 'distutils', 'core.pyo'))
    else:
        copy2(join(stdlib_dir, 'distutils', 'core.py'), join(stdlib_dir,
            'distutils', 'core.py-copy'))
    apply_patch(join(stdlib_dir, 'distutils'), patch, config=config)

    # Save PYTHONPATH for later
    env = os.environ.copy()
    if 'PYTHONPATH' in env:
        env[str('PYTHONPATH')] = str(src_dir + ':' + env['PYTHONPATH'])
    else:
        env[str('PYTHONPATH')] = str(src_dir)
    cwd = getcwd()
    chdir(src_dir)
    cmdargs = [config.build_python, 'setup.py', 'install']
    cmdargs.extend(setup_options)
    try:
        check_call_env(cmdargs, env=env)
    except subprocess.CalledProcessError:
        print('$PYTHONPATH = %s' % env['PYTHONPATH'])
        sys.exit('Error: command failed: %s' % ' '.join(cmdargs))
    finally:
        chdir(cwd)


def make_entry_tests(entry_list):
    tests = []
    for entry_point in entry_list:
        entry = entry_point.partition('=')[0].strip()
        tests.append(entry + " --help")
    return tests
