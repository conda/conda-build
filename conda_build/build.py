'''
Module that does most of the heavy lifting for the ``conda build`` command.
'''
from __future__ import absolute_import, division, print_function

from collections import deque
import io
import fnmatch
from glob import glob
import json
import logging
import mmap
import os
from os.path import exists, isdir, isfile, islink, join
import shutil
import stat
import subprocess
import sys
import tarfile

# this one is some strange error that requests raises: "LookupError: unknown encoding: idna"
#    http://stackoverflow.com/a/13057751/1170370
import encodings.idna  # noqa

import filelock

import conda.config as cc
import conda.plan as plan
from conda.api import get_index
from conda.compat import PY3, TemporaryDirectory
from conda.fetch import fetch_index
from conda.install import prefix_placeholder, linked, symlink_conda
from conda.utils import url_path
from conda.resolve import Resolve, MatchSpec, NoPackagesFound, Unsatisfiable

from conda_build import __version__
from conda_build import environ, source, tarcheck
from conda_build.render import (parse_or_try_download, output_yaml, bldpkg_path,
                                render_recipe, reparse)
import conda_build.os_utils.external as external
from conda_build.post import (post_process, post_build,
                              fix_permissions, get_build_metadata)
from conda_build.scripts import create_entry_points, prepend_bin_path
from conda_build.utils import rm_rf, _check_call, copy_into, on_win, get_build_folders
from conda_build.index import update_index
from conda_build.create_test import (create_files, create_shell_files,
                                     create_py_files, create_pl_files)
from conda_build.exceptions import indent
from conda_build.features import feature_list

# this is to compensate for a requests idna encoding error.  Conda is a better place to fix,
#    eventually.
import encodings.idna  # NOQA

if 'bsd' in sys.platform:
    shell_path = '/bin/sh'
else:
    shell_path = '/bin/bash'

log = logging.getLogger(__file__)


def prefix_files(prefix):
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


def create_post_scripts(m, config):
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
        copy_into(src, dst, config)
        os.chmod(dst, int('755', 8))


def have_prefix_files(files, prefix):
    '''
    Yields files that contain the current prefix in them, and modifies them
    to replace the prefix with a placeholder.

    :param files: Filenames to check for instances of prefix
    :type files: list of tuples containing strings (prefix, mode, filename)
    '''
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


def get_run_dists(m, config):
    prefix = join(cc.envs_dirs[0], '_run')
    rm_rf(prefix)
    create_env(prefix, [ms.spec for ms in m.ms_depends('run')], config=config)
    return sorted(linked(prefix))


