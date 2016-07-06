'''
Module that does most of the heavy lifting for the ``conda build`` command.
'''
from __future__ import absolute_import, division, print_function

from distutils.dir_util import copy_tree
import io
from glob import glob
import json
import logging
import os
import shutil
import stat
import subprocess
import sys
import time
import tarfile
import fnmatch
import tempfile
from os.path import exists, isdir, isfile, islink, join
import mmap

import conda.config as cc
import conda.plan as plan
from conda.api import get_index
from conda.compat import PY3, TemporaryDirectory
from conda.fetch import fetch_index
from conda.install import prefix_placeholder, linked, symlink_conda
from conda.lock import Locked
from conda.utils import url_path
from conda.resolve import Resolve, MatchSpec, NoPackagesFound

from conda_build import __version__
from conda_build import environ, source, tarcheck, external
from conda_build.config import config
from conda_build.render import parse_or_try_download, output_yaml, bldpkg_path
from conda_build.scripts import create_entry_points, prepend_bin_path
from conda_build.post import (post_process, post_build,
                              fix_permissions, get_build_metadata)
from conda_build.utils import rm_rf, _check_call
from conda_build.index import update_index
from conda_build.create_test import (create_files, create_shell_files,
                                     create_py_files, create_pl_files)
from conda_build.exceptions import indent
from conda_build.features import feature_list


on_win = (sys.platform == 'win32')
if 'bsd' in sys.platform:
    shell_path = '/bin/sh'
else:
    shell_path = '/bin/bash'

# these gloabls may be modified after importing this module
channel_urls = ()
override_channels = False
verbose = True

log = logging.getLogger(__file__)


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
    ext = '.bat' if on_win else '.sh'
    for tp in 'pre-link', 'post-link', 'pre-unlink':
        src = join(recipe_dir, tp + ext)
        if not isfile(src):
            continue
        dst_dir = join(config.build_prefix,
                       'Scripts' if on_win else 'bin')
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
    prefix_placeholder_bytes = prefix_placeholder.encode('utf-8')
    if on_win:
        forward_slash_prefix = prefix.replace('\\', '/')
        forward_slash_prefix_bytes = forward_slash_prefix.encode('utf-8')
        double_backslash_prefix = prefix.replace('\\', '\\\\')
        double_backslash_prefix_bytes = double_backslash_prefix.encode('utf-8')

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

        # dont try to mmap an empty file
        if os.stat(path).st_size == 0:
            continue

        fi = open(path, 'rb+')
        mm = mmap.mmap(fi.fileno(), 0)

        mode = 'binary' if mm.find(b'\x00') != -1 else 'text'
        if mode == 'text':
            if not on_win and mm.find(prefix_bytes) != -1:
                # Use the placeholder for maximal backwards compatibility, and
                # to minimize the occurrences of usernames appearing in built
                # packages.
                rewrite_file_with_new_prefix(path, mm[:], prefix_bytes, prefix_placeholder_bytes)
                mm.close() and fi.close()
                fi = open(path, 'rb+')
                mm = mmap.mmap(fi.fileno(), 0)
        if mm.find(prefix_bytes) != -1:
            yield (prefix, mode, f)
        if on_win and mm.find(forward_slash_prefix_bytes) != -1:
            # some windows libraries use unix-style path separators
            yield (forward_slash_prefix, mode, f)
        elif on_win and mm.find(double_backslash_prefix_bytes) != -1:
            # some windows libraries have double backslashes as escaping
            yield (double_backslash_prefix, mode, f)
        if mm.find(prefix_placeholder_bytes) != -1:
            yield (prefix_placeholder, mode, f)
        mm.close() and fi.close()


def rewrite_file_with_new_prefix(path, data, old_prefix, new_prefix):
    # Old and new prefix should be bytes

    st = os.stat(path)
    data = data.replace(old_prefix, new_prefix)
    # Save as
    with open(path, 'wb') as fo:
        fo.write(data)
    os.chmod(path, stat.S_IMODE(st.st_mode) | stat.S_IWUSR)  # chmod u+w
    return data


