# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
Tools for converting CPAN packages to conda recipes.
"""


import codecs
import gzip
import hashlib
import json
import os
import pickle
import subprocess
import sys
import tempfile
from functools import lru_cache, partial
from glob import glob
from os import makedirs
from os.path import basename, dirname, exists, join

import requests

from conda_build import environ
from conda_build.conda_interface import (
    CondaError,
    CondaHTTPError,
    MatchSpec,
    Resolve,
    TmpDownload,
    download,
    get_index,
)
from conda_build.config import get_or_merge_config
from conda_build.utils import check_call_env, on_win
from conda_build.variants import get_default_variant
from conda_build.version import _parse as parse_version

CPAN_META = """\
{{% set name = "{packagename}" %}}
{{% set version = "{version}" %}}
{{% set sha256 = "{sha256}" %}}

package:
  name: {{{{ name }}}}
  version: {{{{ version }}}}

{source_comment}source:
  {useurl}url: {cpanurl}
  {usesha256}sha256: {{{{ sha256 }}}}

# If this is a new build for the same version, increment the build
# number. If you do not include this key, it defaults to 0.
build:
  number: 0
  run_exports:
    weak:
      - {{{{ name }}}} ={{{{ version }}}}

requirements:
  build:{build_depends}

  # Run exports are used now
  host:
    - perl{host_depends}

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
# https://docs.conda.io/projects/conda-build for
# more information about meta.yaml
"""

CPAN_BUILD_SH = """\
#!/bin/bash

set -o errexit -o pipefail

# If it has Build.PL use that, otherwise use Makefile.PL
if [[ -f Build.PL ]]; then
    perl Build.PL
    perl ./Build
    perl ./Build test
    # Make sure this goes in site
    perl ./Build install --installdirs site
elif [[ -f Makefile.PL ]]; then
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
# https://docs.conda.io/projects/conda-build
# for a list of environment variables that are set during the build process.
"""

CPAN_BLD_BAT = """\
:: If it has Build.PL use that, otherwise use Makefile.PL
IF exist Build.PL (
    perl Build.PL
    IF %ERRORLEVEL% NEQ 0 exit /B 1
    Build
    IF %ERRORLEVEL% NEQ 0 exit /B 1
    Build test
    :: Make sure this goes in site
    Build install --installdirs site
    IF %ERRORLEVEL% NEQ 0 exit /B 1
) ELSE IF exist Makefile.PL (
    :: Make sure this goes in site
    perl Makefile.PL INSTALLDIRS=site
    IF %ERRORLEVEL% NEQ 0 exit /B 1
    make
    IF %ERRORLEVEL% NEQ 0 exit /B 1
    make test
    IF %ERRORLEVEL% NEQ 0 exit /B 1
    make install
) ELSE (
    ECHO 'Unable to find Build.PL or Makefile.PL. You need to modify bld.bat.'
    exit 1
)

:: Add more build steps here, if they are necessary.

