'''
Module that does most of the heavy lifting for the ``conda build`` command.
'''
from __future__ import absolute_import, division, print_function

from collections import deque, OrderedDict
import fnmatch
from glob import glob
import io
import json
import os
from os.path import isdir, isfile, islink, join, dirname
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import hashlib
import logging

# this is to compensate for a requests idna encoding error.  Conda is a better place to fix,
#   eventually
# exception is raises: "LookupError: unknown encoding: idna"
#    http://stackoverflow.com/a/13057751/1170370
import encodings.idna  # NOQA

from bs4 import UnicodeDammit
import yaml

# used to get version
from .conda_interface import env_path_backup_var_exists
from .conda_interface import PY3
from .conda_interface import prefix_placeholder
from .conda_interface import TemporaryDirectory
from .conda_interface import VersionOrder
from .conda_interface import text_type
from .conda_interface import CrossPlatformStLink
from .conda_interface import PathType, FileMode
from .conda_interface import EntityEncoder
from .conda_interface import get_rc_urls
from .conda_interface import url_path
from .conda_interface import cc_platform, root_dir, pkgs_dirs
from .conda_interface import conda_private
from .conda_interface import dist_str_in_index
from .conda_interface import MatchSpec

from conda_build import __version__
from conda_build import environ, source, tarcheck, utils
from conda_build.index import get_build_index, update_index
from conda_build.render import (output_yaml, bldpkg_path, render_recipe, reparse, finalize_metadata,
                                distribute_variants, expand_outputs, try_download,
                                add_upstream_pins)
import conda_build.os_utils.external as external
from conda_build.metadata import FIELDS, MetaData
from conda_build.post import (post_process, post_build,
                              fix_permissions, get_build_metadata)

from conda_build.exceptions import indent, DependencyNeedsBuildingError, CondaBuildException
from conda_build.variants import (set_language_env_vars, dict_of_lists_to_list_of_dicts,
                                  get_package_variants)
from conda_build.create_test import create_all_test_files

import conda_build.noarch_python as noarch_python
from conda_verify.verify import Verify

from conda import __version__ as conda_version
from conda_build import __version__ as conda_build_version

if sys.platform == 'win32':
    import conda_build.windows as windows

if 'bsd' in sys.platform:
    shell_path = '/bin/sh'
else:
    shell_path = '/bin/bash'


def create_post_scripts(m):
    '''
    Create scripts to run after build step
    '''
    recipe_dir = m.path
    ext = '.bat' if utils.on_win else '.sh'
    for tp in 'pre-link', 'post-link', 'pre-unlink':
        src = join(recipe_dir, tp + ext)
        if not isfile(src):
            continue
        # TODOCROSS :: utils.on_win here needs to check if the host is Windows instead.
        dst_dir = join(m.config.host_prefix,
                       'Scripts' if utils.on_win else 'bin')
        if not isdir(dst_dir):
            os.makedirs(dst_dir, 0o775)
        dst = join(dst_dir, '.%s-%s%s' % (m.name(), tp, ext))
        utils.copy_into(src, dst, m.config.timeout, locking=m.config.locking)
        os.chmod(dst, 0o775)


def have_prefix_files(files, prefix):
    '''
    Yields files that contain the current prefix in them, and modifies them
    to replace the prefix with a placeholder.

    :param files: Filenames to check for instances of prefix
    :type files: list of tuples containing strings (prefix, mode, filename)
    '''

    prefix_bytes = prefix.encode(utils.codec)
    prefix_placeholder_bytes = prefix_placeholder.encode(utils.codec)
    if utils.on_win:
        forward_slash_prefix = prefix.replace('\\', '/')
        forward_slash_prefix_bytes = forward_slash_prefix.encode(utils.codec)
        double_backslash_prefix = prefix.replace('\\', '\\\\')
        double_backslash_prefix_bytes = double_backslash_prefix.encode(utils.codec)

    for f in files:
        if f.endswith(('.pyc', '.pyo')):
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

        try:
            fi = open(path, 'rb+')
        except IOError:
            log = utils.get_logger(__name__)
            log.warn("failed to open %s for detecting prefix.  Skipping it." % f)
            continue
        try:
            mm = utils.mmap_mmap(fi.fileno(), 0, tagname=None, flags=utils.mmap_MAP_PRIVATE)
        except OSError:
            mm = fi.read()

        mode = 'binary' if mm.find(b'\x00') != -1 else 'text'
        if mode == 'text':
            if not utils.on_win and mm.find(prefix_bytes) != -1:
                # Use the placeholder for maximal backwards compatibility, and
                # to minimize the occurrences of usernames appearing in built
                # packages.
                data = mm[:]
                mm.close()
                fi.close()
                rewrite_file_with_new_prefix(path, data, prefix_bytes, prefix_placeholder_bytes)
                fi = open(path, 'rb+')
                mm = utils.mmap_mmap(fi.fileno(), 0, tagname=None, flags=utils.mmap_MAP_PRIVATE)
        if mm.find(prefix_bytes) != -1:
            yield (prefix, mode, f)
        if utils.on_win and mm.find(forward_slash_prefix_bytes) != -1:
            # some windows libraries use unix-style path separators
            yield (forward_slash_prefix, mode, f)
        elif utils.on_win and mm.find(double_backslash_prefix_bytes) != -1:
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


def copy_recipe(m):
    output_metadata = m.copy()
    if output_metadata.config.include_recipe and output_metadata.include_recipe():
        recipe_dir = join(output_metadata.config.info_dir, 'recipe')
        try:
            os.makedirs(recipe_dir)
        except:
            pass

        if os.path.isdir(output_metadata.path):
            files = utils.rec_glob(m.path, "*")
            src_dir = m.path
            file_paths = sorted([f.replace(m.path + os.sep, '') for f in files])
            # exclude meta.yaml because the json dictionary captures its content
            file_paths = [f for f in file_paths if not (f == 'meta.yaml' or
                                                        f == 'conda_build_config.yaml')]
            file_paths = utils.filter_files(file_paths, m.path)
            # store the rendered meta.yaml file, plus information about where it came from
            #    and what version of conda-build created it
            original_recipe = os.path.join(output_metadata.path, 'meta.yaml')
        # it's a subpackage.
        else:
            original_recipe = ""
            # this will be a subsection for just this output

            src_dir = m.meta.get('extra', {}).get('parent_recipe', {}).get('path')
            if src_dir:
                this_output = m.get_rendered_output(m.name()) or {}
                install_script = this_output.get('script')
                # # HACK: conda-build renames the actual test script from the recipe into
                # #    run_test.* in the package.  This makes the test discovery code work.
                # if test_script:
                #     ext = os.path.splitext(test_script)[1]
                #     test_script = 'run_test' + ext
                build_inputs = []
                for build_input in ('build.sh', 'bld.bat'):
                    if os.path.isfile(os.path.join(src_dir, build_input)):
                        build_inputs.append(build_input)
                inputs = [install_script] + build_inputs
                file_paths = [script for script in inputs if script]
                file_paths = utils.filter_files(file_paths, src_dir)
            else:
                file_paths = []

        for f in file_paths:
            utils.copy_into(join(src_dir, f), join(recipe_dir, f),
                            timeout=output_metadata.config.timeout,
                            locking=output_metadata.config.locking, clobber=True)

        # hard code the build string, so that tests don't get it mixed up
        build = output_metadata.meta.get('build', {})
        build['string'] = output_metadata.build_id()
        output_metadata.meta['build'] = build

        # just for lack of confusion, don't show outputs in final rendered recipes
        if 'outputs' in output_metadata.meta:
            del output_metadata.meta['outputs']

        utils.sort_list_in_nested_structure(output_metadata.meta,
                                            ('build/script', 'test/commands'))

        rendered = output_yaml(output_metadata)

        if original_recipe:
            with open(original_recipe, 'rb') as f:
                original_recipe_text = UnicodeDammit(f.read()).unicode_markup

        if not original_recipe or not original_recipe_text == rendered:
            with open(join(recipe_dir, "meta.yaml"), 'w') as f:
                f.write("# This file created by conda-build {}\n".format(__version__))
                if original_recipe:
                    f.write("# meta.yaml template originally from:\n")
                    f.write("# " + source.get_repository_info(m.path) + "\n")
                f.write("# ------------------------------------------------\n\n")
                f.write(rendered)
            if original_recipe:
                utils.copy_into(original_recipe, os.path.join(recipe_dir, 'meta.yaml.template'),
                                timeout=m.config.timeout, locking=m.config.locking, clobber=True)

        # dump the full variant in use for this package to the recipe folder
        with open(os.path.join(recipe_dir, 'conda_build_config.yaml'), 'w') as f:
            yaml.dump(m.config.variant, f)


def copy_readme(m):
    readme = m.get_value('about/readme')
    if readme:
        src = join(m.config.work_dir, readme)
        if not isfile(src):
            sys.exit("Error: no readme file: %s" % readme)
        dst = join(m.config.info_dir, readme)
        utils.copy_into(src, dst, m.config.timeout, locking=m.config.locking)
        if os.path.split(readme)[1] not in {"README.md", "README.rst", "README"}:
            print("WARNING: anaconda.org only recognizes about/readme "
                  "as README.md and README.rst", file=sys.stderr)


def copy_license(m):
    license_file = m.get_value('about/license_file')
    if license_file:
        utils.copy_into(join(m.config.work_dir, license_file),
                        join(m.config.info_dir, 'LICENSE.txt'), m.config.timeout,
                        locking=m.config.locking)


def copy_test_source_files(m, destination):
    create_all_test_files(m, destination)
    test_deps = m.meta.get('test', {}).get('requires', [])
    if test_deps:
        with open(os.path.join(destination, 'test_time_dependencies.json'), 'w') as f:
            json.dump(test_deps, f)
    src_dir = None
    if os.listdir(m.config.work_dir):
        src_dir = m.config.work_dir
    elif hasattr(m.config, 'recipe_dir') and m.config.recipe_dir:
        src_dir = os.path.join(m.config.recipe_dir, 'info', 'test')

    if src_dir:
        for pattern in utils.ensure_list(m.get_value('test/source_files', [])):
            if utils.on_win and '\\' in pattern:
                raise RuntimeError("test/source_files paths must use / "
                                    "as the path delimiter on Windows")
            files = glob(join(src_dir, pattern))
            if not files:
                raise RuntimeError("Did not find any source_files for test with pattern %s",
                                   pattern)
            for f in files:
                try:
                    # disable locking to avoid locking a temporary directory (the extracted
                    #     test folder)
                    utils.copy_into(f, f.replace(src_dir, destination), m.config.timeout,
                            locking=False, clobber=True)
                except OSError as e:
                    log = logging.getLogger(__name__)
                    log.warn("Failed to copy {0} into test files.  Error was: {1}".format(f,
                                                                                          str(e)))
            for ext in '.pyc', '.pyo':
                for f in utils.get_ext_files(destination, ext):
                    os.remove(f)