def get_run_dists(m):
    prefix = join(cc.envs_dirs[0], '_run')
    rm_rf(prefix)
    create_env(prefix, [ms.spec for ms in m.ms_depends('run')])
    return sorted(linked(prefix))


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
                copy_tree(src_path, dst_path)
            else:
                shutil.copy(src_path, dst_path)

        # store the rendered meta.yaml file, plus information about where it came from
        #    and what version of conda-build created it
        metayaml = output_yaml(m)
        with open(join(recipe_dir, "meta.yaml.rendered"), 'w') as f:
            f.write("# This file created by conda-build {}\n".format(__version__))
            f.write("# meta.yaml template originally from:\n")
            f.write("# " + source.get_repository_info(m.path) + "\n")
            f.write("# ------------------------------------------------\n\n")
            f.write(metayaml)

    license_file = m.get_value('about/license_file')
    if license_file:
        shutil.copyfile(join(source.get_dir(), license_file),
                        join(config.info_dir, 'LICENSE.txt'))

    readme = m.get_value('about/readme')
    if readme:
        src = join(source.get_dir(), readme)
        if not isfile(src):
            sys.exit("Error: no readme file: %s" % readme)
        dst = join(config.info_dir, readme)
        shutil.copyfile(src, dst)
        if os.path.split(readme)[1] not in {"README.md", "README.rst", "README"}:
            print("WARNING: anaconda.org only recognizes about/readme as README.md and README.rst", file=sys.stderr)  # noqa

    info_index = m.info_index()
    pin_depends = m.get_value('build/pin_depends')
    if pin_depends:
        dists = get_run_dists(m)
        with open(join(config.info_dir, 'requires'), 'w') as fo:
            fo.write("""\
# This file as created when building:
#
#     %s.tar.bz2  (on '%s')
#
# It can be used to create the runtime environment of this package using:
# $ conda create --name <env> --file <this file>
""" % (m.dist(), cc.subdir))
            for dist in sorted(dists + [m.dist()]):
                fo.write('%s\n' % '='.join(dist.rsplit('-', 2)))
        if pin_depends == 'strict':
            info_index['depends'] = [' '.join(dist.rsplit('-', 2))
                                     for dist in dists]

    # Deal with Python 2 and 3's different json module type reqs
    mode_dict = {'mode': 'w', 'encoding': 'utf-8'} if PY3 else {'mode': 'wb'}
    with open(join(config.info_dir, 'index.json'), **mode_dict) as fo:
        json.dump(info_index, fo, indent=2, sort_keys=True)

    with open(join(config.info_dir, 'about.json'), 'w') as fo:
        d = {}
        for key in ('home', 'dev_url', 'doc_url', 'license_url',
                    'license', 'summary', 'description', 'license_family'):
            value = m.get_value('about/%s' % key)
            if value:
                d[key] = value
        json.dump(d, fo, indent=2, sort_keys=True)

    if on_win:
        # make sure we use '/' path separators in metadata
        files = [_f.replace('\\', '/') for _f in files]

    with open(join(config.info_dir, 'files'), **mode_dict) as fo:
        if m.get_value('build/noarch_python'):
            fo.write('\n')
        else:
            for f in files:
                fo.write(f + '\n')

    files_with_prefix = sorted(have_prefix_files(files))
    binary_has_prefix_files = m.binary_has_prefix_files()
    text_has_prefix_files = m.has_prefix_files()

    ignore_files = m.ignore_prefix_files()
    if ignore_files:
        # do we have a list of files, or just ignore everything?
        if hasattr(ignore_files, "__iter__"):
            files_with_prefix = [f for f in files_with_prefix if f[2] not in ignore_files]
            binary_has_prefix_files = [f for f in binary_has_prefix_files if f[2] not in ignore_files]  # noqa
            text_has_prefix_files = [f for f in text_has_prefix_files if f[2] not in ignore_files]
        else:
            files_with_prefix = []

    if files_with_prefix and not m.get_value('build/noarch_python'):
        auto_detect = m.get_value('build/detect_binary_files_with_prefix')
        if on_win:
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


def get_build_index(clear_cache=True):
    if clear_cache:
        # remove the cache such that a refetch is made,
        # this is necessary because we add the local build repo URL
        fetch_index.cache = {}
    return get_index(channel_urls=[url_path(config.croot)] + list(channel_urls),
                     prepend=not override_channels)


