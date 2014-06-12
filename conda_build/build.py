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
import subprocess
import sys
import tarfile
from io import open
from os.path import exists, isdir, isfile, islink, join
import yaml


import conda.config as cc
import conda.plan as plan
from conda.api import get_index
from conda.compat import PY3
from conda.fetch import fetch_index
from conda.install import prefix_placeholder
from conda.utils import url_path

from conda_build import config, environ, source, tarcheck
from conda_build.scripts import create_entry_points, bin_dirname
from conda_build.post import (post_process, post_build, is_obj,
                              fix_permissions, get_build_metadata)
from conda_build.utils import rm_rf, _check_call
from conda_build.index import update_index
from conda_build.create_test import (create_files, create_shell_files,
                                     create_py_files, create_pl_files)


prefix = config.build_prefix
info_dir = join(prefix, 'info')

broken_dir = join(config.croot, "broken")


def prefix_files():
    '''
    Returns a set of all files in prefix.
    '''
    res = set()
    for root, dirs, files in os.walk(prefix):
        for fn in files:
            res.add(join(root, fn)[len(prefix) + 1:])
        for dn in dirs:
            path = join(root, dn)
            if islink(path):
                res.add(path[len(prefix) + 1:])
    return res


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
        dst_dir = join(prefix,
                       'Scripts' if sys.platform == 'win32' else 'bin')
        if not isdir(dst_dir):
            os.makedirs(dst_dir, int('755', 8))
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
    for f in files:
        if f.endswith(('.pyc', '.pyo', '.a', '.dylib')):
            continue
        path = join(prefix, f)
        if isdir(path):
            continue
        if sys.platform != 'darwin' and islink(path):
            # OSX does not allow hard-linking symbolic links, so we cannot
            # skip symbolic links (as we can on Linux)
            continue
        if is_obj(path):
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
        prefix_bytes = prefix.encode('utf-8')
        if prefix_bytes not in data:
            continue
        st = os.stat(path)
        data = data.replace(prefix_bytes, prefix_placeholder.encode('utf-8'))
        # Save as
        with open(path, 'wb') as fo:
            fo.write(data)
        os.chmod(path, stat.S_IMODE(st.st_mode) | stat.S_IWUSR) # chmod u+w
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
    recipe_dir = join(info_dir, 'recipe')
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

    with open(join(info_dir, 'files'), 'w', encoding='utf-8') as fo:
        for f in files:
            if sys.platform == 'win32':
                f = f.replace('\\', '/')
            fo.write(f + '\n')

    # Deal with Python 2 and 3's different json module type reqs
    mode_dict = {'mode': 'w', 'encoding': 'utf-8'} if PY3 else {'mode': 'wb'}
    with open(join(info_dir, 'index.json'), **mode_dict) as fo:
        json.dump(m.info_index(), fo, indent=2, sort_keys=True)

    with open(join(info_dir, 'recipe.json'), **mode_dict) as fo:
        json.dump(m.meta, fo, indent=2, sort_keys=True)

    files_with_prefix = m.has_prefix_files()
    for file in files_with_prefix:
        if file not in files:
            raise RuntimeError("file %s from build/has_prefix_files was "
                               "not found" % file)
    if sys.platform != 'win32':
        files_with_prefix += list(have_prefix_files(files))
    files_with_prefix = sorted(set(files_with_prefix))
    if files_with_prefix:
        with open(join(info_dir, 'has_prefix'), 'w', encoding='utf-8') as fo:
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
        with open(join(info_dir, 'no_link'), 'w', encoding='utf-8') as fo:
            for f in files:
                if pat.match(f):
                    fo.write(f + '\n')

    if m.get_value('source/git_url'):
        with open(join(info_dir, 'git'), 'w', encoding='utf-8') as fo:
            source.git_info(fo)

    if m.get_value('app/icon'):
        shutil.copyfile(join(m.path, m.get_value('app/icon')),
                        join(info_dir, 'icon.png'))


def create_env(pref, specs, clear_cache=True, verbose=True):
    '''
    Create a conda envrionment for the given prefix and specs.
    '''
    if not isdir(config.bldpkgs_dir):
        os.makedirs(config.bldpkgs_dir)
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
    if not isdir(pref):
        os.makedirs(pref)

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
        rm_rf(prefix)

        print("BUILD START:", m.dist())
        create_env(prefix, [ms.spec for ms in m.ms_depends('build')],
                   verbose=verbose)

        if get_src:
            source.provide(m.path, m.get_section('source'))
        assert isdir(source.WORK_DIR)
        src_dir = source.get_dir()
        contents = os.listdir(src_dir)
        if contents:
            print("source tree in:", src_dir)
        else:
            print("no source")

        rm_rf(info_dir)
        files1 = prefix_files()
        if post == False:
            # Save this for later
            with open(join(source.WORK_DIR, 'prefix_files.txt'), 'w') as f:
                f.write(u'\n'.join(sorted(list(files1))))
                f.write(u'\n')

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
        if post == True:
            with open(join(source.WORK_DIR, 'prefix_files.txt'), 'r') as f:
                files1 = set(f.read().splitlines())

        get_build_metadata(m)
        create_post_scripts(m)
        create_entry_points(m.get_value('build/entry_points'))
        post_process(preserve_egg_dir=bool(m.get_value('build/preserve_egg_dir')))

        assert not exists(info_dir)
        files2 = prefix_files()

        post_build(sorted(files2 - files1),
              binary_relocation=bool(m.get_value('build/binary_relocation', True)))
        create_info_files(m, sorted(files2 - files1), include_recipe=bool(m.path))
        files3 = prefix_files()
        fix_permissions(files3 - files1)

        path = bldpkg_path(m)
        t = tarfile.open(path, 'w:bz2')
        for f in sorted(files3 - files1):
            t.add(join(prefix, f), f)
        t.close()

        print("BUILD END:", m.dist())

        # we're done building, perform some checks
        tarcheck.check_all(path)
        update_index(config.bldpkgs_dir)
    else:
        print("STOPPING BUILD BEFORE POST:", m.dist())


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
    rm_rf(prefix)
    rm_rf(config.test_prefix)
    specs = ['%s %s %s' % (m.name(), m.version(), m.build_id())]

    if py_files:
        # as the tests are run by python, we need to specify it
        specs += ['python %s*' % environ.PY_VER]
    if pl_files:
        # as the tests are run by perl, we need to specify it
        specs += ['perl %s*' % environ.PERL_VER]
    # add packages listed in test/requires
    for spec in m.get_value('test/requires'):
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
            subprocess.check_call([config.test_python,
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
    if not isdir(broken_dir):
        os.makedirs(broken_dir)

    shutil.move(bldpkg_path(m), join(broken_dir, "%s.tar.bz2" % m.dist()))
    sys.exit("TESTS FAILED: " + m.dist())
