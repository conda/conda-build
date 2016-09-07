'''
Module to handle generating test files.
'''

from __future__ import absolute_import, division, print_function

import glob
import os
from os.path import join, exists, isdir
import sys

from conda_build.utils import copy_into, get_ext_files, on_win
from conda_build import source


header = '''
from __future__ import absolute_import, division, print_function

import sys
import subprocess
from distutils.spawn import find_executable
import shlex


def call_args(string):
    args = shlex.split(string)
    arg0 = args[0]
    args[0] = find_executable(arg0)
    if not args[0]:
        sys.exit("Command not found: '%s'" % arg0)

    try:
        subprocess.check_call(args)
    except subprocess.CalledProcessError:
        sys.exit('Error: command failed: %s' % ' '.join(args))

# --- end header
'''


def create_files(dir_path, m, config):
    """
    Create the test files for pkg in the directory given.  The resulting
    test files are configuration (i.e. platform, architecture, Python and
    numpy version, ...) independent.
    Return False, if the package has no tests (for any configuration), and
    True if it has.
    """
    has_files = False
    for fn in m.get_value('test/files', []):
        has_files = True
        path = join(m.path, fn)
        copy_into(path, join(dir_path, fn), config.timeout)
    # need to re-download source in order to do tests
    if m.get_value('test/source_files') and not isdir(config.work_dir):
        source.provide(m.path, m.get_section('source'), config=config)
    for pattern in m.get_value('test/source_files', []):
        if on_win and '\\' in pattern:
            raise RuntimeError("test/source_files paths must use / "
                                "as the path delimiter on Windows")
        has_files = True
        files = glob.glob(join(source.get_dir(config), pattern))
        if not files:
            raise RuntimeError("Did not find any source_files for test with pattern %s", pattern)
        for f in files:
            copy_into(f, f.replace(source.get_dir(config), config.test_dir), config.timeout)
        for ext in '.pyc', '.pyo':
            for f in get_ext_files(config.test_dir, ext):
                os.remove(f)
    return has_files


def create_shell_files(dir_path, m, config):
    has_tests = False
    if sys.platform == 'win32':
        name = 'run_test.bat'
    else:
        name = 'run_test.sh'

    if exists(join(m.path, name)):
        copy_into(join(m.path, name), dir_path, config.timeout)
        has_tests = True

    with open(join(dir_path, name), 'a') as f:
        f.write('\n\n')
        for cmd in m.get_value('test/commands', []):
            f.write(cmd)
            f.write('\n')
            if sys.platform == 'win32':
                f.write("if errorlevel 1 exit 1\n")
            has_tests = True

    return has_tests


def create_py_files(dir_path, m):
    has_tests = False
    with open(join(dir_path, 'run_test.py'), 'w') as fo:
        fo.write("# tests for %s (this is a generated file)\n" % m.dist())
        fo.write(header + '\n')
        fo.write("print('===== testing package: %s =====')\n" % m.dist())

        for name in m.get_value('test/imports', []):
            fo.write('print("import: %r")\n' % name)
            fo.write('import %s\n' % name)
            fo.write('\n')
            has_tests = True

        try:
            with open(join(m.path, 'run_test.py')) as fi:
                fo.write("print('running run_test.py')\n")
                fo.write("# --- run_test.py (begin) ---\n")
                fo.write(fi.read())
                fo.write("# --- run_test.py (end) ---\n")
            has_tests = True
        except IOError:
            fo.write("# no run_test.py exists for this package\n")
        except AttributeError:
            fo.write("# tests were not packaged with this module, and cannot be run\n")
        fo.write("\nprint('===== %s OK =====')\n" % m.dist())

    return has_tests


def create_pl_files(dir_path, m):
    has_tests = False
    with open(join(dir_path, 'run_test.pl'), 'w') as fo:
        print(r'# tests for %s (this is a generated file)' % m.dist(), file=fo)
        print(r'print("===== testing package: %s =====\n");' % m.dist(),
              file=fo)
        print(r'my $expected_version = "%s";' % m.version().rstrip('0'),
              file=fo)
        for name in m.get_value('test/imports'):
            print(r'print("import: %s\n");' % name, file=fo)
            print('use %s;\n' % name, file=fo)
            # Don't try to print version for complex imports
            if ' ' not in name:
                print(("if (defined {0}->VERSION) {{\n" +
                       "\tmy $given_version = {0}->VERSION;\n" +
                       "\t$given_version =~ s/0+$//;\n" +
                       "\tdie('Expected version ' . $expected_version . ' but" +
                       " found ' . $given_version) unless ($expected_version " +
                       "eq $given_version);\n" +
                       "\tprint('\tusing version ' . {0}->VERSION . '\n');\n" +
                       "\n}}").format(name), file=fo)
            has_tests = True

        try:
            with open(join(m.path, 'run_test.pl')) as fi:
                print("# --- run_test.pl (begin) ---", file=fo)
                fo.write(fi.read())
                print("# --- run_test.pl (end) ---", file=fo)
            has_tests = True
        except IOError:
            fo.write("# no run_test.pl exists for this package\n")
        print('\nprint("===== %s OK =====\\n");' % m.dist(), file=fo)

    return has_tests