def create_env(prefix, specs, clear_cache=True):
    '''
    Create a conda envrionment for the given prefix and specs.
    '''
    specs = list(specs)
    for feature, value in feature_list:
        if value:
            specs.append('%s@' % feature)

    for d in config.bldpkgs_dirs:
        if not isdir(d):
            os.makedirs(d)
        update_index(d)
    if specs:  # Don't waste time if there is nothing to do
        index = get_build_index(clear_cache=True)

        warn_on_old_conda_build(index)

        cc.pkgs_dirs = cc.pkgs_dirs[:1]
        actions = plan.install_actions(prefix, index, specs)
        plan.display_actions(actions, index)
        plan.execute_actions(actions, index, verbose=verbose)
    # ensure prefix exists, even if empty, i.e. when specs are empty
    if not isdir(prefix):
        os.makedirs(prefix)
    if on_win:
        shell = "cmd.exe"
    else:
        shell = "bash"
    symlink_conda(prefix, sys.prefix, shell)


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
        print("WARNING: Could not find any versions of conda-build in the channels", file=sys.stderr)  # noqa
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


def build(m, post=None, include_recipe=True, keep_old_work=False,
          need_source_download=True, verbose=True, dirty=False,
          activate=True):
    '''
    Build the package with the specified metadata.

    :param m: Package metadata
    :type m: Metadata
    :type post: bool or None. None means run the whole build. True means run
    post only. False means stop just before the post.
    :type keep_old_work: bool: Keep any previous work directory.
    :type need_source_download: bool: if rendering failed to download source
    (due to missing tools), retry here after build env is populated
    '''

    if (m.get_value('build/detect_binary_files_with_prefix') or
            m.binary_has_prefix_files()) and not on_win:
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

    with Locked(config.build_folder):

        if post in [False, None]:
            print("Removing old build environment")
            print("BUILD START:", m.dist())

            specs = [ms.spec for ms in m.ms_depends('build')]
            if activate:
                # If we activate the build envrionment, we need to be sure that we
                #    have the appropriate VCS available in the environment.  People
                #    are not used to explicitly listing it in recipes, though.
                #    We add it for them here, but warn them about it.
                vcs_source = m.uses_vcs_in_build()
                if vcs_source and vcs_source not in specs:
                    vcs_executable = "hg" if vcs_source == "mercurial" else vcs_source
                    has_vcs_available = os.path.isfile(external.find_executable(vcs_executable))
                    if not has_vcs_available:
                        if (vcs_source != "mercurial" or
                                not any(spec.startswith('python') and "3." in spec
                                        for spec in specs)):
                            specs.append(vcs_source)

                            log.warn("Your recipe depends on {} at build time (for templates), "
                                    "but you have not listed it as a build dependency.  Doing "
                                    "so for this build.")
                        else:
                            raise ValueError("Your recipe uses mercurial in build, but mercurial"
                                            " does not yet support Python 3.  Please handle all of "
                                            "your mercurial actions outside of your build script.")
            # Display the name only
            # Version number could be missing due to dependency on source info.
            create_env(config.build_prefix, specs)

            if need_source_download:
                # Execute any commands fetching the source (e.g., git) in the _build environment.
                # This makes it possible to provide source fetchers (eg. git, hg, svn) as build
                # dependencies.
                if not activate:
                    _old_path = os.environ['PATH']
                    os.environ['PATH'] = prepend_bin_path({'PATH': _old_path},
                                                          config.build_prefix)['PATH']
                try:
                    m, need_source_download = parse_or_try_download(m,
                                                                    no_download_source=False,
                                                                    force_download=True,
                                                                    verbose=verbose,
                                                                    dirty=dirty)
                    assert not need_source_download, "Source download failed.  Please investigate."
                finally:
                    if not activate:
                        os.environ['PATH'] = _old_path

            if m.name() in [i.rsplit('-', 2)[0] for i in linked(config.build_prefix)]:
                print("%s is installed as a build dependency. Removing." %
                    m.name())
                index = get_build_index(clear_cache=False)
                actions = plan.remove_actions(config.build_prefix, [m.name()], index=index)
                assert not plan.nothing_to_do(actions), actions
                plan.display_actions(actions, index)
                plan.execute_actions(actions, index)

            print("Package:", m.dist())

            assert isdir(config.work_dir)
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
                    sys.exit("Error: Glob %s from always_include_files does not match any files" %
                             pat)
            # Save this for later
            with open(join(config.croot, 'prefix_files.txt'), 'w') as f:
                f.write(u'\n'.join(sorted(list(files1))))
                f.write(u'\n')

            # Use script from recipe?
            script = m.get_value('build/script', None)
            if script:
                if isinstance(script, list):
                    script = '\n'.join(script)

            if on_win:
                build_file = join(m.path, 'bld.bat')
                if script:
                    build_file = join(source.get_dir(), 'bld.bat')
                    with open(join(source.get_dir(), 'bld.bat'), 'w') as bf:
                        bf.write(script)
                import conda_build.windows as windows
                windows.build(m, build_file, dirty=dirty, activate=activate)
            else:
                build_file = join(m.path, 'build.sh')

                # There is no sense in trying to run an empty build script.
                if isfile(build_file) or script:
                    env = environ.get_dict(m, dirty=dirty)
                    work_file = join(source.get_dir(), 'conda_build.sh')
                    if script:
                        with open(work_file, 'w') as bf:
                            bf.write(script)
                    if activate:
                        if isfile(build_file):
                            data = open(build_file).read()
                        else:
                            data = open(work_file).read()
                        with open(work_file, 'w') as bf:
                            bf.write("source activate {build_prefix}\n".format(
                                build_prefix=config.build_prefix))
                            bf.write(data)
                    else:
                        if not isfile(work_file):
                            shutil.copy(build_file, work_file)
                    os.chmod(work_file, 0o766)

                    if isfile(work_file):
                        cmd = [shell_path, '-x', '-e', work_file]

                        _check_call(cmd, env=env, cwd=src_dir)

        if post in [True, None]:
            if post:
                with open(join(config.croot, 'prefix_files.txt'), 'r') as f:
                    files1 = set(f.read().splitlines())

            get_build_metadata(m)
            create_post_scripts(m)
            create_entry_points(m.get_value('build/entry_points'))
            assert not exists(config.info_dir)
            files2 = prefix_files()

            post_process(sorted(files2 - files1),
                         preserve_egg_dir=bool(m.get_value('build/preserve_egg_dir')))

            # The post processing may have deleted some files (like easy-install.pth)
            files2 = prefix_files()
            if any(config.meta_dir in join(config.build_prefix, f) for f in
                    files2 - files1):
                meta_files = (tuple(f for f in files2 - files1 if config.meta_dir in
                        join(config.build_prefix, f)),)
                sys.exit(indent("""Error: Untracked file(s) %s found in conda-meta directory.
    This error usually comes from using conda in the build script.  Avoid doing this, as it
    can lead to packages that include their dependencies.""" % meta_files))
            post_build(m, sorted(files2 - files1))
            create_info_files(m, sorted(files2 - files1),
                            include_recipe=bool(m.path) and include_recipe)
            if m.get_value('build/noarch_python'):
                import conda_build.noarch_python as noarch_python
                noarch_python.transform(m, sorted(files2 - files1))

            files3 = prefix_files()
            fix_permissions(files3 - files1)

            path = bldpkg_path(m)

            # lock the output directory while we build this file
            # create the tarball in a temporary directory to minimize lock time
            with TemporaryDirectory() as tmp:
                tmp_path = os.path.join(tmp, os.path.basename(path))
                t = tarfile.open(tmp_path, 'w:bz2')

                def order(f):
                    # we don't care about empty files so send them back via 100000
                    fsize = os.stat(join(config.build_prefix, f)).st_size or 100000
                    # info/* records will be False == 0, others will be 1.
                    info_order = int(os.path.dirname(f) != 'info')
                    return info_order, fsize

                # add files in order of a) in info directory, b) increasing size so
                # we can access small manifest or json files without decompressing
                # possible large binary or data files
                for f in sorted(files3 - files1, key=order):
                    t.add(join(config.build_prefix, f), f)
                t.close()

                # we're done building, perform some checks
                tarcheck.check_all(tmp_path)

                # lock the packages folder while performing this operation, so that package and index are each safe
                with Locked(os.path.dirname(path)):
                    shutil.copy2(tmp_path, path)
                    update_index(config.bldpkgs_dir)

                print("BUILD END:", m.dist())
        else:
            print("STOPPING BUILD BEFORE POST:", m.dist())


