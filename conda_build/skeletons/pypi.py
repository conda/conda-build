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
from six.moves.urllib.parse import urljoin, urlsplit
import yaml
try:
    import ruamel_yaml
except ImportError:
    try:
        import ruamel.yaml as ruamel_yaml
    except ImportError:
        raise ImportError("No ruamel_yaml library available.\n"
                          "To proceed, conda install ruamel_yaml")

from conda_build.conda_interface import spec_from_line
from conda_build.conda_interface import input, configparser, StringIO, string_types, PY3
from conda_build.conda_interface import download
from conda_build.conda_interface import normalized_version
from conda_build.conda_interface import human_bytes, hashsum_file
from conda_build.conda_interface import default_python

from conda_build.utils import tar_xf, unzip, rm_rf, check_call_env, ensure_list
from conda_build.source import apply_patch
from conda_build.environ import create_env
from conda_build.config import Config
from conda_build.metadata import MetaData
from conda_build.license_family import allowed_license_families, guess_license_family
from conda_build.render import FIELDS as EXPECTED_SECTION_ORDER

pypi_example = """
Examples:

Create a recipe for the sympy package:

    conda skeleton pypi sympy

Create a recipes for the flake8 package and all its dependencies:

    conda skeleton pypi --recursive flake8

Use the --pypi-url flag to point to a PyPI mirror url:

    conda skeleton pypi --pypi-url <mirror-url> package_name
"""

# Definition of REQUIREMENTS_ORDER below are from
# https://github.com/conda-forge/conda-smithy/blob/master/conda_smithy/lint_recipe.py#L16
REQUIREMENTS_ORDER = ['host', 'run']

# Definition of ABOUT_ORDER reflects current practice
ABOUT_ORDER = ['home', 'license', 'license_family', 'license_file', 'summary',
               'description', 'doc_url', 'dev_url']

# This may be overkill, but some day sha256 won't be enough. Might as well be
# ready...list these in order of decreasing preference.
POSSIBLE_DIGESTS = ['sha256', 'md5']

POSSIBLE_FILE_EXTENSIONS = ['tar.gz', 'tar.bz2', 'zip', 'tar', 'gz']

PYPI_META_HEADER = """{{% set name = "{packagename}" %}}
{{% set version = "{version}" %}}
{{% set file_ext = "{file_ext}" %}}
{{% set hash_type = "{hash_type}" %}}
{{% set hash_value = "{hash_value}" %}}

"""

# To preserve order of the output in each of the sections the data type
# needs to be ordered.
# The top-level ordering is irrelevant because the write order of 'package',
# etc. is determined by EXPECTED_SECTION_ORDER.
PYPI_META_STATIC = {
    'package': ruamel_yaml.comments.CommentedMap([
        ('name', '{{ name|lower }}'),
        ('version', '{{ version }}'),
    ]),
    'source': ruamel_yaml.comments.CommentedMap([
        ('fn', '{{ name }}-{{ version }}.{{ file_ext }}'),
        ('url', '/packages/source/{{ name[0] }}/{{ name }}/{{ name }}-{{ version }}.{{ file_ext }}'),  # NOQA
        ('{{ hash_type }}', '{{ hash_value }}'),
    ]),
    'build': ruamel_yaml.comments.CommentedMap([
        ('number', 0),
    ]),
    'extra': ruamel_yaml.comments.CommentedMap([
        ('recipe-maintainers', '')
    ]),
}

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
+    data['home'] = kwargs.get('url', None)
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


def _ssl_no_verify():
    """Gets whether the SSL_NO_VERIFY environment variable is set to 1 or True.

    This provides a workaround for users in some corporate environments where
    MITM style proxies make it difficult to fetch data over HTTPS.
    """
    return os.environ.get('SSL_NO_VERIFY', '').strip().lower() in ('1', 'true')


def package_exists(package_name, pypi_url=None):
    if not pypi_url:
        pypi_url = 'https://pypi.io/pypi'
    # request code will be 404 if the package does not exist.  Requires exact match.
    r = requests.get(pypi_url + '/' + package_name, verify=not _ssl_no_verify())
    return r.status_code != 404


