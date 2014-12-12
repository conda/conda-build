from __future__ import absolute_import, division, print_function

import os
import sys
import shutil
from os.path import dirname, isdir, isfile, join, exists

import conda.config as cc
from conda.compat import iteritems

from conda_build.config import config
from conda_build import environ
from conda_build import source
from conda_build.utils import _check_call

try:
    import psutil
except ImportError:
    psutil = None

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


def msvc_env_cmd():
    if 'ProgramFiles(x86)' in os.environ:
        program_files = os.environ['ProgramFiles(x86)']
    else:
        program_files = os.environ['ProgramFiles']

    if config.PY3K:
        vcvarsall = os.path.join(program_files,
                                 r'Microsoft Visual Studio 10.0'
                                 r'\VC\vcvarsall.bat')
    else:
        vcvarsall = os.path.join(program_files,
                                 r'Microsoft Visual Studio 9.0'
                                 r'\VC\vcvarsall.bat')

    if not isfile(vcvarsall):
        print("Warning: Couldn't find Visual Studio: %r" % vcvarsall)
        return ''

    return '''\
call "%s" %s
''' % (vcvarsall, {32: 'x86', 64: 'amd64'}[cc.bits])


def kill_processes():
    if psutil is None:
        return
    for n in psutil.get_pid_list():
        try:
            p = psutil.Process(n)
            if p.name.lower() == 'msbuild.exe':
                print('Terminating:', p.name)
                p.terminate()
        except:
            continue


def build(m):
    env = dict(os.environ)
    env.update(environ.get_dict(m))

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
            fo.write(msvc_env_cmd())
            for kv in iteritems(env):
                fo.write('set %s=%s\n' % kv)
            # more debuggable with echo on
            fo.write('@echo on\n')
            fo.write("REM ===== end generated header =====\n")
            fo.write(data)

        cmd = [os.environ['COMSPEC'], '/c', 'bld.bat']
        _check_call(cmd, cwd=src_dir)
        kill_processes()
        fix_staged_scripts()
