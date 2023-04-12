# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
Tools for converting luarocks packages to conda recipes.
"""

# TODO:
# - mingw32 support (really any windows support, completely untested)
# - replace manual "luajit -e require 'blah'" with built-in entry-point testing

import json
import os
import subprocess
import tempfile
from glob import glob
from sys import platform as _platform

INDENT = "\n    - "

rockspec_parser = """
local ok,cjson = pcall(require, "cjson")
if not ok then
   print("ERROR: lua-cjson not installed. Use conda to install luarocks, "
         "then run 'luarocks install lua-cjson'.")
   os.exit()
end

local rockspecFile = "%s"
local origPackage = package
local ok, _ = pcall(dofile, rockspecFile)
if not ok then
   print("ERROR: could not load rockspecFile " .. tostring(rockspecFile))
   os.exit()
end

-- Resolve name clash
if origPackage == package then
   package = nil
end
local out = {
   rockspec_format=rockspec_format,
   package=package,
   version=version,
   description=description,
   supported_platforms=supported_platforms,
   dependencies=dependencies,
   external_dependencies=external_dependencies,
   source=source,
   build=build,
   modules=modules,
}
print(cjson.encode(out))
"""


LUAROCKS_META = """\
package:
  name: {packagename}
  version: "{version}"

source:
  {usefile}fn: {filename}
  {usefile}url: {url}
  {usegit}git_url: {url}
  {usegittag}git_tag: {gittag} # can also be a branch, but that is highly discouraged
  {usegitrev}git_rev: {gitrev} # prefer tags over commits, commits over branches
  {usemd5}md5:{md5}
#  patches:
   # List any patch files here
   # - fix.patch

build:
  {noarch_python_comment}noarch: generic
  # Useful to leave this on by default, will allow relocating
  # packages that have hard-coded paths in them
  detect_binary_files_with_prefix: true
  # If this is a new build for the same version, increment the build
  # number. If you do not include this key, it defaults to 0.
  # number: 1

requirements:
  build:{build_depends}

  run:{run_depends}

{test_comment}test:
  {entry_comment}commands:
    # You can put test commands to be run here.  Use this to test that the
    # entry points work.
{test_commands}

  # You can also put a file called run_test.lua in the recipe that will be run
  # at test time.

about:
  {home_comment}home: {homeurl}
  license: {license}
  {summary_comment}summary: {summary}

# See
# https://docs.conda.io/projects/conda-build for
# more information about meta.yaml
"""

LUAROCKS_BUILD_SH = """\
#!/bin/bash

set -o errexit -o pipefail

# Make sure luarocks can see all local dependencies
"${{PREFIX}}"/bin/luarocks-admin make_manifest --local-tree

# Install
# Rocks aren't located in a standard location, although
# they tend to be top-level or in a rocks/ directory.
# NOTE: we're just picking the first rock we find. If there's
# more than one, specify it manually.
ROCK=$(find . -name "*.rockspec" | sort -n -r | head -n 1)
"${{PREFIX}}"/bin/luarocks install "${{ROCK}}" --local-tree

# Add more build steps here, if they are necessary.

