'''
Module that does most of the heavy lifting for the ``conda build`` command.
'''
from __future__ import absolute_import, division, print_function

import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import fnmatch
from os.path import exists, isdir, isfile, islink, join

import conda.config as cc
import conda.plan as plan
from conda.api import get_index
from conda.compat import PY3
from conda.fetch import fetch_index
from conda.install import prefix_placeholder, linked, move_to_trash
from conda.utils import url_path
from conda.resolve import Resolve, MatchSpec, NoPackagesFound

from conda_build import environ, source, tarcheck
from conda_build.config import config
from conda_build.scripts import create_entry_points, prepend_bin_path
from conda_build.post import (post_process, post_build,
                              fix_permissions, get_build_metadata)
from conda_build.utils import rm_rf, _check_call, comma_join
from conda_build.index import update_index
from conda_build.create_test import (create_files, create_shell_files,
                                     create_py_files, create_pl_files)
from conda_build.exceptions import indent


on_win = (sys.platform == 'win32')


def prefix_files():
    '''
    Returns a set of all files in prefix.
    '''
    res = set()
    for root, dirs, files in os.walk(config.build_prefix):
        for fn in files:
            res.add(join(root, fn)[len(config.build_prefix) + 1:])
        for dn in dirs:
            path = join(root, dn)
            if islink(path):
                res.add(path[len(config.build_prefix) + 1:])
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
        dst_dir = join(config.build_prefix,
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
    :type files: list of tuples containing strings (prefix, mode, filename)
    '''
    prefix = config.build_prefix
    prefix_bytes = prefix.encode('utf-8')
    alt_prefix = prefix.replace('\\', '/')
    alt_prefix_bytes = alt_prefix.encode('utf-8')
    prefix_placeholder_bytes = prefix_placeholder.encode('utf-8')
    for f in files:
        if f.endswith(('.pyc', '.pyo', '.a')):
            continue
        path = join(prefix, f)
        if isdir(path):
            continue
        if sys.platform != 'darwin' and islink(path):
            # OSX does not allow hard-linking symbolic links, so we cannot
            # skip symbolic links (as we can on Linux)
            continue
        with open(path, 'rb') as fi:
            data = fi.read()
        mode = 'binary' if b'\x00' in data else 'text'
        if mode == 'text':
            if not (sys.platform == 'win32' and alt_prefix_bytes in data):
                # Use the placeholder for maximal backwards compatibility, and
                # to minimize the occurrences of usernames appearing in built
                # packages.
                data = rewrite_file_with_new_prefix(path, data, prefix_bytes, prefix_placeholder_bytes)

        if prefix_bytes in data:
            yield (prefix, mode, f)
        if (sys.platform == 'win32') and (alt_prefix_bytes in data):
            # some windows libraries use unix-style path separators
            yield (alt_prefix, mode, f)
        if prefix_placeholder_bytes in data:
            yield (prefix_placeholder, mode, f)


def rewrite_file_with_new_prefix(path, data, old_prefix, new_prefix):
    # Old and new prefix should be bytes
    data = data.replace(old_prefix, new_prefix)

    st = os.stat(path)
    # Save as
    with open(path, 'wb') as fo:
        fo.write(data)
    os.chmod(path, stat.S_IMODE(st.st_mode) | stat.S_IWUSR) # chmod u+w
    return data

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
    if not isdir(config.info_dir):
        os.makedirs(config.info_dir)

    if include_recipe:
        recipe_dir = join(config.info_dir, 'recipe')
        os.makedirs(recipe_dir)

        for fn in os.listdir(m.path):
            if fn.startswith('.'):
                continue
            src_path = join(m.path, fn)
            dst_path = join(recipe_dir, fn)
            if isdir(src_path):
                shutil.copytree(src_path, dst_path)
            else:
                shutil.copy(src_path, dst_path)

    license_file = m.get_value('about/license_file')
    if license_file:
        filenames = 'LICENSE', 'LICENSE.txt', 'license', 'license.txt'
        if license_file is True:
            for fn in filenames:
                src = join(source.get_dir(), fn)
                if isfile(src):
                    break
            else:
                sys.exit("Error: could not locate license file (any of "
                         "%s) in: %s" % (comma_join(filenames),
                                         source.get_dir()))
        else:
            src = join(source.get_dir(), license_file)
        shutil.copy(src, join(config.info_dir, 'license.txt'))

    readme = m.get_value('about/readme')
    if readme:
        src = join(source.get_dir(), readme)
        if not isfile(src):
            sys.exit("Error: no readme file: %s" % readme)
        dst = join(config.info_dir, readme)
        shutil.copy(src, dst)
        if os.path.split(readme)[1] not in {"README.md", "README.rst", "README"}:
            print("WARNING: anaconda.org only recognizes about/readme as README.md and README.rst",
                  file=sys.stderr)

    # Deal with Python 2 and 3's different json module type reqs
    mode_dict = {'mode': 'w', 'encoding': 'utf-8'} if PY3 else {'mode': 'wb'}
    with open(join(config.info_dir, 'index.json'), **mode_dict) as fo:
        json.dump(m.info_index(), fo, indent=2, sort_keys=True)

    if include_recipe:
        with open(join(config.info_dir, 'recipe.json'), **mode_dict) as fo:
            json.dump(m.meta, fo, indent=2, sort_keys=True)

    if sys.platform == 'win32':
        # make sure we use '/' path separators in metadata
        files = [f.replace('\\', '/') for f in files]

    with open(join(config.info_dir, 'files'), 'w') as fo:
        if m.get_value('build/noarch_python'):
            fo.write('\n')
        else:
            for f in files:
                fo.write(f + '\n')

    files_with_prefix = sorted(have_prefix_files(files))
    binary_has_prefix_files = m.binary_has_prefix_files()
    text_has_prefix_files = m.has_prefix_files()
    if files_with_prefix and not m.get_value('build/noarch_python'):
        auto_detect = m.get_value('build/detect_binary_files_with_prefix')
        if sys.platform == 'win32':
            # Paths on Windows can contain spaces, so we need to quote the
            # paths. Fortunately they can't contain quotes, so we don't have
            # to worry about nested quotes.
            fmt_str = '"%s" %s "%s"\n'
        else:
            # Don't do it everywhere because paths on Unix can contain quotes,
            # and we don't have a good method of escaping, and because older
            # versions of conda don't support quotes in has_prefix
            fmt_str = '%s %s %s\n'
        with open(join(config.info_dir, 'has_prefix'), 'w') as fo:
            for pfix, mode, fn in files_with_prefix:
                if (fn in text_has_prefix_files):
                    # register for text replacement, regardless of mode
                    fo.write(fmt_str % (pfix, 'text', fn))
                    text_has_prefix_files.remove(fn)
                elif ((mode == 'binary') and (fn in binary_has_prefix_files)):
                    print("Detected hard-coded path in binary file %s" % fn)
                    fo.write(fmt_str % (pfix, mode, fn))
                    binary_has_prefix_files.remove(fn)
                elif (auto_detect or (mode == 'text')):
                    print("Detected hard-coded path in %s file %s" % (mode, fn))
                    fo.write(fmt_str % (pfix, mode, fn))
                else:
                    print("Ignored hard-coded path in %s" % fn)

    # make sure we found all of the files expected
    errstr = ""
    for f in text_has_prefix_files:
        errstr += "Did not detect hard-coded path in %s from has_prefix_files\n" % f
    for f in binary_has_prefix_files:
        errstr += "Did not detect hard-coded path in %s from binary_has_prefix_files\n" % f
    if errstr:
        raise RuntimeError(errstr)

    no_link = m.get_value('build/no_link')
    if no_link:
        if not isinstance(no_link, list):
            no_link = [no_link]
        with open(join(config.info_dir, 'no_link'), 'w') as fo:
            for f in files:
                if any(fnmatch.fnmatch(f, p) for p in no_link):
                    fo.write(f + '\n')

    if m.get_value('source/git_url'):
        with io.open(join(config.info_dir, 'git'), 'w', encoding='utf-8') as fo:
            source.git_info(fo)

    if m.get_value('app/icon'):
        shutil.copyfile(join(m.path, m.get_value('app/icon')),
                        join(config.info_dir, 'icon.png'))

def get_build_index(clear_cache=True, channel_urls=(), override_channels=False):
    if clear_cache:
        # remove the cache such that a refetch is made,
        # this is necessary because we add the local build repo URL
        fetch_index.cache = {}
    return get_index(channel_urls=[url_path(config.croot)] + list(channel_urls),
        prepend=not override_channels)

def create_env(prefix, specs, clear_cache=True, verbose=True, channel_urls=(),
    override_channels=False):
    '''
    Create a conda envrionment for the given prefix and specs.
    '''
    if not isdir(config.bldpkgs_dir):
        os.makedirs(config.bldpkgs_dir)
    update_index(config.bldpkgs_dir)
    if specs: # Don't waste time if there is nothing to do
        index = get_build_index(clear_cache=True, channel_urls=channel_urls,
            override_channels=override_channels)

        warn_on_old_conda_build(index)

        cc.pkgs_dirs = cc.pkgs_dirs[:1]
        actions = plan.install_actions(prefix, index, specs)
        plan.display_actions(actions, index)
        plan.execute_actions(actions, index, verbose=verbose)
    # ensure prefix exists, even if empty, i.e. when specs are empty
    if not isdir(prefix):
        os.makedirs(prefix)

def warn_on_old_conda_build(index):
    root_linked = linked(cc.root_dir)
    vers_inst = [dist.rsplit('-', 2)[1] for dist in root_linked
        if dist.rsplit('-', 2)[0] == 'conda-build']
    if not len(vers_inst) == 1:
        print("WARNING: Could not detect installed version of conda-build", file=sys.stderr)
        return
    r = Resolve(index)
    try:
        pkgs = sorted(r.get_pkgs(MatchSpec('conda-build')))
    except NoPackagesFound:
        print("WARNING: Could not find any versions of conda-build in the channels", file=sys.stderr)
        return
    if pkgs[-1].version != vers_inst[0]:
        print("""
WARNING: conda-build appears to be out of date. You have version %s but the
latest version is %s. Run

conda update -n root conda-build

to get the latest version.
""" % (vers_inst[0], pkgs[-1].version), file=sys.stderr)



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

def build(m, get_src=True, verbose=True, post=None, channel_urls=(),
    override_channels=False, include_recipe=True):
    '''
    Build the package with the specified metadata.

    :param m: Package metadata
    :type m: Metadata
    :param get_src: Should we download the source?
    :type get_src: bool
    :type post: bool or None. None means run the whole build. True means run
    post only. False means stop just before the post.
    '''

    if (m.get_value('build/detect_binary_files_with_prefix')
        or m.binary_has_prefix_files()):
        # We must use a long prefix here as the package will only be
        # installable into prefixes shorter than this one.
        config.use_long_build_prefix = True
    else:
        # In case there are multiple builds in the same process
        config.use_long_build_prefix = False

    if m.skip():
        print("Skipped: The %s recipe defines build/skip for this "
              "configuration." % m.dist())
        return

    if post in [False, None]:
        print("Removing old build environment")
        if on_win:
            if isdir(config.short_build_prefix):
                move_to_trash(config.short_build_prefix, '')
            if isdir(config.long_build_prefix):
                move_to_trash(config.long_build_prefix, '')
        else:
            rm_rf(config.short_build_prefix)
            rm_rf(config.long_build_prefix)
        print("Removing old work directory")
        if on_win:
            if isdir(source.WORK_DIR):
                move_to_trash(source.WORK_DIR, '')
        else:
            rm_rf(source.WORK_DIR)

        # Display the name only
        # Version number could be missing due to dependency on source info.
        print("BUILD START:", m.dist())
        create_env(config.build_prefix,
            [ms.spec for ms in m.ms_depends('build')],
            verbose=verbose, channel_urls=channel_urls,
            override_channels=override_channels)

        if m.name() in [i.rsplit('-', 2)[0] for i in linked(config.build_prefix)]:
            print("%s is installed as a build dependency. Removing." %
                m.name())
            index = get_build_index(clear_cache=False, channel_urls=channel_urls, override_channels=override_channels)
            actions = plan.remove_actions(config.build_prefix, [m.name()], index=index)
            assert not plan.nothing_to_do(actions), actions
            plan.display_actions(actions, index)
            plan.execute_actions(actions, index)

        if get_src:
            source.provide(m.path, m.get_section('source'))

        # Parse our metadata again because we did not initialize the source
        # information before.
        # By now, all jinja variables should be defined, so don't permit undefined vars.
        m.parse_again(permit_undefined_jinja=False)

        print("Package:", m.dist())

        assert isdir(source.WORK_DIR)
        src_dir = source.get_dir()
        contents = os.listdir(src_dir)
        if contents:
            print("source tree in:", src_dir)
        else:
            print("no source")

        rm_rf(config.info_dir)
        files1 = prefix_files()
        for pat in m.always_include_files():
            has_matches = False
            for f in set(files1):
                if fnmatch.fnmatch(f, pat):
                    print("Including in package existing file", f)
                    files1.discard(f)
                    has_matches = True
            if not has_matches:
                sys.exit("Error: Glob %s from always_include_files does not match any files" % pat)
        # Save this for later
        with open(join(config.croot, 'prefix_files.txt'), 'w') as f:
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
                build_file = join(source.get_dir(), 'conda_build.sh')
                with open(build_file, 'w') as bf:
                    bf.write(script)
                os.chmod(build_file, 0o766)

            if isfile(build_file):
                cmd = ['/bin/sh', '-x', '-e', build_file]

                _check_call(cmd, env=env, cwd=src_dir)

    if post in [True, None]:
        if post == True:
            with open(join(config.croot, 'prefix_files.txt'), 'r') as f:
                files1 = set(f.read().splitlines())

        get_build_metadata(m)
        create_post_scripts(m)
        create_entry_points(m.get_value('build/entry_points'))
        assert not exists(config.info_dir)
        files2 = prefix_files()

        post_process(sorted(files2 - files1), preserve_egg_dir=bool(m.get_value('build/preserve_egg_dir')))

        # The post processing may have deleted some files (like easy-install.pth)
        files2 = prefix_files()
        if any(config.meta_dir in join(config.build_prefix, f) for f in
            files2 - files1):
            sys.exit(indent("""Error: Untracked file(s) %s found in conda-meta directory.  This error
usually comes from using conda in the build script.  Avoid doing this, as it
can lead to packages that include their dependencies.""" %
                (tuple(f for f in files2 - files1 if config.meta_dir in
                    join(config.build_prefix, f)),)))
        post_build(m, sorted(files2 - files1))
        create_info_files(m, sorted(files2 - files1),
                          include_recipe=bool(m.path) and include_recipe)
        if m.get_value('build/noarch_python'):
            import conda_build.noarch_python as noarch_python
            noarch_python.transform(m, sorted(files2 - files1))

        files3 = prefix_files()
        fix_permissions(files3 - files1)

        path = bldpkg_path(m)
        t = tarfile.open(path, 'w:bz2')
        for f in sorted(files3 - files1):
            t.add(join(config.build_prefix, f), f)
        t.close()

        print("BUILD END:", m.dist())

        # we're done building, perform some checks
        tarcheck.check_all(path)
        update_index(config.bldpkgs_dir)
    else:
        print("STOPPING BUILD BEFORE POST:", m.dist())


def test(m, verbose=True, channel_urls=(), override_channels=False):
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
    if on_win:
        if isdir(config.build_prefix):
            move_to_trash(config.build_prefix, '')
        if isdir(config.test_prefix):
            move_to_trash(config.test_prefix, '')
    else:
        rm_rf(config.build_prefix)
        rm_rf(config.test_prefix)
    specs = ['%s %s %s' % (m.name(), m.version(), m.build_id())]

    # add packages listed in test/requires
    specs += m.get_value('test/requires', [])

    if py_files:
        # as the tests are run by python, ensure that python is installed.
        # (If they already provided python as a run or test requirement, this won't hurt anything.)
        specs += ['python %s*' % environ.get_py_ver()]
    if pl_files:
        # as the tests are run by perl, we need to specify it
        specs += ['perl %s*' % environ.get_perl_ver()]

    create_env(config.test_prefix, specs, verbose=verbose,
        channel_urls=channel_urls, override_channels=override_channels)

    env = dict(os.environ)
    env.update(environ.get_dict(m, prefix=config.test_prefix))

    # prepend bin (or Scripts) directory
    env = prepend_bin_path(env, config.test_prefix, prepend_prefix=True)

    if sys.platform == 'win32':
        env['PATH'] = config.test_prefix + os.pathsep + env['PATH']
    for varname in 'CONDA_PY', 'CONDA_NPY', 'CONDA_PERL':
        env[varname] = str(getattr(config, varname) or '')
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
            cmd = [os.environ['COMSPEC'], '/c', 'call', test_file]
            try:
                subprocess.check_call(cmd, env=env, cwd=tmp_dir)
            except subprocess.CalledProcessError:
                tests_failed(m)
        else:
            test_file = join(tmp_dir, 'run_test.sh')
            # TODO: Run the test/commands here instead of in run_test.py
            cmd = ['/bin/sh', '-x', '-e', test_file]
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
    if not isdir(config.broken_dir):
        os.makedirs(config.broken_dir)

    shutil.move(bldpkg_path(m), join(config.broken_dir, "%s.tar.bz2" % m.dist()))
    sys.exit("TESTS FAILED: " + m.dist())
