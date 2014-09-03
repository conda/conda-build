'''
Module that does most of the heavy lifting for the ``conda build`` command.
'''

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import json
import os
import re
import shutil
import stat
import operator
import functools
import subprocess
import sys
import tarfile
from io import open
from os import readlink
from os.path import exists, isdir, isfile, islink, join, basename, dirname
import yaml
from collections import defaultdict


import conda.config as cc
import conda.plan as plan
from conda.api import get_index
from conda.compat import PY3
from conda.fetch import fetch_index
from conda.install import prefix_placeholder
from conda.utils import url_path

from conda_build import environ, source, tarcheck
from conda_build.config import (
    config,
    verify_rpaths,
    use_new_rpath_logic,
)
from conda_build.scripts import create_entry_points, bin_dirname
from conda_build.post import (post_process, post_build, is_obj,
                              fix_permissions, get_build_metadata)
from conda_build.utils import rm_rf, _check_call, SlotObject
from conda_build.index import update_index
from conda_build.create_test import (create_files, create_shell_files,
                                     create_py_files, create_pl_files)
from conda_build.dll import DynamicLibrary
from conda_build.link import LinkErrors

prefix = config.build_prefix
info_dir = join(prefix, 'info')


def invert_defaultdict_by_value_len(d):
    i = defaultdict(list)
    for (k, v) in d.items():
        i[len(v)].append(k)
    return i