def write_hash_input(m):
    recipe_input = m.get_hash_contents()
    with open(os.path.join(m.config.info_dir, 'hash_input.json'), 'w') as f:
        json.dump(recipe_input, f, indent=2)


def get_files_with_prefix(m, files, prefix):
    files_with_prefix = sorted(have_prefix_files(files, prefix))

    ignore_files = m.ignore_prefix_files()
    ignore_types = set()
    if not hasattr(ignore_files, "__iter__"):
        if ignore_files is True:
            ignore_types.update((FileMode.text.name, FileMode.binary.name))
        ignore_files = []
    if not m.get_value('build/detect_binary_files_with_prefix', True):
        ignore_types.update((FileMode.binary.name,))
    # files_with_prefix is a list of tuples containing (prefix_placeholder, file_type, file_path)
    ignore_files.extend(
        f[2] for f in files_with_prefix if f[1] in ignore_types and f[2] not in ignore_files)
    files_with_prefix = [f for f in files_with_prefix if f[2] not in ignore_files]
    return files_with_prefix


def detect_and_record_prefix_files(m, files, prefix):
    files_with_prefix = get_files_with_prefix(m, files, prefix)
    binary_has_prefix_files = m.binary_has_prefix_files()
    text_has_prefix_files = m.has_prefix_files()

    if files_with_prefix and not m.noarch:
        if utils.on_win:
            # Paths on Windows can contain spaces, so we need to quote the
            # paths. Fortunately they can't contain quotes, so we don't have
            # to worry about nested quotes.
            fmt_str = '"%s" %s "%s"\n'
        else:
            # Don't do it everywhere because paths on Unix can contain quotes,
            # and we don't have a good method of escaping, and because older
            # versions of conda don't support quotes in has_prefix
            fmt_str = '%s %s %s\n'

        with open(join(m.config.info_dir, 'has_prefix'), 'w') as fo:
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


def sanitize_channel(channel):
    return re.sub('\/t\/[a-zA-Z0-9\-]*\/', '/t/<TOKEN>/', channel)


def write_info_files_file(m, files):
    entry_point_scripts = m.get_value('build/entry_points')
    entry_point_script_names = get_entry_point_script_names(entry_point_scripts)

    mode_dict = {'mode': 'w', 'encoding': 'utf-8'} if PY3 else {'mode': 'wb'}
    with open(join(m.config.info_dir, 'files'), **mode_dict) as fo:
        if m.noarch == 'python':
            for f in sorted(files):
                if f.find("site-packages") >= 0:
                    fo.write(f[f.find("site-packages"):] + '\n')
                elif f.startswith("bin") and (f not in entry_point_script_names):
                    fo.write(f.replace("bin", "python-scripts") + '\n')
                elif f.startswith("Scripts") and (f not in entry_point_script_names):
                    fo.write(f.replace("Scripts", "python-scripts") + '\n')
                else:
                    fo.write(f + '\n')
        else:
            for f in sorted(files):
                fo.write(f + '\n')


def write_link_json(m):
    package_metadata = OrderedDict()
    noarch_type = m.get_value('build/noarch')
    if noarch_type:
        noarch_dict = OrderedDict(type=text_type(noarch_type))
        if text_type(noarch_type).lower() == "python":
            entry_points = m.get_value('build/entry_points')
            if entry_points:
                noarch_dict['entry_points'] = entry_points
        package_metadata['noarch'] = noarch_dict

    preferred_env = m.get_value("build/preferred_env")
    if preferred_env:
        preferred_env_dict = OrderedDict(name=text_type(preferred_env))
        executable_paths = m.get_value("build/preferred_env_executable_paths")
        if executable_paths:
            preferred_env_dict["executable_paths"] = executable_paths
        package_metadata["preferred_env"] = preferred_env_dict
    if package_metadata:
        # The original name of this file was info/package_metadata_version.json, but we've
        #   now changed it to info/link.json.  Still, we must indefinitely keep the key name
        #   package_metadata_version, or we break conda.
        package_metadata["package_metadata_version"] = 1
        with open(os.path.join(m.config.info_dir, "link.json"), 'w') as fh:
            fh.write(json.dumps(package_metadata, sort_keys=True, indent=2, separators=(',', ': ')))


def write_about_json(m):
    with open(join(m.config.info_dir, 'about.json'), 'w') as fo:
        d = {}
        for key in FIELDS["about"]:
            value = m.get_value('about/%s' % key)
            if value:
                d[key] = value

        # for sake of reproducibility, record some conda info
        d['conda_version'] = conda_version
        d['conda_build_version'] = conda_build_version
        # conda env will be in most, but not necessarily all installations.
        #    Don't die if we don't see it.
        stripped_channels = []
        for channel in get_rc_urls() + list(m.config.channel_urls):
            stripped_channels.append(sanitize_channel(channel))
        d['channels'] = stripped_channels
        evars = ['PATH', 'PYTHONPATH', 'PYTHONHOME', 'CONDA_DEFAULT_ENV',
                 'CIO_TEST', 'CONDA_ENVS_PATH']

        if cc_platform == 'linux':
            evars.append('LD_LIBRARY_PATH')
        elif cc_platform == 'osx':
            evars.append('DYLD_LIBRARY_PATH')
        d['env_vars'] = {ev: os.getenv(ev, '<not set>') for ev in evars}
        # this information will only be present in conda 4.2.10+
        try:
            d['conda_private'] = conda_private
        except (KeyError, AttributeError):
            pass
        env = environ.Environment(root_dir)
        d['root_pkgs'] = env.package_specs()
        json.dump(d, fo, indent=2, sort_keys=True)


def write_info_json(m):
    info_index = m.info_index()
    if m.pin_depends:
        # Wtih 'strict' depends, we will have pinned run deps during rendering
        if m.pin_depends == 'strict':
            runtime_deps = m.meta.get('requirements', {}).get('run', [])
            info_index['depends'] = runtime_deps
        else:
            runtime_deps = environ.get_pinned_deps(m, 'run')
        with open(join(m.config.info_dir, 'requires'), 'w') as fo:
            fo.write("""\
# This file as created when building:
#
#     %s.tar.bz2  (on '%s')
#
# It can be used to create the runtime environment of this package using:
# $ conda create --name <env> --file <this file>
""" % (m.dist(), m.config.build_subdir))
            for dist in sorted(runtime_deps + [' '.join(m.dist().rsplit('-', 2))]):
                fo.write('%s\n' % '='.join(dist.split()))

    # Deal with Python 2 and 3's different json module type reqs
    mode_dict = {'mode': 'w', 'encoding': 'utf-8'} if PY3 else {'mode': 'wb'}
    with open(join(m.config.info_dir, 'index.json'), **mode_dict) as fo:
        json.dump(info_index, fo, indent=2, sort_keys=True)


def write_no_link(m, files):
    no_link = m.get_value('build/no_link')
    if no_link:
        if not isinstance(no_link, list):
            no_link = [no_link]
        with open(join(m.config.info_dir, 'no_link'), 'w') as fo:
            for f in files:
                if any(fnmatch.fnmatch(f, p) for p in no_link):
                    fo.write(f + '\n')


def get_entry_point_script_names(entry_point_scripts):
    scripts = []
    for entry_point in entry_point_scripts:
        cmd = entry_point[:entry_point.find("=")].strip()
        if utils.on_win:
            scripts.append("Scripts\\%s-script.py" % cmd)
            scripts.append("Scripts\\%s.exe" % cmd)
        else:
            scripts.append("bin/%s" % cmd)
    return scripts


def write_run_exports(m):
    run_exports = m.meta.get('build', {}).get('run_exports', {})
    if run_exports:
        with open(os.path.join(m.config.info_dir, 'run_exports.yaml'), 'w') as f:
            if not hasattr(run_exports, 'keys'):
                run_exports = {'weak': run_exports}
            for k in ('weak', 'strong'):
                if k in run_exports:
                    run_exports[k] = utils.ensure_list(run_exports[k])
            yaml.dump(run_exports, f)


def create_info_files(m, files, prefix):
    '''
    Creates the metadata files that will be stored in the built package.

    :param m: Package metadata
    :type m: Metadata
    :param files: Paths to files to include in package
    :type files: list of str
    '''
    if utils.on_win:
        # make sure we use '/' path separators in metadata
        files = [_f.replace('\\', '/') for _f in files]

    if m.config.filename_hashing:
        write_hash_input(m)
    write_info_json(m)  # actually index.json
    write_about_json(m)
    write_link_json(m)
    write_run_exports(m)

    copy_recipe(m)
    copy_readme(m)
    copy_license(m)
    if m.config.copy_test_source_files:
        copy_test_source_files(m, join(m.config.info_dir, 'test'))

    write_info_files_file(m, files)

    files_with_prefix = get_files_with_prefix(m, files, prefix)
    checksums = create_info_files_json_v1(m, m.config.info_dir, prefix, files, files_with_prefix)

    detect_and_record_prefix_files(m, files, prefix)
    write_no_link(m, files)

    sources = m.get_section('source')
    if hasattr(sources, 'keys'):
        sources = [sources]

    with io.open(join(m.config.info_dir, 'git'), 'w', encoding='utf-8') as fo:
        for src in sources:
            if src.get('git_url'):
                source.git_info(os.path.join(m.config.work_dir, src.get('folder', '')),
                                verbose=m.config.verbose, fo=fo)

    if m.get_value('app/icon'):
        utils.copy_into(join(m.path, m.get_value('app/icon')),
                        join(m.config.info_dir, 'icon.png'),
                        m.config.timeout, locking=m.config.locking)
    return checksums


def get_short_path(m, target_file):
    entry_point_script_names = get_entry_point_script_names(m.get_value('build/entry_points'))
    if m.noarch == 'python':
        if target_file.find("site-packages") >= 0:
            return target_file[target_file.find("site-packages"):]
        elif target_file.startswith("bin") and (target_file not in entry_point_script_names):
            return target_file.replace("bin", "python-scripts")
        elif target_file.startswith("Scripts") and (target_file not in entry_point_script_names):
            return target_file.replace("Scripts", "python-scripts")
        else:
            return target_file
    elif m.get_value('build/noarch_python', None):
        return None
    else:
        return target_file


