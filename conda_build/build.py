'''
Module that does most of the heavy lifting for the ``conda build`` command.
'''
from __future__ import absolute_import, division, print_function

from collections import deque
import fnmatch
from glob import glob
import io
import json
import logging
import mmap
import os
from os.path import isdir, isfile, islink, join
import shutil
import stat
import subprocess
import sys
import tarfile

# this is to compensate for a requests idna encoding error.  Conda is a better place to fix,
#   eventually
# exception is raises: "LookupError: unknown encoding: idna"
#    http://stackoverflow.com/a/13057751/1170370
import encodings.idna  # NOQA

import filelock

from .conda_interface import cc
from .conda_interface import envs_dirs, root_dir
from .conda_interface import plan
from .conda_interface import get_index
from .conda_interface import PY3
from .conda_interface import package_cache
from .conda_interface import prefix_placeholder, linked, symlink_conda
from .conda_interface import url_path
from .conda_interface import Resolve, MatchSpec, NoPackagesFound, Unsatisfiable
from .conda_interface import TemporaryDirectory
from .conda_interface import get_rc_urls, get_local_urls
from .conda_interface import VersionOrder
from .conda_interface import PaddingError, LinkError

from conda_build import __version__
from conda_build import environ, source, tarcheck
from conda_build.render import (parse_or_try_download, output_yaml, bldpkg_path,
                                render_recipe, reparse)
import conda_build.os_utils.external as external
from conda_build.post import (post_process, post_build,
                              fix_permissions, get_build_metadata)
from conda_build.utils import (rm_rf, _check_call, copy_into, on_win, get_build_folders,
                               silence_loggers, path_prepended, create_entry_points,
                               prepend_bin_path, codec, root_script_dir, print_skip_message)
from conda_build.index import update_index
from conda_build.create_test import (create_files, create_shell_files,
                                     create_py_files, create_pl_files)
from conda_build.exceptions import indent
from conda_build.features import feature_list

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
        copy_into(src, dst, config.timeout)
        os.chmod(dst, int('755', 8))


def have_prefix_files(files, prefix):
    '''
    Yields files that contain the current prefix in them, and modifies them
    to replace the prefix with a placeholder.

    :param files: Filenames to check for instances of prefix
    :type files: list of tuples containing strings (prefix, mode, filename)
    '''
    prefix_bytes = prefix.encode(codec)
    prefix_placeholder_bytes = prefix_placeholder.encode(codec)
    if on_win:
        forward_slash_prefix = prefix.replace('\\', '/')
        forward_slash_prefix_bytes = forward_slash_prefix.encode(codec)
        double_backslash_prefix = prefix.replace('\\', '\\\\')
        double_backslash_prefix_bytes = double_backslash_prefix.encode(codec)

    for f in files:
        if f.endswith(('.pyc', '.pyo', '.a')):
            continue
        path = join(prefix, f)
        if not isfile(path):
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
                mm.close()
                fi.close()
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
        mm.close()
        fi.close()


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
    prefix = join(envs_dirs[0], '_run')
    rm_rf(prefix)
    create_env(prefix, [ms.spec for ms in m.ms_depends('run')], config=config)
    return sorted(linked(prefix))


def copy_recipe(m, config):
    if config.include_recipe and m.include_recipe():
        recipe_dir = join(config.info_dir, 'recipe')
        os.makedirs(recipe_dir)

        if os.path.isdir(m.path):
            for fn in os.listdir(m.path):
                if fn.startswith('.'):
                    continue
                src_path = join(m.path, fn)
                dst_path = join(recipe_dir, fn)
                copy_into(src_path, dst_path, timeout=config.timeout)

            # store the rendered meta.yaml file, plus information about where it came from
            #    and what version of conda-build created it
            original_recipe = os.path.join(m.path, 'meta.yaml')
        else:
            original_recipe = ""

        rendered = output_yaml(m)
        if not original_recipe or not open(original_recipe).read() == rendered:
            with open(join(recipe_dir, "meta.yaml"), 'w') as f:
                f.write("# This file created by conda-build {}\n".format(__version__))
                if original_recipe:
                    f.write("# meta.yaml template originally from:\n")
                    f.write("# " + source.get_repository_info(m.path) + "\n")
                f.write("# ------------------------------------------------\n\n")
                f.write(rendered)
            if original_recipe:
                copy_into(original_recipe, os.path.join(recipe_dir, 'meta.yaml.template'),
                          timeout=config.timeout)