#===============================================================================
# Build Root Classes
#===============================================================================
class BuildRoot(SlotObject):
    __slots__ = (
        'prefix',
        'forgiving',
        'allow_x11',
        'link_errors',
        'relative_start_index',

        'old_files',
        'all_files',
        'new_files',

        'old_paths',
        'all_paths',
        'new_paths',

        'old_dll_paths',
        'all_dll_paths',
        'all_symlink_dll_paths',
        'new_dll_paths',

        'old_non_dll_paths',
        'new_non_dll_paths',
        'all_non_dll_paths',

        'old_dlls',
        'all_dlls',
        'all_dlls_by_len',
        'all_symlink_dlls',
        'all_symlink_dlls_by_len',
        'new_dlls',
    )

    _repr_exclude_ = set(__slots__[4:-1])

    def __init__(self, prefix=None, old_files=None, all_files=None,
                       forgiving=False, is_build=True, prefix_paths=True,
                       allow_x11=None, extra_external=None):
        self.forgiving = forgiving
        if not prefix:
            prefix = config.build_prefix
        self.prefix = prefix
        self.relative_start_ix = len(prefix)+1
        self.allow_x11 = allow_x11
        self.extra_external = extra_external
        self.link_errors = None

        if prefix_paths:
            join_prefix = lambda f: join(prefix, f)
        else:
            join_prefix = lambda f: f

        if not old_files and is_build:
            # Ugh, this should be abstracted into a single interface that we
            # can use from both here and post.py/build.py.  Consider that an
            # xxx todo.
            old_files = read_prefix_files()
        self.old_files = old_files

        if not all_files:
            from conda_build.dll import get_files
            all_files = get_files(self.prefix)

        self.all_files = all_files
        self.all_paths = [ join_prefix(f) for f in self.all_files ]

        # Nice little cyclic dependency we're introducing here on post.py
        # (which is the thing that should be calling us).
        from conda_build.post import is_obj as _is_obj
        is_obj = lambda f: _is_obj(join(prefix, f) if f[0] != '/' else f)

        if is_build:
            self.new_files = self.all_files - self.old_files
            self.old_paths = [ join_prefix(f) for f in self.old_files ]
            self.old_dll_paths = set(p for p in self.old_paths if is_obj(p))
            self.new_paths = [ join_prefix(f) for f in self.new_files ]
            self.all_dll_paths = set(
                p for p in self.all_paths
                    if p in self.old_dll_paths or is_obj(p)
            )
            self.new_dll_paths = self.all_dll_paths - self.old_dll_paths

            self.old_non_dll_paths = set(self.old_paths) - self.old_dll_paths
            self.new_non_dll_paths = set(self.new_paths) - self.new_dll_paths
            self.all_non_dll_paths = set(self.all_paths) - self.all_dll_paths
        else:
            self.new_files = self.all_files
            self.new_paths = self.all_paths
            self.old_paths = []
            self.old_dll_paths = set()
            self.all_dll_paths = set(p for p in self.all_paths if is_obj(p))
            self.new_dll_paths = self.all_dll_paths

            self.old_non_dll_paths = set()
            self.all_non_dll_paths = set(self.all_paths) - self.all_dll_paths
            self.new_non_dll_paths = self.all_non_dll_paths


        def create_path_list_lookup(path_list):
            path_list_lookup = defaultdict(list)
            for path in path_list:
                name = basename(path)
                path_list_lookup[name].append(path)
            return path_list_lookup

        self.all_dlls = create_path_list_lookup(self.all_dll_paths)

        self.all_symlink_dll_paths = [
            p for p in self.all_paths
                if islink(p) and basename(readlink(p)) in self.all_dlls
        ]

        self.all_symlink_dlls = create_path_list_lookup(
                self.all_symlink_dll_paths)

        # Invert both dicts such that the keys become the length of the lists;
        # in a perfect world, there would only be one key, [1], which means
        # all the target filenames were unique within the entire build root.
        #
        # R has one with two:
        #
        #    In [75]: br.all_dlls_by_len.keys()
        #    Out[75]: [1, 2]
        #
        #    In [76]: br.all_dlls_by_len[2]
        #    Out[76]: [u'Rscript']
        #
        #    In [77]: br.all_dlls['Rscript']
        #    Out[77]:
        #    [u'/home/r/miniconda/envs/_build/bin/Rscript',
        #     u'/home/r/miniconda/envs/_build/lib64/R/bin/Rscript']
        #
        # In the case above, we can ignore this one, as nothing links to
        # Rscript directly (technically, it's an executable, but is_elf()
        # can't distinguish between exe and .so).  If libR.so was showing
        # two hits, that's a much bigger problem (we'll trap that via an
        # assert in our __getitem__()).
        self.all_dlls_by_len = invert_defaultdict_by_value_len(self.all_dlls)
        self.all_symlink_dlls_by_len = (
            invert_defaultdict_by_value_len(self.all_symlink_dlls)
        )

        self.new_dlls = [
            DynamicLibrary.create(p, build_root=self)
                for p in sorted(self.new_dll_paths)
        ]

        if is_build:
            self.old_dlls = [
                DynamicLibrary.create(p, build_root=self)
                    for p in sorted(self.old_dll_paths)
            ]

    def __getitem__(self, dll_name):
        ''' Return relative path to folder containing the specified dependency

        If multiple possibilities exist *and* not self.forgiving, raise an
        assertion error
        '''

        targets = self.all_dlls.get(dll_name, self.all_symlink_dlls[dll_name])
        if len(targets) != 1:
            if not self.forgiving:
                assert len(targets) == 1, (dll_name, targets)
            else:
                #print("error: unresolved: %s" % dll_name)
                return

        target = targets[0]
        relative_target = target[self.relative_start_ix:]
        return dirname(relative_target)

    def __contains__(self, dll_name):
        return (
            dll_name in self.all_dlls or
            dll_name in self.all_symlink_dlls
        )

    def verify(self):
        get_dll_link_errors = lambda dll: dll.link_errors
        link_errors = map(get_dll_link_errors, self.new_dlls)
        self.link_errors = functools.reduce(operator.add, link_errors, [])

        if self.link_errors:
            raise LinkErrors(self)

    def make_relocatable(self, dlls=None, copy=False):
        if not dlls:
            dlls = self.new_dlls

        for dll in dlls:
            dll.make_relocatable(copy=copy)

    def post_build(self):
        self.make_relocatable()
        self.verify()


def ensure_dir(dir, *args):
    if not isdir(dir):
        os.makedirs(dir, *args)

def get_prefix_files():
    '''
    Returns a set of all files in prefix.
    '''
    from conda_build.dll import get_files
    return get_files(prefix)

def read_prefix_files():
    with open(join(config.croot, 'prefix_files.txt'), 'r') as f:
        prefix_files = set(f.read().splitlines())
    return prefix_files