def sha256_checksum(filename, buffersize=65536):
    if not isfile(filename):
        return None
    sha256 = hashlib.sha256()
    with open(filename, 'rb') as f:
        for block in iter(lambda: f.read(buffersize), b''):
            sha256.update(block)
    return sha256.hexdigest()


def has_prefix(short_path, files_with_prefix):
    for prefix, mode, filename in files_with_prefix:
        if short_path == filename:
            return prefix, mode
    return None, None


def is_no_link(no_link, short_path):
    if no_link is not None and short_path in no_link:
        return True


def get_inode_paths(files, target_short_path, prefix):
    utils.ensure_list(files)
    target_short_path_inode = os.lstat(join(prefix, target_short_path)).st_ino
    hardlinked_files = [sp for sp in files
                        if os.lstat(join(prefix, sp)).st_ino == target_short_path_inode]
    return sorted(hardlinked_files)


def path_type(path):
    return PathType.softlink if islink(path) else PathType.hardlink


def build_info_files_json_v1(m, prefix, files, files_with_prefix):
    no_link_files = m.get_value('build/no_link')
    files_json = []
    for fi in sorted(files):
        prefix_placeholder, file_mode = has_prefix(fi, files_with_prefix)
        path = os.path.join(prefix, fi)
        file_info = {
            "_path": get_short_path(m, fi),
            "sha256": sha256_checksum(path),
            "size_in_bytes": os.path.getsize(path),
            "path_type": path_type(path),
        }
        no_link = is_no_link(no_link_files, fi)
        if no_link:
            file_info["no_link"] = no_link
        if prefix_placeholder and file_mode:
            file_info["prefix_placeholder"] = prefix_placeholder
            file_info["file_mode"] = file_mode
        if file_info.get("path_type") == PathType.hardlink and CrossPlatformStLink.st_nlink(
                join(prefix, fi)) > 1:
            inode_paths = get_inode_paths(files, fi, prefix)
            file_info["inode_paths"] = inode_paths
        files_json.append(file_info)
    return files_json


def create_info_files_json_v1(m, info_dir, prefix, files, files_with_prefix):
    # fields: "_path", "sha256", "size_in_bytes", "path_type", "file_mode",
    #         "prefix_placeholder", "no_link", "inode_paths"
    files_json_files = build_info_files_json_v1(m, prefix, files, files_with_prefix)
    files_json_info = {
        "paths_version": 1,
        "paths": files_json_files,
    }

    # don't create info/paths.json file if this is an old noarch package
    if not m.noarch_python:
        with open(join(info_dir, 'paths.json'), "w") as files_json:
            json.dump(files_json_info, files_json, sort_keys=True, indent=2, separators=(',', ': '),
                    cls=EntityEncoder)
    # Return a dict of file: sha1sum. We could (but currently do not)
    # use this to detect overlap and mutated overlap.
    checksums = dict()
    for file in files_json_files:
        checksums[file['_path']] = file['sha256']

    return checksums


def post_process_files(m, initial_prefix_files):
    get_build_metadata(m)
    create_post_scripts(m)

    # this is new-style noarch, with a value of 'python'
    if m.noarch != 'python':
        utils.create_entry_points(m.get_value('build/entry_points'), config=m.config)
    current_prefix_files = utils.prefix_files(prefix=m.config.host_prefix)

    python = (m.config.build_python if os.path.isfile(m.config.build_python) else
              m.config.host_python)
    post_process(sorted(current_prefix_files - initial_prefix_files),
                    prefix=m.config.host_prefix,
                    config=m.config,
                    preserve_egg_dir=bool(m.get_value('build/preserve_egg_dir')),
                    noarch=m.get_value('build/noarch'),
                    skip_compile_pyc=m.get_value('build/skip_compile_pyc'))

    # The post processing may have deleted some files (like easy-install.pth)
    current_prefix_files = utils.prefix_files(prefix=m.config.host_prefix)
    new_files = sorted(current_prefix_files - initial_prefix_files)
    new_files = utils.filter_files(new_files, prefix=m.config.host_prefix)

    if any(m.config.meta_dir in join(m.config.host_prefix, f) for f in new_files):
        meta_files = (tuple(f for f in new_files if m.config.meta_dir in
                join(m.config.host_prefix, f)),)
        sys.exit(indent("""Error: Untracked file(s) %s found in conda-meta directory.
This error usually comes from using conda in the build script.  Avoid doing this, as it
can lead to packages that include their dependencies.""" % meta_files))
    post_build(m, new_files, build_python=python)

    entry_point_script_names = get_entry_point_script_names(m.get_value('build/entry_points'))
    if m.noarch == 'python':
        pkg_files = [fi for fi in new_files if fi not in entry_point_script_names]
    else:
        pkg_files = new_files

    # the legacy noarch
    if m.get_value('build/noarch_python'):
        noarch_python.transform(m, new_files, m.config.host_prefix)
    # new way: build/noarch: python
    elif m.noarch == 'python':
        noarch_python.populate_files(m, pkg_files, m.config.host_prefix, entry_point_script_names)

    current_prefix_files = utils.prefix_files(prefix=m.config.host_prefix)
    new_files = current_prefix_files - initial_prefix_files
    fix_permissions(new_files, m.config.host_prefix)

    return new_files


def bundle_conda(output, metadata, env, **kw):
    log = utils.get_logger(__name__)
    log.info('Packaging %s', metadata.dist())

    files = output.get('files', [])

    try:
        os.makedirs(metadata.config.host_prefix)
    except OSError:
        pass

    # Use script from recipe?
    script = utils.ensure_list(metadata.get_value('build/script', None))

    # need to treat top-level stuff specially.  build/script in top-level stuff should not be
    #     re-run for an output with a similar name to the top-level recipe
    is_output = 'package:' not in metadata.get_recipe_text()
    top_build = metadata.get_top_level_recipe_without_outputs().get('build', {}) or {}
    activate_script = metadata.activate_build_script
    if (script and not output.get('script')) and (is_output or not top_build.get('script')):
        # do add in activation, but only if it's not disabled
        activate_script = metadata.config.activate
        script = '\n'.join(script)
        suffix = "bat" if utils.on_win else "sh"
        script_fn = output.get('script') or 'output_script.{}'.format(suffix)
        with open(os.path.join(metadata.config.work_dir, script_fn), 'w') as f:
            f.write('\n')
            f.write(script)
            f.write('\n')
        output['script'] = script_fn

    if output.get('script'):
        env = environ.get_dict(config=metadata.config, m=metadata)

        interpreter = output.get('script_interpreter')
        if not interpreter:
            interpreter = guess_interpreter(output['script'])
        initial_files = utils.prefix_files(metadata.config.host_prefix)
        env_output = env.copy()
        env_output['TOP_PKG_NAME'] = env['PKG_NAME']
        env_output['TOP_PKG_VERSION'] = env['PKG_VERSION']
        env_output['PKG_VERSION'] = metadata.version()
        env_output['PKG_NAME'] = metadata.get_value('package/name')
        for var in utils.ensure_list(metadata.get_value('build/script_env')):
            if var not in os.environ:
                raise ValueError("env var '{}' specified in script_env, but is not set."
                                    .format(var))
            env_output[var] = os.environ[var]
        dest_file = os.path.join(metadata.config.work_dir, output['script'])
        recipe_dir = (metadata.path or
                      metadata.meta.get('extra', {}).get('parent_recipe', {}).get('path', ''))
        utils.copy_into(os.path.join(recipe_dir, output['script']), dest_file)
        if activate_script:
            _write_activation_text(dest_file, metadata)
        utils.check_call_env(interpreter.split(' ') + [dest_file],
                            cwd=metadata.config.work_dir, env=env_output)
    elif files:
        # Files is specified by the output
        # we exclude the list of files that we want to keep, so post-process picks them up as "new"
        keep_files = set(os.path.normpath(pth)
                         for pth in utils.expand_globs(files, metadata.config.host_prefix))
        pfx_files = set(utils.prefix_files(metadata.config.host_prefix))
        initial_files = set(item for item in (pfx_files - keep_files)
                            if not any(keep_file.startswith(item + os.path.sep)
                                       for keep_file in keep_files))
        initial_files = set(item for item in (pfx_files - keep_files)
                            if not any(keep_file.startswith(item + os.path.sep)
                                       for keep_file in keep_files))
    else:
        if not metadata.always_include_files():
            log.warn("No files or script found for output {}".format(output.get('name')))
        initial_files = set(utils.prefix_files(metadata.config.host_prefix))

    for pat in metadata.always_include_files():
        has_matches = False
        for f in set(initial_files):
            if fnmatch.fnmatch(f, pat):
                print("Including in package existing file", f)
                initial_files.remove(f)
                has_matches = True
        if not has_matches:
            log.warn("Glob %s from always_include_files does not match any files", pat)
    files = post_process_files(metadata, initial_files)

    if output.get('name') and output.get('name') != 'conda':
        assert 'bin/conda' not in files and 'Scripts/conda.exe' not in files, ("Bug in conda-build "
            "has included conda binary in package. Please report this on the conda-build issue "
            "tracker.")

    output_filename = ('-'.join([output['name'], metadata.version(),
                                 metadata.build_id()]) + '.tar.bz2')
    # first filter is so that info_files does not pick up ignored files
    files = utils.filter_files(files, prefix=metadata.config.host_prefix)
    output['checksums'] = create_info_files(metadata, files, prefix=metadata.config.host_prefix)
    for ext in ('.py', '.r', '.pl', '.lua', '.sh'):
        test_dest_path = os.path.join(metadata.config.info_dir, 'test', 'run_test' + ext)
        script = output.get('test', {}).get('script')
        if script and script.endswith(ext):
            utils.copy_into(os.path.join(metadata.config.work_dir, output['test']['script']),
                            test_dest_path, metadata.config.timeout,
                            locking=metadata.config.locking)
        elif os.path.isfile(test_dest_path) and metadata.meta.get('extra', {}).get('parent_recipe'):
            # the test belongs to the parent recipe.  Don't include it in subpackages.
            utils.rm_rf(test_dest_path)
    # here we add the info files into the prefix, so we want to re-collect the files list
    prefix_files = set(utils.prefix_files(metadata.config.host_prefix))
    files = utils.filter_files(prefix_files - initial_files, prefix=metadata.config.host_prefix)

    with TemporaryDirectory() as tmp:
        tmp_path = os.path.join(tmp, os.path.basename(output_filename))
        t = tarfile.open(tmp_path, 'w:bz2')

        def order(f):
            # we don't care about empty files so send them back via 100000
            fsize = os.stat(join(metadata.config.host_prefix, f)).st_size or 100000
            # info/* records will be False == 0, others will be 1.
            info_order = int(os.path.dirname(f) != 'info')
            return info_order, fsize

        # add files in order of a) in info directory, b) increasing size so
        # we can access small manifest or json files without decompressing
        # possible large binary or data files
        for f in sorted(files, key=order):
            t.add(join(metadata.config.host_prefix, f), f)
        t.close()

        # we're done building, perform some checks
        tarcheck.check_all(tmp_path, metadata.config)
        if getattr(metadata.config, "verify", False):
            verifier = Verify()
            ignore_scripts = metadata.config.ignore_package_verify_scripts if \
                             metadata.config.ignore_package_verify_scripts else None
            run_scripts = metadata.config.run_package_verify_scripts if \
                          metadata.config.run_package_verify_scripts else None
            verifier.verify_package(ignore_scripts=ignore_scripts, run_scripts=run_scripts,
                                    path_to_package=tmp_path)
        try:
            crossed_subdir = metadata.config.target_subdir
        except AttributeError:
            crossed_subdir = metadata.config.host_subdir
        subdir = ('noarch' if (metadata.noarch or metadata.noarch_python)
                  else crossed_subdir)
        if metadata.config.output_folder:
            output_folder = os.path.join(metadata.config.output_folder, subdir)
        else:
            output_folder = os.path.join(os.path.dirname(metadata.config.bldpkgs_dir), subdir)
        final_output = os.path.join(output_folder, output_filename)
        if os.path.isfile(final_output):
            utils.rm_rf(final_output)

        # disable locking here.  It's just a temp folder getting locked.  Removing it proved to be
        #    a major bottleneck.
        utils.copy_into(tmp_path, final_output, metadata.config.timeout,
                        locking=False)
    update_index(output_folder, verbose=metadata.config.verbose, locking=metadata.config.locking,
                 timeout=metadata.config.timeout)

    # HACK: conda really wants a noarch folder to be around.  Create it as necessary.
    if os.path.basename(output_folder) != 'noarch':
        try:
            os.makedirs(os.path.join(os.path.dirname(output_folder), 'noarch'))
        except OSError:
            pass
        update_index(os.path.join(os.path.dirname(output_folder), 'noarch'),
                     verbose=metadata.config.verbose, locking=metadata.config.locking,
                    timeout=metadata.config.timeout)

    # clean out host prefix so that this output's files don't interfere with other outputs
    #   We have a backup of how things were before any output scripts ran.  That's
    #   restored elsewhere.
    utils.rm_rf(metadata.config.host_prefix)

    return final_output