:: See
:: https://docs.conda.io/projects/conda-build
:: for a list of environment variables that are set during the build process.
"""

perl_core = []


class InvalidReleaseError(RuntimeError):

    """
    An exception that is raised when a release is not available on MetaCPAN.
    """

    pass


class PerlTmpDownload(TmpDownload):

    """
    Subclass Conda's TmpDownload to replace : in download filenames.
    Critical on win.
    """

    def __enter__(self):
        if "://" not in self.url:
            # if we provide the file itself, no tmp dir is created
            self.tmp_dir = None
            return self.url
        else:
            if "CHECKSUMS" in self.url:
                turl = self.url.split("id/")
                filename = turl[1]
            else:
                filename = basename(self.url)

            filename = filename.replace("::", "-")

            self.tmp_dir = tempfile.mkdtemp()

            home = os.path.expanduser("~")
            base_dir = join(
                home, ".conda-build", "cpan", basename(self.url).replace("::", "-")
            )
            dst = join(base_dir, filename)
            dst = dst.replace("::", "-")
            base_dir = dirname(dst)

            if not exists(base_dir):
                makedirs(base_dir)
            dst = get_pickle_file_path(
                cache_dir=base_dir, filename_prefix=filename, other_hashed=(self.url,)
            )
            if not exists(os.path.dirname(dst)):
                makedirs(os.path.dirname(dst))
            if not exists(dst):
                download(self.url, dst)

            return dst


def get_build_dependencies_from_src_archive(package_url, sha256, src_cache):
    import tarfile

    from conda_build import source

    cached_path, _ = source.download_to_cache(
        src_cache, "", {"url": package_url, "sha256": sha256}
    )
    result = []
    with tarfile.open(cached_path) as tf:
        need_f = any(
            [
                f.name.lower().endswith((".f", ".f90", ".f77", ".f95", ".f03"))
                for f in tf
            ]
        )
        # Fortran builds use CC to perform the link (they do not call the linker directly).
        need_c = (
            True
            if need_f
            else any([f.name.lower().endswith((".c", ".xs")) for f in tf])
        )
        need_cxx = any(
            [f.name.lower().endswith((".cxx", ".cpp", ".cc", ".c++")) for f in tf]
        )
        need_autotools = any([f.name.lower().endswith("/configure") for f in tf])
        need_make = (
            True
            if any((need_autotools, need_f, need_cxx, need_c))
            else any([f.name.lower().endswith(("/makefile", "/makevars")) for f in tf])
        )
        if need_c or need_cxx or need_f:
            result.append("{{ compiler('c') }}")
        if need_cxx:
            result.append("{{ compiler('cxx') }}")
        if need_f:
            result.append("{{ compiler('fortran') }}")
        if need_autotools:
            result.append("autoconf  # [not win]")
            result.append("automake  # [not win]")
            result.append("m2-autoconf  # [win]")
            result.append("m2-automake-wrapper  # [win]")
        if need_make:
            result.append("make  # [not win]")
            result.append("m2-make  # [win]")
    print(
        f"INFO :: For {os.path.basename(package_url)}, we need the following build tools:\n{result}"
    )
    return result


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
                output = output.decode("utf-8-sig")
            rel_dict = json.loads(output)
        except OSError:
            rel_dict = json.loads(codecs.open(json_path, encoding="utf-8").read())
        except CondaHTTPError:
            rel_dict = None
    return rel_dict


# Probably uses a system cpan? TODO :: Fix this.
def package_exists(package_name):
    try:
        cmd = ["cpan", "-D", package_name]
        if on_win:
            cmd.insert(0, "/c")
            cmd.insert(0, "/d")
            cmd.insert(0, "cmd.exe")
        check_call_env(cmd)
        in_repo = True
    except subprocess.CalledProcessError:
        in_repo = False
    return in_repo


def md5d_file_and_other(filename, other_hashed):
    sha1 = hashlib.md5()
    with open(filename, "rb") as f:
        while True:
            data = f.read(65536)
            if not data:
                break
            sha1.update(data)
    for other in other_hashed:
        sha1.update(other.encode("utf-8") if hasattr(other, "encode") else other)
    return sha1.hexdigest()


def get_pickle_file_path(cache_dir, filename_prefix, other_hashed=()):
    h = "h" + md5d_file_and_other(__file__, other_hashed)[2:10]
    return os.path.join(cache_dir, filename_prefix.replace("::", "-") + "." + h + ".p")


def load_or_pickle(filename_prefix, base_folder, data_partial, key):
    # It might be nice to hash the entire code tree of data_partial
    # along with all the args to it via hashlib instead but that's
    # difficult.
    pickled = get_pickle_file_path(
        cache_dir=base_folder, filename_prefix=filename_prefix + key
    )
    # if exists(pickled):
    #     os.unlink(pickled)
    if exists(pickled):
        with open(pickled, "rb") as f:
            key_stored = pickle.load(f)
            if key and key_stored and key == key_stored:
                return pickle.load(f)
    result = data_partial()
    try:
        os.makedirs(os.path.dirname(pickled))
    except:
        pass
    with open(pickled, "wb") as f:
        pickle.dump(key, f)
        pickle.dump(result, f)
    return result


def install_perl_get_core_modules(version):
    try:
        from conda_build.conda_interface import TemporaryDirectory
        from conda_build.config import Config

        config = Config()

        if sys.platform.startswith("win"):
            subdirs = ("win-64", "Library", "bin", "perl.exe")
        elif sys.platform.startswith("linux"):
            subdirs = ("linux-64", "bin", "perl")
        else:
            subdirs = ("osx-64", "bin", "perl")
        # Return one of the dist things instead?
        with TemporaryDirectory() as tmpdir:
            environ.create_env(
                tmpdir,
                [f"perl={version}"],
                env="host",
                config=config,
                subdir=subdirs[0],
            )
            args = [
                f"{join(tmpdir, *subdirs[1:])}",
                "-e",
                "use Module::CoreList; "
                "my @modules = grep {Module::CoreList::is_core($_)} Module::CoreList->find_modules(qr/.*/); "
                'print join "\n", @modules;',
            ]
            from subprocess import check_output

            all_core_modules = (
                check_output(args, shell=False)
                .decode("utf-8")
                .replace("\r\n", "\n")
                .split("\n")
            )
            return all_core_modules
    except Exception as e:
        print(
            "Failed to query perl={} for core modules list, attempted command was:\n{}".format(
                version, " ".join(args)
            )
        )
        print(e.message)

    return []


def get_core_modules_for_this_perl_version(version, cache_dir):
    return load_or_pickle(
        "perl-core-modules",
        base_folder=cache_dir,
        data_partial=partial(install_perl_get_core_modules, version),
        key=version,
    )


# meta_cpan_url="http://api.metacpan.org",
def skeletonize(
    packages,
    output_dir=".",
    version=None,
    meta_cpan_url="https://fastapi.metacpan.org/v1",
    recursive=False,
    force=False,
    config=None,
    write_core=False,
):
    """
    Loops over packages, outputting conda recipes converted from CPAN metata.
    """
    config = get_or_merge_config(config)
    cache_dir = os.path.join(config.src_cache_root, ".conda-build", "pickled.cb")

    # TODO :: Make a temp env. with perl (which we need anyway) and use whatever version
    #         got installed instead of this. Also allow the version to be specified.
    perl_version = config.variant.get("perl", get_default_variant(config)["perl"])
    core_modules = get_core_modules_for_this_perl_version(perl_version, cache_dir)

    # wildcards are not valid for perl
    perl_version = perl_version.replace(".*", "")
    package_dicts = {}
    indent = "\n    - "
    indent_core = "\n    #- "
    processed_packages = set()
    orig_version = version
    new_packages = []
    for package in packages:
        # TODO :: Determine whether the user asked for a module or a package here.
        #      :: if a package, then the 2nd element is None, if a module then the
        #      :: 2nd element gives the name of that module.
        #      :: I also need to take care about the differences between package
        #      :: versions and module versions.
        # module = package
        # module = dist_for_module(meta_cpan_url, cache_dir, core_modules, package)
        module = None
        new_packages.append((package, module))
    packages = new_packages
    while packages:
        package, module = packages.pop()
        # If we're passed version in the same format as `PACKAGE=VERSION`
        # update version
        if "=" in package:
            package, _, version = package.partition("=")
        else:
            version = orig_version

        # Skip duplicates
        if package in processed_packages:
            continue
        processed_packages.add(package)

        # Convert modules into distributions .. incorrectly. Instead we should just look up
        # https://fastapi.metacpan.org/v1/module/Regexp::Common which seems to contain every
        # bit of information we could want here. Versions, modules, module versions,
        # distribution name, urls. The lot. Instead we mess about with other API end-points
        # getting a load of nonsense.
        orig_package = package
        package = dist_for_module(
            meta_cpan_url, cache_dir, core_modules, module if module else package
        )
        if package == "perl":
            print(
                (
                    "WARNING: {0} is a Perl core module that is not developed "
                    + "outside of Perl, so we are skipping creating a recipe "
                    + "for it."
                ).format(orig_package)
            )
            continue
        elif package not in {orig_package, orig_package.replace("::", "-")}:
            print(
                (
                    "WARNING: {0} was part of the {1} distribution, so we are "
                    + "making a recipe for {1} instead."
                ).format(orig_package, package)
            )

        latest_release_data = get_release_info(
            meta_cpan_url,
            cache_dir,
            core_modules,
            module if module else orig_package,
            version,
        )
        packagename = perl_to_conda(package)

        # Skip duplicates
        if (
            version is not None
            and ((packagename + "-" + version) in processed_packages)
        ) or (
            (packagename + "-" + latest_release_data["version"]) in processed_packages
        ):
            continue

        d = package_dicts.setdefault(
            package,
            {
                "packagename": packagename,
                "build_depends": "",
                "host_depends": "",
                "run_depends": "",
                "build_comment": "# ",
                "test_commands": "",
                "usesha256": "",
                "useurl": "",
                "source_comment": "",
                "summary": "''",
                "import_tests": "",
            },
        )

        # Fetch all metadata from CPAN
        if version is None:
            release_data = latest_release_data
        else:
            release_data = get_release_info(
                meta_cpan_url, cache_dir, core_modules, package, parse_version(version)
            )

        # Check if recipe directory already exists
        dir_path = join(output_dir, packagename, release_data["version"])

        # Add Perl version to core module requirements, since these are empty
        # packages, unless we're newer than what's in core
        if metacpan_api_is_core_version(meta_cpan_url, package):
            if not write_core:
                print(
                    "We found core module %s. Skipping recipe creation." % packagename
                )
                continue

            d["useurl"] = "#"
            d["usesha256"] = "#"
            d["source_comment"] = "#"
            empty_recipe = True
        # Add dependencies to d if not in core, or newer than what's in core
        else:
            deps, packages_to_append = deps_for_package(
                package,
                release_data=release_data,
                output_dir=output_dir,
                cache_dir=cache_dir,
                meta_cpan_url=meta_cpan_url,
                recursive=recursive,
                core_modules=core_modules,
            )

            # If this is something we're downloading, get MD5
            d["cpanurl"] = ""
            d["sha256"] = ""
            if release_data.get("download_url"):
                d["cpanurl"] = release_data["download_url"]
                d["sha256"], size = get_checksum_and_size(release_data["download_url"])
                print("Using url {} ({}) for {}.".format(d["cpanurl"], size, package))
                src_build_depends = get_build_dependencies_from_src_archive(
                    release_data["download_url"], d["sha256"], config.src_cache
                )
            else:
                src_build_depends = []
                d["useurl"] = "#"
                d["usesha256"] = "#"
                d["source_comment"] = "#"

            d["build_depends"] += indent.join([""] + src_build_depends)

            #            d['build_depends'] += indent_core.join([''] + list(deps['build']['core'] |
            #                                                               deps['run']['core']))

            d["host_depends"] += indent.join(
                [""] + list(deps["build"]["noncore"] | deps["run"]["noncore"])
            )

            # run_exports will set these, but:
            # TODO :: Add ignore_run_exports for things in deps['build'] that are not also
            #         in deps['run']
            d["run_depends"] += indent_core.join([""] + list(deps["run"]["noncore"]))

            # Make sure we append any packages before continuing
            for pkg in packages_to_append:
                if pkg not in packages:
                    packages.append(pkg)
                else:
                    print(
                        "INFO :: Already building package {} (module {})".format(*pkg)
                    )
            empty_recipe = False

        # If we are recursively getting packages for a particular version
        # we need to make sure this is reset on the loop
        version = None
        if exists(dir_path) and not force:
            print(
                "Directory %s already exists and you have not specified --force "
                % dir_path
            )
            continue
        elif exists(dir_path) and force:
            print("Directory %s already exists, but forcing recipe creation" % dir_path)

        try:
            d["homeurl"] = release_data["resources"]["homepage"]
        except KeyError:
            d["homeurl"] = "http://metacpan.org/pod/" + package
        if "abstract" in release_data:
            # TODO this does not escape quotes in a YAML friendly manner
            summary = repr(release_data["abstract"]).lstrip("u")
            d["summary"] = summary
            # d['summary'] = repr(release_data['abstract']).lstrip('u')
        try:
            d["license"] = (
                release_data["license"][0]
                if isinstance(release_data["license"], list)
                else release_data["license"]
            )
        except KeyError:
            d["license"] = "perl_5"
        d["version"] = release_data["version"]

        processed_packages.add(packagename + "-" + d["version"])

        # Create import tests
        module_prefix = package.replace("::", "-").split("-")[0]
        if "provides" in release_data:
            for provided_mod in sorted(set(release_data["provides"])):
                # Filter out weird modules that don't belong
                if provided_mod.startswith(module_prefix) and "::_" not in provided_mod:
                    d["import_tests"] += indent + provided_mod
        if d["import_tests"]:
            d["import_comment"] = ""
        else:
            d["import_comment"] = "# "

        if not exists(dir_path):
            makedirs(dir_path)

        # Write recipe files to a directory
        # TODO def write_recipe
        print("Writing recipe for {}-{}".format(packagename, d["version"]))
        with open(join(dir_path, "meta.yaml"), "wb") as f:
            f.write(CPAN_META.format(**d).encode("utf-8"))
        with open(join(dir_path, "build.sh"), "wb") as f:
            if empty_recipe:
                f.write(b'#!/bin/bash\necho "Nothing to do."\n')
            else:
                f.write(CPAN_BUILD_SH.format(**d).encode("utf-8"))
        with open(join(dir_path, "bld.bat"), "w") as f:
            if empty_recipe:
                f.write('echo "Nothing to do."\n')
            else:
                f.write(CPAN_BLD_BAT.format(**d))


@lru_cache(maxsize=None)
def is_core_version(core_version, version):
    if core_version is None:
        return False
    elif core_version is not None and (
        (version in [None, ""]) or (core_version >= parse_version(version))
    ):
        return True
    else:
        return False


def add_parser(repos):
    cpan = repos.add_parser(
        "cpan",
        help="""
    Create recipe skeleton for packages hosted on the Comprehensive Perl Archive
    Network (CPAN) (cpan.org).
        """,
    )
    cpan.add_argument(
        "packages",
        nargs="+",
        help="CPAN packages to create recipe skeletons for.",
    )
    cpan.add_argument(
        "--output-dir",
        help="Directory to write recipes to (default: %(default)s).",
        default=".",
    )
    cpan.add_argument(
        "--version",
        help="Version to use. Applies to all packages.",
    )
    cpan.add_argument(
        "--meta-cpan-url",
        default="https://fastapi.metacpan.org/v1",
        help="URL to use for MetaCPAN API. It must include a version, such as v1",
    )
    cpan.add_argument(
        "--recursive",
        action="store_true",
        help="Create recipes for dependencies if they do not already exist (default: %(default)s).",
    )
    cpan.add_argument(
        "--force",
        action="store_true",
        help="Force overwrite of existing recipes (default: %(default)s).",
    )
    cpan.add_argument(
        "--write_core",
        action="store_true",
        help="Write recipes for perl core modules (default: %(default)s). ",
    )


@lru_cache(maxsize=None)
def latest_pkg_version(pkg):
    """
    :returns: the latest version of the specified conda package available
    """
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


def deps_for_package(
    package, release_data, output_dir, cache_dir, meta_cpan_url, recursive, core_modules
):
    """
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
    """

    # Create lists of dependencies
    deps = {
        "build": {"core": set(), "noncore": set()},
        "test": {"core": set(), "noncore": set()},
        "run": {"core": set(), "noncore": set()},
    }
    phase_to_dep_type = {
        "build": "build",
        "configure": "build",
        "test": "test",
        "runtime": "run",
        # TODO :: Check this, I am unsure about it ..
        #         These (sometimes?) reference sub-components of modules
        #         e.g. inc::MMPackageStash instead of inc which does not
        #         get found on metacpan fastapi. We may need to chop the
        #         suffix off an try again (and repeat until we find it).
        "x_Dist_Zilla": None,
        "develop": None,
    }
    packages_to_append = set()

    print("Processing dependencies for %s..." % package, end="")
    sys.stdout.flush()

    if not release_data.get("dependency"):
        return deps, packages_to_append

    # release_data['dependency'] = ['FindBin-libs' if r == 'FindBin' else r for r in release_data['dependency']]
    new_deps = []
    for dep in release_data["dependency"]:
        if "phase" in dep and dep["phase"] == "develop":
            print("Skipping develop dependency {}".format(dep["module"]))
            continue
        elif "module" in dep and dep["module"] == "FindBin":
            dep["module"] = "FindBin::Bin"
        elif "module" in dep and dep["module"] == "Exporter":
            dep["module"] = "Exporter"
        new_deps.append(dep)
    release_data["dependency"] = new_deps

    for dep_dict in release_data["dependency"]:
        # Only care about requirements
        try:
            if dep_dict["relationship"] == "requires":
                if not phase_to_dep_type[dep_dict["phase"]]:
                    continue
                if "module" in dep_dict and dep_dict["module"] == "common::sense":
                    print("debug common::sense version mismatch")
                print(".", end="")
                sys.stdout.flush()
                # Format dependency string (with Perl trailing dist comment)
                orig_dist = dist_for_module(
                    meta_cpan_url, cache_dir, core_modules, dep_dict["module"]
                )

                dep_entry = perl_to_conda(orig_dist)
                # Skip perl as a dependency, since it's already in list
                if orig_dist.lower() == "perl":
                    continue

                # See if version is specified
                # There is a dep version and a pkg_version ... why?
                if dep_dict["version"] in {"", "undef"}:
                    dep_dict["version"] = "0"
                dep_version = parse_version(dep_dict["version"])

                # Make sure specified version is valid
                # TODO def valid_release_info
                try:
                    get_release_info(
                        meta_cpan_url,
                        cache_dir,
                        core_modules,
                        dep_dict["module"],
                        dep_version,
                    )
                except InvalidReleaseError:
                    print(
                        (
                            "WARNING: The version of %s listed as a "
                            + "dependency for %s, %s, is not available on MetaCPAN, "
                            + "so we are just assuming the latest version is "
                            + "okay."
                        )
                        % (orig_dist, package, str(dep_version))
                    )
                    dep_version = parse_version("0")

                # Add version number to dependency, if it's newer than latest
                # we have package for.
                if loose_version(dep_version) > loose_version("0"):
                    pkg_version = latest_pkg_version(dep_entry)
                    # If we don't have a package, use core version as version
                    if pkg_version is None:
                        # pkg_version = core_module_version(dep_entry,
                        #                                   perl_version,
                        #                                   config=config)
                        # print('dep entry is {}'.format(dep_entry))
                        pkg_version = metacpan_api_get_core_version(
                            core_modules, dep_dict["module"]
                        )
                    # If no package is available at all, it's in the core, or
                    # the latest is already good enough, don't specify version.
                    # This is because conda doesn't support > in version
                    # requirements.
                    # J = Conda does support >= ?
                    try:
                        if pkg_version is not None and (
                            loose_version(dep_version) > loose_version(pkg_version)
                        ):
                            dep_entry += " " + dep_dict["version"]
                    except Exception:
                        print("We have got an expected error with dependency versions")
                        print("Module {}".format(dep_dict["module"]))
                        print(f"Pkg_version {pkg_version}")
                        print(f"Dep Version {dep_version}")

                # If recursive, check if we have a recipe for this dependency
                if recursive:
                    # If dependency entry is versioned, make sure this is too
                    if " " in dep_entry:
                        if not exists(join(output_dir, dep_entry.replace("::", "-"))):
                            packages_to_append.add(
                                ("=".join((orig_dist, dep_dict["version"]))),
                                dep_dict["module"],
                            )
                    elif not glob(join(output_dir, (dep_entry + "-[v1-9][0-9.]*"))):
                        packages_to_append.add((orig_dist, dep_dict["module"]))

                # Add to appropriate dependency list
                core = metacpan_api_is_core_version(meta_cpan_url, dep_dict["module"])

                cb_phase = phase_to_dep_type[dep_dict["phase"]]
                if cb_phase:
                    if core:
                        deps[cb_phase]["core"].add(dep_entry)
                    else:
                        deps[cb_phase]["noncore"].add(dep_entry)
                else:
                    print(
                        "Skipping {} dependency {}".format(dep_dict["phase"], dep_entry)
                    )
        # seemingly new in conda 4.3: HTTPErrors arise when we ask for
        # something that is a
        # perl module, but not a package.
        # See https://github.com/conda/conda-build/issues/1675
        except (CondaError, CondaHTTPError):
            continue

    print(f"module {package} adds {packages_to_append}")

    return deps, packages_to_append


def dist_for_module(cpan_url, cache_dir, core_modules, module):
    """
    Given a name that could be a module or a distribution, return the
    distribution.
    """
    if "Git::Check" in module:
        print("debug this")
    # First check if it is a core module, those mask distributions here, or at least they
    # do in the case of `import Exporter`
    distribution = None
    try:
        mod_dict = core_module_dict(core_modules, module)
        distribution = mod_dict["distribution"]
    except:
        # Next check if its already a distribution
        rel_dict = release_module_dict(cpan_url, cache_dir, module)
        if rel_dict is not None:
            if rel_dict["distribution"] != module.replace("::", "-"):
                print(
                    "WARNING :: module {} found in distribution {}".format(
                        module, rel_dict["distribution"]
                    )
                )
            distribution = rel_dict["distribution"]
    if not distribution:
        print("debug")
    assert distribution, "dist_for_module must succeed"

    return distribution


def release_module_dict_direct(cpan_url, cache_dir, module):
    if "Dist-Zilla-Plugin-Git" in module:
        print(f"debug {module}")
    elif "Dist::Zilla::Plugin::Git" in module:
        print(f"debug {module}")
    elif "Time::Zone" in module:
        print(f"debug {module}")

    try:
        url_module = f"{cpan_url}/module/{module}"
        print(f"INFO :: url_module {url_module}")
        rel_dict = get_cpan_api_url(url_module, colons=True)
    except RuntimeError:
        rel_dict = None
    except CondaHTTPError:
        rel_dict = None
    if not rel_dict:
        print(f"WARNING :: Did not find rel_dict for module {module}")
    distribution = module.replace("::", "-")
    if not rel_dict or "dependency" not in rel_dict:
        if rel_dict and "distribution" in rel_dict:
            distribution = rel_dict["distribution"]
        else:
            print(
                f"WARNING :: 'distribution' was not in {module}'s module info, making it up"
            )
        try:
            url_release = f"{cpan_url}/release/{distribution}"
            rel_dict2 = get_cpan_api_url(url_release, colons=False)
            rel_dict = rel_dict2
        except RuntimeError:
            rel_dict = None
        except CondaHTTPError:
            rel_dict = None
    else:
        print(f"INFO :: OK, found 'dependency' in module {module}")
    if not rel_dict or "dependency" not in rel_dict:
        print(
            "WARNING :: No dependencies found for module {} in distribution {}\n"
            "WARNING :: Please check {} and {}".format(
                module, distribution, url_module, url_release
            )
        )
    return rel_dict


def release_module_dict(cpan_url, cache_dir, module):
    if "Regexp-Common" in module:
        print("debug")
    rel_dict = release_module_dict_direct(cpan_url, cache_dir, module)
    if not rel_dict:
        # In this case, the module may be a submodule of another dist, let's try something else.
        # An example of this is Dist::Zilla::Plugin::Git::Check.
        pickled = get_pickle_file_path(cache_dir, module + ".dl_url")
        url = f"{cpan_url}/download_url/{module}"
        try:
            os.makedirs(os.path.dirname(pickled))
        except:
            pass
        download(url, pickled)
        with open(pickled, "rb") as dl_url_json:
            output = dl_url_json.read()
        if hasattr(output, "decode"):
            output = output.decode("utf-8-sig")
        dl_url_dict = json.loads(output)
        if dl_url_dict["release"].endswith(dl_url_dict["version"]):
            # Easy case.
            print(f"Up to date: {module}")
            dist = dl_url_dict["release"].replace("-" + dl_url_dict["version"], "")
        else:
            # Difficult case.
            print(f"Not up to date: {module}")
            # cpan -D Time::Zone
            # Time::Zone
            # -------------------------------------------------------------------------
            # 	(no description)
            # 	A/AT/ATOOMIC/TimeDate-2.33.tar.gz
            # 	(no installation file)
            # 	Installed: not installed
            # 	CPAN:      2.24  Not up to date
            # 	icolas . (ATOOMIC)
            # 	atoomic@cpan.org
            #
            # .. there is no field that lists a version of '2.33' in the data. We need
            #    to inspect the tarball.
            dst = os.path.join(cache_dir, basename(dl_url_dict["download_url"]))
            download(dl_url_dict["download_url"], dst)
            with gzip.open(dst) as dist_json_file:
                output = dist_json_file.read()
            # (base) Rays-Mac-Pro:Volumes rdonnelly$ cpan -D Time::Zone
            rel_dict = release_module_dict_direct(cpan_url, cache_dir, dist)

    return rel_dict


def core_module_dict_old(cpan_url, module):
    if "FindBin" in module:
        print("debug")
    if "Exporter" in module:
        print("debug")
    try:
        mod_dict = get_cpan_api_url(f"{cpan_url}/module/{module}", colons=True)
        # If there was an error, report it
    except CondaHTTPError as e:
        sys.exit(
            (
                "Error: Could not find module or distribution named"
                " %s on MetaCPAN. Error was: %s"
            )
            % (module, e.message)
        )
    else:
        mod_dict = {"distribution": "perl"}

    return mod_dict


def core_module_dict(core_modules, module):
    if module in core_modules:
        return {"distribution": "perl"}
    return None


@lru_cache(maxsize=None)
def metacpan_api_is_core_version(cpan_url, module):
    if "FindBin" in module:
        print("debug")
    url = f"{cpan_url}/release/{module}"
    url = url.replace("::", "-")
    req = requests.get(url)

    if req.status_code == 200:
        return False
    else:
        url = f"{cpan_url}/module/{module}"
        req = requests.get(url)
        if req.status_code == 200:
            return True
        else:
            sys.exit(
                (
                    "Error: Could not find module or distribution named"
                    " %s on MetaCPAN."
                )
                % (module)
            )


def metacpan_api_get_core_version(core_modules, module):
    module_dict = core_module_dict(core_modules, module)
    try:
        version = module_dict["module"][-1]["version"]
    except Exception:
        version = None

    return version


def get_release_info(cpan_url, cache_dir, core_modules, package, version):
    """
    Return a dictionary of the JSON information stored at cpan.metacpan.org
    corresponding to the given package/dist/module.
    """
    # Transform module name to dist name if necessary
    orig_package = package
    package = dist_for_module(cpan_url, cache_dir, core_modules, package)

    # Get latest info to find author, which is necessary for retrieving a
    # specific version
    try:
        rel_dict = get_cpan_api_url(f"{cpan_url}/release/{package}", colons=False)
        rel_dict["version"] = str(rel_dict["version"]).lstrip("v")
    except CondaHTTPError:
        core_version = metacpan_api_is_core_version(cpan_url, package)
        if core_version is not None and (version is None or (version == core_version)):
            print(
                (
                    "WARNING: {0} is not available on MetaCPAN, but it's a "
                    + "core module, so we do not actually need the source file, "
                    + "and are omitting the URL and MD5 from the recipe "
                    + "entirely."
                ).format(orig_package)
            )
            rel_dict = {
                "version": str(core_version),
                "download_url": "",
                "license": ["perl_5"],
                "dependency": {},
            }
        else:
            sys.exit(
                ("Error: Could not find any versions of package %s on " + "MetaCPAN.")
                % (orig_package)
            )

    version_mismatch = False

    if version is not None:
        version_str = str(version)
        rel_version = str(rel_dict["version"])
        loose_str = str(parse_version(version_str))

        try:
            version_mismatch = (version is not None) and (
                loose_version("0") != loose_version(version_str)
                and parse_version(rel_version) != loose_version(version_str)
            )
            # print(version_mismatch)
        except Exception as e:
            print("We have some strange version mismatches. Please investigate.")
            print(e)
            print(f"Package {package}")
            print(f"Version {version}")
            print("Pkg Version {}".format(rel_dict["version"]))
            print(f"Loose Version {loose_str}")

    # TODO  - check for major/minor version mismatches
    # Allow for minor
    if version_mismatch:
        print(f"WARNING :: Version mismatch in {package}")
        print(f"WARNING :: Version: {version_str}, RelVersion: {rel_version}")

    return rel_dict


def get_checksum_and_size(download_url):
    """
    Looks in the CHECKSUMS file in the same directory as the file specified
    at download_url and returns the sha256 hash and file size.
    """
    base_url = dirname(download_url)
    filename = basename(download_url)
    with PerlTmpDownload(base_url + "/CHECKSUMS") as checksum_path:
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
                    elif line.startswith("}"):
                        break
    return sha256, size


def perl_to_conda(name):
    """Sanitizes a Perl package name for use as a conda package name."""
    return "perl-" + name.replace("::", "-").lower()
