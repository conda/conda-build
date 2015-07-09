from __future__ import absolute_import, division, print_function

import os
import sys
import shutil
import textwrap
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
    if config.CONDA_MSVC is not None:
        msvc = config.CONDA_MSVC
    elif config.PY3K:
        msvc = 100
    else:
        msvc = 90

    if msvc == 100:
        setenv_paths = [
            # SetEnv must be first choice because the default installation of
            # Visual Studio 2010 Express has a 'vcvarsall.bat' that does not work
            # for amd64 (even though it fails silently)
            r'%ProgramFiles%\Microsoft SDKs\Windows\v7.1\Bin\SetEnv.cmd',
            r'%ProgramFiles(x86)%\Microsoft Visual Studio 10.0\VC\vcvarsall.bat',
            r'%ProgramFiles%\Microsoft Visual Studio 10.0\VC\vcvarsall.bat',
        ]
    elif msvc == 90:
        setenv_paths = [
            r'%ProgramFiles(x86)%\Microsoft Visual Studio 9.0\VC\vcvarsall.bat',
            r'%ProgramFiles%\Microsoft Visual Studio 9.0\VC\vcvarsall.bat',
            r'%LOCALAPPDATA%\Programs\Common\Microsoft\Visual C++ for Python\9.0\vcvarsall.bat',
            r'%ProgramFiles(x86)%\Common Files\Microsoft\Visual C++ for Python\9.0\vcvarsall.bat',
            r'%ProgramFiles%\Common Files\Microsoft\Visual C++ for Python\9.0\vcvarsall.bat',
        ]
    else:
        raise ValueError('Unknown MSVC version "%s"' % msvc)

    for filename in setenv_paths:
        filename = os.path.expandvars(filename)
        if isfile(filename):
            if 'SetEnv.cmd' in filename:
                # When using SDK to build python 2.7 in MSVC100, we need to set
                # additional variables and pass different parameters from vcvarsall
                # see http://bugs.python.org/issue14708
                mssdk = filename.replace(r'\Bin\SetEnv.cmd', '')
                return textwrap.dedent('''
                    set MSSDK=%s
                    set DISTUTILS_USE_SDK=1
                    call "%s" %s /Release
                    ''' % (mssdk, filename, {32: '/x86', 64: '/x64'}[cc.bits])
                )

            # Otherwise, its a simple vcvarsall.bat call
            return textwrap.dedent('''
                call "%s" %s /Release
                ''' % (filename, {32: 'x86', 64: 'amd64'}[cc.bits])
            )

    # If code reaches this point, we could not find MSVC.
    # If the user specified a --msvc version, raise an error. Otherwise, just print a warning.
    message = "Couldn't find Visual Studio in any of these paths: %r" % setenv_paths
    if config.CONDA_MSVC is not None:
        raise RuntimeError('Error: ' + message)
    else:
        print("Warning: " + message)
        return ''


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
            # more debuggable with echo on
            fo.write('@echo on\n')
            for kv in iteritems(env):
                fo.write('set %s=%s\n' % kv)
            fo.write("REM ===== end generated header =====\n")
            fo.write(data)

        cmd = [os.environ['COMSPEC'], '/c', 'call', 'bld.bat']
        _check_call(cmd, cwd=src_dir)
        kill_processes()
        fix_staged_scripts()