def write_prefix_files(prefix_files):
    with open(join(config.croot, 'prefix_files.txt'), 'w') as f:
        f.write(u'\n'.join(sorted(list(prefix_files))))
        f.write(u'\n')

def create_post_scripts(m):
    '''
    Create scripts to run after build step
    '''
    recipe_dir = m.path
    ext = '.bat' if sys.platform == 'win32' else '.sh'
    for tp in 'pre-link', 'post-link', 'pre-unlink':
        src = join(recipe_dir, tp + ext)
        if not isfile(src):
            continue
        dst_dir = join(config.build_prefix,
                       'Scripts' if sys.platform == 'win32' else 'bin')
        ensure_dir(dst_dir, int('755', 8))
        dst = join(dst_dir, '.%s-%s%s' % (m.name(), tp, ext))
        shutil.copyfile(src, dst)
        os.chmod(dst, int('755', 8))


def have_prefix_files(files):
    '''
    Yields files that contain the current prefix in them, and modifies them
    to replace the prefix with a placeholder.

    :param files: Filenames to check for instances of prefix
    :type files: list of str
    '''
    prefix_bytes = config.build_prefix.encode('utf-8')
    placeholder_bytes = prefix_placeholder.encode('utf-8')
    alt_prefix_bytes = prefix_bytes.replace(b'\\', b'/')
    alt_placeholder_bytes = placeholder_bytes.replace(b'\\', b'/')
    for f in files:
        if f.endswith(('.pyc', '.pyo', '.a', '.dylib')):
            continue
        path = join(config.build_prefix, f)
        if isdir(path):
            continue
        if sys.platform != 'darwin' and islink(path):
            # OSX does not allow hard-linking symbolic links, so we cannot
            # skip symbolic links (as we can on Linux)
            continue
        if sys.platform != 'win32' and is_obj(path):
            continue
        # Open file as binary, since it might have any crazy encoding
        with open(path, 'rb') as fi:
            data = fi.read()
        # Skip files that are truly binary
        if b'\x00' in data:
            continue
        # This may end up mixing encodings, but since paths are usually ASCII,
        # this shouldn't be a problem very often. The only way to completely
        # avoid this would be to use chardet (or cChardet) to detect the
        # encoding on the fly.
        if prefix_bytes in data:
            data = data.replace(prefix_bytes, placeholder_bytes)
        elif (sys.platform == 'win32') and (alt_prefix_bytes in data):
            # some windows libraries use unix-style path separators
            data = data.replace(alt_prefix_bytes, alt_placeholder_bytes)
        else:
            continue
        st = os.stat(path)
        # Save as
        os.chmod(path, stat.S_IMODE(st.st_mode) | stat.S_IWUSR) # chmod u+w
        with open(path, 'wb') as fo:
            fo.write(data)
        if sys.platform == 'win32':
            f = f.replace('\\', '/')
        yield f