def skeletonize(packages, output_dir=".", version=None, recursive=False,
                all_urls=False, pypi_url='https://pypi.io/pypi/', noprompt=True,
                version_compare=False, python_version=default_python, manual_url=False,
                all_extras=False, noarch_python=False, config=None, setup_options=None,
                extra_specs=[],
                pin_numpy=False):
    package_dicts = {}

    if not setup_options:
        setup_options = []

    if isinstance(setup_options, string_types):
        setup_options = [setup_options]

    if not config:
        config = Config()

    created_recipes = []
    while packages:
        package = packages.pop()
        created_recipes.append(package)

        is_url = ':' in package

        if is_url:
            package_pypi_url = ''
        else:
            package_pypi_url = urljoin(pypi_url, '/'.join((package, 'json')))

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
                'test_commands': '',
                'tests_require': '',
            })
        if is_url:
            del d['packagename']

        if is_url:
            d['version'] = 'UNKNOWN'
            # Make sure there is always something to pass in for this
            pypi_data = {}
        else:
            sort_by_version = lambda l: sorted(l, key=parse_version)

            pypi_resp = requests.get(package_pypi_url, verify=not _ssl_no_verify())

            if pypi_resp.status_code != 200:
                sys.exit("Request to fetch %s failed with status: %d"
                        % (package_pypi_url, pypi_resp.status_code))

            pypi_data = pypi_resp.json()

            versions = sort_by_version(pypi_data['releases'].keys())

            if version_compare:
                version_compare(versions)
            if version:
                if version not in versions:
                    sys.exit("Error: Version %s of %s is not available on PyPI."
                             % (version, package))
                d['version'] = version
            else:
                # select the most visible version from PyPI.
                if not versions:
                    sys.exit("Error: Could not find any versions of package %s" % package)
                if len(versions) > 1:
                    print("Warning, the following versions were found for %s" %
                          package)
                    for ver in versions:
                        print(ver)
                    print("Using %s" % versions[-1])
                    print("Use --version to specify a different version.")
                d['version'] = versions[-1]

        data, d['pypiurl'], d['filename'], d['digest'] = get_download_data(pypi_data,
                                                                           package,
                                                                           d['version'],
                                                                           is_url, all_urls,
                                                                           noprompt, manual_url)

        d['import_tests'] = ''

        # Get summary and description directly from the metadata returned
        # from PyPI. summary will be pulled from package information in
        # get_package_metadata or a default value set if it turns out that
        # data['summary'] is empty.
        d['summary'] = data.get('summary', '')
        d['description'] = data.get('description', '')
        get_package_metadata(package, d, data, output_dir, python_version,
                             all_extras, recursive, created_recipes, noarch_python,
                             noprompt, packages, extra_specs, config=config,
                             setup_options=setup_options)

        # Set these *after* get_package_metadata so that the preferred hash
        # can be calculated from the downloaded file, if necessary.
        d['hash_type'] = d['digest'][0]
        d['hash_value'] = d['digest'][1]

        # Change requirements to use format that guarantees the numpy
        # version will be pinned when the recipe is built and that
        # the version is included in the build string.
        if pin_numpy:
            for depends in ['build_depends', 'run_depends']:
                deps = d[depends]
                numpy_dep = [idx for idx, dep in enumerate(deps)
                             if 'numpy' in dep]
                if numpy_dep:
                    # Turns out this needs to be inserted before the rest
                    # of the numpy spec.
                    deps.insert(numpy_dep[0], 'numpy x.x')
                    d[depends] = deps

    for package in package_dicts:
        d = package_dicts[package]
        name = d['packagename']
        makedirs(join(output_dir, name))
        print("Writing recipe for %s" % package.lower())
        with open(join(output_dir, name, 'meta.yaml'), 'w') as f:
            rendered_recipe = PYPI_META_HEADER.format(**d)

            ordered_recipe = ruamel_yaml.comments.CommentedMap()
            # Create all keys in expected ordered
            for key in EXPECTED_SECTION_ORDER:
                try:
                    ordered_recipe[key] = PYPI_META_STATIC[key]
                except KeyError:
                    ordered_recipe[key] = ruamel_yaml.comments.CommentedMap()

            if '://' not in pypi_url:
                raise ValueError("pypi_url must have protocol (e.g. http://) included")
            base_url = urlsplit(pypi_url)
            base_url = "://".join((base_url.scheme, base_url.netloc))
            ordered_recipe['source']['url'] = urljoin(base_url, ordered_recipe['source']['url'])

            if d['entry_points']:
                ordered_recipe['build']['entry_points'] = d['entry_points']

            if noarch_python:
                ordered_recipe['build']['noarch'] = 'python'

            ordered_recipe['build']['script'] = 'python setup.py install ' + ' '.join(setup_options)
            if any(re.match(r'^setuptools(?:\s|$)', req) for req in d['build_depends']):
                ordered_recipe['build']['script'] += ('--single-version-externally-managed '
                                                      '--record=record.txt')

            # Always require python as a dependency
            ordered_recipe['requirements'] = ruamel_yaml.comments.CommentedMap()
            ordered_recipe['requirements']['host'] = ['python'] + ensure_list(d['build_depends'])
            ordered_recipe['requirements']['run'] = ['python'] + ensure_list(d['run_depends'])

            if d['import_tests']:
                ordered_recipe['test']['imports'] = d['import_tests']

            if d['test_commands']:
                ordered_recipe['test']['commands'] = d['test_commands']

            if d['tests_require']:
                ordered_recipe['test']['requires'] = d['tests_require']

            ordered_recipe['about'] = ruamel_yaml.comments.CommentedMap()

            for key in ABOUT_ORDER:
                try:
                    ordered_recipe['about'][key] = d[key]
                except KeyError:
                    ordered_recipe['about'][key] = ''
            ordered_recipe['extra']['recipe-maintainers'] = ''

            # Prune any top-level sections that are empty
            for key in EXPECTED_SECTION_ORDER:
                if not ordered_recipe[key]:
                    del ordered_recipe[key]
                else:
                    rendered_recipe += ruamel_yaml.dump({key: ordered_recipe[key]},
                                                Dumper=ruamel_yaml.RoundTripDumper,
                                                default_flow_style=False,
                                                width=200)
                    rendered_recipe += '\n'
            # make sure that recipe ends with one newline, by god.
            rendered_recipe.rstrip()

            # This hackery is necessary because
            #  - the default indentation of lists is not what we would like.
            #    Ideally we'd contact the ruamel.yaml auther to find the right
            #    way to do this. See this PR thread for more:
            #    https://github.com/conda/conda-build/pull/2205#issuecomment-315803714
            #    Brute force fix below.

            # Fix the indents
            recipe_lines = []
            for line in rendered_recipe.splitlines():
                match = re.search('^\s+(-) ', line,
                                  flags=re.MULTILINE)
                if match:
                    pre, sep, post = line.partition('-')
                    sep = '  ' + sep
                    line = pre + sep + post
                recipe_lines.append(line)
            rendered_recipe = '\n'.join(recipe_lines)

            f.write(rendered_recipe)


