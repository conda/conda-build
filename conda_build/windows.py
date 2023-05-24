# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import os
import pprint
from os.path import dirname, isdir, isfile, join

# importing setuptools patches distutils so that it knows how to find VC for python 2.7
import setuptools  # noqa

# Leverage the hard work done by setuptools/distutils to find vcvarsall using
# either the registry or the VS**COMNTOOLS environment variable
try:
    from setuptools._distutils.msvc9compiler import WINSDK_BASE, Reg
    from setuptools._distutils.msvc9compiler import (
        find_vcvarsall as distutils_find_vcvarsall,
    )
except:
    # Allow some imports to work for cross or CONDA_SUBDIR usage.
    pass

from conda_build import environ
from conda_build.utils import (
    check_call_env,
    copy_into,
    get_logger,
    path_prepended,
    write_bat_activation_text,
)
from conda_build.variants import get_default_variant, set_language_env_vars

VS_VERSION_STRING = {
    "8.0": "Visual Studio 8 2005",
    "9.0": "Visual Studio 9 2008",
    "10.0": "Visual Studio 10 2010",
    "11.0": "Visual Studio 11 2012",
    "12.0": "Visual Studio 12 2013",
    "14.0": "Visual Studio 14 2015",
}


def fix_staged_scripts(scripts_dir, config):
    """
    Fixes scripts which have been installed unix-style to have a .bat
    helper
    """
    if not isdir(scripts_dir):
        return
    for fn in os.listdir(scripts_dir):
        # process all the extensionless files
        if not isfile(join(scripts_dir, fn)) or "." in fn:
            continue

        # read as binary file to ensure we don't run into encoding errors, see #1632
        with open(join(scripts_dir, fn), "rb") as f:
            line = f.readline()
            # If it's a #!python script
            if not (line.startswith(b"#!") and b"python" in line.lower()):
                continue
            print(
                "Adjusting unix-style #! script %s, "
                "and adding a .bat file for it" % fn
            )
            # copy it with a .py extension (skipping that first #! line)
            with open(join(scripts_dir, fn + "-script.py"), "wb") as fo:
                fo.write(f.read())
            # now create the .exe file
            copy_into(
                join(dirname(__file__), "cli-%s.exe" % config.host_arch),
                join(scripts_dir, fn + ".exe"),
            )

        # remove the original script
        os.remove(join(scripts_dir, fn))


def build_vcvarsall_vs_path(version):
    """
    Given the Visual Studio version, returns the default path to the
    Microsoft Visual Studio vcvarsall.bat file.
    Expected versions are of the form {9.0, 10.0, 12.0, 14.0}
    """
    # Set up a load of paths that can be imported from the tests
    if "ProgramFiles(x86)" in os.environ:
        PROGRAM_FILES_PATH = os.environ["ProgramFiles(x86)"]
    else:
        PROGRAM_FILES_PATH = os.environ["ProgramFiles"]

    flatversion = str(version).replace(".", "")
    vstools = f"VS{flatversion}COMNTOOLS"

    if vstools in os.environ:
        return os.path.join(os.environ[vstools], "..\\..\\VC\\vcvarsall.bat")
    else:
        # prefer looking at env var; fall back to program files defaults
        return os.path.join(
            PROGRAM_FILES_PATH,
            f"Microsoft Visual Studio {version}",
            "VC",
            "vcvarsall.bat",
        )


