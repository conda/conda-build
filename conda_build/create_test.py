'''
Module to handle generating test files.
'''

from __future__ import absolute_import, division, print_function

import os
from os.path import join, exists
import sys

from conda_build.utils import copy_into, on_win, ensure_list


def create_files(m, test_dir=None):
    """
    Create the test files for pkg in the directory given.  The resulting
    test files are configuration (i.e. platform, architecture, Python and
    numpy version, ...) independent.
    Return False, if the package has no tests (for any configuration), and
    True if it has.
    """
    if not test_dir:
        test_dir = m.config.test_dir
    has_files = False
    if not os.path.isdir(test_dir):
        os.makedirs(test_dir)

    recipe_dir = m.path or m.meta.get('extra', {}).get('parent_recipe', {}).get('path')

    for fn in ensure_list(m.get_value('test/files', [])):
        has_files = True
        path = join(recipe_dir, fn)
        if not os.path.isdir(os.path.dirname(path)):
            os.makedirs(os.path.dirname(path))
        # disable locking to avoid locking a temporary directory (the extracted test folder)
        copy_into(path, join(test_dir, fn), m.config.timeout, locking=False,
                  clobber=True)
    return has_files


def create_shell_files(m, test_dir=None):
    if not test_dir:
        test_dir = m.config.test_dir
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
        # disable locking to avoid locking a temporary directory (the extracted test folder)
        copy_into(join(m.path, name), test_dir, m.config.timeout, locking=False)
        has_tests = True

    commands = ensure_list(m.get_value('test/commands', []))
    if commands:
        with open(join(test_dir, name), 'a') as f:
            f.write('\n\n')
            if not on_win:
                f.write('set -ex\n\n')
            f.write('\n\n')
            for cmd in commands:
                f.write(cmd)
                f.write('\n')
                if on_win:
                    f.write("IF %ERRORLEVEL% NEQ 0 exit 1\n")
                has_tests = True
            f.write('exit 0\n')

    return has_tests or os.path.isfile(os.path.join(m.config.test_dir, name))


def _create_test_files(m, test_dir, ext, comment_char='# '):
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
    out_file = join(test_dir, 'run_test' + ext)

    if os.path.isfile(test_file):
        with open(out_file, 'w') as fo:
            fo.write("%s tests for %s (this is a generated file);\n" % (comment_char, m.dist()))
            fo.write("print('===== testing package: %s =====');\n" % m.dist())

            try:
                with open(test_file) as fi:
                    fo.write("print('running {0}');\n".format(name))
                    fo.write("{0} --- {1} (begin) ---\n".format(comment_char, name))
                    fo.write(fi.read())
                    fo.write("{0} --- {1} (end) ---\n".format(comment_char, name))
            except AttributeError:
                fo.write("# tests were not packaged with this module, and cannot be run\n")
            fo.write("\nprint('===== %s OK =====');\n" % m.dist())

    return (out_file, os.path.isfile(test_file) and os.path.basename(test_file) != 'no-file')


def create_py_files(m, test_dir=None):
    if not test_dir:
        test_dir = m.config.test_dir
    tf, tf_exists = _create_test_files(m, test_dir, '.py')

    # Ways in which we can mark imports as none python imports
    # 1. preface package name with r-, lua- or perl-
    # 2. use list of dicts for test/imports, and have lang set in those dicts
    pkg_name = m.name()
    likely_r_pkg = pkg_name.startswith('r-')
    likely_lua_pkg = pkg_name.startswith('lua-')
    likely_perl_pkg = pkg_name.startswith('perl-')
    likely_non_python_pkg = likely_r_pkg or likely_lua_pkg or likely_perl_pkg

    if likely_non_python_pkg:
        imports = []
        for import_item in ensure_list(m.get_value('test/imports', [])):
            # add any imports specifically marked as python
            if (hasattr(import_item, 'keys') and 'lang' in import_item and
                    import_item['lang'] == 'python'):
                imports.extend(import_item['imports'])
    else:
        imports = ensure_list(m.get_value('test/imports', []))
        imports = [item for item in imports if (not hasattr(item, 'keys') or
                                                'lang' in item and item['lang'] == 'python')]
    if imports:
        with open(tf, 'a') as fo:
            for name in imports:
                fo.write('print("import: %r")\n' % name)
                fo.write('import %s\n' % name)
                fo.write('\n')
    return tf if (tf_exists or imports) else False


def create_r_files(m, test_dir=None):
    if not test_dir:
        test_dir = m.config.test_dir
    tf, tf_exists = _create_test_files(m, test_dir, '.r')

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
        with open(tf, 'a') as fo:
            for name in imports:
                fo.write('print("library(%r)")\n' % name)
                fo.write('library(%s)\n' % name)
                fo.write('\n')
    return tf if (tf_exists or imports) else False


def create_pl_files(m, test_dir=None):
    if not test_dir:
        test_dir = m.config.test_dir
    tf, tf_exists = _create_test_files(m, test_dir, '.pl')
    imports = None
    if m.name().startswith('perl-'):
        imports = ensure_list(m.get_value('test/imports', []))
    else:
        for import_item in ensure_list(m.get_value('test/imports', [])):
            if (hasattr(import_item, 'keys') and 'lang' in import_item and
                    import_item['lang'] == 'perl'):
                imports = import_item['imports']
                break
    if tf_exists or imports:
        with open(tf, 'a') as fo:
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


def create_lua_files(m, test_dir=None):
    if not test_dir:
        test_dir = m.config.test_dir
    tf, tf_exists = _create_test_files(m, test_dir, '.lua')
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


def create_all_test_files(m, test_dir=None):
    if not test_dir:
        test_dir = m.config.test_dir
    files = create_files(m, test_dir)
    pl_files = create_pl_files(m, test_dir)
    py_files = create_py_files(m, test_dir)
    r_files = create_r_files(m, test_dir)
    lua_files = create_lua_files(m, test_dir)
    shell_files = create_shell_files(m, test_dir)
    return files, pl_files, py_files, r_files, lua_files, shell_files