def add_parser(repos):
    """Modify repos in place, adding the PyPI option"""
    pypi = repos.add_parser(
        "pypi",
        help="""
    Create recipe skeleton for packages hosted on the Python Packaging Index
    (PyPI) (pypi.io).
        """,
        epilog=pypi_example,
    )
    pypi.add_argument(
        "packages",
        nargs='+',
        help="""PyPi packages to create recipe skeletons for.
                You can also specify package[extra,...] features.""",
    )
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
        default='https://pypi.io/pypi/',
        help="URL to use for PyPI (default: %(default)s).",
    )
    pypi.add_argument(
        "--prompt",
        action="store_false",
        default=True,
        dest="noprompt",
        help="""Prompt the user on ambiguous choices.  Default is to make the
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


def digest_from_fragment(fragment):
    """
    Try to parse a checksum from a URL fragment.
    """
    for p in POSSIBLE_DIGESTS:
        search_for = p + '='
        if fragment.startswith(search_for):
            digest = (p, fragment[len(search_for):])
            break
    else:
        digest = ()
    return digest


def get_download_data(pypi_data, package, version, is_url, all_urls, noprompt, manual_url):
    """
    Get at least one valid *source* download URL or fail.

    Returns
    -------

    data : dict
        Summary of package information
    pypiurl : str
        Download URL of package, which may or may not actually be from PyPI.
    filename : str
        Name of file; used to check cache
    digest : dict
        Key is type of checksum, value is the checksum.
    """
    data = pypi_data['info'] if not is_url else {}

    # PyPI will typically have several downloads (source, wheels) for one
    # package/version.
    urls = [url for url in pypi_data['releases'][version]] if not is_url else [package]

    if not is_url and not all_urls:
        # Try to find source urls
        urls = [url for url in urls if url['packagetype'] == 'sdist']

    if not urls:
        # Try harder for a download location
        if data.get('download_url'):
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
            digest = digest_from_fragment(fragment)
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
        # Found a location from PyPI.
        url = urls[n]
        pypiurl = url['url']
        print("Using url %s (%s) for %s." % (pypiurl,
            human_bytes(url['size'] or 0), package))
        # List of digests we might get in order of preference
        for p in POSSIBLE_DIGESTS:
            try:
                if url['digests'][p]:
                    digest = (p, url['digests'][p])
                    break
            except KeyError:
                continue
        else:
            # That didn't work, even though as of 7/17/2017 some packages
            # have a 'digests' entry.
            # As a last-ditch effort, try for the md5_digest entry.
            try:
                digest = ('md5', url['md5_digest'])
            except KeyError:
                # Give up
                digest = ()
        filename = url['filename'] or 'package'
    else:
        # User provided a URL, try to use it.
        print("Using url %s" % package)
        pypiurl = package
        U = parse_url(package)
        digest = digest_from_fragment(U.fragment)
        # TODO: 'package' won't work with unpack()
        filename = U.path.rsplit('/', 1)[-1] or 'package'

    return (data, pypiurl, filename, digest)


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


def convert_version(version):
    """Convert version into a pin-compatible format according to PEP440."""
    version_parts = version.split('.')
    suffixes = ('post', 'pre')
    if any(suffix in version_parts[-1] for suffix in suffixes):
        version_parts.pop()
    # the max pin length is n-1, but in terms of index this is n-2
    max_ver_len = len(version_parts) - 2
    version_parts[max_ver_len] = int(version_parts[max_ver_len]) + 1
    max_pin = '.'.join(str(v) for v in version_parts[:max_ver_len + 1])
    pin_compatible = ' >={},<{}' .format(version, max_pin)
    return pin_compatible


def get_package_metadata(package, d, data, output_dir, python_version, all_extras,
                         recursive, created_recipes, noarch_python, noprompt, packages,
                         extra_specs, config, setup_options):

    print("Downloading %s" % package)
    print("PyPI URL: ", d['pypiurl'])
    pkginfo = get_pkginfo(package,
                          filename=d['filename'],
                          pypiurl=d['pypiurl'],
                          digest=d['digest'],
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
            elif cs and isinstance(cs, list) and isinstance(cs[0], list):
                # We can have lists of lists here
                cs = [item for sublist in [s for s in cs] for item in sublist]
            if isinstance(gs, string_types):
                gs = [gs]
            elif gs and isinstance(gs, list) and isinstance(gs[0], list):
                gs = [item for sublist in [s for s in gs] for item in sublist]
            # We have *other* kinds of entry-points so we need
            # setuptools at run-time
            if set(entry_points.keys()) - {'console_scripts', 'gui_scripts'}:
                setuptools_build = True
                setuptools_run = True
            # TODO: Use pythonw for gui scripts
            entry_list = (cs + gs)
            if len(cs + gs) != 0:
                d['entry_points'] = entry_list
                d['test_commands'] = make_entry_tests(entry_list)

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
                    if '~' in spec:
                        version = spec.split()[-1]
                        tilde_version = '~ {}' .format(version)
                        pin_compatible = convert_version(version)
                        spec = spec.replace(tilde_version, pin_compatible)
                    if spec is None:
                        sys.exit("Error: Could not parse: %s" % dep)
                    deps.append(spec)

        if 'setuptools' in deps:
            setuptools_build = False
            setuptools_run = False
        d['build_depends'] = ['setuptools'] * setuptools_build + deps
        # Never add setuptools to runtime dependencies.
        d['run_depends'] = deps

        if recursive:
            for dep in deps:
                dep = dep.split()[0]
                if not exists(join(output_dir, dep)):
                    if dep not in created_recipes:
                        packages.append(dep)

    if 'packagename' not in d:
        d['packagename'] = pkginfo['name'].lower()
    if d['version'] == 'UNKNOWN':
        d['version'] = pkginfo['version']

    for ext in POSSIBLE_FILE_EXTENSIONS:
        if d['pypiurl'].split('#')[0].endswith(ext):
            d['file_ext'] = ext
            break

    if pkginfo.get('packages'):
        deps = set(pkginfo['packages'])
        if d['import_tests']:
            if not d['import_tests'] or d['import_tests'] == 'PLACEHOLDER':
                olddeps = []
            else:
                olddeps = [x for x in d['import_tests'].split()
                        if x != '-']
            deps = set(olddeps) | deps
        d['import_tests'] = sorted(deps)

        d['tests_require'] = sorted([spec_from_line(pkg) for pkg
                                     in ensure_list(pkginfo['tests_require'])])

    if pkginfo.get('home'):
        d['home'] = pkginfo['home']
    else:
        if data and 'home' in data:
            d['home'] = data['home']
        else:
            d['home'] = "The package home page"

    if pkginfo.get('summary'):
        if 'summary' in d and not d['summary']:
            # Need something here, use what the package had
            d['summary'] = pkginfo['summary']
    else:
        d['summary'] = "Summary of the package"

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
    if 'new_hash_value' in pkginfo:
        d['digest'] = pkginfo['new_hash_value']


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
        # match PEP 508 environment markers; currently only matches the
        #  subset of environment markers that compare to python_version
        #  using a single basic Python comparison operator
        version_marker = re.compile(r'^:python_version(<|<=|!=|==|>=|>)(.+)$')
        for extra in pkginfo['extras_require']:
            match_ver_mark = version_marker.match(extra)
            if match_ver_mark:
                op, ver = match_ver_mark.groups()
                try:
                    ver_tuple = tuple(int(x) for x in ver.strip('\'"').split("."))
                except ValueError:
                    pass  # bad match; abort
                else:
                    if op == "<":
                        satisfies_ver = sys.version_info < ver_tuple
                    elif op == "<=":
                        satisfies_ver = sys.version_info <= ver_tuple
                    elif op == "!=":
                        satisfies_ver = sys.version_info != ver_tuple
                    elif op == "==":
                        satisfies_ver = sys.version_info == ver_tuple
                    elif op == ">=":
                        satisfies_ver = sys.version_info >= ver_tuple
                    else:  # op == ">":
                        satisfies_ver = sys.version_info > ver_tuple
                    if satisfies_ver:
                        extras_require += pkginfo['extras_require'][extra]

    # ... and collect all needed requirement specs in a single list:
    requires = []
    for specs in [pkginfo.get('install_requires', "")] + extras_require:
        if isinstance(specs, string_types):
            requires.append(specs)
        else:
            requires.extend(specs)

    return requires


def get_pkginfo(package, filename, pypiurl, digest, python_version, extra_specs, config,
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

    hash_type = digest[0]
    hash_value = digest[1]
    try:
        # Download it to the build source cache. That way, you have
        # it.
        download_path = join(config.src_cache, filename)
        if not isfile(download_path) or \
                hashsum_file(download_path, hash_type) != hash_value:
            download(pypiurl, join(config.src_cache, filename))
            if hashsum_file(download_path, hash_type) != hash_value:
                raise RuntimeError(' Download of {} failed'
                                   ' checksum type {} expected value {}. Please'
                                   ' try again.'.format(package, hash_type, hash_value))
        else:
            print("Using cached download")
        # Calculate the preferred hash type here if necessary.
        # Needs to be done in this block because this is where we have
        # access to the source file.
        if hash_type != POSSIBLE_DIGESTS[0]:
            new_hash_value = hashsum_file(download_path, POSSIBLE_DIGESTS[0])
        else:
            new_hash_value = ''

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
                pkg_info = yaml.safe_load(fn)
        except IOError:
            pkg_info = pkginfo.SDist(download_path).__dict__
        if new_hash_value:
            pkg_info['new_hash_value'] = (POSSIBLE_DIGESTS[0], new_hash_value)
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
    # TODO: we could make everyone's lives easier if we include packaging here, because setuptools
    #    needs it in recent versions.  At time of writing, it is not a package in defaults, so this
    #    actually breaks conda-build right now.  Omit it until packaging is on defaults.
    # specs = ['python %s*' % python_version, 'pyyaml', 'setuptools', 'six', 'packaging', 'appdirs']
    specs = ['python %s*' % python_version, 'pyyaml', 'setuptools']
    with open(os.path.join(src_dir, "setup.py")) as setup:
        text = setup.read()
        if 'import numpy' in text or 'from numpy' in text:
            specs.append('numpy')

    specs.extend(extra_specs)

    rm_rf(config.host_prefix)
    create_env(config.host_prefix, specs_or_actions=specs, env='host',
                subdir=config.host_subdir, clear_cache=False, config=config)
    stdlib_dir = join(config.host_prefix,
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
    cmdargs = [config.host_python, 'setup.py', 'install']
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
