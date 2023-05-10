# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
Tools for converting PyPI packages to conda recipes.
"""


import keyword
import logging
import os
import re
import subprocess
import sys
from collections import OrderedDict, defaultdict
from os import chdir, getcwd, listdir, makedirs
from os.path import abspath, exists, isdir, isfile, join
from shutil import copy2
from tempfile import mkdtemp
from urllib.parse import urljoin, urlsplit

import pkginfo
import requests
import yaml
from requests.packages.urllib3.util.url import parse_url

from conda_build.conda_interface import (
    StringIO,
    configparser,
    default_python,
    download,
    hashsum_file,
    human_bytes,
    input,
    normalized_version,
    spec_from_line,
)
from conda_build.config import Config
from conda_build.environ import create_env
from conda_build.license_family import allowed_license_families, guess_license_family
from conda_build.metadata import MetaData
from conda_build.render import FIELDS as EXPECTED_SECTION_ORDER
from conda_build.source import apply_patch
from conda_build.utils import (
    check_call_env,
    decompressible_exts,
    ensure_list,
    rm_rf,
    tar_xf,
)
from conda_build.version import _parse as parse_version

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
REQUIREMENTS_ORDER = ["host", "run"]

# Definition of ABOUT_ORDER reflects current practice
ABOUT_ORDER = [
    "home",
    "license",
    "license_family",
    "license_file",
    "summary",
    "doc_url",
    "dev_url",
]

PYPI_META_HEADER = """{{% set name = "{packagename}" %}}
{{% set version = "{version}" %}}

