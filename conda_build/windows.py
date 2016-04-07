from __future__ import absolute_import, division, print_function

import os
import sys
import shutil
from os.path import dirname, isdir, isfile, join, exists

import conda.config as cc

from conda_build.config import config
from conda_build import environ
from conda_build import source
from conda_build.utils import _check_call

assert sys.platform == 'win32'


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


def msvc_env_cmd(bits, override=None):
    if 'ProgramFiles(x86)' in os.environ:
        program_files = os.environ['ProgramFiles(x86)']
    else:
        program_files = os.environ['ProgramFiles']
    arch_selector = 'x86' if bits == 32 else 'amd64'

    msvc_env_lines = []

    version = None
    if override is not None:
        version = override
        msvc_env_lines.append('set DISTUTILS_USE_SDK=1')
        msvc_env_lines.append('set MSSdk=1')

    if not version:
        if config.PY3K and config.use_MSVC2015:
            version = '14.0'
        elif config.PY3K:
            version = '10.0'
        else:
            version = '9.0'

    vcvarsall_vs_path = os.path.join(
        program_files, 'Microsoft Visual Studio {}'.format(version), 'VC', 
        'vcvarsall.bat')

    def build_vcvarsall_cmd(cmd, arch=arch_selector):
        return 'call "{cmd}" {arch}'.format(cmd=cmd, arch=arch)

    if version == '10.0':
        vcvarsall = vcvarsall_vs_path
        vcvars_cmd = build_vcvarsall_cmd(vcvarsall)
        
        # Note that we explicitly want "Program Files" and not 
        # "Program Files (x86)"
        win_sdk_bat_path = os.path.join(os.path.abspath(os.sep),
                                        'Program Files', 'Microsoft SDKs',
                                        'Windows', 'v7.1', 'Bin', 'SetEnv.cmd')
        # Unfortunately, the Windows SDK takes a different command format for
        # the arch selector - debug is default so explicitly set 'Release'
        win_sdk_arch = '/x86 /Release' if bits == 32 else '/x64 /Release'
        win_sdk_cmd = build_vcvarsall_cmd(win_sdk_bat_path, arch=win_sdk_arch)
        
        # Always call the Windows SDK first - if VS 2010 exists but was
        # installed using the broken installer then it will try and call the 
        # vcvars script, which will fail but NOT EXIT 1. To work around this,
        # we always call the Windows SDK, and then try calling VS 2010 which
        # will overwrite any environemnt variables it needs, if necessary.
        msvc_env_lines.append(win_sdk_cmd)
        msvc_env_lines.append(vcvars_cmd)
    elif version == '9.0':
        # First, check for Microsoft Visual C++ Compiler for Python 2.7
        localappdata = os.getenv('localappdata', program_files)
        vs_tools_py_local_path = os.path.join(
            localappdata, 'Programs', 'Common', 'Microsoft', 
            'Visual C++ for Python', '9.0', 'vcvarsall.bat')
        msvc_env_lines.append(build_vcvarsall_cmd(vs_tools_py_local_path))
        
        vs_tools_py_common_path = os.path.join(
            localappdata, 'Common Files', 'Microsoft', 'Visual C++ for Python', 
            '9.0', 'vcvarsall.bat')
        msvc_env_lines.append('if errorlevel 1 {}'.format(
            build_vcvarsall_cmd(vs_tools_py_common_path)))
        # The Visual Studio 2008 Express edition does not properly contain
        # the amd64 build files, so we call the vcvars64.bat manually,
        # rather than using the vcvarsall.bat which would try and call the
        # missing bat file.
        if arch_selector == 'amd64':
            vcvars9x64_bat_path = os.path.join(program_files, 
                                               'Microsoft Visual Studio 9.0', 
                                               'VC', 'bin', 'vcvars64.bat')
            msvc_env_lines.append('if errorlevel 1 {}'.format(
                build_vcvarsall_cmd(vcvars9x64_bat_path)))
        else:
            msvc_env_lines.append('if errorlevel 1 {}'.format(
                build_vcvarsall_cmd(vcvarsall_vs_path)))
    else:
        # Visual Studio 14 or otherwise
        vcvarsall = vcvarsall_vs_path
        msvc_env_lines.append(build_vcvarsall_cmd(vcvarsall))

    return '\n'.join(msvc_env_lines)


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


def build(m, bld_bat):
    env = dict(os.environ)
    env.update(environ.get_dict(m))
    env = environ.prepend_bin_path(env, config.build_prefix, True)

    for name in 'BIN', 'INC', 'LIB':
        path = env['LIBRARY_' + name]
        if not isdir(path):
            os.makedirs(path)

    src_dir = source.get_dir()
    if exists(bld_bat):
        with open(bld_bat) as fi:
            data = fi.read()
        with open(join(src_dir, 'bld.bat'), 'w') as fo:
            fo.write(msvc_env_cmd(bits=cc.bits, override=m.get_value('build/msvc_compiler', None)))
            fo.write('\n')
            # more debuggable with echo on
            fo.write('@echo on\n')
            fo.write("set INCLUDE={};%INCLUDE%\n".format(env["LIBRARY_INC"]))
            fo.write("set LIB={};%LIB%\n".format(env["LIBRARY_LIB"]))
            fo.write("REM ===== end generated header =====\n")
            fo.write(data)

        cmd = [os.environ['COMSPEC'], '/c', 'call', 'bld.bat']
        _check_call(cmd, cwd=src_dir, env={str(k): str(v) for k, v in env.items()})
        kill_processes()
        fix_staged_scripts()