def bundle_wheel(output, metadata, env):
    with TemporaryDirectory() as tmpdir, utils.tmp_chdir(metadata.config.work_dir):
        utils.check_call_env(['pip', 'wheel', '--wheel-dir', tmpdir, '--no-deps', '.'], env=env)
        wheel_files = glob(os.path.join(tmpdir, "*.whl"))
        if not wheel_files:
            raise RuntimeError("Wheel creation failed.  Please see output above to debug.")
        wheel_file = wheel_files[0]
        if metadata.config.output_folder:
            output_folder = os.path.join(metadata.config.output_folder, metadata.config.subdir)
        else:
            output_folder = metadata.config.bldpkgs_dir
        utils.copy_into(wheel_file, output_folder, locking=metadata.config.locking)
    return os.path.join(output_folder, os.path.basename(wheel_file))


def scan_metadata(path):
    '''
    Scan all json files in 'path' and return a dictionary with their contents.
    Files are assumed to be in 'index.json' format.
    '''
    installed = dict()
    for filename in glob(os.path.join(path, '*.json')):
        with open(filename) as file:
            data = json.load(file)
            installed[data['name']] = data
    return installed


bundlers = {
    'conda': bundle_conda,
    'wheel': bundle_wheel,
}


def _write_sh_activation_text(file_handle, m):
    file_handle.write('source "{0}activate" "{1}"\n'
                .format(utils.root_script_dir + os.path.sep,
                        m.config.build_prefix))

    # conda 4.4 requires a conda-meta/history file for a valid conda prefix
    history_file = join(m.config.build_prefix, 'conda-meta', 'history')
    if not isfile(history_file):
        if not isdir(dirname(history_file)):
            os.makedirs(dirname(history_file))
        open(history_file, 'a').close()

    if m.is_cross:
        # HACK: we need both build and host envs "active" - i.e. on PATH,
        #     and with their activate.d scripts sourced. Conda only
        #     lets us activate one, though. This is a
        #     vile hack to trick conda into "stacking"
        #     two environments.
        #
        # Net effect: binaries come from host first, then build
        #
        # Conda 4.4 may break this by reworking the activate scripts.
        #  ^^ shouldn't be true
        # In conda 4.4, export CONDA_MAX_SHLVL=2 to stack envs to two
        #   levels deep.
        # conda 4.4 does require that a conda-meta/history file
        #   exists to identify a valid conda environment
        history_file = join(m.config.host_prefix, 'conda-meta', 'history')
        if not isfile(history_file):
            if not isdir(dirname(history_file)):
                os.makedirs(dirname(history_file))
            open(history_file, 'a').close()
        file_handle.write('unset CONDA_PATH_BACKUP\n')
        file_handle.write('export CONDA_MAX_SHLVL=2\n')
        file_handle.write('source "{0}activate" "{1}"\n'
                          .format(utils.root_script_dir + os.path.sep,
                                  m.config.host_prefix))


def _write_activation_text(script_path, m):
    with open(script_path, 'r+') as fh:
        data = fh.read()
        fh.seek(0)
        if os.path.splitext(script_path)[1].lower() == ".bat":
            windows._write_bat_activation_text(fh, m)
        elif os.path.splitext(script_path)[1].lower() == ".sh":
            _write_sh_activation_text(fh, m)
        else:
            log = utils.get_logger(__name__)
            log.warn("not adding activation to {} - I don't know how to do so for "
                        "this file type".format(script_path))
        fh.write(data)