"""

# To preserve order of the output in each of the sections the data type
# needs to be ordered.
# The top-level ordering is irrelevant because the write order of 'package',
# etc. is determined by EXPECTED_SECTION_ORDER.
PYPI_META_STATIC = {
    "package": OrderedDict(
        [
            ("name", "{{ name|lower }}"),
            ("version", "{{ version }}"),
        ]
    ),
    "source": OrderedDict(
        [
            (
                "url",
                "/packages/source/{{ name[0] }}/{{ name }}/{{ name }}-{{ version }}.tar.gz",
            ),  # NOQA
        ]
    ),
    "build": OrderedDict(
        [
            ("number", 0),
        ]
    ),
    "extra": OrderedDict([("recipe-maintainers", "")]),
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
+import ruamel.yaml as yaml
+from ruamel.yaml import Loader, SafeLoader
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

INDENT = "\n    - "


def _ssl_no_verify():
    """Gets whether the SSL_NO_VERIFY environment variable is set to 1 or True.

    This provides a workaround for users in some corporate environments where
    MITM style proxies make it difficult to fetch data over HTTPS.
    """
    return os.environ.get("SSL_NO_VERIFY", "").strip().lower() in ("1", "true")


def package_exists(package_name, pypi_url=None):
    if not pypi_url:
        pypi_url = "https://pypi.io/pypi"
    # request code will be 404 if the package does not exist.  Requires exact match.
    r = requests.get(pypi_url + "/" + package_name, verify=not _ssl_no_verify())
    return r.status_code != 404


def __print_with_indent(line, prefix="", suffix="", level=0, newline=True):
    output = ""
    if level:
        output = " " * level
    return output + prefix + line + suffix + ("\n" if newline else "")


def _print_dict(recipe_metadata, order=None, level=0, indent=2):
    """Free function responsible to get the metadata which represents the
    recipe and convert it to the yaml format.

    :param OrderedDict recipe_metadata:
    :param list order: Order to be write each section
    :param int level:
    :param int indent: Indentation - Number of empty spaces for each level
    :return string: Recipe rendered with the metadata
    """
    rendered_recipe = ""
    if not order:
        order = sorted(list(recipe_metadata.keys()))
    for section_name in order:
        if section_name in recipe_metadata and recipe_metadata[section_name]:
            rendered_recipe += __print_with_indent(section_name, suffix=":")
            for attribute_name, attribute_value in recipe_metadata[
                section_name
            ].items():
                if attribute_value is None:
                    continue
                if isinstance(attribute_value, str) or not hasattr(
                    attribute_value, "__iter__"
                ):
                    rendered_recipe += __print_with_indent(
                        attribute_name, suffix=":", level=level + indent, newline=False
                    )
                    rendered_recipe += _formating_value(attribute_name, attribute_value)
                elif hasattr(attribute_value, "keys"):
                    rendered_recipe += _print_dict(
                        attribute_value, sorted(list(attribute_value.keys()))
                    )
                # assume that it's a list if it exists at all
                elif attribute_value:
                    rendered_recipe += __print_with_indent(
                        attribute_name, suffix=":", level=level + indent
                    )
                    for item in attribute_value:
                        rendered_recipe += __print_with_indent(
                            item, prefix="- ", level=level + indent
                        )
            # add a newline in between sections
            if level == 0:
                rendered_recipe += "\n"

    return rendered_recipe


def _formating_value(attribute_name, attribute_value):
    """Format the value of the yaml file. This function will quote the
    attribute value if needed.

    :param string attribute_name: Attribute name
    :param string attribute_value: Attribute value
    :return string: Value quoted if need
    """
    pattern_search = re.compile(r"[@_!#$%^&*()<>?/\|}{~:]")
    if (
        isinstance(attribute_value, str)
        and pattern_search.search(attribute_value)
        or attribute_name in ["summary", "description", "version", "script"]
    ):
        return ' "' + str(attribute_value) + '"\n'
    return " " + str(attribute_value) + "\n"


def skeletonize(
    packages,
    output_dir=".",
    version=None,
    recursive=False,
    all_urls=False,
    pypi_url="https://pypi.io/pypi/",
    noprompt=True,
    version_compare=False,
    python_version=None,
    manual_url=False,
    all_extras=False,
    noarch_python=False,
    config=None,
    setup_options=None,
    extra_specs=[],
    pin_numpy=False,
):
    package_dicts = {}

    if not setup_options:
        setup_options = []

    if isinstance(setup_options, str):
        setup_options = [setup_options]

    if not config:
        config = Config()

    python_version = python_version or config.variant.get("python", default_python)

    created_recipes = []
    while packages:
        package = packages.pop()
        created_recipes.append(package)

        is_url = ":" in package

        if is_url:
            package_pypi_url = ""
        else:
            package_pypi_url = urljoin(pypi_url, "/".join((package, "json")))

        if not is_url:
            dir_path = join(output_dir, package.lower())
            if exists(dir_path) and not version_compare:
                raise RuntimeError("directory already exists: %s" % dir_path)
        d = package_dicts.setdefault(
            package,
            {
                "packagename": package,
                "run_depends": "",
                "build_depends": "",
                "entry_points": "",
                "test_commands": "",
                "tests_require": "",
            },
        )
        if is_url:
            del d["packagename"]

        if is_url:
            d["version"] = "UNKNOWN"
            # Make sure there is always something to pass in for this
            pypi_data = {}
        else:
            pypi_resp = requests.get(package_pypi_url, verify=not _ssl_no_verify())

            if pypi_resp.status_code != 200:
                sys.exit(
                    "Request to fetch %s failed with status: %d"
                    % (package_pypi_url, pypi_resp.status_code)
                )

            pypi_data = pypi_resp.json()

            versions = sorted(pypi_data["releases"].keys(), key=parse_version)

            if version_compare:
                version_compare(versions)
            if version:
                if version not in versions:
                    sys.exit(
                        "Error: Version %s of %s is not available on PyPI."
                        % (version, package)
                    )
                d["version"] = version
            else:
                # select the most visible version from PyPI.
                if not versions:
                    sys.exit(
                        "Error: Could not find any versions of package %s" % package
                    )
                if len(versions) > 1:
                    print("Warning, the following versions were found for %s" % package)
                    for ver in versions:
                        print(ver)
                    print("Using %s" % versions[-1])
                    print("Use --version to specify a different version.")
                d["version"] = versions[-1]

        data, d["pypiurl"], d["filename"], d["digest"] = get_download_data(
            pypi_data, package, d["version"], is_url, all_urls, noprompt, manual_url
        )

        d["import_tests"] = ""

        # Get summary directly from the metadata returned
        # from PyPI. summary will be pulled from package information in
        # get_package_metadata or a default value set if it turns out that
        # data['summary'] is empty.  Ignore description as it is too long.
        d["summary"] = data.get("summary", "")
        get_package_metadata(
            package,
            d,
            data,
            output_dir,
            python_version,
            all_extras,
            recursive,
            created_recipes,
            noarch_python,
            noprompt,
            packages,
            extra_specs,
            config=config,
            setup_options=setup_options,
        )

        # Set these *after* get_package_metadata so that the preferred hash
        # can be calculated from the downloaded file, if necessary.
        d["hash_type"] = d["digest"][0]
        d["hash_value"] = d["digest"][1]

        # Change requirements to use format that guarantees the numpy
        # version will be pinned when the recipe is built and that
        # the version is included in the build string.
        if pin_numpy:
            for depends in ["build_depends", "run_depends"]:
                deps = d[depends]
                numpy_dep = [idx for idx, dep in enumerate(deps) if "numpy" in dep]
                if numpy_dep:
                    # Turns out this needs to be inserted before the rest
                    # of the numpy spec.
                    deps.insert(numpy_dep[0], "numpy x.x")
                    d[depends] = deps

    for package in package_dicts:
        d = package_dicts[package]
        name = d["packagename"].lower()
        makedirs(join(output_dir, name))
        print("Writing recipe for %s" % package.lower())
        with open(join(output_dir, name, "meta.yaml"), "w") as f:
            rendered_recipe = PYPI_META_HEADER.format(**d)

            ordered_recipe = OrderedDict()
            # Create all keys in expected ordered
            for key in EXPECTED_SECTION_ORDER:
                try:
                    ordered_recipe[key] = PYPI_META_STATIC[key]
                except KeyError:
                    ordered_recipe[key] = OrderedDict()

            if "://" not in pypi_url:
                raise ValueError("pypi_url must have protocol (e.g. http://) included")
            base_url = urlsplit(pypi_url)
            base_url = "://".join((base_url.scheme, base_url.netloc))
            ordered_recipe["source"]["url"] = urljoin(
                base_url, ordered_recipe["source"]["url"]
            )
            ordered_recipe["source"]["sha256"] = d["hash_value"]

            if d["entry_points"]:
                ordered_recipe["build"]["entry_points"] = d["entry_points"]

            if noarch_python:
                ordered_recipe["build"]["noarch"] = "python"

            recipe_script_cmd = ["{{ PYTHON }} -m pip install . -vv"]
            ordered_recipe["build"]["script"] = " ".join(
                recipe_script_cmd + setup_options
            )

            # Always require python as a dependency.  Pip is because we use pip for
            #    the install line.
            ordered_recipe["requirements"] = OrderedDict()
            ordered_recipe["requirements"]["host"] = sorted(
                set(["python", "pip"] + list(d["build_depends"]))
            )
            ordered_recipe["requirements"]["run"] = sorted(
                set(["python"] + list(d["run_depends"]))
            )

            if d["import_tests"]:
                ordered_recipe["test"]["imports"] = d["import_tests"]

            if d["test_commands"]:
                ordered_recipe["test"]["commands"] = d["test_commands"]

            if d["tests_require"]:
                ordered_recipe["test"]["requires"] = d["tests_require"]

            ordered_recipe["about"] = OrderedDict()

            for key in ABOUT_ORDER:
                try:
                    ordered_recipe["about"][key] = d[key]
                except KeyError:
                    ordered_recipe["about"][key] = ""
            ordered_recipe["extra"]["recipe-maintainers"] = ["your-github-id-here"]

            # Prune any top-level sections that are empty
            rendered_recipe += _print_dict(ordered_recipe, EXPECTED_SECTION_ORDER)

            # make sure that recipe ends with one newline, by god.
            rendered_recipe.rstrip()

            # This hackery is necessary because
            #  - the default indentation of lists is not what we would like.
            #    Ideally we'd contact the ruamel.yaml author to find the right
            #    way to do this. See this PR thread for more:
            #    https://github.com/conda/conda-build/pull/2205#issuecomment-315803714
            #    Brute force fix below.

            # Fix the indents
            recipe_lines = []
            for line in rendered_recipe.splitlines():
                match = re.search(r"^\s+(-) ", line, flags=re.MULTILINE)
                if match:
                    pre, sep, post = line.partition("-")
                    sep = "  " + sep
                    line = pre + sep + post
                recipe_lines.append(line)
            rendered_recipe = "\n".join(recipe_lines)

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
        nargs="+",
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
        default="https://pypi.io/pypi/",
        help="URL to use for PyPI (default: %(default)s).",
    )
    pypi.add_argument(
        "--prompt",
        action="store_false",
        default=True,
        dest="noprompt",
        help="""Prompt the user on ambiguous choices.  Default is to make the
        best possible choice and continue.""",
    )
    pypi.add_argument(
        "--all-extras",
        action="store_true",
        default=False,
        help="Add all extra feature requirements. Applies to all packages.",
    )
    pypi.add_argument(
        "--recursive",
        action="store_true",
        help="Create recipes for dependencies if they do not already exist.",
    )
    pypi.add_argument(
        "--version-compare",
        action="store_true",
        help="""Compare the package version of the recipe with all available
        versions on PyPI.""",
    )
    pypi.add_argument(
        "--python-version",
        action="store",
        default=default_python,
        help="""Version of Python to use to run setup.py. Default is %(default)s.""",
        choices=["2.7", "3.5", "3.6", "3.7", "3.8", "3.9", "3.10", "3.11"],
    )

    pypi.add_argument(
        "--manual-url",
        action="store_true",
        default=False,
        help=(
            "Manually choose source url when more than one urls are present."
            "Default is the one with least source size."
        ),
    )

    pypi.add_argument(
        "--noarch-python",
        action="store_true",
        default=False,
        help="Creates recipe as noarch python",
    )

    pypi.add_argument(
        "--setup-options",
        action="append",
        default=[],
        help="Options to be added to setup.py install in the recipe. "
        "The same options are passed to setup.py install in both "
        "the construction of the recipe and in the recipe itself."
        "For options that include a double-hypen or to pass multiple "
        "options, use the syntax "
        '--setup-options="--option1 --option-with-arg arg"',
    )

    pypi.add_argument(
        "--pin-numpy",
        action="store_true",
        help="Ensure that the generated recipe pins the version of numpy"
        "to CONDA_NPY.",
    )

    pypi.add_argument(
        "--extra-specs",
        action="append",
        default=[],
        help="Extra specs for the build environment to extract the skeleton.",
    )


def get_download_data(
    pypi_data, package, version, is_url, all_urls, noprompt, manual_url
):
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
    data = pypi_data["info"] if not is_url else {}

    # PyPI will typically have several downloads (source, wheels) for one
    # package/version.
    urls = [url for url in pypi_data["releases"][version]] if not is_url else [package]

    if not is_url and not all_urls:
        # Try to find source urls
        urls = [url for url in urls if url["packagetype"] == "sdist"]

    if not urls:
        # Try harder for a download location
        if data.get("download_url"):
            urls = [defaultdict(str, {"url": data["download_url"]})]
            if not urls[0]["url"]:
                # The package doesn't have a url, or maybe it only has a wheel.
                sys.exit(
                    "Error: Could not build recipe for %s. "
                    "Could not find any valid urls." % package
                )
            U = parse_url(urls[0]["url"])
            if not U.path:
                sys.exit(f"Error: Could not parse url for {package}: {U}")
            urls[0]["filename"] = U.path.rsplit("/")[-1]
            fragment = U.fragment or ""
            digest = fragment.split("=")
        else:
            sys.exit("Error: No source urls found for %s" % package)
    if len(urls) > 1 and not noprompt:
        print("More than one source version is available for %s:" % package)
        if manual_url:
            for i, url in enumerate(urls):
                print(
                    "%d: %s (%s) %s"
                    % (i, url["url"], human_bytes(url["size"]), url["comment_text"])
                )
            n = int(input("which version should i use? "))
        else:
            print("Using the one with the least source size")
            print("use --manual-url to override this behavior")
            _, n = min((url["size"], i) for (i, url) in enumerate(urls))
    else:
        n = 0

    if not is_url:
        # Found a location from PyPI.
        url = urls[n]
        pypiurl = url["url"]
        print(
            "Using url {} ({}) for {}.".format(
                pypiurl, human_bytes(url["size"] or 0), package
            )
        )

        if url["digests"]["sha256"]:
            digest = ("sha256", url["digests"]["sha256"])
        else:
            # That didn't work, even though as of 7/17/2017 some packages
            # have a 'digests' entry.
            # As a last-ditch effort, try for the md5_digest entry.
            digest = ()
        filename = url["filename"] or "package"
    else:
        # User provided a URL, try to use it.
        print("Using url %s" % package)
        pypiurl = package
        U = parse_url(package)
        digest = U.fragment.split("=")
        # TODO: 'package' won't work with unpack()
        filename = U.path.rsplit("/", 1)[-1] or "package"

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
    print(f"Local recipe for {package} has version {local_version}")
    if local_version not in versions:
        sys.exit(f"Error: {package} {local_version} is not available on PyPI.")
    else:
        # Comparing normalized versions, displaying non normalized ones
        new_versions = versions[: norm_versions.index(local_version)]
        if len(new_versions) > 0:
            print("Following new versions of %s are avaliable" % (package))
            for ver in new_versions:
                print(ver)
        else:
            print("No new version for %s is available" % (package))
        sys.exit()


def convert_version(version):
    """Convert version into a pin-compatible format according to PEP440."""
    version_parts = version.split(".")
    suffixes = ("post", "pre")
    if any(suffix in version_parts[-1] for suffix in suffixes):
        version_parts.pop()
    # the max pin length is n-1, but in terms of index this is n-2
    max_ver_len = len(version_parts) - 2
    version_parts[max_ver_len] = int(version_parts[max_ver_len]) + 1
    max_pin = ".".join(str(v) for v in version_parts[: max_ver_len + 1])
    pin_compatible = f" >={version},<{max_pin}"
    return pin_compatible


MARKER_RE = re.compile(
    r"(?P<name>^[^=<>!~\s;]+)"
    r"\s*"
    r"(?P<constraint>[=!><~]=?\s*[^\s;]+)?"
    r"(?:\s*;\s+)?(?P<env_mark_name>[^=<>!~\s;]+)?"
    r"\s*"
    r"(?P<env_mark_constraint>[=<>!\s]+[^=<>!~\s]+)?"
)


def _get_env_marker_operator_and_value(constraint):
    operator, value = constraint.split()
    value = value.strip("'").strip('"').strip()
    return operator, value


def _translate_python_constraint(constraint):
    translation = constraint
    if len(constraint.split()) == 2:
        operator, value = _get_env_marker_operator_and_value(constraint)
        value = "".join(value.split(".")[:2])
        translation = " ".join((operator, value))
    return f"py {translation}"


def _translate_platform_system_constraint(constraint):
    operator, value = _get_env_marker_operator_and_value(constraint)
    system = {
        "Linux": "linux",
        "Darwin": "osx",
        "Windows": "win",
    }.get(value, value.lower())
    return "{}{}".format("not " if operator == "!=" else "", system)


def _translate_sys_platform_constraint(constraint):
    operator, value = _get_env_marker_operator_and_value(constraint)
    # Only take the "letter" part to translate, e.g., "linux2"->"linux", "win32"->"win".
    system = re.match("^[a-z]*", value, re.I)[0]
    return "{}{}".format("not " if operator == "!=" else "", system)


def env_mark_lookup(env_mark_name, env_mark_constraint):
    """returns translated variable name and corresponding function to run to normalize the
    version constraint to conda style"""
    # TODO: implement more of these from PEP 508 as necessary:
    #   https://www.python.org/dev/peps/pep-0508/
    env_mark_table = {
        "python_version": _translate_python_constraint,
        "platform_system": _translate_platform_system_constraint,
        "sys_platform": _translate_sys_platform_constraint,
    }
    marker = env_mark_table[env_mark_name](env_mark_constraint)
    return "  # [ " + marker + " ]"


def parse_dep_with_env_marker(dep_str):
    match = MARKER_RE.match(dep_str)
    name = match.group("name")
    if match.group("constraint"):
        name = " ".join((name, match.group("constraint").replace(" ", "")))
    env_mark = ""
    if match.group("env_mark_name"):
        env_mark = env_mark_lookup(
            match.group("env_mark_name"), match.group("env_mark_constraint")
        )
    return name, env_mark


def get_package_metadata(
    package,
    metadata,
    data,
    output_dir,
    python_version,
    all_extras,
    recursive,
    created_recipes,
    noarch_python,
    no_prompt,
    packages,
    extra_specs,
    config,
    setup_options,
):
    print("Downloading %s" % package)
    print("PyPI URL: ", metadata["pypiurl"])
    pkginfo = get_pkginfo(
        package,
        filename=metadata["filename"],
        pypiurl=metadata["pypiurl"],
        digest=metadata["digest"],
        python_version=python_version,
        extra_specs=extra_specs,
        setup_options=setup_options,
        config=config,
    )

    metadata.update(get_entry_points(pkginfo))

    requires = get_requirements(package, pkginfo, all_extras=all_extras)

    if requires or is_setuptools_enabled(pkginfo):
        list_deps = get_dependencies(requires, is_setuptools_enabled(pkginfo))

        metadata["build_depends"] = ["pip"] + list_deps
        # Never add setuptools to runtime dependencies.
        metadata["run_depends"] = list_deps

        if recursive:
            packages += get_recursive_deps(created_recipes, list_deps, output_dir)

    if "packagename" not in metadata:
        metadata["packagename"] = pkginfo["name"].lower()

    if metadata["version"] == "UNKNOWN":
        metadata["version"] = pkginfo["version"]

    metadata["import_tests"] = get_import_tests(pkginfo, metadata.get("import_tests"))
    metadata["tests_require"] = get_tests_require(pkginfo)

    metadata["home"] = get_home(pkginfo, data)

    if not metadata.get("summary"):
        metadata["summary"] = get_summary(pkginfo)
        metadata["summary"] = get_summary(pkginfo)

    license_name = get_license_name(package, pkginfo, no_prompt, data)
    metadata["license"] = clean_license_name(license_name)
    metadata["license_family"] = guess_license_family(
        license_name, allowed_license_families
    )

    if "new_hash_value" in pkginfo:
        metadata["digest"] = pkginfo["new_hash_value"]


def get_recursive_deps(created_recipes, list_deps, output_dir):
    """Function responsible to return the list of dependencies of the other
    projects which were requested.

    :param list created_recipes:
    :param list list_deps:
    :param output_dir:
    :return list:
    """
    recursive_deps = []
    for dep in list_deps:
        dep = dep.split()[0]
        if exists(join(output_dir, dep)) or dep in created_recipes:
            continue
        recursive_deps.append(dep)

    return recursive_deps


def get_dependencies(requires, setuptools_enabled=True):
    """Return the whole dependencies of the specified package
    :param list requires: List of requirements
    :param Bool setuptools_enabled: True if setuptools is enabled and False otherwise
    :return list: Return list of dependencies
    """

    # START :: Copied from conda
    # These can be removed if we want to drop support for conda <= 4.9.0
    def _strip_comment(line):
        return line.split("#")[0].rstrip()

    def _spec_from_line(line):
        spec_pat = re.compile(
            r"""
            (?P<name>[^=<>!\s]+)  # package name
            \s*  # ignore spaces
            (
                (?P<cc>=[^=]+(=[^=]+)?)  # conda constraint
                |
                (?P<pc>(?:[=!]=|[><]=?|~=).+)  # new pip-style constraints
            )?$
            """,
            re.VERBOSE,
        )
        m = spec_pat.match(_strip_comment(line))
        if m is None:
            return None
        name, cc, pc = (m.group("name").lower(), m.group("cc"), m.group("pc"))
        if cc:
            return name + cc.replace("=", " ")
        elif pc:
            if pc.startswith("~= "):
                assert (
                    pc.count("~=") == 1
                ), f"Overly complex 'Compatible release' spec not handled {line}"
                assert pc.count("."), f"No '.' in 'Compatible release' version {line}"
                ver = pc.replace("~= ", "")
                ver2 = ".".join(ver.split(".")[:-1]) + ".*"
                return name + " >=" + ver + ",==" + ver2
            else:
                return name + " " + pc.replace(" ", "")
        else:
            return name

    # END :: Copied from conda

    list_deps = ["setuptools"] if setuptools_enabled else []

    for dep_text in requires:
        if isinstance(dep_text, str):
            dep_text = dep_text.splitlines()
        # Every item may be a single requirement
        #  or a multiline requirements string...
        for dep in dep_text:
            # ... and may also contain comments...
            dep = dep.split("#")[0].strip()
            if not dep:
                continue

            dep_orig = dep
            dep, marker = parse_dep_with_env_marker(dep_orig)
            # if '~' in dep_orig:
            #     # dep_orig = 'kubernetes ~= 11'
            #     version = dep_orig.split()[-1]
            #     tilde_version = '~= {}'.format(version)
            #     pin_compatible = convert_version(version)
            #     spec = dep_orig.replace(tilde_version, pin_compatible)
            #     spec2 = spec_from_line(dep)
            #     if spec != spec2:
            #         print("Disagreement on PEP440 'Compatible release' {} vs {}".format(spec, spec2))
            spec = spec_from_line(dep)
            if "~=" in dep_orig:
                spec = None

            if spec is None:
                if "~=" in dep_orig:
                    log = logging.getLogger(__name__)
                    log.warning(
                        "Your conda is too old to handle ~= PEP440 'Compatible versions', "
                        "using copied implementation."
                    )
                    spec = _spec_from_line(dep_orig)
                if spec is None:
                    sys.exit("Error: Could not parse: %s" % dep)

            if marker:
                spec = " ".join((spec, marker))

            list_deps.append(spec)
    return list_deps


def get_import_tests(pkginfo, import_tests_metada=""):
    """Return the section import in tests

    :param dict pkginfo: Package information
    :param dict import_tests_metada: Imports already present
    :return list: Sorted list with the libraries necessary for the test phase
    """
    if not pkginfo.get("packages"):
        return import_tests_metada

    olddeps = []
    if import_tests_metada != "PLACEHOLDER":
        olddeps = [x for x in import_tests_metada.split() if x != "-"]
    return sorted(set(olddeps) | set(pkginfo["packages"]))


def get_tests_require(pkginfo):
    return sorted(spec_from_line(pkg) for pkg in ensure_list(pkginfo["tests_require"]))


def get_home(pkginfo, data=None):
    default_home = "The package home page"
    if pkginfo.get("home"):
        return pkginfo["home"]
    if data:
        return data.get("home", default_home)
    return default_home


def get_summary(pkginfo):
    return pkginfo.get("summary", "Summary of the package").replace('"', r"\"")


def get_license_name(package, pkginfo, no_prompt=False, data=None):
    """Responsible to return the license name
    :param str package: Package's name
    :param dict pkginfo:Package information
    :param no_prompt: If Prompt is not enabled
    :param dict data: Data
    :return str: License name
    """
    license_classifier = "License :: OSI Approved :: "

    data_classifier = data.get("classifiers", []) if data else []
    pkg_classifier = pkginfo.get("classifiers", data_classifier)
    pkg_classifier = pkg_classifier if pkg_classifier else data_classifier

    licenses = [
        classifier.split(license_classifier, 1)[1]
        for classifier in pkg_classifier
        if classifier.startswith(license_classifier)
    ]

    if licenses:
        return " or ".join(licenses)

    if pkginfo.get("license"):
        license_name = pkginfo["license"]
    elif data and "license" in data:
        license_name = data["license"]
    else:
        license_name = None

    if license_name:
        if no_prompt:
            return license_name
        elif "\n" not in license_name:
            print('Using "%s" for the license' % license_name)
        else:
            # Some projects put the whole license text in this field
            print("This is the license for %s" % package)
            print()
            print(license_name)
            print()
            license_name = input("What license string should I use? ")
    elif no_prompt:
        license_name = "UNKNOWN"
    else:
        license_name = input(
            "No license could be found for %s on PyPI or in the source. "
            "What license should I use? " % package
        )
    return license_name


def clean_license_name(license_name):
    """Remove the word ``license`` from the license
    :param str license_name: Receives the license name
    :return str: Return a string without the word ``license``
    """
    return re.subn(r"(.*)\s+license", r"\1", license_name, flags=re.IGNORECASE)[0]


def get_entry_points(pkginfo):
    """Look at the entry_points and construct console_script and gui_scripts entry_points for conda
    :param pkginfo:
    :return dict:
    """
    entry_points = pkginfo.get("entry_points")
    if not entry_points:
        return {}

    if isinstance(entry_points, str):
        # makes sure it is left-shifted
        newstr = "\n".join(x.strip() for x in entry_points.splitlines())
        _config = configparser.ConfigParser()

        try:
            _config.read_file(StringIO(newstr))
        except Exception as err:
            print("WARNING: entry-points not understood: ", err)
            print("The string was", newstr)
        else:
            entry_points = {}
            for section in _config.sections():
                if section in ["console_scripts", "gui_scripts"]:
                    entry_points[section] = [
                        f"{option}={_config.get(section, option)}"
                        for option in _config.options(section)
                    ]

    if isinstance(entry_points, dict):
        console_script = convert_to_flat_list(entry_points.get("console_scripts", []))
        gui_scripts = convert_to_flat_list(entry_points.get("gui_scripts", []))

        # TODO: Use pythonw for gui scripts
        entry_list = console_script + gui_scripts
        if entry_list:
            return {
                "entry_points": entry_list,
                "test_commands": make_entry_tests(entry_list),
            }
    else:
        print("WARNING: Could not add entry points. They were:")
        print(entry_points)
    return {}


def convert_to_flat_list(var_scripts):
    """Convert a string to a list.
    If the first element of the list is a nested list this function will
    convert it to a flat list.

    :param str/list var_scripts: Receives a string or a list to be converted
    :return list: Return a flat list
    """
    if isinstance(var_scripts, str):
        var_scripts = [var_scripts]
    elif (
        var_scripts
        and isinstance(var_scripts, list)
        and isinstance(var_scripts[0], list)
    ):
        var_scripts = [item for sublist in [s for s in var_scripts] for item in sublist]
    return var_scripts


def is_setuptools_enabled(pkginfo):
    """Function responsible to inspect if skeleton requires setuptools
    :param dict pkginfo: Dict which holds the package information
    :return Bool: Return True if it is enabled or False otherwise
    """
    entry_points = pkginfo.get("entry_points")
    if not isinstance(entry_points, dict):
        return False

    # We have *other* kinds of entry-points so we need
    # setuptools at run-time
    if set(entry_points.keys()) - {"console_scripts", "gui_scripts"}:
        return True
    return False


def valid(name):
    if re.match("[_A-Za-z][_a-zA-Z0-9]*$", name) and not keyword.iskeyword(name):
        return name
    else:
        return ""


def unpack(src_path, tempdir):
    if src_path.lower().endswith(decompressible_exts):
        tar_xf(src_path, tempdir)
    else:
        raise Exception("not a valid source: %s" % src_path)


def get_dir(tempdir):
    lst = [
        fn
        for fn in listdir(tempdir)
        if not fn.startswith(".") and isdir(join(tempdir, fn))
    ]
    if len(lst) == 1:
        dir_path = join(tempdir, lst[0])
        if isdir(dir_path):
            return dir_path
    if not lst:
        return tempdir
    raise Exception("could not find unpacked source dir")


def get_requirements(package, pkginfo, all_extras=True):
    # Look for package[extra,...] features spec:
    match_extras = re.match(r"^([^[]+)\[([^]]+)\]$", package)
    if match_extras:
        package, extras = match_extras.groups()
        extras = extras.split(",")
    else:
        extras = []

    # Extract requested extra feature requirements...
    if all_extras:
        extras_require = list(pkginfo["extras_require"].values())
    else:
        try:
            extras_require = [pkginfo["extras_require"][x] for x in extras]
        except KeyError:
            sys.exit("Error: Invalid extra features: [%s]" % ",".join(extras))
        # match PEP 508 environment markers; currently only matches the
        #  subset of environment markers that compare to python_version
        #  using a single basic Python comparison operator
        version_marker = re.compile(r"^:python_version(<|<=|!=|==|>=|>)(.+)$")
        for extra in pkginfo["extras_require"]:
            match_ver_mark = version_marker.match(extra)
            if match_ver_mark:
                op, ver = match_ver_mark.groups()
                try:
                    ver_tuple = tuple(int(x) for x in ver.strip("'\"").split("."))
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
                        extras_require += pkginfo["extras_require"][extra]

    # ... and collect all needed requirement specs in a single list:
    requires = []
    for specs in [pkginfo.get("install_requires", "")] + extras_require:
        if isinstance(specs, str):
            requires.append(specs)
        else:
            requires.extend(specs)

    return requires


def get_pkginfo(
    package,
    filename,
    pypiurl,
    digest,
    python_version,
    extra_specs,
    config,
    setup_options,
):
    # Unfortunately, two important pieces of metadata are only stored in
    # the package itself: the dependencies, and the entry points (if the
    # package uses distribute).  Our strategy is to download the package
    # and "fake" distribute/setuptools's setup() function to get this
    # information from setup.py. If this sounds evil, keep in mind that
    # distribute itself already works by monkeypatching distutils.
    tempdir = mkdtemp("conda_skeleton_" + filename)

    if not isdir(config.src_cache):
        makedirs(config.src_cache)

    hash_type = digest[0]
    hash_value = digest[1]
    try:
        # Download it to the build source cache. That way, you have
        # it.
        download_path = join(config.src_cache, filename)
        if (
            not isfile(download_path)
            or hashsum_file(download_path, hash_type) != hash_value
        ):
            download(pypiurl, join(config.src_cache, filename))
            if hashsum_file(download_path, hash_type) != hash_value:
                raise RuntimeError(
                    " Download of {} failed"
                    " checksum type {} expected value {}. Please"
                    " try again.".format(package, hash_type, hash_value)
                )
        else:
            print("Using cached download")
        # Calculate the preferred hash type here if necessary.
        # Needs to be done in this block because this is where we have
        # access to the source file.
        if hash_type != "sha256":
            new_hash_value = hashsum_file(download_path, "sha256")
        else:
            new_hash_value = ""

        print("Unpacking %s..." % package)
        unpack(join(config.src_cache, filename), tempdir)
        print("done")
        print("working in %s" % tempdir)
        src_dir = get_dir(tempdir)
        # TODO: find args parameters needed by run_setuppy
        run_setuppy(
            src_dir,
            tempdir,
            python_version,
            extra_specs=extra_specs,
            config=config,
            setup_options=setup_options,
        )
        try:
            with open(join(tempdir, "pkginfo.yaml")) as fn:
                pkg_info = yaml.safe_load(fn)
        except OSError:
            print(
                "WARNING: the pkginfo.yaml file was absent, falling back to pkginfo.SDist"
            )
            pkg_info = pkginfo.SDist(download_path).__dict__
        if new_hash_value:
            pkg_info["new_hash_value"] = ("sha256", new_hash_value)
    finally:
        rm_rf(tempdir)

    return pkg_info


def run_setuppy(src_dir, temp_dir, python_version, extra_specs, config, setup_options):
    """
    Patch distutils and then run setup.py in a subprocess.

    :param src_dir: Directory containing the source code
    :type src_dir: str
    :param temp_dir: Temporary directory for doing for storing pkginfo.yaml
    :type temp_dir: str
    """
    subdir = config.host_subdir
    specs = [
        f"python {python_version}*",
        "pip",
        "ruamel.yaml",
        "setuptools",
    ] + (
        ["m2-patch", "m2-gcc-libs"]
        if config.host_subdir.startswith("win")
        else ["patch"]
    )
    with open(os.path.join(src_dir, "setup.py")) as setup:
        text = setup.read()
        if "import numpy" in text or "from numpy" in text:
            specs.append("numpy")

    specs.extend(extra_specs)

    rm_rf(config.host_prefix)

    create_env(
        config.host_prefix,
        specs_or_actions=specs,
        env="host",
        subdir=subdir,
        clear_cache=False,
        config=config,
    )
    stdlib_dir = join(
        config.host_prefix,
        "Lib" if sys.platform == "win32" else "lib/python%s" % python_version,
    )

    patch = join(temp_dir, "pypi-distutils.patch")
    with open(patch, "wb") as f:
        f.write(DISTUTILS_PATCH.format(temp_dir.replace("\\", "\\\\")).encode("utf-8"))

    if exists(join(stdlib_dir, "distutils", "core.py-copy")):
        rm_rf(join(stdlib_dir, "distutils", "core.py"))
        copy2(
            join(stdlib_dir, "distutils", "core.py-copy"),
            join(stdlib_dir, "distutils", "core.py"),
        )
        # Avoid race conditions. Invalidate the cache.
        rm_rf(
            join(
                stdlib_dir,
                "distutils",
                "__pycache__",
                "core.cpython-%s%s.pyc" % sys.version_info[:2],
            )
        )
        rm_rf(
            join(
                stdlib_dir,
                "distutils",
                "__pycache__",
                "core.cpython-%s%s.pyo" % sys.version_info[:2],
            )
        )
    else:
        copy2(
            join(stdlib_dir, "distutils", "core.py"),
            join(stdlib_dir, "distutils", "core.py-copy"),
        )
    apply_patch(join(stdlib_dir, "distutils"), patch, config=config)

    vendored = join(stdlib_dir, "site-packages", "setuptools", "_distutils")
    if os.path.isdir(vendored):
        apply_patch(vendored, patch, config=config)

    # Save PYTHONPATH for later
    env = os.environ.copy()
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = str(src_dir + ":" + env["PYTHONPATH"])
    else:
        env["PYTHONPATH"] = str(src_dir)
    cwd = getcwd()
    chdir(src_dir)
    cmdargs = [config.host_python, "setup.py", "install"]
    cmdargs.extend(setup_options)
    try:
        check_call_env(cmdargs, env=env)
    except subprocess.CalledProcessError:
        print("$PYTHONPATH = %s" % env["PYTHONPATH"])
        sys.exit("Error: command failed: %s" % " ".join(cmdargs))
    finally:
        chdir(cwd)


def make_entry_tests(entry_list):
    tests = []
    for entry_point in entry_list:
        entry = entry_point.partition("=")[0].strip()
        tests.append(entry + " --help")
    return tests