# See
# https://docs.conda.io/projects/conda-build
# for a list of environment variables that are set during the build process.
"""

LUAROCKS_POSTLINK_SH = """\
# Let luarocks know that we've installed a new project
$PREFIX/bin/luarocks-admin make_manifest --local-tree
"""

LUAROCKS_PREUNLINK_SH = """\
# Tell luarocks we've removed the project
$PREFIX/bin/luarocks remove {rockname}
"""


def add_parser(repos):
    luarocks = repos.add_parser(
        "luarocks",
        help="""
    Create recipe skeleton for luarocks, hosted at luarocks.org
        """,
    )
    luarocks.add_argument(
        "packages",
        nargs="+",
        help="luarocks packages to create recipe skeletons for.",
    )
    luarocks.add_argument(
        "--output-dir",
        help="Directory to write recipes to (default: %(default)s).",
        default=".",
    )
    luarocks.add_argument(
        "--version",
        help="Version to use. Applies to all packages.",
    )
    luarocks.add_argument(
        "--recursive",
        action="store_true",
        help="Create recipes for dependencies if they do not already exist.",
    )


def package_exists(package_name):
    return True
    # TODO: no current Lua packages work for me.  Need to verify this method.
    # subprocess.check_call(['luarocks', 'search', package_name])


def getval(spec, k):
    if k not in spec:
        raise Exception("Required key %s not in spec" % k)
    else:
        return spec[k]


def warn_against_branches(branch):
    print("")
    print("=========================================")
    print("")
    print("WARNING:")
    print("Building a rock referenced to branch %s." % branch)
    print("This is not a tag. This is dangerous, because rebuilding")
    print("at a later date may produce a different package.")
    print("Please replace with a tag, git commit, or tarball.")
    print("")
    print("=========================================")


def format_dep(dep):
    name_without_ver = "".join([c for c in dep if c.isalpha()])
    if name_without_ver not in ["lua"]:
        # Enforce conda naming convention.
        # lower case, no white-space, and prepended "lua-"
        # (all languages other than Python prepend their language to package names)
        if dep[:4] != "lua-":
            dep = "lua-" + dep
    dep = dep.replace(" ", "").lower()

    # Ensure a space between the first special-character that specifies version logic
    # Not "-", because that's used in e.g. lua-penlight
    special_char_test = [c in "<>=~" for c in dep]
    for i, v in enumerate(special_char_test):
        if v:
            split_dep = [c for c in dep]
            split_dep.insert(i, " ")
            dep = "".join(split_dep)
            break
    return dep


def ensure_base_deps(deps):
    basenames = ["".join([c for c in dep if c.isalpha()]) for dep in deps]
    extra_deps = []
    if "lua" not in basenames:
        extra_deps.append("lua")
    if "luarocks" not in basenames:
        extra_deps.append("luarocks")
    if len(extra_deps):
        deps = extra_deps + deps
    return deps


def skeletonize(packages, output_dir=".", version=None, recursive=False):
    # Check that we have Lua installed (any version)

    # Check that we have luarocks installed

    # Check that we have lua-cjson installed

    # Get the platform
    platform = "linux" if _platform == "linux2" else _platform

    # Make temporary directory
    cwd = os.getcwd()
    temp_dir = tempfile.mkdtemp()
    package_dicts = {}

    # Step into it
    os.chdir(temp_dir)

    while packages:
        package = packages.pop()

        packagename = (
            "lua-%s" % package.lower() if package[:4] != "lua-" else package.lower()
        )
        d = package_dicts.setdefault(
            package,
            {
                "packagename": packagename,
                "version": "0.0",
                "filename": "",
                "url": "",
                "md5": "",
                "usemd5": "# ",
                "usefile": "# ",
                "usegit": "# ",
                "usegittag": "# ",
                "usegitrev": "# ",
                "gittag": "",
                "gitrev": "",
                "noarch_python_comment": "# ",
                "build_depends": "",
                "run_depends": "",
                "test_comment": "",
                "entry_comment": "",
                "test_commands": "",
                "home_comment": "# ",
                "homeurl": "",
                "license": "Unknown",
                "summary_comment": "# ",
                "summary": "",
            },
        )

        # Download rockspec
        o = subprocess.call(["luarocks", "download", package, "--rockspec"])
        if o != 0:
            raise Exception(f"Could not download rockspec for {package}")

        # Find the downloaded rockspec
        fs = glob(package + "*.rockspec")
        if len(fs) != 1:
            raise Exception("Failed to download rockspec")
        d["rockspec_file"] = fs[0]

        # Parse the rockspec into a dictionary
        p = subprocess.Popen(
            ["lua", "-e", rockspec_parser % d["rockspec_file"]], stdout=subprocess.PIPE
        )
        out, err = p.communicate()
        if "ERROR" in out:
            raise Exception(out.replace("ERROR: ", ""))
        spec = json.loads(out)

        # Gather the basic details
        d["rockname"] = getval(spec, "package")
        d["version"] = getval(spec, "version")
        d["version"] = "".join([c for c in d["version"] if c.isalnum()])
        source = getval(spec, "source")

        # Figure out how to download the package, and from where
        d["url"] = getval(source, "url")
        ext = os.path.splitext(d["url"])[-1]
        if ext in [".zip", ".tar", ".tar.bz2", ".tar.xz", ".tar.gz"]:
            d["usefile"] = ""
            d["filename"] = os.path.split(d["url"])[-1]
            if "md5" in source:
                md5 = getval(source, "md5")
                if len(md5):
                    d["md5"] = md5
                    d["usemd5"] = ""
        elif ext in [".git"] or d["url"][:4] == "git:":
            d["usegit"] = ""
            # Check if we're using a tag or a commit
            if "tag" in source:
                d["usegittag"] = ""
                d["gittag"] = getval(source, "tag")
            elif "branch" in source:
                d["usegittag"] = ""
                d["gittag"] = getval(source, "branch")
                warn_against_branches(d["gittag"])
            else:
                d["usegittag"] = ""
                d["gittag"] = "master"
                warn_against_branches(d["gittag"])

        # Gather the description
        if "description" in spec:
            desc = getval(spec, "description")
            if "homepage" in desc:
                d["homeurl"] = desc["homepage"]
                d["home_comment"] = ""
            if "summary" in desc:
                d["summary"] = desc["summary"]
                d["summary_comment"] = ""
            if "license" in desc:
                d["license"] = desc["license"]

        # Gather the dependencies
        if "dependencies" in spec:
            deps = getval(spec, "dependencies")
            if len(deps):
                deps = ensure_base_deps([format_dep(dep) for dep in deps])
                d["build_depends"] = INDENT.join([""] + deps)
                d["run_depends"] = d["build_depends"]

    # Build some entry-point tests.
    if "build" in spec:
        if platform == "darwin":
            our_plat = "macosx"
        elif platform == "linux":
            our_plat = "unix"

        modules = None
        if "modules" in spec["build"]:
            modules = spec["build"]["modules"]
        elif "platforms" in spec["build"]:
            if our_plat in spec["build"]["platforms"]:
                if "modules" in spec["build"]["platforms"][our_plat]:
                    modules = spec["build"]["platforms"][our_plat]["modules"]
        if modules:
            d["test_commands"] = INDENT.join(
                [""] + ["""lua -e "require '%s'\"""" % r for r in modules.keys()]
            )

    # If we didn't find any modules to import, import the base name
    if d["test_commands"] == "":
        d["test_commands"] = INDENT.join(
            [""] + ["""lua -e "require '%s'" """ % d["rockname"]]
        )

    # Build the luarocks skeleton
    os.chdir(cwd)
    for package in package_dicts:
        d = package_dicts[package]
        name = d["packagename"]
        os.makedirs(os.path.join(output_dir, name))
        print(
            f"Writing recipe for {package.lower()} to {os.path.join(output_dir, name)}"
        )
        with open(os.path.join(output_dir, name, "meta.yaml"), "w") as f:
            f.write(LUAROCKS_META.format(**d))
        with open(os.path.join(output_dir, name, "build.sh"), "w") as f:
            f.write(LUAROCKS_BUILD_SH.format(**d))
        with open(os.path.join(output_dir, name, "post-link.sh"), "w") as f:
            f.write(LUAROCKS_POSTLINK_SH)
        with open(os.path.join(output_dir, name, "pre-unlink.sh"), "w") as f:
            f.write(LUAROCKS_PREUNLINK_SH.format(**d))
