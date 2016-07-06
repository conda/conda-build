from __future__ import absolute_import, division, print_function

import os
import sys
import shutil
from os.path import dirname, isdir, isfile, join

# Leverage the hard work done by setuptools/distutils to find vcvarsall using
# either the registry or the VS**COMNTOOLS environment variable
from distutils.msvc9compiler import find_vcvarsall as distutils_find_vcvarsall
from distutils.msvc9compiler import Reg, WINSDK_BASE

import conda.config as cc

from conda_build.config import config
from conda_build import environ
from conda_build import source
from conda_build.utils import _check_call


assert sys.platform == 'win32'


VS_VERSION_STRING = {
    '8.0': 'Visual Studio 8 2005',
    '9.0': 'Visual Studio 9 2008',
    '10.0': 'Visual Studio 10 2010',
    '11.0': 'Visual Studio 11 2012',
    '12.0': 'Visual Studio 12 2013',
    '14.0': 'Visual Studio 14 2015'
}


def fix_staged_scripts():
    """
    Fixes scripts which have been installed unix-style to have a .bat
    helper
    """
    scripts_dir = join(config.build_prefix, 'Scripts')
    if not isdir(scripts_dir):
        return
    for fn in os.listdir(scripts_dir):
        # process all the extensionless files
        if not isfile(join(scripts_dir, fn)) or '.' in fn:
            continue

        with open(join(scripts_dir, fn)) as f:
            line = f.readline().lower()
            # If it's a #!python script
            if not (line.startswith('#!') and 'python' in line.lower()):
                continue
            print('Adjusting unix-style #! script %s, '
                  'and adding a .bat file for it' % fn)
            # copy it with a .py extension (skipping that first #! line)
            with open(join(scripts_dir, fn + '-script.py'), 'w') as fo:
                fo.write(f.read())
            # now create the .exe file
            shutil.copyfile(join(dirname(__file__), 'cli-%d.exe' % cc.bits),
                            join(scripts_dir, fn + '.exe'))

        # remove the original script
        os.remove(join(scripts_dir, fn))


def build_vcvarsall_vs_path(version):
    """
    Given the Visual Studio version, returns the default path to the
    Microsoft Visual Studio vcvarsall.bat file.
    Expected versions are of the form {9, 10, 12, 14}
    """
    # Set up a load of paths that can be imported from the tests
    if 'ProgramFiles(x86)' in os.environ:
        PROGRAM_FILES_PATH = os.environ['ProgramFiles(x86)']
    else:
        PROGRAM_FILES_PATH = os.environ['ProgramFiles']

    vstools = "VS{0}0COMNTOOLS".format(version)
    if vstools in os.environ:
        return os.path.join(os.environ[vstools], '..\\..\\VC\\vcvarsall.bat')
    else:
        # prefer looking at env var; fall back to program files defaults
        return os.path.join(PROGRAM_FILES_PATH,
                            'Microsoft Visual Studio {}'.format(version), 'VC',
                            'vcvarsall.bat')