def create_info_files(m, files, include_recipe=True):
    '''
    Creates the metadata files that will be stored in the built package.

    :param m: Package metadata
    :type m: Metadata
    :param files: Paths to files to include in package
    :type files: list of str
    :param include_recipe: Whether or not to include the recipe (True by default)
    :type include_recipe: bool
    '''
    recipe_dir = join(config.info_dir, 'recipe')
    os.makedirs(recipe_dir)

    if include_recipe:
        for fn in os.listdir(m.path):
            if fn.startswith('.'):
                continue
            src_path = join(m.path, fn)
            dst_path = join(recipe_dir, fn)
            if isdir(src_path):
                shutil.copytree(src_path, dst_path)
            else:
                shutil.copy(src_path, dst_path)

    if isfile(join(recipe_dir, 'meta.yaml')):
        shutil.move(join(recipe_dir, 'meta.yaml'),
                    join(recipe_dir, 'meta.yaml.orig'))

    with open(join(recipe_dir, 'meta.yaml'), 'w', encoding='utf-8') as fo:
        yaml.safe_dump(m.meta, fo)

    if sys.platform == 'win32':
        for i, f in enumerate(files):
            files[i] = f.replace('\\', '/')

    with open(join(config.info_dir, 'files'), 'w', encoding='utf-8') as fo:
        for f in files:
            fo.write(f + '\n')

    # Deal with Python 2 and 3's different json module type reqs
    mode_dict = {'mode': 'w', 'encoding': 'utf-8'} if PY3 else {'mode': 'wb'}
    with open(join(config.info_dir, 'index.json'), **mode_dict) as fo:
        json.dump(m.info_index(), fo, indent=2, sort_keys=True)

    with open(join(config.info_dir, 'recipe.json'), **mode_dict) as fo:
        json.dump(m.meta, fo, indent=2, sort_keys=True)

    files_with_prefix = m.has_prefix_files()
    binary_files_with_prefix = m.binary_has_prefix_files()

    for file in files_with_prefix:
        if file not in files:
            raise RuntimeError("file %s from build/has_prefix_files was "
                               "not found" % file)

    for file in binary_files_with_prefix:
        if file not in files:
            raise RuntimeError("file %s from build/has_prefix_files was "
                               "not found" % file)
        if sys.platform == 'win32':
            # Paths on Windows can contain spaces, so we need to quote the
            # paths. Fortunately they can't contain quotes, so we don't have
            # to worry about nested quotes.
            fmt_str = '"%s" %s "%s"'
        else:
            # Don't do it everywhere because paths on Unix can contain quotes,
            # and we don't have a good method of escaping, and because older
            # versions of conda don't support quotes in has_prefix
            fmt_str = '%s %s %s'
        prefix = config.build_prefix
        with open(os.path.join(prefix, file), 'rb') as f:
            data = f.read()
        if prefix.encode('utf-8') in data:
            files_with_prefix.append(fmt_str % (prefix, 'binary', file))
        elif sys.platform == 'win32':
            # some windows libraries encode prefix with unix path separators
            alt_p = prefix.replace('\\', '/')
            if alt_p.encode('utf-8') in data:
                files_with_prefix.append(fmt_str % (alt_p, 'binary', file))
            else:
                print('Warning: prefix %s not found in %s' % (prefix, file))
        else:
            print('Warning: prefix %s not found in %s' % (prefix, file))

    files_with_prefix += list(have_prefix_files(files))
    files_with_prefix = sorted(set(files_with_prefix))
    if files_with_prefix:
        with open(join(config.info_dir, 'has_prefix'), 'w', encoding='utf-8') as fo:
            for f in files_with_prefix:
                fo.write(f + '\n')

    no_link = m.get_value('build/no_link')
    if no_link:
        def w2rx(p):
            return p.replace('.', r'\.').replace('*', r'.*')
        if not isinstance(no_link, list):
            no_link = [no_link]
        rx = '(%s)$' % '|'.join(w2rx(p) for p in no_link)
        pat = re.compile(rx)
        with open(join(config.info_dir, 'no_link'), 'w', encoding='utf-8') as fo:
            for f in files:
                if pat.match(f):
                    fo.write(f + '\n')

    if m.get_value('source/git_url'):
        with open(join(config.info_dir, 'git'), 'w', encoding='utf-8') as fo:
            source.git_info(fo)

    if m.get_value('app/icon'):
        shutil.copyfile(join(m.path, m.get_value('app/icon')),
                        join(config.info_dir, 'icon.png'))


def create_env(pref, specs, clear_cache=True, verbose=True):
    '''
    Create a conda envrionment for the given prefix and specs.
    '''
    ensure_dir(config.bldpkgs_dir)
    update_index(config.bldpkgs_dir)
    if specs: # Don't waste time if there is nothing to do
        if clear_cache:
            # remove the cache such that a refetch is made,
            # this is necessary because we add the local build repo URL
            fetch_index.cache = {}
        index = get_index([url_path(config.croot)])

        cc.pkgs_dirs = cc.pkgs_dirs[:1]
        actions = plan.install_actions(pref, index, specs)
        plan.display_actions(actions, index)
        plan.execute_actions(actions, index, verbose=verbose)
    # ensure prefix exists, even if empty, i.e. when specs are empty
    ensure_dir(pref)