def build(m, post=None, need_source_download=True, need_reparse_in_env=False, built_packages=None,
          notest=False):
    '''
    Build the package with the specified metadata.

    :param m: Package metadata
    :type m: Metadata
    :type post: bool or None. None means run the whole build. True means run
    post only. False means stop just before the post.
    :type need_source_download: bool: if rendering failed to download source
    (due to missing tools), retry here after build env is populated
    '''
    default_return = {}
    if not built_packages:
        built_packages = {}

    if m.skip():
        print(utils.get_skip_message(m))
        return default_return

    log = utils.get_logger(__name__)
    host_actions = []
    build_actions = []
    output_metas = []

    with utils.path_prepended(m.config.build_prefix):
        env = environ.get_dict(config=m.config, m=m)
    env["CONDA_BUILD_STATE"] = "BUILD"
    if env_path_backup_var_exists:
        env["CONDA_PATH_BACKUP"] = os.environ["CONDA_PATH_BACKUP"]

    # this should be a no-op if source is already here
    if m.needs_source_for_render:
        try_download(m, no_download_source=False)

    if post in [False, None]:
        output_metas = expand_outputs([(m, need_source_download, need_reparse_in_env)])

        if m.config.skip_existing:
            # TODO: should we check both host and build envs?  These are the same, except when
            #    cross compiling.
            package_locations = [is_package_built(om, 'host') for _, om in output_metas]
            if all(package_locations):
                print("Packages for ", m.path or m.name(),
                        "are already built in {0}, skipping.".format(package_locations))
                return default_return
            else:
                package_locations = [bldpkg_path(om) for _, om in output_metas if not om.skip()]
        else:
            package_locations = [bldpkg_path(om) for _, om in output_metas if not om.skip()]

        print("BUILD START:", [os.path.basename(pkg) for pkg in package_locations])

        specs = [ms.spec for ms in m.ms_depends('build')]
        if any(out.get('type') == 'wheel' for out in m.meta.get('outputs', [])):
            specs.extend(['pip', 'wheel'])

        vcs_source = m.uses_vcs_in_build
        if vcs_source and vcs_source not in specs:
            vcs_executable = "hg" if vcs_source == "mercurial" else vcs_source
            has_vcs_available = os.path.isfile(external.find_executable(vcs_executable,
                                                                m.config.build_prefix) or "")
            if not has_vcs_available:
                if (vcs_source != "mercurial" or
                        not any(spec.startswith('python') and "3." in spec
                                for spec in specs)):
                    specs.append(vcs_source)

                    log.warn("Your recipe depends on %s at build time (for templates), "
                             "but you have not listed it as a build dependency.  Doing "
                             "so for this build.", vcs_source)
                else:
                    raise ValueError("Your recipe uses mercurial in build, but mercurial"
                                    " does not yet support Python 3.  Please handle all of "
                                    "your mercurial actions outside of your build script.")

        exclude_pattern = None
        excludes = set(m.config.variant.get('ignore_version', []))

        for key in m.config.variant.get('pin_run_as_build', {}).keys():
            if key in excludes:
                excludes.remove(key)

        output_excludes = set()
        if hasattr(m, 'other_outputs'):
            output_excludes = set(name for (name, variant) in m.other_outputs.keys())

        if excludes or output_excludes:
            exclude_pattern = re.compile('|'.join('(?:^{}(?:\s|$|\Z))'.format(exc)
                                            for exc in excludes | output_excludes))

        # this metadata object may not be finalized - the outputs are, but this is the
        #     top-level metadata.  We need to make sure that the variant pins are added in.
        utils.insert_variant_versions(m.meta.get('requirements', {}), m.config.variant, 'build')
        utils.insert_variant_versions(m.meta.get('requirements', {}), m.config.variant, 'host')
        add_upstream_pins(m, False, exclude_pattern)

        build_ms_deps = m.ms_depends('build')
        build_ms_deps = [utils.ensure_valid_spec(spec) for spec in build_ms_deps]
        host_ms_deps = m.ms_depends('host')
        host_ms_deps = [utils.ensure_valid_spec(spec) for spec in host_ms_deps]

        if m.is_cross and not m.config.build_is_host:
            if VersionOrder(conda_version) < VersionOrder('4.3.2'):
                raise RuntimeError("Non-native subdir support only in conda >= 4.3.2")

            host_actions = environ.get_install_actions(m.config.host_prefix,
                                                       tuple(host_ms_deps), 'host',
                                                       subdir=m.config.host_subdir,
                                                       debug=m.config.debug,
                                                       verbose=m.config.verbose,
                                                       locking=m.config.locking,
                                                       bldpkgs_dirs=tuple(m.config.bldpkgs_dirs),
                                                       timeout=m.config.timeout,
                                                       disable_pip=m.config.disable_pip,
                                                       max_env_retry=m.config.max_env_retry,
                                                       output_folder=m.config.output_folder,
                                                       channel_urls=tuple(m.config.channel_urls))
            environ.create_env(m.config.host_prefix, host_actions, env='host', config=m.config,
                               subdir=m.config.host_subdir, is_cross=m.is_cross,
                               is_conda=m.name() == 'conda')
        if m.config.build_is_host:
            build_ms_deps.extend(host_ms_deps)
        build_actions = environ.get_install_actions(m.config.build_prefix,
                                                    tuple(build_ms_deps), 'build',
                                                    subdir=m.config.build_subdir,
                                                    debug=m.config.debug,
                                                    verbose=m.config.verbose,
                                                    locking=m.config.locking,
                                                    bldpkgs_dirs=tuple(m.config.bldpkgs_dirs),
                                                    timeout=m.config.timeout,
                                                    disable_pip=m.config.disable_pip,
                                                    max_env_retry=m.config.max_env_retry,
                                                    output_folder=m.config.output_folder,
                                                    channel_urls=tuple(m.config.channel_urls))

        try:
            if not notest:
                utils.insert_variant_versions(m.meta.get('requirements', {}),
                                              m.config.variant, 'run')
                test_run_ms_deps = m.get_value('test/requires', []) + \
                                   m.get_value('requirements/run', [])
                # make sure test deps are available before taking time to create build env
                environ.get_install_actions(m.config.test_prefix,
                                            tuple(test_run_ms_deps), 'test',
                                            subdir=m.config.host_subdir,
                                            debug=m.config.debug,
                                            verbose=m.config.verbose,
                                            locking=m.config.locking,
                                            bldpkgs_dirs=tuple(m.config.bldpkgs_dirs),
                                            timeout=m.config.timeout,
                                            disable_pip=m.config.disable_pip,
                                            max_env_retry=m.config.max_env_retry,
                                            output_folder=m.config.output_folder,
                                            channel_urls=tuple(m.config.channel_urls))
        except DependencyNeedsBuildingError as e:
            # subpackages are not actually missing.  We just haven't built them yet.
            from .conda_interface import MatchSpec
            missing_deps = set(MatchSpec(pkg).name for pkg in e.packages) - set(
                out.name() for _, out in m.get_output_metadata_set(permit_undefined_jinja=True)
            )
            if missing_deps:
                e.packages = missing_deps
                raise e
        if (not m.config.dirty or not os.path.isdir(m.config.build_prefix) or
                not os.listdir(m.config.build_prefix)):
            environ.create_env(m.config.build_prefix, build_actions, env='build',
                               config=m.config, subdir=m.config.build_subdir,
                               is_cross=m.is_cross, is_conda=m.name() == 'conda')

        # this check happens for the sake of tests, but let's do it before the build so we don't
        #     make people wait longer only to see an error
        warn_on_use_of_SRC_DIR(m)

        # Execute any commands fetching the source (e.g., git) in the _build environment.
        # This makes it possible to provide source fetchers (eg. git, hg, svn) as build
        # dependencies.

        with utils.path_prepended(m.config.build_prefix):
            try_download(m, no_download_source=False, raise_error=True)
        if need_source_download and not m.final:
            m.parse_until_resolved(allow_no_other_outputs=True)

        elif need_reparse_in_env:
            m = reparse(m)

        # get_dir here might be just work, or it might be one level deeper,
        #    dependening on the source.
        src_dir = m.config.work_dir
        if isdir(src_dir):
            print("source tree in:", src_dir)
        else:
            print("no source - creating empty work folder")
            os.makedirs(src_dir)

        utils.rm_rf(m.config.info_dir)
        files1 = utils.prefix_files(prefix=m.config.host_prefix)
        with open(join(m.config.build_folder, 'prefix_files.txt'), 'w') as f:
            f.write(u'\n'.join(sorted(list(files1))))
            f.write(u'\n')

        # Use script from recipe?
        script = utils.ensure_list(m.get_value('build/script', None))
        if script:
            script = '\n'.join(script)

        if isdir(src_dir):
            if utils.on_win:
                build_file = join(m.path, 'bld.bat')
                if script:
                    build_file = join(src_dir, 'bld.bat')
                    with open(build_file, 'w') as bf:
                        bf.write(script)
                windows.build(m, build_file)
            else:
                build_file = join(m.path, 'build.sh')
                if isfile(build_file) and script:
                    raise CondaBuildException("Found a build.sh script and a build/script section"
                                              "inside meta.yaml. Either remove the build.sh script "
                                              "or remove the build/script section in meta.yaml.")
                # There is no sense in trying to run an empty build script.
                if isfile(build_file) or script:

                    with utils.path_prepended(m.config.build_prefix):
                        env = environ.get_dict(config=m.config, m=m)
                    env["CONDA_BUILD_STATE"] = "BUILD"

                    work_file = join(m.config.work_dir, 'conda_build.sh')
                    with open(work_file, 'w') as bf:
                        for k, v in env.items():
                            if v:
                                bf.write('export {0}="{1}"\n'.format(k, v))

                        if m.config.activate and not m.name() == 'conda':
                            _write_sh_activation_text(bf, m)
                        if script:
                                bf.write(script)
                        if isfile(build_file) and not script:
                            bf.write(open(build_file).read())

                    os.chmod(work_file, 0o766)

                    cmd = [shell_path] + (['-x'] if m.config.debug else []) + ['-e', work_file]
                    # this should raise if any problems occur while building
                    utils.check_call_env(cmd, env=env, cwd=src_dir)
                    utils.remove_pycache_from_scripts(m.config.host_prefix)

    prefix_file_list = join(m.config.build_folder, 'prefix_files.txt')
    initial_files = set()
    if os.path.isfile(prefix_file_list):
        with open(prefix_file_list) as f:
            initial_files = set(f.read().splitlines())
    new_prefix_files = utils.prefix_files(prefix=m.config.host_prefix) - initial_files

    new_pkgs = default_return
    if post in [True, None]:
        outputs = output_metas or m.get_output_metadata_set(permit_unsatisfiable_variants=False)
        top_level_meta = m

        # this is the old, default behavior: conda package, with difference between start
        #    set of files and end set of files
        prefix_file_list = join(m.config.build_folder, 'prefix_files.txt')
        if os.path.isfile(prefix_file_list):
            with open(prefix_file_list) as f:
                initial_files = set(f.read().splitlines())
        else:
            initial_files = set()

        # subdir needs to always be some real platform - so ignore noarch.
        subdir = (m.config.host_subdir if m.config.host_subdir != 'noarch' else
                    m.config.subdir)

        with TemporaryDirectory() as prefix_files_backup:
            # back up new prefix files, because we wipe the prefix before each output build
            for f in new_prefix_files:
                utils.copy_into(os.path.join(m.config.host_prefix, f),
                                os.path.join(prefix_files_backup, f),
                                symlinks=True)
            for (output_d, m) in outputs:
                if m.skip():
                    print(utils.get_skip_message(m))
                    continue
                if (top_level_meta.name() == output_d.get('name') and not (output_d.get('files') or
                                                                           output_d.get('script'))):
                    output_d['files'] = (utils.prefix_files(prefix=m.config.host_prefix) -
                                         initial_files)

                meta_dir = (m.meta_path or
                            m.meta.get('extra', {}).get('parent_recipe', {}).get('path'))
                if meta_dir and meta_dir.endswith('.yaml'):
                    meta_dir = os.path.dirname(meta_dir)
                # ensure that packaging scripts are copied over into the workdir
                if 'script' in output_d and meta_dir:
                    utils.copy_into(os.path.join(meta_dir, output_d['script']), m.config.work_dir)

                # same thing, for test scripts
                test_script = output_d.get('test', {}).get('script')
                if test_script and meta_dir:
                    if not os.path.isfile(os.path.join(meta_dir, test_script)):
                        raise ValueError("test script specified as {} does not exist.  Please "
                                         "check for typos or create the file and try again."
                                         .format(test_script))
                    utils.copy_into(os.path.join(meta_dir, test_script),
                                    os.path.join(m.config.work_dir, test_script))

                assert output_d.get('type') != 'conda' or m.final, (
                    "output metadata for {} is not finalized".format(m.dist()))
                pkg_path = bldpkg_path(m)
                if pkg_path not in built_packages and pkg_path not in new_pkgs:
                    log.info("Packaging {}".format(m.name()))
                    # for more than one output, we clear and rebuild the environment before each
                    #    package.  We also do this for single outputs that present their own
                    #    build reqs.
                    if not (m.meta['extra'].get('parent_recipe') or
                            (os.path.isdir(m.config.host_prefix) and
                             len(os.listdir(m.config.host_prefix)) <= 1)):
                        log.debug('Not creating new env for output - already exists from top-level')
                    else:
                        utils.rm_rf(m.config.host_prefix)
                        utils.rm_rf(m.config.build_prefix)
                        utils.rm_rf(m.config.test_prefix)

                        host_ms_deps = m.ms_depends('host')
                        sub_build_ms_deps = m.ms_depends('build')
                        if m.is_cross and not m.config.build_is_host:
                            host_actions = environ.get_install_actions(m.config.host_prefix,
                                                    tuple(host_ms_deps), 'host',
                                                    subdir=m.config.host_subdir,
                                                    debug=m.config.debug,
                                                    verbose=m.config.verbose,
                                                    locking=m.config.locking,
                                                    bldpkgs_dirs=tuple(m.config.bldpkgs_dirs),
                                                    timeout=m.config.timeout,
                                                    disable_pip=m.config.disable_pip,
                                                    max_env_retry=m.config.max_env_retry,
                                                    output_folder=m.config.output_folder,
                                                    channel_urls=tuple(m.config.channel_urls))
                            environ.create_env(m.config.host_prefix, host_actions, env='host',
                                               config=m.config, subdir=subdir, is_cross=m.is_cross,
                                               is_conda=m.name() == 'conda')
                        else:
                            # When not cross-compiling, the build deps aggregate 'build' and 'host'.
                            sub_build_ms_deps.extend(host_ms_deps)
                        build_actions = environ.get_install_actions(m.config.build_prefix,
                                                    tuple(sub_build_ms_deps), 'build',
                                                    subdir=m.config.build_subdir,
                                                    debug=m.config.debug,
                                                    verbose=m.config.verbose,
                                                    locking=m.config.locking,
                                                    bldpkgs_dirs=tuple(m.config.bldpkgs_dirs),
                                                    timeout=m.config.timeout,
                                                    disable_pip=m.config.disable_pip,
                                                    max_env_retry=m.config.max_env_retry,
                                                    output_folder=m.config.output_folder,
                                                    channel_urls=tuple(m.config.channel_urls))
                        environ.create_env(m.config.build_prefix, build_actions, env='build',
                                           config=m.config, subdir=m.config.build_subdir,
                                           is_cross=m.is_cross,
                                           is_conda=m.name() == 'conda')

                    to_remove = set()
                    for f in output_d.get('files', []):
                        if f.startswith('conda-meta'):
                            to_remove.add(f)

                    if 'files' in output_d:
                        output_d['files'] = set(output_d['files']) - to_remove

                    # copies the backed-up new prefix files into the newly created host env
                    for f in new_prefix_files:
                        utils.copy_into(os.path.join(prefix_files_backup, f),
                                        os.path.join(m.config.host_prefix, f),
                                        symlinks=True)

                    # we must refresh the environment variables because our env for each package
                    #    can be different from the env for the top level build.
                    with utils.path_prepended(m.config.build_prefix):
                        env = environ.get_dict(config=m.config, m=m)
                    built_package = bundlers[output_d.get('type', 'conda')](output_d, m, env)
                    # warn about overlapping files.
                    if 'checksums' in output_d:
                        for file, csum in output_d['checksums'].items():
                            for _, prev_om in new_pkgs.items():
                                prev_output_d, _ = prev_om
                                if file in prev_output_d['checksums']:
                                    prev_csum = prev_output_d['checksums'][file]
                                    nature = 'Exact' if csum == prev_csum else 'Inexact'
                                    log.warn("{} overlap between {} in packages {} and {}"
                                             .format(nature, file, output_d['name'],
                                                     prev_output_d['name']))
                    new_pkgs[built_package] = (output_d, m)

                    # must rebuild index because conda has no way to incrementally add our last
                    #    package to the index.

                    subdir = ('noarch' if (m.noarch or m.noarch_python)
                              else m.config.host_subdir)
                    if m.is_cross:
                        host_index, host_ts = get_build_index(subdir=subdir,
                                                              bldpkgs_dir=m.config.bldpkgs_dir,
                                                              output_folder=m.config.output_folder,
                                                              channel_urls=m.config.channel_urls,
                                                              debug=m.config.debug,
                                                              verbose=m.config.verbose,
                                                              locking=m.config.locking,
                                                              timeout=m.config.timeout,
                                                              clear_cache=True)
                    index, index_timestamp = get_build_index(subdir=subdir,
                                                             bldpkgs_dir=m.config.bldpkgs_dir,
                                                             output_folder=m.config.output_folder,
                                                             channel_urls=m.config.channel_urls,
                                                             debug=m.config.debug,
                                                             verbose=m.config.verbose,
                                                             locking=m.config.locking,
                                                             timeout=m.config.timeout,
                                                             clear_cache=True)
    else:
        print("STOPPING BUILD BEFORE POST:", m.dist())

    # return list of all package files emitted by this build
    return new_pkgs


