from __future__ import absolute_import, division, print_function

import os
import re
import sys
import shutil
import subprocess
from os.path import dirname, isdir, isfile, join

# Leverage the hard work done by setuptools/distutils to find vcvarsall using
# either the registry or the VS**COMNTOOLS environment variable
from distutils.msvc9compiler import query_vcvarsall

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


def msvc_env_cmd(bits, override=None):
    arch_selector = 'x86' if bits == 32 else 'amd64'

    compiler_vars = {}

    version = None
    if override:
        version = override
        # The DISTUTILS_USE_SDK variable tells distutils to not try and validate
        # the MSVC compiler. For < 3.5 this still forcibly looks for 'cl.exe'.
        # For > 3.5 it literally just skips the validation logic.
        # See distutils _msvccompiler.py and msvc9compiler.py / msvccompiler.py
        # for more information.
        compiler_vars.update({"DISTUTILS_USE_SDK": 1,
                              # This is also required to hit the 'don't validate' logic on < 3.5.
                              # For > 3.5 this is ignored.
                              "MSSdk": 1})

    if not version:
        if config.PY3K and config.use_MSVC2015:
            version = '14.0'
        elif config.PY3K:
            version = '10.0'
        else:
            version = '9.0'

    compiler_vars.update({
        "VS_VERSION": version,
        "VS_MAJOR": version.split('.')[0],
        "VS_YEAR": VS_VERSION_STRING[version][-4:],
        "CMAKE_GENERATOR": VS_VERSION_STRING[version] + {64: ' Win64', 32: ''}[bits],
        # tell msys2 to ignore path conversions for issue-causing windows-style flags in build
        #   See https://github.com/conda-forge/icu-feedstock/pull/5
        "MSYS2_ARG_CONV_EXCL": "/AI;/AL;/OUT;/out;%MSYS2_ARG_CONV_EXCL%",
        "MSYS2_ENV_CONV_EXCL": "CL;%MSYS2_ENV_CONV_EXCL%",
        })

    captured_vars = query_vcvarsall(float(version), arch_selector)
    compiler_vars.update(captured_vars)
    return compiler_vars


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

def _merge_dicts(d1, d2):
    """Merges d2's contents into d1.  Unlike update, this keeps all entries of both, by performing
    unions of values."""
    for key, value in d1.items():
        if key in d2:
            combined = set(value.split(';'))
            combined.update(set(d2[key].split(';')))
            d1[key] = ";".join(combined)
            # delete it.  We'll merge remaining vars at the end.
            del d2[key]
    d1.update(d2)
    return d1

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

            compiler_vars = msvc_env_cmd(bits=cc.bits, override=m.get_value('build/msvc_compiler', None))
            # ensure that all values are uppercase, for sake of merge.
            env = {key.upper(): value for key, value in env.items()}
            compiler_vars = {key.upper(): value for key, value in compiler_vars.items()}

            # this is a union of all values from env and from compiler vars.  env should take priority.
            env = _merge_dicts(env, compiler_vars)

            for key, value in env.items():
                fo.write('set "{key}={value}"\n'.format(key=key, value=value))
            fo.write("set INCLUDE={};%INCLUDE%\n".format(env["LIBRARY_INC"]))
            fo.write("set LIB={};%LIB%\n".format(env["LIBRARY_LIB"]))
            fo.write('\n')
            fo.write("REM ===== end generated header =====\n")
            fo.write(data)


        cmd = [os.environ['COMSPEC'], '/c', 'call', 'bld.bat']
        _check_call(cmd, cwd=src_dir)
        kill_processes()
        fix_staged_scripts()