def rm_pkgs_cache(dist):
    '''
    Removes dist from the package cache.
    '''
    cc.pkgs_dirs = cc.pkgs_dirs[:1]
    rmplan = ['RM_FETCHED %s' % dist,
              'RM_EXTRACTED %s' % dist]
    plan.execute_plan(rmplan)

def bldpkg_path(m):
    '''
    Returns path to built package's tarball given its ``Metadata``.
    '''
    return join(config.bldpkgs_dir, '%s.tar.bz2' % m.dist())

def write_package_bz2(path, package_files):
    with tarfile.open(path, 'w:bz2') as fh:
        for f in sorted(package_files):
            t.add(join(config.build_prefix, f), f)

def build(m, get_src=True, verbose=True, post=None):
    '''
    Build the package with the specified metadata.

    :param m: Package metadata
    :type m: Metadata
    :param get_src: Should we download the source?
    :type get_src: bool
    :type post: bool or None. None means run the whole build. True means run
    post only. False means stop just before the post.
    '''
    if post in [False, None]:
        rm_rf(config.short_build_prefix)
        rm_rf(config.long_build_prefix)

        if m.binary_has_prefix_files():
            # We must use a long prefix here as the package will only be
            # installable into prefixes shorter than this one.
            config.use_long_build_prefix = True
        else:
            # In case there are multiple builds in the same process
            config.use_long_build_prefix = False

        # Display the name only
        # Version number could be missing due to dependency on source info.
        print("BUILD START:", m.dist())
        create_env(config.build_prefix,
                   [ms.spec for ms in m.ms_depends('build')],
                   verbose=verbose)

        if get_src:
            source.provide(m.path, m.get_section('source'))
            # Parse our metadata again because we did not initialize the source
            # information before.
            m.parse_again()

        print("Package:", m.dist())

        assert isdir(source.WORK_DIR)
        src_dir = source.get_dir()
        contents = os.listdir(src_dir)
        if contents:
            print("source tree in:", src_dir)
        else:
            print("no source")

        rm_rf(config.info_dir)
        pre_build_prefix_files = get_prefix_files()
        # Save this for later
        write_prefix_files(pre_build_prefix_files)

        if sys.platform == 'win32':
            import conda_build.windows as windows
            windows.build(m)
        else:
            env = environ.get_dict(m)
            build_file = join(m.path, 'build.sh')

            script = m.get_value('build/script', None)
            if script:
                if isinstance(script, list):
                    script = '\n'.join(script)
                with open(build_file, 'w', encoding='utf-8') as bf:
                    bf.write(script)
                os.chmod(build_file, 0o766)

            if exists(build_file):
                cmd = ['/bin/bash', '-x', '-e', build_file]

                _check_call(cmd, env=env, cwd=src_dir)

    if post in [True, None]:
        pre_build_prefix_files = read_prefix_files()

        get_build_metadata(m)
        create_post_scripts(m)
        create_entry_points(m.get_value('build/entry_points'))
        post_process(preserve_egg_dir=bool(m.get_value('build/preserve_egg_dir')))

        assert not exists(config.info_dir)
        pre_post_prefix_files = get_prefix_files()
        new_files = sorted(pre_post_prefix_files - pre_build_prefix_files)
        binary_relocation = bool(m.get_value('build/binary_relocation', True))

        build_root = None
        if use_new_rpath_logic or verify_rpaths:
            allow_x11 = bool(m.get_value('build/allow_x11', True))
            extra_external = m.get_value('build/extra_external', None)
            build_root = BuildRoot(
                old_files=pre_build_prefix_files,
                all_files=pre_post_prefix_files,
                forgiving=True,
                allow_x11=allow_x11,
                extra_external=extra_external,
            )

        if use_new_rpath_logic:
            print("Using new RPATH logic.")
            build_root.post_build()
        else:
            post_build(new_files, binary_relocation=binary_relocation)

        if verify_rpaths and not use_new_rpath_logic:
            build_root.verify()

        create_info_files(m, new_files, include_recipe=bool(m.path))
        post_post_prefix_files = get_prefix_files()
        package_files = post_post_prefix_files - pre_build_prefix_files
        fix_permissions(package_files)
        path = bldpkg_path(m)
        write_package_bz2(path, package_files)

        print("BUILD END:", m.dist())

        # we're done building, perform some checks
        tarcheck.check_all(path)
        update_index(config.bldpkgs_dir)
    else:
        print("STOPPING BUILD BEFORE POST:", m.dist())