def msvc_env_cmd(bits, config, override=None):
    # TODO: this function will likely break on `win-arm64`. However, unless
    # there's clear user demand, it's not clear that we should invest the
    # effort into updating a known deprecated function for a new platform.
    log = get_logger(__name__)
    log.warn(
        "Using legacy MSVC compiler setup.  This will be removed in conda-build 4.0. "
        "If this recipe does not use a compiler, this message is safe to ignore.  "
        "Otherwise, use {{compiler('<language>')}} jinja2 in requirements/build."
    )
    if override:
        log.warn(
            "msvc_compiler key in meta.yaml is deprecated. Use the new"
            "variant-powered compiler configuration instead. Note that msvc_compiler"
            "is incompatible with the new {{{{compiler('c')}}}} jinja scheme."
        )
    # this has been an int at times.  Make sure it's a string for consistency.
    bits = str(bits)
    arch_selector = "x86" if bits == "32" else "amd64"

    msvc_env_lines = []

    version = None
    if override is not None:
        version = override

    # The DISTUTILS_USE_SDK variable tells distutils to not try and validate
    # the MSVC compiler. For < 3.5 this still forcibly looks for 'cl.exe'.
    # For > 3.5 it literally just skips the validation logic.
    # See distutils _msvccompiler.py and msvc9compiler.py / msvccompiler.py
    # for more information.
    msvc_env_lines.append("set DISTUTILS_USE_SDK=1")
    # This is also required to hit the 'don't validate' logic on < 3.5.
    # For > 3.5 this is ignored.
    msvc_env_lines.append("set MSSdk=1")

    if not version:
        py_ver = config.variant.get("python", get_default_variant(config)["python"])
        if int(py_ver[0]) >= 3:
            if int(py_ver.split(".")[1]) < 5:
                version = "10.0"
            version = "14.0"
        else:
            version = "9.0"

    if float(version) >= 14.0:
        # For Python 3.5+, ensure that we link with the dynamic runtime.  See
        # http://stevedower.id.au/blog/building-for-python-3-5-part-two/ for more info
        msvc_env_lines.append(
            "set PY_VCRUNTIME_REDIST=%LIBRARY_BIN%\\vcruntime{}.dll".format(
                version.replace(".", "")
            )
        )

    vcvarsall_vs_path = build_vcvarsall_vs_path(version)

    def build_vcvarsall_cmd(cmd, arch=arch_selector):
        # Default argument `arch_selector` is defined above
        return f'call "{cmd}" {arch}'

    vs_major = version.split(".")[0]
    msvc_env_lines.append(f'set "VS_VERSION={version}"')
    msvc_env_lines.append(f'set "VS_MAJOR={vs_major}"')
    msvc_env_lines.append(f'set "VS_YEAR={VS_VERSION_STRING[version][-4:]}"')
    if int(vs_major) >= 16:
        # No Win64 for VS 2019.
        msvc_env_lines.append(f'set "CMAKE_GENERATOR={VS_VERSION_STRING[version]}"')
    else:
        msvc_env_lines.append(
            'set "CMAKE_GENERATOR={}"'.format(
                VS_VERSION_STRING[version] + {"64": " Win64", "32": ""}[bits]
            )
        )
    # tell msys2 to ignore path conversions for issue-causing windows-style flags in build
    #   See https://github.com/conda-forge/icu-feedstock/pull/5
    msvc_env_lines.append('set "MSYS2_ARG_CONV_EXCL=/AI;/AL;/OUT;/out"')
    msvc_env_lines.append('set "MSYS2_ENV_CONV_EXCL=CL"')
    if version == "10.0":
        try:
            WIN_SDK_71_PATH = Reg.get_value(
                os.path.join(WINSDK_BASE, "v7.1"), "installationfolder"
            )
            WIN_SDK_71_BAT_PATH = os.path.join(WIN_SDK_71_PATH, "Bin", "SetEnv.cmd")

            win_sdk_arch = "/Release /x86" if bits == "32" else "/Release /x64"
            win_sdk_cmd = build_vcvarsall_cmd(WIN_SDK_71_BAT_PATH, arch=win_sdk_arch)

            # There are two methods of building Python 3.3 and 3.4 extensions (both
            # of which required Visual Studio 2010 - as explained in the Python wiki
            # https://wiki.python.org/moin/WindowsCompilers)
            # 1) Use the Windows SDK 7.1
            # 2) Use Visual Studio 2010 (any edition)
            # However, VS2010 never shipped with a 64-bit compiler, so in this case
            # **only** option (1) applies. For this reason, we always try and
            # activate the Windows SDK first. Unfortunately, unsuccessfully setting
            # up the environment does **not EXIT 1** and therefore we must fall
            # back to attempting to set up VS2010.
            # DelayedExpansion is required for the SetEnv.cmd
            msvc_env_lines.append("Setlocal EnableDelayedExpansion")
            msvc_env_lines.append(win_sdk_cmd)
            # If the WindowsSDKDir environment variable has not been successfully
            # set then try activating VS2010
            msvc_env_lines.append(
                'if not "%WindowsSDKDir%" == "{}" ( {} )'.format(
                    WIN_SDK_71_PATH, build_vcvarsall_cmd(vcvarsall_vs_path)
                )
            )
        # sdk is not installed.  Fall back to only trying VS 2010
        except KeyError:
            msvc_env_lines.append(build_vcvarsall_cmd(vcvarsall_vs_path))
    elif version == "9.0":
        # Get the Visual Studio 2008 path (not the Visual C++ for Python path)
        # and get the 'vcvars64.bat' from inside the bin (in the directory above
        # that returned by distutils_find_vcvarsall)
        try:
            VCVARS64_VS9_BAT_PATH = os.path.join(
                os.path.dirname(distutils_find_vcvarsall(9)), "bin", "vcvars64.bat"
            )
        # there's an exception if VS or the VC compiler for python are not actually installed.
        except (KeyError, TypeError):
            VCVARS64_VS9_BAT_PATH = None

        error1 = "IF %ERRORLEVEL% NEQ 0 {}"

        # Prefer VS9 proper over Microsoft Visual C++ Compiler for Python 2.7
        msvc_env_lines.append(build_vcvarsall_cmd(vcvarsall_vs_path))
        # The Visual Studio 2008 Express edition does not properly contain
        # the amd64 build files, so we call the vcvars64.bat manually,
        # rather than using the vcvarsall.bat which would try and call the
        # missing bat file.
        if arch_selector == "amd64" and VCVARS64_VS9_BAT_PATH:
            msvc_env_lines.append(
                error1.format(build_vcvarsall_cmd(VCVARS64_VS9_BAT_PATH))
            )
        # Otherwise, fall back to icrosoft Visual C++ Compiler for Python 2.7+
        # by using the logic provided by setuptools
        msvc_env_lines.append(
            error1.format(build_vcvarsall_cmd(distutils_find_vcvarsall(9)))
        )
    else:
        # Visual Studio 14 or otherwise
        msvc_env_lines.append(build_vcvarsall_cmd(vcvarsall_vs_path))

    return "\n".join(msvc_env_lines) + "\n"


