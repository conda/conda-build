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

log = logging.getLogger(__file__)


assert sys.platform == 'win32'

WIN_SDK_71_PATH = Reg.get_value(os.path.join(WINSDK_BASE, 'v7.1'),
                                'installationfolder')
WIN_SDK_71_BAT_PATH = os.path.join(WIN_SDK_71_PATH, 'Bin', 'SetEnv.cmd')
# Get the Visual Studio 2008 path (not the Visual C++ for Python path)
# and get the 'vcvars64.bat' from inside the bin (in the directory above
# that returned by distutils_find_vcvarsall)
VCVARS64_VS9_BAT_PATH = os.path.join(os.path.dirname(distutils_find_vcvarsall(9)),
                                     'bin', 'vcvars64.bat')
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


def get_vs_vars(version, arch):
    """This is mostly a copy of distutils' query_vcvarsall.  It is adapted to support
    the win 7 SDK vs 2010 compiler."""
    if version != "10.0":
        result = query_vcvarsall(float(version), arch)
    else:
        WIN_SDK_71_PATH = Reg.get_value(os.path.join(WINSDK_BASE, 'v7.1'),
                                        'installationfolder')
        WIN_SDK_71_BAT_PATH = os.path.join(WIN_SDK_71_PATH, 'Bin', 'SetEnv.cmd')
        vcvarsall = WIN_SDK_71_BAT_PATH
        arch = '/Release /x86' if arch == 'x86' else '/Release /x64'
        interesting = set(("include", "lib", "libpath", "path"))
        result = {}

        log.debug("Calling 'vcvarsall.bat %s' (version=%s)", arch, version)
        popen = subprocess.Popen('"%s" %s & set' % (vcvarsall, arch),
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        try:
            stdout, stderr = popen.communicate()
            stdout = stdout.decode("mbcs")
            for line in stdout.split("\n"):
                line = Reg.convert_mbcs(line)
                if '=' not in line:
                    continue
                line = line.strip()
                key, value = line.split('=', 1)
                key = key.lower()
                if key in interesting:
                    if value.endswith(os.pathsep):
                        value = value[:-1]
                    result[key] = removeDuplicates(value)

        finally:
            popen.stdout.close()
            popen.stderr.close()

        if len(result) != len(interesting):
            raise ValueError(str(list(result.keys())))
    return result


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
    elif version == '9.0':
        error1 = 'if errorlevel 1 {}'

        # Setuptools captures the logic of preferring the Microsoft Visual C++
        # Compiler for Python 2.7 - falls back to VS2008 if necessary
        msvc_env_lines.append(build_vcvarsall_cmd(vcvarsall_vs_path))
        # The Visual Studio 2008 Express edition does not properly contain
        # the amd64 build files, so we call the vcvars64.bat manually,
        # rather than using the vcvarsall.bat which would try and call the
        # missing bat file.
        if arch_selector == 'amd64':
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
            fo.write('\n')
            fo.write("REM ===== end generated header =====\n")
            fo.write(data)

        cmd = [os.environ['COMSPEC'], '/c', 'call', 'bld.bat']
        _check_call(cmd, cwd=src_dir)
        kill_processes()
        fix_staged_scripts()