def guess_interpreter(script_filename):
    # -l is needed for MSYS2 as the login scripts set some env. vars (TMP, TEMP)
    # Since the MSYS2 installation is probably a set of conda packages we do not
    # need to worry about system environmental pollution here. For that reason I
    # do not pass -l on other OSes.
    extensions_to_run_commands = {'.sh': 'bash{}'.format(' -l' if utils.on_win else ''),
                                  '.bat': 'cmd /d /c',
                                  '.ps1': 'powershell -executionpolicy bypass -File',
                                  '.py': 'python'}
    file_ext = os.path.splitext(script_filename)[1]
    for ext, command in extensions_to_run_commands.items():
        if file_ext.lower().startswith(ext):
            interpreter_command = command
            break
    else:
        raise NotImplementedError("Don't know how to run {0} file.   Please specify "
                                  "script_interpreter for {1} output".format(file_ext,
                                                                             script_filename))
    return interpreter_command


def warn_on_use_of_SRC_DIR(metadata):
    test_files = glob(os.path.join(metadata.path, 'run_test*'))
    for f in test_files:
        with open(f) as _f:
            contents = _f.read()
        if ("SRC_DIR" in contents and 'source_files' not in metadata.get_section('test') and
                metadata.config.remove_work_dir):
            raise ValueError("In conda-build 2.1+, the work dir is removed by default before the "
                             "test scripts run.  You are using the SRC_DIR variable in your test "
                             "script, but these files have been deleted.  Please see the "
                             " documentation regarding the test/source_files meta.yaml section, "
                             "or pass the --no-remove-work-dir flag.")


def _construct_metadata_for_test_from_recipe(recipe_dir, config):
    config.need_cleanup = False
    config.recipe_dir = None
    hash_input = {}
    metadata = render_recipe(recipe_dir, config=config, reset_build_id=False)[0][0]

    utils.rm_rf(metadata.config.test_dir)

    if metadata.meta.get('test', {}).get('source_files'):
        if not metadata.source_provided:
            try_download(metadata, no_download_source=False)
    if not metadata.final:
        metadata = finalize_metadata(metadata)
    return metadata, hash_input


def _construct_metadata_for_test_from_package(package, config):
    recipe_dir, need_cleanup = utils.get_recipe_abspath(package)
    config.need_cleanup = need_cleanup
    config.recipe_dir = recipe_dir
    hash_input = {}

    info_dir = os.path.normpath(os.path.join(recipe_dir, 'info'))
    with open(os.path.join(info_dir, 'index.json')) as f:
        package_data = json.load(f)

    if package_data['subdir'] != 'noarch':
        config.host_subdir = package_data['subdir']
    # We may be testing an (old) package built without filename hashing.
    hash_input = os.path.join(info_dir, 'hash_input.json')
    if os.path.isfile(hash_input):
        with open(os.path.join(info_dir, 'hash_input.json')) as f:
            hash_input = json.load(f)
    else:
        config.filename_hashing = False
        hash_input = {}
    # not actually used as a variant, since metadata will have been finalized.
    #    This is still necessary for computing the hash correctly though
    config.variant = hash_input

    log = utils.get_logger(__name__)

    # get absolute file location
    local_pkg_location = os.path.normpath(os.path.abspath(os.path.dirname(package)))

    # get last part of the path
    last_element = os.path.basename(local_pkg_location)
    is_channel = False
    for platform in ('win-', 'linux-', 'osx-', 'noarch'):
        if last_element.startswith(platform):
            is_channel = True

    if not is_channel:
        raise ValueError("Your package must reside in a channel structure with "
                         "platform-subfolders.  See more info at what a valid channel is "
                         "at https://conda.io/docs/user-guide/tasks/create-custom-channels.html")

    # get channel url
    local_channel = os.path.dirname(local_pkg_location)

    # update indices in the channel
    for pattern in ('win-*', 'linux-*', 'osx-*', 'noarch'):
        for folder in glob(os.path.join(local_channel, pattern)):
            log.info("Updating index at %s to make package installable with dependencies" % folder)
            update_index(folder)

    # make an url out of the channel and add to channel list
    local_channel_url = url_path(local_channel)

    # channel_urls is an iterable, but we don't know if it's a tuple or list.  Don't know
    #    how to add elements.
    config.channel_urls = list(config.channel_urls)
    config.channel_urls.insert(0, local_channel_url)

    try:
        metadata = render_recipe(os.path.join(info_dir, 'recipe'), config=config,
                                        reset_build_id=False)[0][0]

    # no recipe in package.  Fudge metadata
    except (IOError, SystemExit, OSError):
        # force the build string to line up - recomputing it would
        #    yield a different result
        metadata = MetaData.fromdict({'package': {'name': package_data['name'],
                                                  'version': package_data['version']},
                                      'build': {'number': int(package_data['build_number']),
                                                'string': package_data['build']},
                                      'requirements': {'run': package_data['depends']}
                                      }, config=config)
    # HACK: because the recipe is fully baked, detecting "used" variables no longer works.  The set
    #     of variables in the hash_input suffices, though.
    metadata.config.used_vars = list(hash_input.keys())
    return metadata, hash_input


def _extract_test_files_from_package(metadata):
    if metadata.config.recipe_dir:
        info_dir = os.path.normpath(os.path.join(metadata.config.recipe_dir, 'info'))
        test_files = os.path.join(info_dir, 'test')
        if os.path.exists(test_files) and os.path.isdir(test_files):
            # things are re-extracted into the test dir because that's cwd when tests are run,
            #    and provides the most intuitive experience. This is a little
            #    tricky, because SRC_DIR still needs to point at the original
            #    work_dir, for legacy behavior where people aren't using
            #    test/source_files. It would be better to change SRC_DIR in
            #    test phase to always point to test_dir. Maybe one day.
            utils.copy_into(test_files, metadata.config.test_dir,
                            metadata.config.timeout, symlinks=True,
                            locking=metadata.config.locking, clobber=True)
            dependencies_file = os.path.join(test_files, 'test_time_dependencies.json')
            test_deps = []
            if os.path.isfile(dependencies_file):
                with open(dependencies_file) as f:
                    test_deps = json.load(f)
            test_section = metadata.meta.get('test', {})
            test_section['requires'] = test_deps
            metadata.meta['test'] = test_section

        else:
            if metadata.meta.get('test', {}).get('source_files'):
                if not metadata.source_provided:
                    try_download(metadata, no_download_source=False)


def construct_metadata_for_test(recipedir_or_package, config):
    if os.path.isdir(recipedir_or_package) or os.path.basename(recipedir_or_package) == 'meta.yaml':
        m, hash_input = _construct_metadata_for_test_from_recipe(recipedir_or_package, config)
    else:
        m, hash_input = _construct_metadata_for_test_from_package(recipedir_or_package, config)
    return m, hash_input