def write_build_scripts(m, env, bld_bat):
    env_script = join(m.config.work_dir, "build_env_setup.bat")
    if m.noarch == "python":
        env["PYTHONDONTWRITEBYTECODE"] = True
    import codecs

    with codecs.getwriter("utf-8")(open(env_script, "wb")) as fo:
        # more debuggable with echo on
        fo.write("@echo on\n")
        for key, value in env.items():
            if value != "" and value is not None:
                fo.write(f'set "{key}={value}"\n')
        if not m.uses_new_style_compiler_activation:
            fo.write(
                msvc_env_cmd(
                    bits=m.config.host_arch,
                    config=m.config,
                    override=m.get_value("build/msvc_compiler", None),
                )
            )
        # Reset echo on, because MSVC scripts might have turned it off
        fo.write("@echo on\n")
        fo.write('set "INCLUDE={};%INCLUDE%"\n'.format(env["LIBRARY_INC"]))
        fo.write('set "LIB={};%LIB%"\n'.format(env["LIBRARY_LIB"]))
        if m.config.activate and m.name() != "conda":
            write_bat_activation_text(fo, m)
    # bld_bat may have been generated elsewhere with contents of build/script
    work_script = join(m.config.work_dir, "conda_build.bat")
    if os.path.isfile(bld_bat):
        with open(bld_bat) as fi:
            data = fi.read()
        with codecs.getwriter("utf-8")(open(work_script, "wb")) as fo:
            fo.write('IF "%CONDA_BUILD%" == "" (\n')
            fo.write(f"    call {env_script}\n")
            fo.write(")\n")
            fo.write("REM ===== end generated header =====\n")
            fo.write(data)
    return work_script, env_script


def build(m, bld_bat, stats, provision_only=False):
    # TODO: Prepending the prefixes here should probably be guarded by
    #         if not m.activate_build_script:
    #       Leaving it as is, for now, since we need a quick, non-disruptive patch release.
    with path_prepended(m.config.host_prefix):
        with path_prepended(m.config.build_prefix):
            env = environ.get_dict(m=m)
    env["CONDA_BUILD_STATE"] = "BUILD"

    # hard-code this because we never want pip's build isolation
    #    https://github.com/conda/conda-build/pull/2972#discussion_r198290241
    #
    # Note that pip env "NO" variables are inverted logic.
    #      PIP_NO_BUILD_ISOLATION=False means don't use build isolation.
    #
    env["PIP_NO_BUILD_ISOLATION"] = "False"
    # some other env vars to have pip ignore dependencies.
    # we supply them ourselves instead.
    #    See note above about inverted logic on "NO" variables
    env["PIP_NO_DEPENDENCIES"] = True
    env["PIP_IGNORE_INSTALLED"] = True

    # pip's cache directory (PIP_NO_CACHE_DIR) should not be
    # disabled as this results in .egg-info rather than
    # .dist-info directories being created, see gh-3094
    # set PIP_CACHE_DIR to a path in the work dir that does not exist.
    env["PIP_CACHE_DIR"] = m.config.pip_cache_dir

    # tell pip to not get anything from PyPI, please.  We have everything we need
    # locally, and if we don't, it's a problem.
    env["PIP_NO_INDEX"] = True

    # set variables like CONDA_PY in the test environment
    env.update(set_language_env_vars(m.config.variant))

    for name in "BIN", "INC", "LIB":
        path = env["LIBRARY_" + name]
        if not isdir(path):
            os.makedirs(path)

    work_script, env_script = write_build_scripts(m, env, bld_bat)

    if not provision_only and os.path.isfile(work_script):
        cmd = ["cmd.exe", "/d", "/c", os.path.basename(work_script)]
        # rewrite long paths in stdout back to their env variables
        if m.config.debug or m.config.no_rewrite_stdout_env:
            rewrite_env = None
        else:
            rewrite_env = {
                k: env[k] for k in ["PREFIX", "BUILD_PREFIX", "SRC_DIR"] if k in env
            }
            print("Rewriting env in output: %s" % pprint.pformat(rewrite_env))
        check_call_env(
            cmd, cwd=m.config.work_dir, stats=stats, rewrite_stdout_env=rewrite_env
        )
        fix_staged_scripts(join(m.config.host_prefix, "Scripts"), config=m.config)