def copy_readme(m, config):
    readme = m.get_value('about/readme')
    if readme:
        src = join(config.work_dir, readme)
        if not isfile(src):
            sys.exit("Error: no readme file: %s" % readme)
        dst = join(config.info_dir, readme)
        copy_into(src, dst, config.timeout)
        if os.path.split(readme)[1] not in {"README.md", "README.rst", "README"}:
            print("WARNING: anaconda.org only recognizes about/readme "
                  "as README.md and README.rst", file=sys.stderr)


def copy_license(m, config):
    license_file = m.get_value('about/license_file')
    if license_file:
        copy_into(join(config.work_dir, license_file),
                        join(config.info_dir, 'LICENSE.txt'), config.timeout)


def detect_and_record_prefix_files(m, files, prefix, config):
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

    is_noarch = m.get_value('build/noarch_python') or \
        str(m.get_value('build/noarch')).lower() == "python"

    if files_with_prefix and not is_noarch:
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


def write_about_json(m, config):
    with open(join(config.info_dir, 'about.json'), 'w') as fo:
        d = {}
        for key in ('home', 'dev_url', 'doc_url', 'license_url',
                    'license', 'summary', 'description', 'license_family'):
            value = m.get_value('about/%s' % key)
            if value:
                d[key] = value
        json.dump(d, fo, indent=2, sort_keys=True)