def msvc_env_cmd(bits, override=None):
    arch_selector = 'x86' if bits == 32 else 'amd64'

    msvc_env_lines = []

    version = None
    if override is not None:
        version = override

    # The DISTUTILS_USE_SDK variable tells distutils to not try and validate
    # the MSVC compiler. For < 3.5 this still forcibly looks for 'cl.exe'.
    # For > 3.5 it literally just skips the validation logic.
    # See distutils _msvccompiler.py and msvc9compiler.py / msvccompiler.py
    # for more information.
    msvc_env_lines.append('set DISTUTILS_USE_SDK=1')
    # This is also required to hit the 'don't validate' logic on < 3.5.
    # For > 3.5 this is ignored.
    msvc_env_lines.append('set MSSdk=1')

    if not version:
        if config.PY3K and config.use_MSVC2015:
            version = '14.0'
        elif config.PY3K:
            version = '10.0'
        else:
            version = '9.0'

    vcvarsall_vs_path = build_vcvarsall_vs_path(version)

    def build_vcvarsall_cmd(cmd, arch=arch_selector):
        # Default argument `arch_selector` is defined above
        return 'call "{cmd}" {arch}'.format(cmd=cmd, arch=arch)

    msvc_env_lines.append('set "VS_VERSION={}"'.format(version))
    msvc_env_lines.append('set "VS_MAJOR={}"'.format(version.split('.')[0]))
    msvc_env_lines.append('set "VS_YEAR={}"'.format(VS_VERSION_STRING[version][-4:]))
    msvc_env_lines.append('set "CMAKE_GENERATOR={}"'.format(VS_VERSION_STRING[version] +
                                                            {64: ' Win64', 32: ''}[bits]))
    # tell msys2 to ignore path conversions for issue-causing windows-style flags in build
    #   See https://github.com/conda-forge/icu-feedstock/pull/5
    msvc_env_lines.append('set "MSYS2_ARG_CONV_EXCL=/AI;/AL;/OUT;/out;%MSYS2_ARG_CONV_EXCL%"')
    msvc_env_lines.append('set "MSYS2_ENV_CONV_EXCL=CL"')
    if version == '10.0':
        try:
            WIN_SDK_71_PATH = Reg.get_value(os.path.join(WINSDK_BASE, 'v7.1'),
                                            'installationfolder')
            WIN_SDK_71_BAT_PATH = os.path.join(WIN_SDK_71_PATH, 'Bin', 'SetEnv.cmd')

            win_sdk_arch = '/Release /x86' if bits == 32 else '/Release /x64'
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
            msvc_env_lines.append('Setlocal EnableDelayedExpansion')
            msvc_env_lines.append(win_sdk_cmd)
            # If the WindowsSDKDir environment variable has not been successfully
            # set then try activating VS2010
            msvc_env_lines.append('if not "%WindowsSDKDir%" == "{}" ( {} )'.format(
                WIN_SDK_71_PATH, build_vcvarsall_cmd(vcvarsall_vs_path)))
        # sdk is not installed.  Fall back to only trying VS 2010
        except KeyError:
            msvc_env_lines.append(build_vcvarsall_cmd(vcvarsall_vs_path))
    elif version == '9.0':
        # Get the Visual Studio 2008 path (not the Visual C++ for Python path)
        # and get the 'vcvars64.bat' from inside the bin (in the directory above
        # that returned by distutils_find_vcvarsall)
        try:
            VCVARS64_VS9_BAT_PATH = os.path.join(os.path.dirname(distutils_find_vcvarsall(9)),
                                                'bin', 'vcvars64.bat')
        # there's an exception if VS or the VC compiler for python are not actually installed.
        except (KeyError, TypeError):
            VCVARS64_VS9_BAT_PATH = None

        error1 = 'if errorlevel 1 {}'

        # Setuptools captures the logic of preferring the Microsoft Visual C++
        # Compiler for Python 2.7 - falls back to VS2008 if necessary
        msvc_env_lines.append(build_vcvarsall_cmd(vcvarsall_vs_path))
        # The Visual Studio 2008 Express edition does not properly contain
        # the amd64 build files, so we call the vcvars64.bat manually,
        # rather than using the vcvarsall.bat which would try and call the
        # missing bat file.
        if arch_selector == 'amd64' and VCVARS64_VS9_BAT_PATH:
            msvc_env_lines.append(error1.format(
                build_vcvarsall_cmd(VCVARS64_VS9_BAT_PATH)))
    else:
        # Visual Studio 14 or otherwise
        msvc_env_lines.append(build_vcvarsall_cmd(vcvarsall_vs_path))

    return '\n'.join(msvc_env_lines) + '\n'


def kill_processes(process_names=["msbuild.exe"]):
    # for things that uniform across both APIs
    import psutil
    # list of pids changed APIs from v1 to v2.
    try:
        # V1 API
        from psutil import get_pid_list
    except:
        try:
            # V2 API
            from psutil import pids as get_pid_list
        except:
            raise ImportError("psutil failed to import.")
    for n in get_pid_list():
        try:
            p = psutil.Process(n)
            if p.name.lower() in (process_name.lower() for process_name in process_names):
                print('Terminating:', p.name)
                p.terminate()
        except:
            continue


def build(m, bld_bat, dirty=False, activate=True):
    env = environ.get_dict(m, dirty=dirty)

    for name in 'BIN', 'INC', 'LIB':
        path = env['LIBRARY_' + name]
        if not isdir(path):
            os.makedirs(path)

    src_dir = source.get_dir()
    if os.path.isfile(bld_bat):
        with open(bld_bat) as fi:
            data = fi.read()
        with open(join(src_dir, 'bld.bat'), 'w') as fo:
            # more debuggable with echo on
            fo.write('@echo on\n')
            for key, value in env.items():
                fo.write('set "{key}={value}"\n'.format(key=key, value=value))
            fo.write("set INCLUDE={};%INCLUDE%\n".format(env["LIBRARY_INC"]))
            fo.write("set LIB={};%LIB%\n".format(env["LIBRARY_LIB"]))
            fo.write(msvc_env_cmd(bits=cc.bits, override=m.get_value('build/msvc_compiler', None)))
            if activate:
                fo.write("call activate _build\n")
            fo.write("REM ===== end generated header =====\n")
            fo.write(data)

        cmd = [os.environ['COMSPEC'], '/c', 'bld.bat']
        _check_call(cmd, cwd=src_dir)
        kill_processes()
        fix_staged_scripts()