def test(m, move_broken=True, activate=True):
    '''
    Execute any test scripts for the given package.

    :param m: Package's metadata.
    :type m: Metadata
    '''

    with Locked(config.build_folder):

        # remove from package cache
        rm_pkgs_cache(m.dist())

        tmp_dir = config.test_dir
        if not isdir(tmp_dir):
            os.makedirs(tmp_dir)
        create_files(tmp_dir, m)
        # Make Perl or Python-specific test files
        if m.name().startswith('perl-'):
            pl_files = create_pl_files(tmp_dir, m)
            py_files = False
            lua_files = False
        else:
            py_files = create_py_files(tmp_dir, m)
            pl_files = False
            lua_files = False
        shell_files = create_shell_files(tmp_dir, m)
        if not (py_files or shell_files or pl_files or lua_files):
            print("Nothing to test for:", m.dist())
            return

        print("TEST START:", m.dist())

        get_build_metadata(m)
        specs = ['%s %s %s' % (m.name(), m.version(), m.build_id())]

        # add packages listed in the run environment and test/requires
        specs.extend(ms.spec for ms in m.ms_depends('run'))
        specs += m.get_value('test/requires', [])

        if py_files:
            # as the tests are run by python, ensure that python is installed.
            # (If they already provided python as a run or test requirement,
            #  this won't hurt anything.)
            specs += ['python %s*' % environ.get_py_ver()]
        if pl_files:
            # as the tests are run by perl, we need to specify it
            specs += ['perl %s*' % environ.get_perl_ver()]
        if lua_files:
            # not sure how this shakes out
            specs += ['lua %s*' % environ.get_lua_ver()]

        create_env(config.test_prefix, specs)
        env = dict(os.environ)
        env.update(environ.get_dict(m, prefix=config.test_prefix))

        if not activate:
            # prepend bin (or Scripts) directory
            env = prepend_bin_path(env, config.test_prefix, prepend_prefix=True)

            if on_win:
                env['PATH'] = config.test_prefix + os.pathsep + env['PATH']

        for varname in 'CONDA_PY', 'CONDA_NPY', 'CONDA_PERL', 'CONDA_LUA':
            env[varname] = str(getattr(config, varname) or '')
        env['PREFIX'] = config.test_prefix

        # Python 2 Windows requires that envs variables be string, not unicode
        env = {str(key): str(value) for key, value in env.items()}
        suffix = "bat" if on_win else "sh"
        test_script = join(tmp_dir, "conda_test_runner.{suffix}".format(suffix=suffix))

        with open(test_script, 'w') as tf:
            if activate:
                source = "" if on_win else "source "
                tf.write("{source}activate {prefix}\n".format(source=source,
                                                              prefix=config.test_prefix))
            if py_files:
                tf.write("{python} -s {test_file}\n".format(
                    python=config.test_python,
                    test_file=join(tmp_dir, 'run_test.py')))

            if pl_files:
                tf.write("{perl} {test_file}\n".format(
                    python=config.test_perl,
                    test_file=join(tmp_dir, 'run_test.pl')))

            if lua_files:
                tf.write("{lua} {test_file}\n".format(
                    python=config.test_perl,
                    test_file=join(tmp_dir, 'run_test.lua')))

            if shell_files:
                test_file = join(tmp_dir, 'run_test.' + suffix)
                if on_win:
                    tf.write("call {test_file}\n".format(test_file=test_file))
                else:
                    # TODO: Run the test/commands here instead of in run_test.py
                    tf.write("{shell_path} -x -e {test_file}\n".format(shell_path=shell_path,
                                                                       test_file=test_file))
        if on_win:
            cmd = [env["COMSPEC"], "/d", "/c", test_script]
        else:
            cmd = [shell_path, '-x', '-e', test_script]
        try:
            subprocess.check_call(cmd, env=env, cwd=tmp_dir)
        except subprocess.CalledProcessError:
            tests_failed(m, move_broken=move_broken)

    print("TEST END:", m.dist())


def tests_failed(m, move_broken):
    '''
    Causes conda to exit if any of the given package's tests failed.

    :param m: Package's metadata
    :type m: Metadata
    '''
    if not isdir(config.broken_dir):
        os.makedirs(config.broken_dir)

    if move_broken:
        shutil.move(bldpkg_path(m), join(config.broken_dir, "%s.tar.bz2" % m.dist()))
    sys.exit("TESTS FAILED: " + m.dist())


def get_build_folders(croot=config.croot):
    # remember, glob is not a regex.
    return glob(os.path.join(croot, "*" + "[0-9]" * 6 + "*"))


def print_build_intermediate_warning():
    print("\n\n")
    print('#' * 80)
    print("Source and build intermediates have been left in " + config.croot + ".")
    build_folders = get_build_folders()
    print("There are currently {num_builds} accumulated.".format(num_builds=len(build_folders)))
    print("To remove them, you can run the ```conda build purge``` command")


def clean_build(folders=None):
    if not folders:
        folders = get_build_folders()
    for folder in folders:
        shutil.rmtree(folder)