def test(recipedir_or_package_or_metadata, config, move_broken=True):
    '''
    Execute any test scripts for the given package.

    :param m: Package's metadata.
    :type m: Metadata
    '''
    log = utils.get_logger(__name__)
    # we want to know if we're dealing with package input.  If so, we can move the input on success.
    hash_input = {}

    # store this name to keep it consistent.  By changing files, we change the hash later.
    #    It matches the build hash now, so let's keep it around.
    test_package_name = (recipedir_or_package_or_metadata.dist()
                        if hasattr(recipedir_or_package_or_metadata, 'dist')
                        else recipedir_or_package_or_metadata)

    print("TEST START:", test_package_name)

    if hasattr(recipedir_or_package_or_metadata, 'config'):
        metadata = recipedir_or_package_or_metadata
        utils.rm_rf(metadata.config.test_dir)
    else:
        metadata, hash_input = construct_metadata_for_test(recipedir_or_package_or_metadata,
                                                                  config)

    trace = '-x ' if metadata.config.debug else ''

    metadata.config.compute_build_id(metadata.name())

    # Must download *after* computing build id, or else computing build id will change
    #     folder destination
    utils.rm_rf(metadata.config.test_dir)
    _extract_test_files_from_package(metadata)

    # When testing a .tar.bz2 in the pkgs dir, clean_pkg_cache() will remove it.
    # Prevent this. When https://github.com/conda/conda/issues/5708 gets fixed
    # I think we can remove this call to clean_pkg_cache().
    in_pkg_cache = (not hasattr(recipedir_or_package_or_metadata, 'config') and
                    os.path.isfile(recipedir_or_package_or_metadata) and
                    recipedir_or_package_or_metadata.endswith('.tar.bz2') and
                    os.path.dirname(recipedir_or_package_or_metadata) in pkgs_dirs[:1])
    if not in_pkg_cache:
        environ.clean_pkg_cache(metadata.dist(), metadata.config)

    # this is also copying tests/source_files from work_dir to testing workdir
    _, pl_files, py_files, r_files, lua_files, shell_files = \
        create_all_test_files(metadata)
    copy_test_source_files(metadata, metadata.config.test_dir)
    if not any([py_files, shell_files, pl_files, lua_files, r_files]):
        print("Nothing to test for:", test_package_name)
        return True

    if metadata.config.remove_work_dir:
        # nested if so that there's no warning when we just leave the empty workdir in place
        if metadata.source_provided:
            dest = os.path.join(os.path.dirname(metadata.config.work_dir),
                                '_'.join(('work_moved', metadata.dist(),
                                          metadata.config.host_subdir)))
            # Needs to come after create_files in case there's test/source_files
            print("Renaming work directory, ", metadata.config.work_dir, " to ", dest)
            os.rename(config.work_dir, dest)
    else:
        log.warn("Not moving work directory after build.  Your package may depend on files "
                    "in the work directory that are not included with your package")

    get_build_metadata(metadata)
    specs = ['%s %s %s' % (metadata.name(), metadata.version(), metadata.build_id())]

    # add packages listed in the run environment and test/requires
    specs.extend(ms.spec for ms in metadata.ms_depends('run'))
    specs += utils.ensure_list(metadata.get_value('test/requires', []))

    if py_files:
        # as the tests are run by python, ensure that python is installed.
        # (If they already provided python as a run or test requirement,
        #  this won't hurt anything.)
        specs += ['python']
    if pl_files:
        # as the tests are run by perl, we need to specify it
        specs += ['perl']
    if lua_files:
        # not sure how this shakes out
        specs += ['lua']
    if r_files:
        # not sure how this shakes out
        specs += ['r-base']

    with utils.path_prepended(metadata.config.test_prefix):
        env = dict(os.environ.copy())
        env.update(environ.get_dict(config=metadata.config, m=metadata,
                                    prefix=config.test_prefix))
        env["CONDA_BUILD_STATE"] = "TEST"
        if env_path_backup_var_exists:
            env["CONDA_PATH_BACKUP"] = os.environ["CONDA_PATH_BACKUP"]

    if not metadata.config.activate or metadata.name() == 'conda':
        # prepend bin (or Scripts) directory
        env = utils.prepend_bin_path(env, metadata.config.test_prefix, prepend_prefix=True)

    if utils.on_win:
        env['PATH'] = metadata.config.test_prefix + os.pathsep + env['PATH']

    suffix = "bat" if utils.on_win else "sh"
    test_script = join(metadata.config.test_dir,
                        "conda_test_runner.{suffix}".format(suffix=suffix))

    # In the future, we will need to support testing cross compiled
    #     packages on physical hardware. until then it is expected that
    #     something like QEMU or Wine will be used on the build machine,
    #     therefore, for now, we use host_subdir.

    subdir = ('noarch' if (metadata.noarch or metadata.noarch_python)
                else metadata.config.host_subdir)
    # ensure that the test prefix isn't kept between variants
    utils.rm_rf(metadata.config.test_prefix)
    actions = environ.get_install_actions(metadata.config.test_prefix,
                                            tuple(specs), 'host',
                                            subdir=subdir,
                                            debug=metadata.config.debug,
                                            verbose=metadata.config.verbose,
                                            locking=metadata.config.locking,
                                            bldpkgs_dirs=tuple(metadata.config.bldpkgs_dirs),
                                            timeout=metadata.config.timeout,
                                            disable_pip=metadata.config.disable_pip,
                                            max_env_retry=metadata.config.max_env_retry,
                                            output_folder=metadata.config.output_folder,
                                            channel_urls=tuple(metadata.config.channel_urls))

    environ.create_env(metadata.config.test_prefix, actions, config=metadata.config, env='host',
                       subdir=subdir, is_cross=metadata.is_cross,
                       is_conda=metadata.name() == 'conda')

    with utils.path_prepended(metadata.config.test_prefix):
        env = dict(os.environ.copy())
        env.update(environ.get_dict(config=metadata.config, m=metadata,
                                    prefix=metadata.config.test_prefix))
        env["CONDA_BUILD_STATE"] = "TEST"
        if env_path_backup_var_exists:
            env["CONDA_PATH_BACKUP"] = os.environ["CONDA_PATH_BACKUP"]

    # when workdir is removed, the source files are unavailable.  There's the test/source_files
    #    entry that lets people keep these files around.  The files are copied into test_dir for
    #    intuitive relative path behavior, though, not work_dir, so we need to adjust where
    #    SRC_DIR points.  The initial CWD during tests is test_dir.
    if metadata.config.remove_work_dir:
        env['SRC_DIR'] = metadata.config.test_dir

    if not metadata.config.activate or metadata.name() == 'conda':
        # prepend bin (or Scripts) directory
        env = utils.prepend_bin_path(env, metadata.config.test_prefix, prepend_prefix=True)
        if utils.on_win:
            env['PATH'] = metadata.config.test_prefix + os.pathsep + env['PATH']

    # set variables like CONDA_PY in the test environment
    env.update(set_language_env_vars(metadata.config.variant))

    # Python 2 Windows requires that envs variables be string, not unicode
    env = {str(key): str(value) for key, value in env.items()}
    suffix = "bat" if utils.on_win else "sh"
    test_script = join(metadata.config.test_dir,
                        "conda_test_runner.{suffix}".format(suffix=suffix))

    with open(test_script, 'w') as tf:
        if not utils.on_win:
            tf.write('set {trace}-e\n'.format(trace=trace))
        if metadata.config.activate and not metadata.name() == 'conda':
            ext = ".bat" if utils.on_win else ""
            tf.write('{source} "{conda_root}activate{ext}" "{test_env}"\n'.format(
                conda_root=utils.root_script_dir + os.path.sep,
                source="call" if utils.on_win else "source",
                ext=ext,
                test_env=metadata.config.test_prefix))
            if utils.on_win:
                tf.write("IF %ERRORLEVEL% NEQ 0 exit 1\n")
        if py_files:
            test_python = metadata.config.test_python
            # use pythonw for import tests when osx_is_app is set
            if metadata.get_value('build/osx_is_app') and sys.platform == 'darwin':
                test_python = test_python + 'w'
            tf.write('"{python}" -s "{test_file}"\n'.format(
                python=test_python,
                test_file=join(metadata.config.test_dir, 'run_test.py')))
            if utils.on_win:
                tf.write("IF %ERRORLEVEL% NEQ 0 exit 1\n")
        if pl_files:
            tf.write('"{perl}" "{test_file}"\n'.format(
                perl=metadata.config.perl_bin(metadata.config.test_prefix,
                                              metadata.config.host_platform),
                test_file=join(metadata.config.test_dir, 'run_test.pl')))
            if utils.on_win:
                tf.write("IF %ERRORLEVEL% NEQ 0 exit 1\n")
        if lua_files:
            tf.write('"{lua}" "{test_file}"\n'.format(
                lua=metadata.config.lua_bin(metadata.config.test_prefix,
                                            metadata.config.host_platform),
                test_file=join(metadata.config.test_dir, 'run_test.lua')))
            if utils.on_win:
                tf.write("IF %ERRORLEVEL% NEQ 0 exit 1\n")
        if r_files:
            tf.write('"{r}" CMD BATCH "{test_file}"\n'.format(
                r=metadata.config.r_bin(metadata.config.test_prefix, metadata.config.host_platform),
                test_file=join(metadata.config.test_dir, 'run_test.r')))
            if utils.on_win:
                tf.write("IF %ERRORLEVEL% NEQ 0 exit 1\n")
        if shell_files:
            test_file = join(metadata.config.test_dir, 'run_test.' + suffix)
            if utils.on_win:
                tf.write('call "{test_file}"\n'.format(test_file=test_file))
                if utils.on_win:
                    tf.write("IF %ERRORLEVEL% NEQ 0 exit 1\n")
            else:
                # TODO: Run the test/commands here instead of in run_test.py
                tf.write('"{shell_path}" {trace}-e "{test_file}"\n'.format(shell_path=shell_path,
                                                                           test_file=test_file,
                                                                           trace=trace))
    if utils.on_win:
        cmd = ['cmd.exe', "/d", "/c", test_script]
    else:
        cmd = [shell_path] + (['-x'] if metadata.config.debug else []) + ['-e', test_script]
    try:
        utils.check_call_env(cmd, env=env, cwd=metadata.config.test_dir)
    except subprocess.CalledProcessError:
        tests_failed(metadata, move_broken=move_broken, broken_dir=metadata.config.broken_dir,
                        config=metadata.config)
        raise
    if config.need_cleanup and config.recipe_dir is not None:
        utils.rm_rf(config.recipe_dir)
    print("TEST END:", test_package_name)

    return True