def write_info_json(m, config, mode_dict):
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
""" % (m.dist(), config.subdir))
            for dist in sorted(dists + [m.dist()]):
                fo.write('%s\n' % '='.join(dist.split('::', 1)[-1].rsplit('-', 2)))
        if pin_depends == 'strict':
            info_index['depends'] = [' '.join(dist.split('::', 1)[-1].rsplit('-', 2))
                                     for dist in dists]

    # Deal with Python 2 and 3's different json module type reqs
    with open(join(config.info_dir, 'index.json'), **mode_dict) as fo:
        json.dump(info_index, fo, indent=2, sort_keys=True)


def write_no_link(m, config, files):
    no_link = m.get_value('build/no_link')
    if no_link:
        if not isinstance(no_link, list):
            no_link = [no_link]
        with open(join(config.info_dir, 'no_link'), 'w') as fo:
            for f in files:
                if any(fnmatch.fnmatch(f, p) for p in no_link):
                    fo.write(f + '\n')


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

    copy_recipe(m, config)
    copy_readme(m, config)
    copy_license(m, config)

    mode_dict = {'mode': 'w', 'encoding': 'utf-8'} if PY3 else {'mode': 'wb'}

    write_info_json(m, config, mode_dict)
    write_about_json(m, config)

    if on_win:
        # make sure we use '/' path separators in metadata
        files = [_f.replace('\\', '/') for _f in files]

    with open(join(config.info_dir, 'files'), **mode_dict) as fo:
        if m.get_value('build/noarch_python'):
            fo.write('\n')
        else:
            for f in files:
                fo.write(f + '\n')

    detect_and_record_prefix_files(m, files, prefix, config)
    write_no_link(m, config, files)

    if m.get_value('source/git_url'):
        with io.open(join(config.info_dir, 'git'), 'w', encoding='utf-8') as fo:
            source.git_info(config, fo)

    if m.get_value('app/icon'):
        copy_into(join(m.path, m.get_value('app/icon')),
                        join(config.info_dir, 'icon.png'),
                  config.timeout)


def get_build_index(config, clear_cache=True):
    # priority: local by croot (can vary), then channels passed as args,
    #     then channels from config.
    urls = [url_path(config.croot)] + list(config.channel_urls)
    index = get_index(channel_urls=urls,
                      prepend=not config.override_channels,
                      use_local=False,
                      use_cache=not clear_cache)
    return index


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
        silence_loggers(show_warnings_and_errors=True)

    if os.path.isdir(prefix):
        rm_rf(prefix)

    specs = list(specs)
    for feature, value in feature_list:
        if value:
            specs.append('%s@' % feature)

    if specs:  # Don't waste time if there is nothing to do
        with path_prepended(prefix):
            locks = []
            try:
                cc.pkgs_dirs = cc.pkgs_dirs[:1]
                locked_folders = cc.pkgs_dirs + list(config.bldpkgs_dirs)
                for folder in locked_folders:
                    if not os.path.isdir(folder):
                        os.makedirs(folder)
                    lock = filelock.SoftFileLock(join(folder, '.conda_lock'))
                    if not folder.endswith('pkgs'):
                        update_index(folder, config=config, lock=lock, could_be_mirror=False)
                    lock.acquire(timeout=config.timeout)
                    locks.append(lock)

                index = get_build_index(config=config, clear_cache=True)

                actions = plan.install_actions(prefix, index, specs)
                if config.disable_pip:
                    actions['LINK'] = [spec for spec in actions['LINK'] if not spec.startswith('pip-')]  # noqa
                    actions['LINK'] = [spec for spec in actions['LINK'] if not spec.startswith('setuptools-')]  # noqa
                plan.display_actions(actions, index)
                if on_win:
                    for k, v in os.environ.items():
                        os.environ[k] = str(v)
                plan.execute_actions(actions, index, verbose=config.debug)
            except (SystemExit, PaddingError, LinkError) as exc:
                if (("too short in" in str(exc) or
                        'post-link failed for: openssl' in str(exc) or
                        isinstance(exc, PaddingError)) and
                        config.prefix_length > 80):
                    log.warn("Build prefix failed with prefix length %d", config.prefix_length)
                    log.warn("Error was: ")
                    log.warn(str(exc))
                    log.warn("One or more of your package dependencies needs to be rebuilt "
                            "with a longer prefix length.")
                    log.warn("Falling back to legacy prefix length of 80 characters.")
                    log.warn("Your package will not install into prefixes > 80 characters.")
                    config.prefix_length = 80

                    # Set this here and use to create environ
                    #   Setting this here is important because we use it below (symlink)
                    prefix = config.build_prefix

                    for lock in locks:
                        lock.release()
                        if os.path.isfile(lock._lock_file):
                            os.remove(lock._lock_file)
                    create_env(prefix, specs, config=config,
                                clear_cache=clear_cache)
                else:
                    for lock in locks:
                        lock.release()
                        if os.path.isfile(lock._lock_file):
                            os.remove(lock._lock_file)
                    raise
            finally:
                for lock in locks:
                    lock.release()
                    if os.path.isfile(lock._lock_file):
                        os.remove(lock._lock_file)
        warn_on_old_conda_build(index=index)

    # ensure prefix exists, even if empty, i.e. when specs are empty
    if not isdir(prefix):
        os.makedirs(prefix)
    if on_win:
        shell = "cmd.exe"
    else:
        shell = "bash"
    symlink_conda(prefix, sys.prefix, shell)


def get_installed_conda_build_version():
    root_linked = linked(root_dir)
    vers_inst = [dist.split('::', 1)[-1].rsplit('-', 2)[1] for dist in root_linked
        if dist.split('::', 1)[-1].rsplit('-', 2)[0] == 'conda-build']
    if not len(vers_inst) == 1:
        log.warn("Could not detect installed version of conda-build")
        return None
    return vers_inst[0]


def get_conda_build_index_versions(index):
    r = Resolve(index)
    pkgs = []
    try:
        pkgs = r.get_pkgs(MatchSpec('conda-build'))
    except NoPackagesFound:
        log.warn("Could not find any versions of conda-build in the channels")
    return [pkg.version for pkg in pkgs]


def filter_non_final_releases(pkg_list):
    """cuts out packages wth rc/alpha/beta.

    VersionOrder described in conda/version.py

    Basically, it breaks up the version into pieces, and depends on version
    formats like x.y.z[alpha/beta]
    """
    return [pkg for pkg in pkg_list if len(VersionOrder(pkg).version[3]) == 1]


def warn_on_old_conda_build(index=None, installed_version=None, available_packages=None):
    if not installed_version:
        installed_version = get_installed_conda_build_version() or "0.0.0"
    if not available_packages:
        if index:
            available_packages = get_conda_build_index_versions(index)
        else:
            raise ValueError("Must provide either available packages or"
                             " index to warn_on_old_conda_build")
    available_packages = sorted(filter_non_final_releases(available_packages), key=VersionOrder)
    if (len(available_packages) > 0 and installed_version and
            VersionOrder(installed_version) < VersionOrder(available_packages[-1])):
        print("""
