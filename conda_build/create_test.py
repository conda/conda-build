'''
Module to handle generating test files.
'''

from __future__ import absolute_import, division, print_function

import os
from os.path import join, exists
import json

from conda_build.utils import copy_into, ensure_list, glob, on_win, rm_rf


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

    for pattern in ensure_list(m.get_value('test/files', [])):
        has_files = True
        files = glob(join(m.path, pattern.replace('/', os.sep)))
        for f in files:
            copy_into(f, f.replace(m.path, test_dir), m.config.timeout, locking=False,
                    clobber=True)
    return has_files


def _get_output_script_name(m, win_status):
    # the way this works is that each output needs to explicitly define a test script to run.
    #   They do not automatically pick up run_test.*, but can be pointed at that explicitly.

    ext = '.bat' if win_status else '.sh'
    dst_name = 'run_test' + ext
    src_name = dst_name
    if m.is_output:
        src_name = 'no-file'
        for out in m.meta.get('outputs', []):
            if m.name() == out.get('name'):
                out_test_script = out.get('test', {}).get('script', 'no-file')
                if os.path.splitext(out_test_script)[1].lower() == ext:
                    src_name = out_test_script
                    break
    return src_name, dst_name


def create_shell_files(m, test_dir=None):
    if not test_dir:
        test_dir = m.config.test_dir

    win_status = [on_win]

    if m.noarch:
        win_status = [False, True]

    shell_files = []
    for status in win_status:
        src_name, dst_name = _get_output_script_name(m, status)
        dest_file = join(test_dir, dst_name)
        if exists(join(m.path, src_name)):
            # disable locking to avoid locking a temporary directory (the extracted test folder)
            copy_into(join(m.path, src_name), dest_file, m.config.timeout, locking=False)
        if os.path.basename(test_dir) != 'test_tmp':
            commands = ensure_list(m.get_value('test/commands', []))
            if commands:
                with open(join(dest_file), 'a') as f:
                    f.write('\n\n')
                    if not status:
                        f.write('set -ex\n\n')
                    f.write('\n\n')
                    for cmd in commands:
                        f.write(cmd)
                        f.write('\n')
                        if status:
                            f.write("IF %ERRORLEVEL% NEQ 0 exit /B 1\n")
                    if status:
                        f.write('exit /B 0\n')
                    else:
                        f.write('exit 0\n')
        if os.path.isfile(dest_file):
            shell_files.append(dest_file)
    return shell_files


def _create_test_files(m, test_dir, ext, comment_char='# '):
    name = 'run_test' + ext
    if m.is_output:
        name = ''
        # the way this works is that each output needs to explicitly define a test script to run
        #   They do not automatically pick up run_test.*, but can be pointed at that explicitly.
        for out in m.meta.get('outputs', []):
            if m.name() == out.get('name'):
                out_test_script = out.get('test', {}).get('script', 'no-file')
                if out_test_script.endswith(ext):
                    name = out_test_script
                    break

    out_file = join(test_dir, 'run_test' + ext)
    if name:
        test_file = os.path.join(m.path, name)
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
    return (out_file, bool(name) and os.path.isfile(out_file) and os.path.basename(test_file) != 'no-file')


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
    if test_dir:
        rm_rf(test_dir)
        os.makedirs(test_dir)
        # this happens when we're finishing the build.
        test_deps = m.meta.get('test', {}).get('requires', [])
        if test_deps:
            with open(os.path.join(test_dir, 'test_time_dependencies.json'), 'w') as f:
                json.dump(test_deps, f)
    else:
        # this happens when we're running a package's tests
        test_dir = m.config.test_dir

    files = create_files(m, test_dir)

    pl_files = create_pl_files(m, test_dir)
    py_files = create_py_files(m, test_dir)
    r_files = create_r_files(m, test_dir)
    lua_files = create_lua_files(m, test_dir)
    shell_files = create_shell_files(m, test_dir)
    return files, pl_files, py_files, r_files, lua_files, shell_files
