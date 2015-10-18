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
            shutil.copyfile(join(dirname(__file__),
                                 'cli-%d.exe' % (8 * tuple.__itemsize__)),
                            join(scripts_dir, fn + '.exe'))

        # remove the original script
        os.remove(join(scripts_dir, fn))


def msvc_env_cmd(override=None):
    if 'ProgramFiles(x86)' in os.environ:
        program_files = os.environ['ProgramFiles(x86)']
    else:
        program_files = os.environ['ProgramFiles']

    msvc_env_lines = []

    if config.PY3K and config.use_MSVC2015:
        version = '14.0'
    elif config.PY3K:
        version = '10.0'
    else:
        version = '9.0'

    if override is not None:
        version = override
        msvc_env_lines.append('set DISTUTILS_USE_SDK=1')
        msvc_env_lines.append('set MSSdk=1')

    vcvarsall = os.path.join(program_files,
                             r'Microsoft Visual Studio {version}'.format(version=version),
                             'VC', 'vcvarsall.bat')

    # Try the Microsoft Visual C++ Compiler for Python 2.7
    localappdata = os.environ.get("localappdata")
    not_vcvars = not isfile(vcvarsall)
    if not_vcvars and localappdata and not config.PY3K:
        vcvarsall = os.path.join(localappdata, "Programs", "Common",
            "Microsoft", "Visual C++ for Python", "9.0", "vcvarsall.bat")
    if not_vcvars and program_files and not config.PY3K:
        vcvarsall = os.path.join(program_files, 'Common Files',
            'Microsoft', 'Visual C++ for Python', "9.0", "vcvarsall.bat")
    if not_vcvars:
        print("Warning: Couldn't find Visual Studio: %r" % vcvarsall)
        return ''

    msvc_env_lines.append('call "%s" %s' % (vcvarsall, 'x86' if cc.bits == 32 else 'amd64'))
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
    for n in psutil.get_pid_list():
        try:
            p = psutil.Process(n)
            if p.name.lower() in (process_name.lower() for process_name in process_names):
                print('Terminating:', p.name)
                p.terminate()
        except:
            continue


def build(m):
    env = dict(os.environ)
    env.update(environ.get_dict(m))
    env = environ.prepend_bin_path(env, config.build_prefix, True)

    for name in 'BIN', 'INC', 'LIB':
        path = env['LIBRARY_' + name]
        if not isdir(path):
            os.makedirs(path)

    src_dir = source.get_dir()
    bld_bat = join(m.path, 'bld.bat')
    if exists(bld_bat):
        with open(bld_bat) as fi:
            data = fi.read()
        with open(join(src_dir, 'bld.bat'), 'w') as fo:
            fo.write(msvc_env_cmd(override=m.get_value('build/msvc_compiler', None)))
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