def create_info_files(m, files, config, prefix):
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
    if config.include_recipe and m.include_recipe() and bool(m.path):
        recipe_dir = join(config.info_dir, 'recipe')
        os.makedirs(recipe_dir)

        for fn in os.listdir(m.path):
            if fn.startswith('.'):
                continue
            src_path = join(m.path, fn)
            dst_path = join(recipe_dir, fn)
            copy_into(src_path, dst_path, config=config)

        # store the rendered meta.yaml file, plus information about where it came from
        #    and what version of conda-build created it
        original_recipe = os.path.join(m.path, 'meta.yaml')
        rendered = output_yaml(m)
        if not open(original_recipe).read() == rendered:
            with open(join(recipe_dir, "meta.yaml"), 'w') as f:
                f.write("# This file created by conda-build {}\n".format(__version__))
                f.write("# meta.yaml template originally from:\n")
                f.write("# " + source.get_repository_info(m.path) + "\n")
                f.write("# ------------------------------------------------\n\n")
                f.write(rendered)
            copy_into(original_recipe, os.path.join(recipe_dir, 'meta.yaml.template'),
                      config=config)

    license_file = m.get_value('about/license_file')
    if license_file:
        copy_into(join(source.get_dir(config), license_file),
                        join(config.info_dir, 'LICENSE.txt'), config)

    readme = m.get_value('about/readme')
    if readme:
        src = join(config.work_dir, readme)
        if not isfile(src):
            sys.exit("Error: no readme file: %s" % readme)
        dst = join(config.info_dir, readme)
        copy_into(src, dst, config)
        if os.path.split(readme)[1] not in {"README.md", "README.rst", "README"}:
            print("WARNING: anaconda.org only recognizes about/readme "
                  "as README.md and README.rst", file=sys.stderr)

    info_index = m.info_index()
    pin_depends = m.get_value('build/pin_depends')
    if pin_depends:
        dists = get_run_dists(m, config=config)
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
                fo.write('%s\n' % '='.join(dist.split('::', 1)[-1].rsplit('-', 2)))
        if pin_depends == 'strict':
            info_index['depends'] = [' '.join(dist.split('::', 1)[-1].rsplit('-', 2))
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

    files_with_prefix = sorted(have_prefix_files(files, prefix))
    binary_has_prefix_files = m.binary_has_prefix_files()
    text_has_prefix_files = m.has_prefix_files()

    ignore_files = m.ignore_prefix_files()
    if ignore_files:
        # do we have a list of files, or just ignore everything?
        if hasattr(ignore_files, "__iter__"):
            files_with_prefix = [f for f in files_with_prefix if f[2] not in ignore_files]
        else:
            files_with_prefix = []

    if files_with_prefix and not m.get_value('build/noarch_python'):
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
                print("Detected hard-coded path in %s file %s" % (mode, fn))
                fo.write(fmt_str % (pfix, mode, fn))

                if mode == 'binary' and fn in binary_has_prefix_files:
                    binary_has_prefix_files.remove(fn)
                elif mode == 'text' and fn in text_has_prefix_files:
                    text_has_prefix_files.remove(fn)

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
            source.git_info(config, fo)

    if m.get_value('app/icon'):
        copy_into(join(m.path, m.get_value('app/icon')),
                        join(config.info_dir, 'icon.png'),
                  config)


def get_build_index(config, clear_cache=True, arg_channels=None):
    if clear_cache:
        # remove the cache such that a refetch is made,
        # this is necessary because we add the local build repo URL
        fetch_index.cache = {}
    arg_channels = [] if not arg_channels else arg_channels
    # priority: local by croot (can vary), then channels passed as args,
    #     then channels from config.
    return get_index(channel_urls=[url_path(config.croot)] +
                     arg_channels +
                     list(config.channel_urls),
                     prepend=not config.override_channels,
                     # do not use local because we have that above with config.croot
                     use_local=False)


def create_env(prefix, specs, config, clear_cache=True):
    '''
    Create a conda envrionment for the given prefix and specs.
    '''
    if config.debug:
        logging.getLogger("conda").setLevel(logging.DEBUG)
        logging.getLogger("binstar").setLevel(logging.DEBUG)
        logging.getLogger("install").setLevel(logging.DEBUG)
        logging.getLogger("conda.install").setLevel(logging.DEBUG)
        logging.getLogger("fetch").setLevel(logging.DEBUG)
        logging.getLogger("print").setLevel(logging.DEBUG)
        logging.getLogger("progress").setLevel(logging.DEBUG)
        logging.getLogger("dotupdate").setLevel(logging.DEBUG)
        logging.getLogger("stdoutlog").setLevel(logging.DEBUG)
        logging.getLogger("requests").setLevel(logging.DEBUG)
    else:
        # This squelches a ton of conda output that is not hugely relevant
        logging.getLogger("conda").setLevel(logging.WARN)
        logging.getLogger("binstar").setLevel(logging.WARN)
        logging.getLogger("install").setLevel(logging.ERROR)
        logging.getLogger("conda.install").setLevel(logging.ERROR)
        logging.getLogger("fetch").setLevel(logging.WARN)
        logging.getLogger("print").setLevel(logging.WARN)
        logging.getLogger("progress").setLevel(logging.WARN)
        logging.getLogger("dotupdate").setLevel(logging.WARN)
        logging.getLogger("stdoutlog").setLevel(logging.WARN)
        logging.getLogger("requests").setLevel(logging.WARN)

    specs = list(specs)
    for feature, value in feature_list:
        if value:
            specs.append('%s@' % feature)

    for d in config.bldpkgs_dirs:
        if not isdir(d):
            os.makedirs(d)
        update_index(d, config)
    if specs:  # Don't waste time if there is nothing to do
        # FIXME: stupid hack to put prefix on PATH so that runtime libs can be found
        old_path = os.environ['PATH']
        os.environ['PATH'] = prepend_bin_path(os.environ.copy(), prefix, True)['PATH']

        index = get_build_index(config=config, clear_cache=True)

        warn_on_old_conda_build(index)

        cc.pkgs_dirs = cc.pkgs_dirs[:1]
        actions = plan.install_actions(prefix, index, specs)
        plan.display_actions(actions, index)
        # lock each pkg folder from specs
        locks = []
        for link_pkg in actions['LINK']:
            pkg = link_pkg.split(" ")[0]
            dirname = os.path.join(cc.root_dir, 'pkgs', pkg)
            if os.path.isdir(dirname):
                locks.append(filelock.SoftFileLock(os.path.join(dirname, ".conda_lock"),
                                                   timeout=config.timeout))
        try:
            for lock in locks:
                lock.acquire(timeout=config.timeout)
            plan.execute_actions(actions, index, verbose=config.debug)
        except:
            raise
        finally:
            for lock in locks:
                lock.release()

        os.environ['PATH'] = old_path

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
    vers_inst = [dist.split('::', 1)[-1].rsplit('-', 2)[1] for dist in root_linked
        if dist.split('::', 1)[-1].rsplit('-', 2)[0] == 'conda-build']
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


def build(m, config, post=None, need_source_download=True, need_reparse_in_env=False):
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
        return False

    if post in [False, None]:
        print("Removing old build environment")
        print("BUILD START:", m.dist())
        if m.uses_jinja and (need_source_download or need_reparse_in_env):
            print("    (actual version deferred until further download or env creation)")

        specs = [ms.spec for ms in m.ms_depends('build')]
        if config.activate:
            # If we activate the build envrionment, we need to be sure that we
            #    have the appropriate VCS available in the environment.  People
            #    are not used to explicitly listing it in recipes, though.
            #    We add it for them here, but warn them about it.
            vcs_source = m.uses_vcs_in_build
            if vcs_source and vcs_source not in specs:
                vcs_executable = "hg" if vcs_source == "mercurial" else vcs_source
                has_vcs_available = os.path.isfile(external.find_executable(vcs_executable,
                                                                    config.build_prefix) or "")
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
        create_env(config.build_prefix, specs, config=config)

        if need_source_download:
            # Execute any commands fetching the source (e.g., git) in the _build environment.
            # This makes it possible to provide source fetchers (eg. git, hg, svn) as build
            # dependencies.
            if not config.activate:
                _old_path = os.environ['PATH']
                os.environ['PATH'] = prepend_bin_path({'PATH': _old_path},
                                                        config.build_prefix)['PATH']
            try:
                m, need_source_download, need_reparse_in_env = parse_or_try_download(m,
                                                                no_download_source=False,
                                                                force_download=True,
                                                                config=config)
                assert not need_source_download, "Source download failed.  Please investigate."
            finally:
                if not config.activate:
                    os.environ['PATH'] = _old_path
            print("BUILD START:", m.dist())

        if need_reparse_in_env:
            reparse(m, config=config)
            print("BUILD START:", m.dist())

            if m.name() in [i.rsplit('-', 2)[0] for i in linked(config.build_prefix)]:
                print("%s is installed as a build dependency. Removing." %
                    m.name())
                index = get_build_index(config=config, clear_cache=False)
                actions = plan.remove_actions(config.build_prefix, [m.name()], index=index)
                assert not plan.nothing_to_do(actions), actions
                plan.display_actions(actions, index)
                plan.execute_actions(actions, index)

            print("Package:", m.dist())

        with filelock.SoftFileLock(join(config.build_folder, ".conda_lock"),
                                   timeout=config.timeout):
            # get_dir here might be just work, or it might be one level deeper,
            #    dependening on the source.
            src_dir = source.get_dir(config)
            if isdir(src_dir):
                print("source tree in:", src_dir)
            else:
                print("no source - creating empty work folder")
                os.makedirs(src_dir)

            rm_rf(config.info_dir)
            files1 = prefix_files(prefix=config.build_prefix)
            for pat in m.always_include_files():
                has_matches = False
                for f in set(files1):
                    if fnmatch.fnmatch(f, pat):
                        print("Including in package existing file", f)
                        files1.discard(f)
                        has_matches = True
                if not has_matches:
                    log.warn("Glob %s from always_include_files does not match any files" % pat)
            # Save this for later
            with open(join(config.croot, 'prefix_files.txt'), 'w') as f:
                f.write(u'\n'.join(sorted(list(files1))))
                f.write(u'\n')

            # Use script from recipe?
            script = m.get_value('build/script', None)
            if script:
                if isinstance(script, list):
                    script = '\n'.join(script)

            if isdir(src_dir):
                if on_win:
                    build_file = join(m.path, 'bld.bat')
                    if script:
                        build_file = join(src_dir, 'bld.bat')
                        with open(build_file, 'w') as bf:
                            bf.write(script)
                    import conda_build.windows as windows
                    windows.build(m, build_file, config=config)
                else:
                    build_file = join(m.path, 'build.sh')

                    # There is no sense in trying to run an empty build script.
                    if isfile(build_file) or script:
                        env = environ.get_dict(config=config, m=m, dirty=config.dirty)
                        work_file = join(source.get_dir(config), 'conda_build.sh')
                        if script:
                            with open(work_file, 'w') as bf:
                                bf.write(script)
                        if config.activate:
                            if isfile(build_file):
                                data = open(build_file).read()
                            else:
                                data = open(work_file).read()
                            with open(work_file, 'w') as bf:
                                bf.write("source activate {build_prefix} &> /dev/null\n".format(
                                    build_prefix=config.build_prefix))
                                bf.write(data)
                        else:
                            if not isfile(work_file):
                                copy_into(build_file, work_file, config)
                        os.chmod(work_file, 0o766)

                        if isfile(work_file):
                            cmd = [shell_path, '-x', '-e', work_file]
                            # this should raise if any problems occur while building
                            _check_call(cmd, env=env, cwd=src_dir)

        if post in [True, None]:
            if post:
                with open(join(config.croot, 'prefix_files.txt'), 'r') as f:
                    files1 = set(f.read().splitlines())

            get_build_metadata(m, config=config)
            create_post_scripts(m, config=config)
            create_entry_points(m.get_value('build/entry_points'), config=config)
            assert not exists(config.info_dir)
            files2 = prefix_files(prefix=config.build_prefix)

            post_process(sorted(files2 - files1),
                         prefix=config.build_prefix,
                         config=config,
                         preserve_egg_dir=bool(m.get_value('build/preserve_egg_dir')))

            # The post processing may have deleted some files (like easy-install.pth)
            files2 = prefix_files(prefix=config.build_prefix)
            if any(config.meta_dir in join(config.build_prefix, f) for f in
                    files2 - files1):
                meta_files = (tuple(f for f in files2 - files1 if config.meta_dir in
                        join(config.build_prefix, f)),)
                sys.exit(indent("""Error: Untracked file(s) %s found in conda-meta directory.
    This error usually comes from using conda in the build script.  Avoid doing this, as it
    can lead to packages that include their dependencies.""" % meta_files))
            post_build(m, sorted(files2 - files1),
                       prefix=config.build_prefix,
                       build_python=config.build_python,
                       croot=config.croot)
            create_info_files(m, sorted(files2 - files1), config=config,
                              prefix=config.build_prefix)
            if m.get_value('build/noarch_python'):
                import conda_build.noarch_python as noarch_python
                noarch_python.transform(m, sorted(files2 - files1), config.build_prefix)

            files3 = prefix_files(prefix=config.build_prefix)
            fix_permissions(files3 - files1, config.build_prefix)

            path = bldpkg_path(m, config)

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

                copy_into(tmp_path, path, config=config)
            update_index(config.bldpkgs_dir, config)

        else:
            print("STOPPING BUILD BEFORE POST:", m.dist())

    # returning true here says package is OK to test
    return True


def test(m, config, move_broken=True):
    '''
    Execute any test scripts for the given package.

    :param m: Package's metadata.
    :type m: Metadata
    '''

    with filelock.SoftFileLock(join(config.build_folder, ".conda_lock"), timeout=config.timeout):

        # remove from package cache
        rm_pkgs_cache(m.dist())

        tmp_dir = config.test_dir
        if not isdir(tmp_dir):
            os.makedirs(tmp_dir)
        create_files(tmp_dir, m, config)
        # Make Perl or Python-specific test files
        if m.name().startswith('perl-'):
            pl_files = create_pl_files(tmp_dir, m)
            py_files = False
            lua_files = False
        else:
            py_files = create_py_files(tmp_dir, m)
            pl_files = False
            lua_files = False
        shell_files = create_shell_files(tmp_dir, m, config)
        if not (py_files or shell_files or pl_files or lua_files):
            print("Nothing to test for:", m.dist())
            return

        print("TEST START:", m.dist())

        get_build_metadata(m, config=config)
        specs = ['%s %s %s' % (m.name(), m.version(), m.build_id())]

        # add packages listed in the run environment and test/requires
        specs.extend(ms.spec for ms in m.ms_depends('run'))
        specs += m.get_value('test/requires', [])

        if py_files:
            # as the tests are run by python, ensure that python is installed.
            # (If they already provided python as a run or test requirement,
            #  this won't hurt anything.)
            specs += ['python %s*' % environ.get_py_ver(config)]
        if pl_files:
            # as the tests are run by perl, we need to specify it
            specs += ['perl %s*' % environ.get_perl_ver(config)]
        if lua_files:
            # not sure how this shakes out
            specs += ['lua %s*' % environ.get_lua_ver(config)]

        create_env(config.test_prefix, specs, config=config)

        env = dict(os.environ.copy())
        env.update(environ.get_dict(config=config, m=m, prefix=config.test_prefix))

        if not config.activate:
            # prepend bin (or Scripts) directory
            env = prepend_bin_path(env, config.test_prefix, prepend_prefix=True)

            if on_win:
                env['PATH'] = config.test_prefix + os.pathsep + env['PATH']

        for varname in 'CONDA_PY', 'CONDA_NPY', 'CONDA_PERL', 'CONDA_LUA':
            env[varname] = str(getattr(config, varname) or '')

        # Python 2 Windows requires that envs variables be string, not unicode
        env = {str(key): str(value) for key, value in env.items()}
        suffix = "bat" if on_win else "sh"
        test_script = join(tmp_dir, "conda_test_runner.{suffix}".format(suffix=suffix))

        with open(test_script, 'w') as tf:
            if config.activate:
                ext = ".bat" if on_win else ""
                tf.write("{source} activate{ext} {test_env}\n".format(source="call" if on_win
                                                                     else "source",
                                                                     ext=ext,
                                                                     test_env=config.test_prefix))
                tf.write("if errorlevel 1 exit 1\n") if on_win else None
            if py_files:
                tf.write("{python} -s {test_file}\n".format(
                    python=config.test_python,
                    test_file=join(tmp_dir, 'run_test.py')))
                tf.write("if errorlevel 1 exit 1\n") if on_win else None

            if pl_files:
                tf.write("{perl} {test_file}\n".format(
                    python=config.test_perl,
                    test_file=join(tmp_dir, 'run_test.pl')))
                tf.write("if errorlevel 1 exit 1\n") if on_win else None

            if lua_files:
                tf.write("{lua} {test_file}\n".format(
                    python=config.test_perl,
                    test_file=join(tmp_dir, 'run_test.lua')))
                tf.write("if errorlevel 1 exit 1\n") if on_win else None

            if shell_files:
                test_file = join(tmp_dir, 'run_test.' + suffix)
                if on_win:
                    tf.write("call {test_file}\n".format(test_file=test_file))
                    tf.write("if errorlevel 1 exit 1\n")
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
            tests_failed(m, move_broken=move_broken, broken_dir=config.broken_dir, config=config)

    print("TEST END:", m.dist())


def tests_failed(m, move_broken, broken_dir, config):
    '''
    Causes conda to exit if any of the given package's tests failed.

    :param m: Package's metadata
    :type m: Metadata
    '''
    if not isdir(broken_dir):
        os.makedirs(broken_dir)

    if move_broken:
        shutil.move(bldpkg_path(m, config), join(broken_dir, "%s.tar.bz2" % m.dist()))
    sys.exit("TESTS FAILED: " + m.dist())


def check_external(config):
    if sys.platform.startswith('linux'):
        patchelf = external.find_executable('patchelf')
        if patchelf is None:
            sys.exit("""\
Error:
    Did not find 'patchelf' in: %s
    'patchelf' is necessary for building conda packages on Linux with
    relocatable ELF libraries.  You can install patchelf using conda install
    patchelf.
""" % (os.pathsep.join(external.dir_paths)))


def build_tree(metadata_list, config, check=False, build_only=False, post=False, notest=False,
               need_source_download=True, already_built=None):

    to_build_recursive = []
    metadata_list = deque(metadata_list)
    if not already_built:
        already_built = set()
    while metadata_list:
        # This loop recursively builds dependencies if recipes exist
        if build_only:
            post = False
            notest = True
            config.anaconda_upload = False
        elif post:
            post = True
            notest = True
            config.anaconda_upload = False
        else:
            post = None

        metadata, need_source_download, need_reparse_in_env = metadata_list.popleft()
        recipe_parent_dir = os.path.dirname(metadata.path)
        try:
            ok_to_test = build(metadata, post=post,
                               need_source_download=need_source_download,
                               config=config)
            if not notest and ok_to_test:
                test(metadata, config=config)
        except (NoPackagesFound, Unsatisfiable) as e:
            error_str = str(e)
            # Typically if a conflict is with one of these
            # packages, the other package needs to be rebuilt
            # (e.g., a conflict with 'python 3.5*' and 'x' means
            # 'x' isn't build for Python 3.5 and needs to be
            # rebuilt).
            skip_names = ['python', 'r']
            # add the failed one back in
            add_recipes = [metadata.path]
            for line in error_str.splitlines():
                if not line.startswith('  - '):
                    continue
                pkg = line.lstrip('  - ').split(' -> ')[-1]
                pkg = pkg.strip().split(' ')[0]
                if pkg in skip_names:
                    continue
                recipe_glob = glob(os.path.join(recipe_parent_dir, pkg + '-[v0-9][0-9.]*'))
                if os.path.exists(pkg):
                    recipe_glob.append(pkg)
                if recipe_glob:
                    for recipe_dir in recipe_glob:
                        if pkg in to_build_recursive:
                            sys.exit(str(e))
                        print(error_str)
                        print(("Missing dependency {0}, but found" +
                                " recipe directory, so building " +
                                "{0} first").format(pkg))
                        add_recipes.append(recipe_dir)
                        to_build_recursive.append(pkg)
                else:
                    raise
            metadata_list.extendleft([render_recipe(add_recipe, config=config)
                                      for add_recipe in add_recipes])

        # outputs message, or does upload, depending on value of args.anaconda_upload
        output_file = bldpkg_path(metadata, config=config)
        handle_anaconda_upload(output_file, config=config)

        already_built.add(output_file)

        if not config.keep_old_work and not config.dirty:
            sys.stderr.write("# --keep-old-work flag not specified.  "
                             "Removing source and build files.\n")
            # build folder is the whole burrito containing envs and source folders
            shutil.rmtree(config.build_folder)


def handle_anaconda_upload(path, config):
    import subprocess
    from conda_build.os_utils.external import find_executable

    upload = False
    # this is the default, for no explicit argument.
    # remember that anaconda_upload takes defaults from condarc
    if config.anaconda_upload is None:
        pass
    # rc file has uploading explicitly turned off
    elif config.anaconda_upload is False:
        print("# Automatic uploading is disabled")
    else:
        upload = True

    if config.token or config.user:
        upload = True

    no_upload_message = """\
# If you want to upload this package to anaconda.org later, type:
#
# $ anaconda upload %s
#
# To have conda build upload to anaconda.org automatically, use
# $ conda config --set anaconda_upload yes
""" % path
    if not upload:
        print(no_upload_message)
        return

    anaconda = find_executable('anaconda')
    if anaconda is None:
        print(no_upload_message)
        sys.exit('''
Error: cannot locate anaconda command (required for upload)
# Try:
# $ conda install anaconda-client
''')
    print("Uploading to anaconda.org")
    cmd = [anaconda, ]

    if config.token:
        cmd.extend(['--token', config.token])
    cmd.append('upload')
    if config.user:
        cmd.extend(['--user', config.user])
    cmd.append(path)
    try:
        subprocess.call(cmd)
    except:
        print(no_upload_message)
        raise


def print_build_intermediate_warning(config):
    print("\n\n")
    print('#' * 80)
    print("Source and build intermediates have been left in " + config.croot + ".")
    build_folders = get_build_folders(config.croot)
    print("There are currently {num_builds} accumulated.".format(num_builds=len(build_folders)))
    print("To remove them, you can run the ```conda build purge``` command")


def clean_build(config, folders=None):
    if not folders:
        folders = get_build_folders(config.croot)
    for folder in folders:
        shutil.rmtree(folder)
