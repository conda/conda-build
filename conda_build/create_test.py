'''
Module to handle generating test files.
'''

from __future__ import absolute_import, division, print_function

import glob
import logging
import os
from os.path import join, exists, isdir
import sys

from conda_build.utils import copy_into, get_ext_files, on_win, ensure_list
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
    for fn in ensure_list(m.get_value('test/files', [])):
        has_files = True
        path = join(m.path, fn)
        copy_into(path, join(dir_path, fn), config.timeout, locking=config.locking)
    # need to re-download source in order to do tests
    if m.get_value('test/source_files') and not isdir(config.work_dir):
        source.provide(m, config=config)
    for pattern in ensure_list(m.get_value('test/source_files', [])):
        if on_win and '\\' in pattern:
            raise RuntimeError("test/source_files paths must use / "
                                "as the path delimiter on Windows")
        has_files = True
        files = glob.glob(join(config.work_dir, pattern))
        if not files:
            raise RuntimeError("Did not find any source_files for test with pattern %s", pattern)
        for f in files:
            try:
                copy_into(f, f.replace(config.work_dir, config.test_dir), config.timeout,
                        locking=config.locking)
            except OSError as e:
                log = logging.getLogger(__name__)
                log.warn("Failed to copy {0} into test files.  Error was: {1}".format(f, str(e)))
        for ext in '.pyc', '.pyo':
            for f in get_ext_files(config.test_dir, ext):
                os.remove(f)
    return has_files


def create_shell_files(dir_path, m, config):
    has_tests = False
    ext = '.bat' if sys.platform == 'win32' else '.sh'
    name = 'no-file'

    # the way this works is that each output needs to explicitly define a test script to run.
    #   They do not automatically pick up run_test.*, but can be pointed at that explicitly.
    for out in m.meta.get('outputs', []):
        if m.name() == out.get('name'):
            out_test_script = out.get('test', {}).get('script', 'no-file')
            if os.path.splitext(out_test_script)[1].lower() == ext:
                name = out_test_script
                break
    else:
        name = "run_test{}".format(ext)

    if exists(join(m.path, name)):
        copy_into(join(m.path, name), dir_path, config.timeout, locking=config.locking)
        has_tests = True

    with open(join(dir_path, name), 'a') as f:
        f.write('\n\n')
        for cmd in ensure_list(m.get_value('test/commands', [])):
            f.write(cmd)
            f.write('\n')
            if sys.platform == 'win32':
                f.write("if errorlevel 1 exit 1\n")
            has_tests = True

    return has_tests


def _create_test_files(dir_path, m, ext, comment_char='# '):
    # the way this works is that each output needs to explicitly define a test script to run
    #   They do not automatically pick up run_test.*, but can be pointed at that explicitly.
    name = 'run_test' + ext
    for out in m.meta.get('outputs', []):
        if m.name() == out.get('name'):
            out_test_script = out.get('test', {}).get('script', 'no-file')
            if out_test_script.endswith(ext):
                name = out_test_script
                break

    test_file = os.path.join(m.path, name)
    out_file = join(dir_path, 'run_test' + ext)

    if os.path.isfile(test_file):
        with open(out_file, 'w') as fo:
            fo.write("%s tests for %s (this is a generated file)\n" % (comment_char, m.dist()))
            fo.write(header + '\n')
            fo.write("print('===== testing package: %s =====')\n" % m.dist())

            try:
                with open(test_file) as fi:
                    fo.write("print('running {0}')\n".format(name))
                    fo.write("{0} --- {1} (begin) ---\n".format(comment_char, name))
                    fo.write(fi.read())
                    fo.write("{0} --- {1} (end) ---\n".format(comment_char, name))
            except AttributeError:
                fo.write("# tests were not packaged with this module, and cannot be run\n")
            fo.write("\nprint('===== %s OK =====')\n" % m.dist())

    return (out_file, os.path.isfile(test_file) and os.path.basename(test_file) != 'no-file')


def create_py_files(dir_path, m):
    tf, tf_exists = _create_test_files(dir_path, m, '.py')
    imports = None
    for import_item in ensure_list(m.get_value('test/imports', [])):
        if (hasattr(import_item, 'keys') and 'lang' in import_item and
                import_item['lang'] == 'python'):
            imports = import_item['imports']
            break
    if imports:
        with open(tf, 'a+') as fo:
            for name in imports:
                fo.write('print("import: %r")\n' % name)
                fo.write('import %s\n' % name)
                fo.write('\n')
    return tf if (tf_exists or imports) else False


def create_r_files(dir_path, m):
    tf, tf_exists = _create_test_files(dir_path, m, '.r')

    imports = None
    # two ways we can enable R import tests:
    # 1. preface package name with r- and just list imports in test/imports
    # 2. use list of dicts for test/imports, and have lang: 'r' set in one of those dicts
    if m.name().startswith('r-'):
        imports = ensure_list(m.get_value('test/imports', []))
    else:
        for import_item in ensure_list(m.get_value('test/imports', [])):
            if (hasattr(import_item, 'keys') and 'lang' in import_item and
                    import_item['lang'] == 'r'):
                imports = import_item['imports']
                break
    if imports:
        with open(tf, 'a+') as fo:
            for name in imports:
                fo.write('print("library(%r)")\n' % name)
                fo.write('library(%s)\n' % name)
                fo.write('\n')
    return tf if (tf_exists or imports) else False


def create_pl_files(dir_path, m):
    tf, tf_exists = _create_test_files(dir_path, m, '.pl')
    imports = None
    if m.name().startswith('perl-'):
        imports = ensure_list(m.get_value('test/imports', []))
    else:
        for import_item in ensure_list(m.get_value('test/imports', [])):
            if (hasattr(import_item, 'keys') and 'lang' in import_item and
                    import_item['lang'] == 'perl'):
                imports = import_item['imports']
                break
    if tf or imports:
        with open(tf, 'a+') as fo:
            print(r'my $expected_version = "%s";' % m.version().rstrip('0'),
                    file=fo)
            if imports:
                for name in imports:
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
    return tf if (tf_exists or imports) else False


def create_lua_files(dir_path, m):
    tf, tf_exists = _create_test_files(dir_path, m, '.lua')
    imports = None
    if m.name().startswith('lua-'):
        imports = ensure_list(m.get_value('test/imports', []))
    else:
        for import_item in ensure_list(m.get_value('test/imports', [])):
            if (hasattr(import_item, 'keys') and 'lang' in import_item and
                    import_item['lang'] == 'lua'):
                imports = import_item['imports']
                break
    if imports:
        with open(tf, 'a+') as fo:
            for name in imports:
                print(r'print("require \"%s\"\n");' % name, file=fo)
                print('require "%s"\n' % name, file=fo)
    return tf if (tf_exists or imports) else False