def tests_failed(package_or_metadata, move_broken, broken_dir, config):
    '''
    Causes conda to exit if any of the given package's tests failed.

    :param m: Package's metadata
    :type m: Metadata
    '''
    if not isdir(broken_dir):
        os.makedirs(broken_dir)

    if hasattr(package_or_metadata, 'config'):
        pkg = bldpkg_path(package_or_metadata)
    else:
        pkg = package_or_metadata
    dest = join(broken_dir, os.path.basename(pkg))

    if move_broken:
        log = utils.get_logger(__name__)
        log.warn('Tests failed for %s - moving package to %s' % (os.path.basename(pkg),
                 broken_dir))
        shutil.move(pkg, dest)
        update_index(os.path.dirname(pkg))
    sys.exit("TESTS FAILED: " + os.path.basename(pkg))


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
               need_source_download=True, need_reparse_in_env=False, variants=None):

    to_build_recursive = []
    recipe_list = deque(recipe_list)

    if utils.on_win:
        trash_dir = os.path.join(os.path.dirname(sys.executable), 'pkgs', '.trash')
        if os.path.isdir(trash_dir):
            # We don't really care if this does a complete job.
            #    Cleaning up some files is better than none.
            subprocess.call('del /s /q "{0}\\*.*" >nul 2>&1'.format(trash_dir), shell=True)
        # delete_trash(None)

    extra_help = ""
    built_packages = OrderedDict()
    retried_recipes = []

    # this is primarily for exception handling.  It's OK that it gets clobbered by
    #     the loop below.
    metadata = None

    while recipe_list:
        # This loop recursively builds dependencies if recipes exist
        if build_only:
            post = False
            notest = True
            config.anaconda_upload = False
        elif post:
            post = True
            config.anaconda_upload = False
        else:
            post = None

        try:
            recipe = recipe_list.popleft()
            name = recipe.name() if hasattr(recipe, 'name') else recipe
            if hasattr(recipe, 'config'):
                metadata = recipe
                metadata.config.anaconda_upload = config.anaconda_upload
                config = metadata.config
                # this code is duplicated below because we need to be sure that the build id is set
                #    before downloading happens - or else we lose where downloads are
                if config.set_build_id and metadata.name() not in config.build_id:
                    config.compute_build_id(metadata.name(), reset=True)
                recipe_parent_dir = os.path.dirname(metadata.path)
                to_build_recursive.append(metadata.name())

                if not metadata.final:
                    variants_ = (dict_of_lists_to_list_of_dicts(variants) if variants else
                                get_package_variants(metadata))

                    # This is where reparsing happens - we need to re-evaluate the meta.yaml for any
                    #    jinja2 templating
                    metadata_tuples = distribute_variants(metadata, variants_,
                                                        permit_unsatisfiable_variants=False)
                else:
                    metadata_tuples = ((metadata, False, False), )
            else:
                recipe_parent_dir = os.path.dirname(recipe)
                recipe = recipe.rstrip("/").rstrip("\\")
                to_build_recursive.append(os.path.basename(recipe))

                # each tuple is:
                #    metadata, need_source_download, need_reparse_in_env =
                # We get one tuple per variant
                metadata_tuples = render_recipe(recipe, config=config, variants=variants,
                                                permit_unsatisfiable_variants=False,
                                                reset_build_id=not config.dirty,
                                                bypass_env_check=True)
            # restrict to building only one variant for bdist_conda.  The way it splits the build
            #    job breaks variants horribly.
            if post in (True, False):
                metadata_tuples = metadata_tuples[:1]
            for (metadata, need_source_download, need_reparse_in_env) in metadata_tuples:
                if post is None:
                    utils.rm_rf(metadata.config.host_prefix)
                    utils.rm_rf(metadata.config.build_prefix)
                    utils.rm_rf(metadata.config.test_prefix)

                if metadata.name() not in metadata.config.build_folder:
                    metadata.config.compute_build_id(metadata.name(), reset=True)

                packages_from_this = build(metadata,
                                           post=post,
                                           need_source_download=need_source_download,
                                           need_reparse_in_env=need_reparse_in_env,
                                           built_packages=built_packages,
                                           notest=notest,
                                           )
                if not notest:
                    for pkg, dict_and_meta in packages_from_this.items():
                        if pkg.endswith('.tar.bz2'):
                            # we only know how to test conda packages
                            test(pkg, config=metadata.config)
                        built_packages.update({pkg: dict_and_meta})
                else:
                    built_packages.update(packages_from_this)
            # each metadata element here comes from one recipe, thus it will share one build id
            #    cleaning on the last metadata in the loop should take care of all of the stuff.
            metadata.clean()
        except DependencyNeedsBuildingError as e:
            skip_names = ['python', 'r', 'r-base', 'perl', 'lua']
            built_package_paths = [entry[1][1].path for entry in built_packages.items()]
            add_recipes = []
            # add the failed one back in at the beginning - but its deps may come before it
            recipe_list.extendleft([recipe])
            for pkg, matchspec in zip(e.packages, e.matchspecs):
                pkg_name = pkg.split(' ')[0].split('=')[0]
                # if we hit missing dependencies at test time, the error we get says that our
                #    package that we just built needs to be built.  Very confusing.  Bomb out
                #    if any of our output metadatas are in the exception list of pkgs.
                if metadata and any(pkg_name == output_meta.name() for (_, output_meta) in
                       metadata.get_output_metadata_set(permit_undefined_jinja=True)):
                    raise
                if pkg in to_build_recursive:
                    config.clean(remove_folders=False)
                    raise RuntimeError("Can't build {0} due to environment creation error:\n"
                                       .format(recipe) + str(e.message) + "\n" + extra_help)

                if pkg in skip_names:
                    to_build_recursive.append(pkg)
                    extra_help = """Typically if a conflict is with the Python or R
packages, the other package or one of its dependencies
needs to be rebuilt (e.g., a conflict with 'python 3.5*'
and 'x' means 'x' or one of 'x' dependencies isn't built
for Python 3.5 and needs to be rebuilt."""

                recipe_glob = glob(os.path.join(recipe_parent_dir, pkg_name))
                # conda-forge style.  meta.yaml lives one level deeper.
                if not recipe_glob:
                    recipe_glob = glob(os.path.join(recipe_parent_dir, '..', pkg_name))
                feedstock_glob = glob(os.path.join(recipe_parent_dir, pkg_name + '-feedstock'))
                if not feedstock_glob:
                    feedstock_glob = glob(os.path.join(recipe_parent_dir, '..',
                                                       pkg_name + '-feedstock'))
                available = False
                if recipe_glob or feedstock_glob:
                    for recipe_dir in recipe_glob + feedstock_glob:
                        if not any(path.startswith(recipe_dir) for path in built_package_paths):
                            dep_metas = render_recipe(recipe_dir, config=metadata.config)
                            for dep_meta in dep_metas:
                                if utils.match_peer_job(MatchSpec(matchspec), dep_meta[0],
                                                        metadata):
                                    print(("Missing dependency {0}, but found" +
                                        " recipe directory, so building " +
                                        "{0} first").format(pkg))
                                    add_recipes.append(recipe_dir)
                                    available = True
                if not available:
                    config.clean(remove_folders=False)
                    raise
            # if we failed to render due to unsatisfiable dependencies, we should only bail out
            #    if we've already retried this recipe.
            if (not metadata and retried_recipes.count(recipe) and
                    retried_recipes.count(recipe) >= len(metadata.ms_depends('build'))):
                config.clean(remove_folders=False)
                raise RuntimeError("Can't build {0} due to environment creation error:\n"
                                    .format(recipe) + str(e.message) + "\n" + extra_help)
            retried_recipes.append(os.path.basename(name))
            recipe_list.extendleft(add_recipes)

    if post in [True, None]:
        # TODO: could probably use a better check for pkg type than this...
        tarballs = [f for f in built_packages if f.endswith('.tar.bz2')]
        wheels = [f for f in built_packages if f.endswith('.whl')]
        handle_anaconda_upload(tarballs, config=config)
        handle_pypi_upload(wheels, config=config)

    return list(built_packages.keys())


def handle_anaconda_upload(paths, config):
    from conda_build.os_utils.external import find_executable

    paths = utils.ensure_list(paths)

    upload = False
    # this is the default, for no explicit argument.
    # remember that anaconda_upload takes defaults from condarc
    if config.token or config.user:
        upload = True
    # rc file has uploading explicitly turned off
    elif not config.anaconda_upload:
        print("# Automatic uploading is disabled")
    else:
        upload = True

    no_upload_message = """\
# If you want to upload package(s) to anaconda.org later, type:

"""
    for package in paths:
        no_upload_message += "anaconda upload {}\n".format(package)

    no_upload_message += """\

# To have conda build upload to anaconda.org automatically, use
# $ conda config --set anaconda_upload yes
"""
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
    cmd = [anaconda, ]

    if config.token:
        cmd.extend(['--token', config.token])
    cmd.append('upload')
    if config.force_upload:
        cmd.append('--force')
    if config.user:
        cmd.extend(['--user', config.user])
    for package in paths:
        try:
            print("Uploading {} to anaconda.org".format(os.path.basename(package)))
            subprocess.call(cmd + [package])
        except subprocess.CalledProcessError:
            print(no_upload_message)
            raise


def handle_pypi_upload(wheels, config):
    args = ['twine', 'upload', '--sign-with', config.sign_with, '--repository', config.repository]
    if config.user:
        args.extend(['--user', config.user])
    if config.password:
        args.extend(['--password', config.password])
    if config.sign:
        args.extend(['--sign'])
    if config.identity:
        args.extend(['--identity', config.identity])
    if config.config_file:
        args.extend(['--config-file', config.config_file])
    if config.repository:
        args.extend(['--repository', config.repository])

    wheels = utils.ensure_list(wheels)

    if config.anaconda_upload:
        for f in wheels:
            print("Uploading {}".format(f))
            try:
                utils.check_call_env(args + [f])
            except:
                utils.get_logger(__name__).warn("wheel upload failed - is twine installed?"
                                                "  Is this package registered?")
                utils.get_logger(__name__).warn("Wheel file left in {}".format(f))

    else:
        print("anaconda_upload is not set.  Not uploading wheels: {}".format(wheels))


def print_build_intermediate_warning(config):
    print("\n\n")
    print('#' * 84)
    print("Source and build intermediates have been left in " + config.croot + ".")
    build_folders = utils.get_build_folders(config.croot)
    print("There are currently {num_builds} accumulated.".format(num_builds=len(build_folders)))
    print("To remove them, you can run the ```conda build purge``` command")


def clean_build(config, folders=None):
    if not folders:
        folders = utils.get_build_folders(config.croot)
    for folder in folders:
        utils.rm_rf(folder)


def is_package_built(metadata, env):
    for d in metadata.config.bldpkgs_dirs:
        if not os.path.isdir(d):
            os.makedirs(d)
            update_index(d, metadata.config, could_be_mirror=False)
    subdir = getattr(metadata.config, '{}_subdir'.format(env))
    index, index_ts = get_build_index(subdir=subdir,
                                      bldpkgs_dir=metadata.config.bldpkgs_dir,
                                      output_folder=metadata.config.output_folder,
                                      channel_urls=metadata.config.channel_urls,
                                      debug=metadata.config.debug,
                                      verbose=metadata.config.verbose,
                                      locking=metadata.config.locking,
                                      timeout=metadata.config.timeout,
                                      clear_cache=True)
    urls = [url_path(metadata.config.output_folder), 'local'] + get_rc_urls()
    if metadata.config.channel_urls:
        urls.extend(metadata.config.channel_urls)

    # will be empty if none found, and evalute to False
    found_urls = [url for url in urls
            if dist_str_in_index(index, url + '::' + metadata.dist())]
    return found_urls[0] if found_urls else None