def fake_out_previous_build():
    create_env(pref=config.build_prefix, specs=['python'], verbose=False)
    prefix_files = get_prefix_files()
    with open(join(config.croot, 'prefix_files.txt'), 'w') as f:
        f.write(u'\n'.join(sorted(list(prefix_files))))
        f.write(u'\n')

def test(m, verbose=True):
    '''
    Execute any test scripts for the given package.

    :param m: Package's metadata.
    :type m: Metadata
    '''
    # remove from package cache
    rm_pkgs_cache(m.dist())

    tmp_dir = join(config.croot, 'test-tmp_dir')
    rm_rf(tmp_dir)
    os.makedirs(tmp_dir)
    create_files(tmp_dir, m)
    # Make Perl or Python-specific test files
    if m.name().startswith('perl-'):
        pl_files = create_pl_files(tmp_dir, m)
        py_files = False
    else:
        py_files = create_py_files(tmp_dir, m)
        pl_files = False
    shell_files = create_shell_files(tmp_dir, m)
    if not (py_files or shell_files or pl_files):
        print("Nothing to test for:", m.dist())
        return

    print("TEST START:", m.dist())
    rm_rf(config.build_prefix)
    rm_rf(config.test_prefix)
    specs = ['%s %s %s' % (m.name(), m.version(), m.build_id())]

    if py_files:
        # as the tests are run by python, we need to specify it
        specs += ['python %s*' % environ.get_py_ver()]
    if pl_files:
        # as the tests are run by perl, we need to specify it
        specs += ['perl %s*' % environ.get_perl_ver()]
    # add packages listed in test/requires
    for spec in m.get_value('test/requires', []):
        specs.append(spec)

    create_env(config.test_prefix, specs, verbose=verbose)

    env = dict(os.environ)
    # TODO: Include all the same environment variables that are used in
    # building.
    env.update(environ.get_dict(m, prefix=config.test_prefix))

    # prepend bin (or Scripts) directory
    env['PATH'] = (join(config.test_prefix, bin_dirname) + os.pathsep +
                   env['PATH'])

    for varname in 'CONDA_PY', 'CONDA_NPY', 'CONDA_PERL':
        env[varname] = str(getattr(config, varname))
    env['PREFIX'] = config.test_prefix

    # Python 2 Windows requires that envs variables be string, not unicode
    env = {str(key): str(value) for key, value in env.items()}
    if py_files:
        try:
            subprocess.check_call([config.test_python, '-s',
                                   join(tmp_dir, 'run_test.py')],
                                  env=env, cwd=tmp_dir)
        except subprocess.CalledProcessError:
            tests_failed(m)

    if pl_files:
        try:
            subprocess.check_call([config.test_perl,
                                   join(tmp_dir, 'run_test.pl')],
                                  env=env, cwd=tmp_dir)
        except subprocess.CalledProcessError:
            tests_failed(m)

    if shell_files:
        if sys.platform == 'win32':
            test_file = join(tmp_dir, 'run_test.bat')
            cmd = [os.environ['COMSPEC'], '/c', test_file]
            try:
                subprocess.check_call(cmd, env=env, cwd=tmp_dir)
            except subprocess.CalledProcessError:
                tests_failed(m)
        else:
            test_file = join(tmp_dir, 'run_test.sh')
            # TODO: Run the test/commands here instead of in run_test.py
            cmd = ['/bin/bash', '-x', '-e', test_file]
            try:
                subprocess.check_call(cmd, env=env, cwd=tmp_dir)
            except subprocess.CalledProcessError:
                tests_failed(m)

    print("TEST END:", m.dist())

def tests_failed(m):
    '''
    Causes conda to exit if any of the given package's tests failed.

    :param m: Package's metadata
    :type m: Metadata
    '''
    ensure_dir(config.broken_dir)
    shutil.move(bldpkg_path(m), join(config.broken_dir, "%s.tar.bz2" % m.dist()))
    sys.exit("TESTS FAILED: " + m.dist())