WARNING: conda-build appears to be out of date. You have version %s but the
latest version is %s. Run

conda update -n root conda-build

to get the latest version.
""" % (installed_version, available_packages[-1]), file=sys.stderr)


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

    if m.skip():
        print_skip_message(m)
        return False

    if config.skip_existing:
        package_exists = is_package_built(m, config)
        if package_exists:
            print(m.dist(), "is already built in {0}, skipping.".format(package_exists))
            return False

    if post in [False, None]:
        print("BUILD START:", m.dist())
        if m.uses_jinja and (need_source_download or need_reparse_in_env):
            print("    (actual version deferred until further download or env creation)")

        specs = [ms.spec for ms in m.ms_depends('build')]
        create_env(config.build_prefix, specs, config=config)
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

                    log.warn("Your recipe depends on %s at build time (for templates), "
                            "but you have not listed it as a build dependency.  Doing "
                                "so for this build.", vcs_source)

                    # Display the name only
                    # Version number could be missing due to dependency on source info.
                    create_env(config.build_prefix, specs, config=config)
                else:
                    raise ValueError("Your recipe uses mercurial in build, but mercurial"
                                    " does not yet support Python 3.  Please handle all of "
                                    "your mercurial actions outside of your build script.")

        if need_source_download:
            # Execute any commands fetching the source (e.g., git) in the _build environment.
            # This makes it possible to provide source fetchers (eg. git, hg, svn) as build
            # dependencies.
            with path_prepended(config.build_prefix):
                m, need_source_download, need_reparse_in_env = parse_or_try_download(m,
                                                                no_download_source=False,
                                                                force_download=True,
                                                                config=config)
            assert not need_source_download, "Source download failed.  Please investigate."
            if m.uses_jinja:
                print("BUILD START (revised):", m.dist())

        if need_reparse_in_env:
            reparse(m, config=config)
            print("BUILD START (revised):", m.dist())

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
            src_dir = config.work_dir
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
                    log.warn("Glob %s from always_include_files does not match any files", pat)
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
                        with path_prepended(config.build_prefix):
                            env = environ.get_dict(config=config, m=m)
                        env["CONDA_BUILD_STATE"] = "BUILD"
                        work_file = join(config.work_dir, 'conda_build.sh')
                        if script:
                            with open(work_file, 'w') as bf:
                                bf.write(script)
                        if config.activate:
                            if isfile(build_file):
                                data = open(build_file).read()
                            else:
                                data = open(work_file).read()
                            with open(work_file, 'w') as bf:
                                bf.write("source {conda_root}activate {build_prefix} &> "
                                    "/dev/null\n".format(conda_root=root_script_dir + os.path.sep,
                                                         build_prefix=config.build_prefix))
                                bf.write(data)
                        else:
                            if not isfile(work_file):
                                copy_into(build_file, work_file, config.timeout)
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
        elif str(m.get_value('build/noarch')).lower() == "python":
            import conda_build.noarch_python as noarch_python
            noarch_python.populate_files(m, sorted(files2 - files1), config.build_prefix)

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

            copy_into(tmp_path, path, config.timeout)
        update_index(config.bldpkgs_dir, config, could_be_mirror=False)

    else:
        print("STOPPING BUILD BEFORE POST:", m.dist())

    # returning true here says package is OK to test
    return True


def clean_pkg_cache(dist, timeout):
    cc.pkgs_dirs = cc.pkgs_dirs[:1]
    locks = []
    for folder in cc.pkgs_dirs:
        locks.append(filelock.SoftFileLock(join(folder, ".conda_lock")))

    for lock in locks:
        lock.acquire(timeout=timeout)

    try:
        rmplan = [
            'RM_EXTRACTED {0} local::{0}'.format(dist),
            'RM_FETCHED {0} local::{0}'.format(dist),
        ]
        plan.execute_plan(rmplan)

        # Conda does not seem to do a complete cleanup sometimes.  This is supplemental.
        #   Conda's cleanup is still necessary - it keeps track of its own in-memory
        #   list of downloaded things.
        for folder in cc.pkgs_dirs:
            try:
                assert not os.path.exists(os.path.join(folder, dist))
                assert not os.path.exists(os.path.join(folder, dist + '.tar.bz2'))
                for pkg_id in [dist, 'local::' + dist]:
                    assert pkg_id not in package_cache()
            except AssertionError:
                log.debug("Conda caching error: %s package remains in cache after removal", dist)
                log.debug("Clearing package cache to compensate")
                cache = package_cache()
                keys = [key for key in cache.keys() if dist in key]
                for pkg_id in keys:
                    if pkg_id in cache:
                        del cache[pkg_id]
                for entry in glob(os.path.join(folder, dist + '*')):
                    rm_rf(entry)
    except:
        raise
    finally:
        for lock in locks:
            lock.release()
            if os.path.isfile(lock._lock_file):
                os.remove(lock._lock_file)


def test(m, config, move_broken=True):
    '''
    Execute any test scripts for the given package.

    :param m: Package's metadata.
    :type m: Metadata
    '''

    if not os.path.isdir(config.build_folder):
        os.makedirs(config.build_folder)

    clean_pkg_cache(m.dist(), config.timeout)

    with filelock.SoftFileLock(join(config.build_folder, ".conda_lock"), timeout=config.timeout):
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

        with path_prepended(config.test_prefix):
            env = dict(os.environ.copy())
            env.update(environ.get_dict(config=config, m=m, prefix=config.test_prefix))
            env["CONDA_BUILD_STATE"] = "TEST"

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
                tf.write("{source} {conda_root}activate{ext} {test_env} {squelch}\n".format(
                    conda_root=root_script_dir + os.path.sep,
                    source="call" if on_win else "source",
                    ext=ext,
                    test_env=config.test_prefix,
                    squelch=">nul 2>&1" if on_win else "&> /dev/null"))
                if on_win:
                    tf.write("if errorlevel 1 exit 1\n")
            if py_files:
                tf.write("{python} -s {test_file}\n".format(
                    python=config.test_python,
                    test_file=join(tmp_dir, 'run_test.py')))
                if on_win:
                    tf.write("if errorlevel 1 exit 1\n")
            if pl_files:
                tf.write("{perl} {test_file}\n".format(
                    perl=config.test_perl,
                    test_file=join(tmp_dir, 'run_test.pl')))
                if on_win:
                    tf.write("if errorlevel 1 exit 1\n")
            if lua_files:
                tf.write("{lua} {test_file}\n".format(
                    lua=config.test_lua,
                    test_file=join(tmp_dir, 'run_test.lua')))
                if on_win:
                    tf.write("if errorlevel 1 exit 1\n")
            if shell_files:
                test_file = join(tmp_dir, 'run_test.' + suffix)
                if on_win:
                    tf.write("call {test_file}\n".format(test_file=test_file))
                    if on_win:
                        tf.write("if errorlevel 1 exit 1\n")
                else:
                    # TODO: Run the test/commands here instead of in run_test.py
                    tf.write("{shell_path} -x -e {test_file}\n".format(shell_path=shell_path,
                                                                       test_file=test_file))

        if on_win:
            cmd = ['cmd.exe', "/d", "/c", test_script]
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


def check_external():
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


def build_tree(recipe_list, config, build_only=False, post=False, notest=False,
               need_source_download=True, need_reparse_in_env=False):

    to_build_recursive = []
    recipe_list = deque(recipe_list)

    already_built = set()
    while recipe_list:
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

        recipe = recipe_list.popleft()
        if hasattr(recipe, 'config'):
            metadata = recipe
            recipe_config = metadata.config
            # this code is duplicated below because we need to be sure that the build id is set
            #    before downloading happens - or else we lose where downloads are
            if recipe_config.set_build_id:
                recipe_config.compute_build_id(metadata.name(), reset=True)
            recipe_parent_dir = ""
            to_build_recursive.append(metadata.name())
        else:
            recipe_parent_dir = os.path.dirname(recipe)
            recipe = recipe.rstrip("/").rstrip("\\")
            recipe_config = config
            to_build_recursive.append(os.path.basename(recipe))

            #    before downloading happens - or else we lose where downloads are
            if recipe_config.set_build_id:
                recipe_config.compute_build_id(os.path.basename(recipe), reset=True)
            metadata, need_source_download, need_reparse_in_env = render_recipe(recipe,
                                                                    config=recipe_config)
        try:
            with recipe_config:
                ok_to_test = build(metadata, post=post,
                                   need_source_download=need_source_download,
                                   need_reparse_in_env=need_reparse_in_env,
                                   config=recipe_config)
                if not notest and ok_to_test:
                    test(metadata, config=recipe_config)
        except (NoPackagesFound, Unsatisfiable) as e:
            error_str = str(e)
            # Typically if a conflict is with one of these
            # packages, the other package needs to be rebuilt
            # (e.g., a conflict with 'python 3.5*' and 'x' means
            # 'x' isn't build for Python 3.5 and needs to be
            # rebuilt).
            skip_names = ['python', 'r']
            add_recipes = []
            # add the failed one back in at the beginning - but its deps may come before it
            recipe_list.extendleft([recipe])
            for line in error_str.splitlines():
                if not line.startswith('  - '):
                    continue
                pkg = line.lstrip('  - ').split(' -> ')[-1]
                pkg = pkg.strip().split(' ')[0]
                if pkg in skip_names:
                    continue

                if pkg in to_build_recursive:
                    raise RuntimeError("Can't build {0} due to unsatisfiable dependencies:\n"
                                       .format(recipe) + error_str)

                recipe_glob = glob(os.path.join(recipe_parent_dir, pkg))
                if recipe_glob:
                    for recipe_dir in recipe_glob:
                        print(error_str)
                        print(("Missing dependency {0}, but found" +
                                " recipe directory, so building " +
                                "{0} first").format(pkg))
                        add_recipes.append(recipe_dir)
                else:
                    raise RuntimeError("Can't build {0} due to unsatisfiable dependencies:\n"
                                       .format(recipe) + error_str)
            recipe_list.extendleft(add_recipes)

        # outputs message, or does upload, depending on value of args.anaconda_upload
        if post in [True, None]:
            output_file = bldpkg_path(metadata, config=recipe_config)
            handle_anaconda_upload(output_file, config=recipe_config)
            already_built.add(output_file)


def handle_anaconda_upload(path, config):
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
    print('#' * 84)
    print("Source and build intermediates have been left in " + config.croot + ".")
    build_folders = get_build_folders(config.croot)
    print("There are currently {num_builds} accumulated.".format(num_builds=len(build_folders)))
    print("To remove them, you can run the ```conda build purge``` command")


def clean_build(config, folders=None):
    if not folders:
        folders = get_build_folders(config.croot)
    for folder in folders:
        rm_rf(folder)


def is_package_built(metadata, config):
    for d in config.bldpkgs_dirs:
        if not os.path.isdir(d):
            os.makedirs(d)
        update_index(d, config, could_be_mirror=False)
    index = get_build_index(config=config, clear_cache=True)

    urls = [url_path(config.croot)] + get_rc_urls() + get_local_urls() + ['local', ]
    if config.channel_urls:
        urls.extend(config.channel_urls)

    # will be empty if none found, and evalute to False
    package_exists = [url for url in urls if url + '::' + metadata.pkg_fn() in index]
    return package_exists or metadata.pkg_fn() in index
