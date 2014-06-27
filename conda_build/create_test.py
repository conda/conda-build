'''
Module to handle generating test files.
'''

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import shutil
import sys
from io import open
from os.path import dirname, join, isdir, exists

from conda_build import config, source


def create_files(dir_path, m):
    """
    Create the test files for pkg in the directory given.  The resulting
    test files are configuration (i.e. platform, architecture, Python and
    numpy version, CE/Pro) independent.
    Return False, if the package has no tests (for any configuration), and
    True if it has.
    """
    has_files = False
    for fn in m.get_value('test/files', []):
        has_files = True
        path = join(m.path, fn)
        if isdir(path):
            shutil.copytree(path, join(dir_path, fn))
        else:
            shutil.copy(path, dir_path)
    return has_files


def create_shell_files(dir_path, m):
    has_tests = False
    if sys.platform == 'win32':
        name = 'run_test.bat'
    else:
        name = 'run_test.sh'
    if exists(join(m.path, name)):
        shutil.copy(join(m.path, name), dir_path)
        has_tests = True

    with open(join(dir_path, name), 'a', encoding='utf-8') as f:
        f.write('\n\n')
        for cmd in m.get_value('test/commands'):
            f.write(cmd)
            f.write('\n')
            has_tests = True

    return has_tests


def create_py_files(dir_path, m):
    has_tests = False
    with open(join(dir_path, 'run_test.py'), 'w', encoding='utf-8') as fo:
        fo.write("# tests for %s (this is a generated file)\n" % m.dist())
        with open(join(dirname(__file__), 'header_test.py'),
                  encoding='utf-8') as fi:
            fo.write(fi.read() + '\n')
        fo.write("print('===== testing package: %s =====')\n" % m.dist())

        for name in m.get_value('test/imports'):
            fo.write('print("import: %r")\n' % name)
            fo.write('import %s\n' % name)
            fo.write('\n')
            has_tests = True

        try:
            with open(join(m.path, 'run_test.py'), encoding='utf-8') as fi:
                fo.write("# --- run_test.py (begin) ---\n")
                fo.write(fi.read())
                fo.write("# --- run_test.py (end) ---\n")
            has_tests = True
        except IOError:
            fo.write("# no run_test.py exists for this package\n")
        fo.write("\nprint('===== %s OK =====')\n" % m.dist())

    return has_tests


def create_pl_files(dir_path, m):
    has_tests = False
    with open(join(dir_path, 'run_test.pl'), 'w', encoding='utf-8') as fo:
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
            with open(join(m.path, 'run_test.pl'), encoding='utf-8') as fi:
                print("# --- run_test.pl (begin) ---", file=fo)
                fo.write(fi.read())
                print("# --- run_test.pl (end) ---", file=fo)
            has_tests = True
        except IOError:
            fo.write("# no run_test.pl exists for this package\n")
        print('\nprint("===== %s OK =====\\n");' % m.dist(), file=fo)

    return has_tests
