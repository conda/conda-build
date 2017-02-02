'''
Module that does most of the heavy lifting for the ``conda build`` command.
'''
from __future__ import absolute_import, division, print_function

from collections import deque, OrderedDict
import copy
import fnmatch
from glob import glob
import io
import json
import logging
import mmap
import os
from os.path import isdir, isfile, islink, join
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import hashlib

# this is to compensate for a requests idna encoding error.  Conda is a better place to fix,
#   eventually
# exception is raises: "LookupError: unknown encoding: idna"
#    http://stackoverflow.com/a/13057751/1170370
import encodings.idna  # NOQA


# used to get version
from .conda_interface import envs_dirs, env_path_backup_var_exists
from .conda_interface import PY3, cc
from .conda_interface import prefix_placeholder, linked
from .conda_interface import url_path
from .conda_interface import TemporaryDirectory
from .conda_interface import VersionOrder
from .conda_interface import text_type
from .conda_interface import CrossPlatformStLink
from .conda_interface import PathType, FileMode
from .conda_interface import EntityEncoder
from .conda_interface import get_rc_urls
from .conda_interface import dist_str_in_index

from conda_build import __version__
from conda_build import environ, source, tarcheck, utils
from conda_build.index import get_build_index
from conda_build.render import (output_yaml, bldpkg_path, render_recipe, reparse, finalize_metadata,
                                distribute_variants)
import conda_build.os_utils.external as external
from conda_build.post import (post_process, post_build,
                              fix_permissions, get_build_metadata)

from conda_build.index import update_index
from conda_build.create_test import (create_files, create_shell_files,
                                     create_py_files, create_pl_files)
from conda_build.exceptions import indent, DependencyNeedsBuildingError
from conda_build.variants import (set_language_env_vars, get_default_variants,
                                  dict_of_lists_to_list_of_dicts, get_package_variants)

import conda_build.noarch_python as noarch_python
from conda_verify.verify import Verify

from conda import __version__ as conda_version
from conda_build import __version__ as conda_build_version

if 'bsd' in sys.platform:
    shell_path = '/bin/sh'
else:
    shell_path = '/bin/bash'


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
            if not utils.on_win and mm.find(prefix_bytes) != -1:
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


# TODO: this is mostly duplicated with the scheme of pin_run_as_build.  Could be refactored
#     away, probably.
def get_run_dists(m):
    prefix = join(envs_dirs[0], '_run')
    utils.rm_rf(prefix)
    environ.create_env(prefix, [ms.spec for ms in m.ms_depends('run')], config=m.config,
                       subdir=m.config.host_subdir)
    return sorted(linked(prefix))


def copy_recipe(m):
    if m.config.include_recipe and m.include_recipe():
        recipe_dir = join(m.config.info_dir, 'recipe')
        try:
            os.makedirs(recipe_dir)
        except:
            pass

        if os.path.isdir(m.path):
            for fn in os.listdir(m.path):
                if fn.startswith('.'):
                    continue
                src_path = join(m.path, fn)
                dst_path = join(recipe_dir, fn)
                utils.copy_into(src_path, dst_path, timeout=m.config.timeout,
                                locking=m.config.locking)

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
                utils.copy_into(original_recipe, os.path.join(recipe_dir, 'meta.yaml.template'),
                          timeout=m.config.timeout, locking=m.config.locking)


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


def write_hash_input(m):
    hash_input = m._get_hash_dictionary()
    with open(os.path.join(m.config.info_dir, 'hash_input.json'), 'w') as f:
        json.dump(hash_input, f)


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
    # files_with_prefix is a list of tuples containing (prefix_placeholder, file_mode)
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
        if m.get_value('build/noarch_python'):
            fo.write('\n')
        elif m.noarch == 'python':
            for f in files:
                if f.find("site-packages") >= 0:
                    fo.write(f[f.find("site-packages"):] + '\n')
                elif f.startswith("bin") and (f not in entry_point_script_names):
                    fo.write(f.replace("bin", "python-scripts") + '\n')
                elif f.startswith("Scripts") and (f not in entry_point_script_names):
                    fo.write(f.replace("Scripts", "python-scripts") + '\n')
                else:
                    fo.write(f + '\n')
        else:
            for f in files:
                fo.write(f + '\n')


def write_package_metadata_json(m):
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
        package_metadata["package_metadata_version"] = 1
        with open(os.path.join(m.config.info_dir, "package_metadata.json"), 'w') as fh:
            fh.write(json.dumps(package_metadata, sort_keys=True, indent=2, separators=(',', ': ')))


def write_about_json(m):
    with open(join(m.config.info_dir, 'about.json'), 'w') as fo:
        d = {}
        for key in ('home', 'dev_url', 'doc_url', 'license_url',
                    'license', 'summary', 'description', 'license_family'):
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

        if cc.platform == 'linux':
            evars.append('LD_LIBRARY_PATH')
        elif cc.platform == 'osx':
            evars.append('DYLD_LIBRARY_PATH')
        d['env_vars'] = {ev: os.getenv(ev, '<not set>') for ev in evars}
        # this information will only be present in conda 4.2.10+
        try:
            d['conda_private'] = cc.conda_private
        except (KeyError, AttributeError):
            pass
        env = environ.Environment(cc.root_dir)
        d['root_pkgs'] = env.package_specs()
        json.dump(d, fo, indent=2, sort_keys=True)


def write_info_json(m):
    info_index = m.info_index()
    pin_depends = m.get_value('build/pin_depends')
    if pin_depends:
        dists = get_run_dists(m)
        with open(join(m.config.info_dir, 'requires'), 'w') as fo:
            fo.write("""\
# This file as created when building:
#
#     %s.tar.bz2  (on '%s')
#
# It can be used to create the runtime environment of this package using:
# $ conda create --name <env> --file <this file>
""" % (m.dist(), m.config.build_subdir))
            for dist in sorted(dists + [m.dist()]):
                fo.write('%s\n' % '='.join(dist.split('::', 1)[-1].rsplit('-', 2)))
        if pin_depends == 'strict':
            info_index['depends'] = [' '.join(dist.split('::', 1)[-1].rsplit('-', 2))
                                     for dist in dists]

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
        cmd = entry_point[:entry_point.find("= ")].strip()
        if utils.on_win:
            scripts.append("Scripts\\%s-script.py" % cmd)
            scripts.append("Scripts\\%s.exe" % cmd)
        else:
            scripts.append("bin/%s" % cmd)
    return scripts


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

    copy_recipe(m)
    copy_readme(m)
    copy_license(m)

    write_hash_input(m)
    write_info_json(m)  # actually index.json
    write_about_json(m)
    write_package_metadata_json(m)

    write_info_files_file(m, files)

    files_with_prefix = get_files_with_prefix(m, files, prefix)
    create_info_files_json_v1(m, m.config.info_dir, prefix, files, files_with_prefix)

    detect_and_record_prefix_files(m, files, prefix)
    write_no_link(m, files)

    if m.get_value('source/git_url'):
        with io.open(join(m.config.info_dir, 'git'), 'w', encoding='utf-8') as fo:
            source.git_info(m.config, fo)

    if m.get_value('app/icon'):
        utils.copy_into(join(m.path, m.get_value('app/icon')),
                        join(m.config.info_dir, 'icon.png'),
                        m.config.timeout, locking=m.config.locking)
    return [f.replace(m.config.host_prefix + os.sep, '')
            for root, _, _ in os.walk(m.config.info_dir)
            for f in glob(os.path.join(root, '*'))]


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
    elif m.noarch:
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
    if m.get_value('build/noarch_python', None):
        return
    with open(join(info_dir, 'paths.json'), "w") as files_json:
        json.dump(files_json_info, files_json, sort_keys=True, indent=2, separators=(',', ': '),
                  cls=EntityEncoder)


def filter_files(files_list, prefix, filter_patterns=('(.*[\\\\/])?\.git[\\\\/].*',
                                                      '(.*)?\.DS_Store.*')):
    """Remove things like .git from the list of files to be copied"""
    for pattern in filter_patterns:
        r = re.compile(pattern)
        files_list = set(files_list) - set(filter(r.match, files_list))
    return [f.replace(prefix + os.path.sep, '') for f in files_list
            if not os.path.isdir(os.path.join(prefix, f))]


def bundle_conda(output, metadata, env, **kw):
    files = output.get('files', [])
    if not files and output.get('script'):
        interpreter = output.get('script_interpreter')
        if not interpreter:
            interpreter = guess_interpreter(output['script'])
        initial_files_snapshot = prefix_files(metadata.config.host_prefix)
        utils.check_call_env(interpreter.split(' ') +
                    [os.path.join(metadata.path, output['script'])],
                    cwd=metadata.config.host_prefix, env=env)
        files = prefix_files(metadata.config.host_prefix) - initial_files_snapshot
    tmp_metadata = metadata.copy()
    tmp_metadata.meta['package']['name'] = output['name']
    requirements = tmp_metadata.meta.get('requirements', {})
    requirements['run'] = output.get('requirements', [])
    tmp_metadata.meta['requirements'] = requirements

    output_filename = ('-'.join([output['name'], metadata.version(),
                                 metadata.build_id()]) + '.tar.bz2')
    files = list(set(utils.expand_globs(files, metadata.config.host_prefix)))
    files = filter_files(files, prefix=metadata.config.build_prefix)
    info_files = create_info_files(tmp_metadata, files, prefix=metadata.config.host_prefix)
    info_files = filter_files(info_files, prefix=metadata.config.build_prefix)
    for f in info_files:
        if f not in files:
            files.append(f)

    # lock the output directory while we build this file
    # create the tarball in a temporary directory to minimize lock time
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
        if not getattr(metadata.config, "noverify", False):
            verifier = Verify()
            ignore_scripts = metadata.config.ignore_package_verify_scripts if \
                             metadata.config.ignore_package_verify_scripts else None
            run_scripts = metadata.config.run_package_verify_scripts if \
                          metadata.config.run_package_verify_scripts else None
            verifier.verify_package(ignore_scripts=ignore_scripts, run_scripts=run_scripts,
                                    path_to_package=tmp_path)
        subdir = 'noarch' if metadata.noarch else metadata.config.host_subdir
        if metadata.config.output_folder:
            output_folder = os.path.join(metadata.config.output_folder, subdir)
        else:
            output_folder = os.path.join(os.path.dirname(metadata.config.bldpkgs_dir), subdir)
        final_output = os.path.join(output_folder, output_filename)
        if os.path.isfile(final_output):
            os.remove(final_output)
        utils.copy_into(tmp_path, final_output, metadata.config.timeout,
                        locking=metadata.config.locking)

    update_index(output_folder, config=metadata.config)

    # HACK: conda really wants a noarch folder to be around.  Create it as necessary.
    if os.path.basename(output_folder) != 'noarch':
        try:
            os.makedirs(os.path.join(os.path.dirname(output_folder), 'noarch'))
        except OSError:
            pass
        update_index(os.path.join(os.path.dirname(output_folder), 'noarch'), config=metadata.config)

    # remove files from build prefix.  This is so that they can be included in other packages.  If
    #     we were to leave them in place, then later scripts meant to also include them may not.
    for f in files:
        utils.rm_rf(f)
    return final_output


def bundle_wheel(output, metadata, env):
    import pip
    with TemporaryDirectory() as tmpdir, utils.tmp_chdir(metadata.config.work_dir):
        pip.main(['wheel', '--wheel-dir', tmpdir, '--no-deps', '.'])
        wheel_file = glob(os.path.join(tmpdir, "*.whl"))[0]
        utils.copy_into(wheel_file, metadata.config.bldpkgs_dir, locking=metadata.config.locking)
    return os.path.join(metadata.config.bldpkgs_dir, os.path.basename(wheel_file))


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


def build(m, index, post=None, need_source_download=True, need_reparse_in_env=False):
    '''
    Build the package with the specified metadata.

    :param m: Package metadata
    :type m: Metadata
    :type post: bool or None. None means run the whole build. True means run
    post only. False means stop just before the post.
    :type need_source_download: bool: if rendering failed to download source
    (due to missing tools), retry here after build env is populated
    '''

    if m.skip():
        utils.print_skip_message(m)
        return []

    log = logging.getLogger(__name__)

    with utils.path_prepended(m.config.build_prefix):
        env = environ.get_dict(config=m.config, m=m)
    env["CONDA_BUILD_STATE"] = "BUILD"
    if env_path_backup_var_exists:
        env["CONDA_PATH_BACKUP"] = os.environ["CONDA_PATH_BACKUP"]

    built_packages = []

    if post in [False, None]:
        if m.uses_jinja and (need_source_download or need_reparse_in_env):
            print("    (actual version deferred until further download or env creation)")

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

        environ.create_env(m.config.build_prefix, specs, config=m.config,
                           subdir=m.config.build_subdir, index=index)

        # this check happens for the sake of tests, but let's do it before the build so we don't
        #     make people wait longer only to see an error
        warn_on_use_of_SRC_DIR(m)

        if m.config.skip_existing:
            package_location = is_package_built(m)
            if package_location:
                print(m.dist(),
                        "is already built in {0}, skipping.".format(package_location))
                return []

        print("BUILD START:", m.dist())

        if m.config.has_separate_host_prefix:
            if VersionOrder(conda_version) < VersionOrder('4.3.2'):
                raise RuntimeError("Non-native subdir support only in conda >= 4.3.2")
            specs = [ms.spec for ms in m.ms_depends('host')]
            environ.create_env(m.config.host_prefix, specs, config=m.config,
                               subdir=m.config.host_subdir)

        if need_source_download:
            # Execute any commands fetching the source (e.g., git) in the _build environment.
            # This makes it possible to provide source fetchers (eg. git, hg, svn) as build
            # dependencies.
            with utils.path_prepended(m.config.build_prefix):
                source.provide(m)
            m = reparse(m, index)
            if m.uses_jinja:
                print("BUILD START (revised):", m.dist())

        elif need_reparse_in_env:
            m = reparse(m, index)
            print("BUILD START (revised):", m.dist())

        # get_dir here might be just work, or it might be one level deeper,
        #    dependening on the source.
        src_dir = m.config.work_dir
        if isdir(src_dir):
            print("source tree in:", src_dir)
        else:
            print("no source - creating empty work folder")
            os.makedirs(src_dir)

        utils.rm_rf(m.config.info_dir)
        files1 = prefix_files(prefix=m.config.host_prefix)
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
        with open(join(m.config.croot, 'prefix_files.txt'), 'w') as f:
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
                import conda_build.windows as windows
                windows.build(m, build_file)
            else:
                build_file = join(m.path, 'build.sh')

                # There is no sense in trying to run an empty build script.
                if isfile(build_file) or script:
                    with utils.path_prepended(m.config.build_prefix):
                        env = environ.get_dict(config=m.config, m=m)
                    env["CONDA_BUILD_STATE"] = "BUILD"

                    # set variables like CONDA_PY in the test environment
                    env.update(set_language_env_vars(m.config.variant))

                    work_file = join(m.config.work_dir, 'conda_build.sh')
                    if script:
                        with open(work_file, 'w') as bf:
                            bf.write(script)
                    if m.config.activate:
                        if isfile(build_file):
                            data = open(build_file).read()
                        else:
                            data = open(work_file).read()
                        with open(work_file, 'w') as bf:
                            bf.write('source "{conda_root}activate" "{build_prefix}" &> '
                                        '/dev/null\n'.format(conda_root=utils.root_script_dir +
                                                            os.path.sep,
                                                            build_prefix=m.config.build_prefix))
                            bf.write(data)
                    else:
                        if not isfile(work_file):
                            utils.copy_into(build_file, work_file, m.config.timeout,
                                            locking=m.config.locking)
                    os.chmod(work_file, 0o766)

                    if isfile(work_file):
                        cmd = [shell_path, '-x', '-e', work_file]
                        # this should raise if any problems occur while building
                        utils.check_call_env(cmd, env=env, cwd=src_dir)

    if post in [True, None]:
        if post:
            with open(join(m.config.croot, 'prefix_files.txt'), 'r') as f:
                files1 = set(f.read().splitlines())

        get_build_metadata(m)
        create_post_scripts(m)

        if not m.noarch == 'python':
            utils.create_entry_points(m.get_value('build/entry_points'), config=m.config)
        files2 = prefix_files(prefix=m.config.host_prefix)

        post_process(sorted(files2 - files1),
                     prefix=m.config.host_prefix,
                     config=m.config,
                     preserve_egg_dir=bool(m.get_value('build/preserve_egg_dir')),
                     noarch=m.get_value('build/noarch'),
                     skip_compile_pyc=m.get_value('build/skip_compile_pyc'))

        # The post processing may have deleted some files (like easy-install.pth)
        files2 = prefix_files(prefix=m.config.host_prefix)
        if any(m.config.meta_dir in join(m.config.host_prefix, f) for f in files2 - files1):
            meta_files = (tuple(f for f in files2 - files1 if m.config.meta_dir in
                    join(m.config.host_prefix, f)),)
            sys.exit(indent("""Error: Untracked file(s) %s found in conda-meta directory.
This error usually comes from using conda in the build script.  Avoid doing this, as it
can lead to packages that include their dependencies.""" % meta_files))
        post_build(m, sorted(files2 - files1),
                    prefix=m.config.host_prefix,
                    build_python=m.config.build_python,
                    croot=m.config.croot)

        entry_point_script_names = get_entry_point_script_names(m.get_value('build/entry_points'))
        if m.noarch == 'python':
            pkg_files = [fi for fi in sorted(files2 - files1) if fi not in entry_point_script_names]
        else:
            pkg_files = sorted(files2 - files1)

        # the legacy noarch
        if m.get_value('build/noarch_python'):
            noarch_python.transform(m, sorted(files2 - files1), m.config.host_prefix)
        # new way: build/noarch: python
        elif m.noarch == 'python':
            noarch_python.populate_files(
                m, pkg_files, m.config.host_prefix, entry_point_script_names)

        files3 = prefix_files(prefix=m.config.host_prefix)
        fix_permissions(files3 - files1, m.config.host_prefix)

        outputs = m.get_section('outputs')
        # this is the old, default behavior: conda package, with difference between start
        #    set of files and end set of files
        requirements = m.get_value('requirements/run')
        if not outputs:
            outputs = [{'name': m.name(),
                        'files': files3 - files1,
                        'requirements': requirements}]
        else:
            # make a metapackage for the top-level package if the top-level requirements
            #     mention a subpackage,
            uses_subpackage = any(out.get('name') in requirements for out in outputs)
            # but only if a matching output name is not explicitly provided
            if uses_subpackage and not any(m.name() == out.get('name', '') for out in outputs):
                outputs.append({'name': m.name(), 'requirements': requirements})

        for output in outputs:
            built_package = bundlers[output.get('type', 'conda')](output, m, env)
            built_packages.append(built_package)

    else:
        print("STOPPING BUILD BEFORE POST:", m.dist())

    # return list of all package files emitted by this build
    return built_packages


def guess_interpreter(script_filename):
    extensions_to_run_commands = {'.sh': 'sh',
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


def test(recipedir_or_package_or_metadata, config, move_broken=True):
    '''
    Execute any test scripts for the given package.

    :param m: Package's metadata.
    :type m: Metadata
    '''
    log = logging.getLogger(__name__)
    # we want to know if we're dealing with package input.  If so, we can move the input on success.
    need_cleanup = False
    hash_input = {}

    if hasattr(recipedir_or_package_or_metadata, 'config'):
        metadata_tuples = [(recipedir_or_package_or_metadata, None, None)]
        config = recipedir_or_package_or_metadata.config
        local_url = None
    else:
        recipe_dir, need_cleanup = utils.get_recipe_abspath(recipedir_or_package_or_metadata)
        config.need_cleanup = need_cleanup

        # This will create a new local build folder if and only if config doesn't already have one.
        #   What this means is that if we're running a test immediately after build, we use the one
        #   that the build already provided
        try:
            info_dir = os.path.normpath(os.path.join(recipe_dir, 'info'))
            if os.path.isdir(info_dir):
                with open(os.path.join(info_dir, 'index.json')) as f:
                    subdir = json.load(f)['subdir']
                if subdir != 'noarch':
                    config.host_subdir = subdir
                with open(os.path.join(info_dir, 'hash_input.json')) as f:
                    hash_input = json.load(f)

            local_location = os.path.dirname(recipedir_or_package_or_metadata)
            # strip off extra subdir folders
            for platform in ('win', 'linux', 'osx'):
                if os.path.basename(local_location).startswith(platform + "-"):
                    local_location = os.path.dirname(local_location)

            if not os.path.abspath(local_location):
                local_location = os.path.normpath(os.path.abspath(
                    os.path.join(os.getcwd(), local_location)))
            local_url = url_path(local_location)
            # channel_urls is an iterable, but we don't know if it's a tuple or list.  Don't know
            #    how to add elements.
            config.channel_urls = list(config.channel_urls)
            config.channel_urls.insert(0, local_url)

            metadata_tuples, _ = render_recipe(recipe_dir, config=config)

            metadata = metadata_tuples[0][0]
            if (metadata.meta.get('test') and metadata.meta['test'].get('source_files') and
                    not os.listdir(config.work_dir)):
                source.provide(metadata)
        except IOError:
            raise IOError("Didn't find recipe in folder or package under test.  Can't test "
                          "this after exiting build.")

    for (metadata, _, _) in metadata_tuples:
        metadata.append_metadata_sections(hash_input, merge=False)
        config.compute_build_id(metadata.name())
        environ.clean_pkg_cache(metadata.dist(), config)
        create_files(config.test_dir, metadata)
        # Make Perl or Python-specific test files
        if metadata.name().startswith('perl-'):
            pl_files = create_pl_files(config.test_dir, metadata)
            py_files = False
            lua_files = False
        else:
            py_files = create_py_files(config.test_dir, metadata)
            pl_files = False
            lua_files = False
        shell_files = create_shell_files(config.test_dir, metadata)
        if not (py_files or shell_files or pl_files or lua_files):
            print("Nothing to test for:", metadata.dist())
            continue

        print("TEST START:", metadata.dist())

        if config.remove_work_dir:
            # Needs to come after create_files in case there's test/source_files
            print("Deleting work directory,", config.work_dir)
            utils.rm_rf(config.work_dir)
        else:
            log.warn("Not removing work directory after build.  Your package may depend on files "
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

        with utils.path_prepended(config.test_prefix):
            env = dict(os.environ.copy())
            env.update(environ.get_dict(config=config, m=metadata, prefix=config.test_prefix))
            env["CONDA_BUILD_STATE"] = "TEST"
            if env_path_backup_var_exists:
                env["CONDA_PATH_BACKUP"] = os.environ["CONDA_PATH_BACKUP"]

        if not config.activate:
            # prepend bin (or Scripts) directory
            env = utils.prepend_bin_path(env, config.test_prefix, prepend_prefix=True)

        if utils.on_win:
            env['PATH'] = config.test_prefix + os.pathsep + env['PATH']

        suffix = "bat" if utils.on_win else "sh"
        test_script = join(config.test_dir, "conda_test_runner.{suffix}".format(suffix=suffix))

        # we want subdir to match the target arch.  If we're running the test on the target arch,
        #     the build_subdir should be that match.  The host_subdir may not be, and would lead
        #     to unsatisfiable packages.
        environ.create_env(config.test_prefix, specs, config=config, subdir=config.build_subdir)

        with utils.path_prepended(config.test_prefix):
            env = dict(os.environ.copy())
            env.update(environ.get_dict(config=config, m=metadata, prefix=config.test_prefix))
            env["CONDA_BUILD_STATE"] = "TEST"
            if env_path_backup_var_exists:
                env["CONDA_PATH_BACKUP"] = os.environ["CONDA_PATH_BACKUP"]

        if not config.activate:
            # prepend bin (or Scripts) directory
            env = utils.prepend_bin_path(env, config.test_prefix, prepend_prefix=True)

            if utils.on_win:
                env['PATH'] = config.test_prefix + os.pathsep + env['PATH']

        # set variables like CONDA_PY in the test environment
        env.update(set_language_env_vars(config.variant))

        # Python 2 Windows requires that envs variables be string, not unicode
        env = {str(key): str(value) for key, value in env.items()}
        suffix = "bat" if utils.on_win else "sh"
        test_script = join(config.test_dir, "conda_test_runner.{suffix}".format(suffix=suffix))

        with open(test_script, 'w') as tf:
            if config.activate:
                ext = ".bat" if utils.on_win else ""
                tf.write('{source} "{conda_root}activate{ext}" "{test_env}" {squelch}\n'.format(
                    conda_root=utils.root_script_dir + os.path.sep,
                    source="call" if utils.on_win else "source",
                    ext=ext,
                    test_env=config.test_prefix,
                    squelch=">nul 2>&1" if utils.on_win else "&> /dev/null"))
                if utils.on_win:
                    tf.write("if errorlevel 1 exit 1\n")
            if py_files:
                tf.write("{python} -s {test_file}\n".format(
                    python=config.test_python,
                    test_file=join(config.test_dir, 'run_test.py')))
                if utils.on_win:
                    tf.write("if errorlevel 1 exit 1\n")
            if pl_files:
                tf.write("{perl} {test_file}\n".format(
                    perl=config.test_perl,
                    test_file=join(config.test_dir, 'run_test.pl')))
                if utils.on_win:
                    tf.write("if errorlevel 1 exit 1\n")
            if lua_files:
                tf.write("{lua} {test_file}\n".format(
                    lua=config.test_lua,
                    test_file=join(config.test_dir, 'run_test.lua')))
                if utils.on_win:
                    tf.write("if errorlevel 1 exit 1\n")
            if shell_files:
                test_file = join(config.test_dir, 'run_test.' + suffix)
                if utils.on_win:
                    tf.write("call {test_file}\n".format(test_file=test_file))
                    if utils.on_win:
                        tf.write("if errorlevel 1 exit 1\n")
                else:
                    # TODO: Run the test/commands here instead of in run_test.py
                    tf.write("{shell_path} -x -e {test_file}\n".format(shell_path=shell_path,
                                                                        test_file=test_file))
        if utils.on_win:
            cmd = ['cmd.exe', "/d", "/c", test_script]
        else:
            cmd = [shell_path, '-x', '-e', test_script]
        try:
            utils.check_call_env(cmd, env=env, cwd=config.test_dir)
        except subprocess.CalledProcessError:
            tests_failed(metadata, move_broken=move_broken, broken_dir=config.broken_dir,
                         config=config)

        if need_cleanup:
            utils.rm_rf(recipe_dir)

        print("TEST END:", metadata.dist())
    return True


def tests_failed(m, move_broken, broken_dir, config):
    '''
    Causes conda to exit if any of the given package's tests failed.

    :param m: Package's metadata
    :type m: Metadata
    '''
    if not isdir(broken_dir):
        os.makedirs(broken_dir)

    if move_broken:
        shutil.move(bldpkg_path(m), join(broken_dir, "%s.tar.bz2" % m.dist()))
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


def ensure_metadata_compatible_with_recipe(metadata):
    test_meta = metadata.copy()
    test_meta.final = False
    test_meta.parse_again(raise_on_clobber=True)


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

    already_built = set()
    extra_help = ""
    built_packages = []

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

        try:
            recipe = recipe_list.popleft()
            if hasattr(recipe, 'config'):
                metadata = recipe
                config = metadata.config
                # this code is duplicated below because we need to be sure that the build id is set
                #    before downloading happens - or else we lose where downloads are
                if config.set_build_id:
                    config.compute_build_id(metadata.name(), reset=True)
                recipe_parent_dir = ""
                to_build_recursive.append(metadata.name())
                metadata_tuples = []
                index = metadata.config.index if metadata.config.index else get_build_index(config,
                                                                                config.build_subdir)
                variants = (dict_of_lists_to_list_of_dicts(variants) if variants else
                            get_package_variants(metadata))
                # this is essentially a check to make sure that if people set things on the metadata
                #    object directly, then they get an error when reparsing the recipe would clobber
                #    their changes.
                ensure_metadata_compatible_with_recipe(metadata)
                # This is where reparsing happens - we need to re-evaluate the meta.yaml for any
                #    jinja2 templating
                metadata_tuples = distribute_variants(metadata, variants, index)
            else:
                recipe_parent_dir = os.path.dirname(recipe)
                recipe = recipe.rstrip("/").rstrip("\\")
                to_build_recursive.append(os.path.basename(recipe))

                #    before downloading happens - or else we lose where downloads are
                if config.set_build_id:
                    config.compute_build_id(os.path.basename(recipe), reset=True)
                # each tuple is:
                #    metadata, need_source_download, need_reparse_in_env =
                # We get one tuple per variant
                metadata_tuples, index = render_recipe(recipe, config=config, variants=variants)
            if not getattr(config, "noverify", False):
                verifier = Verify()
                ignore_scripts = config.ignore_recipe_verify_scripts if \
                    config.ignore_recipe_verify_scripts else None
                run_scripts = config.run_recipe_verify_scripts if \
                    config.run_recipe_verify_scripts else None
                for m_tuple in metadata_tuples:
                    verifier.verify_recipe(ignore_scripts=ignore_scripts, run_scripts=run_scripts,
                                        rendered_meta=m_tuple[0].meta, recipe_dir=m_tuple[0].path)

            with config:
                for (metadata, need_source_download, need_reparse_in_env) in metadata_tuples:
                    if not metadata.final:
                        metadata = finalize_metadata(metadata, index)
                    packages_from_this = build(metadata, index=index, post=post,
                                               need_source_download=need_source_download,
                                               need_reparse_in_env=need_reparse_in_env)
                    if not notest:
                        for pkg in packages_from_this:
                            if pkg.endswith('.tar.bz2'):
                                # we only know how to test conda packages
                                try:
                                    test(pkg, config=config)
                                # IOError means recipe was not included with package. use metadata
                                except IOError:
                                    # force the build string to line up - recomputing it would
                                    #    yield a different result
                                    index_contents = utils.package_has_file(pkg,
                                                                        'info/index.json').decode()
                                    build_str = json.loads(index_contents)['build']
                                    build_meta = metadata.meta.get('build', {})
                                    build_meta['string'] = build_str
                                    metadata.meta['build'] = build_meta
                                    test(metadata, config=metadata.config)
                            built_packages.append(pkg)
                    else:
                        built_packages.extend(packages_from_this)
        except DependencyNeedsBuildingError as e:
            skip_names = ['python', 'r']
            add_recipes = []
            # add the failed one back in at the beginning - but its deps may come before it
            recipe_list.extendleft([recipe])
            original_recipe_list = copy.copy(recipe_list)
            for pkg in e.packages:
                if pkg in to_build_recursive:
                    raise RuntimeError("Can't build {0} due to unsatisfiable dependencies:\n {1}"
                                       .format(recipe, e.packages) + "\n" + extra_help)

                if pkg in skip_names:
                    to_build_recursive.append(pkg)
                    extra_help = """Typically if a conflict is with the Python or R
packages, the other package or one of its dependencies
needs to be rebuilt (e.g., a conflict with 'python 3.5*'
and 'x' means 'x' or one of 'x' dependencies isn't built
for Python 3.5 and needs to be rebuilt."""

                recipe_glob = glob(os.path.join(recipe_parent_dir, pkg))
                if recipe_glob:
                    for recipe_dir in recipe_glob:
                        print(("Missing dependency {0}, but found" +
                                " recipe directory, so building " +
                                "{0} first").format(pkg))
                        add_recipes.append(recipe_dir)
                else:
                    raise RuntimeError("Can't build {0} due to unsatisfiable dependencies:\n{1}"
                                       .format(recipe, e.packages) + "\n\n" + extra_help)
            recipe_list.extendleft(add_recipes)

            # we didn't add any recipes, so we don't expect to be able to fix this error.  Reraise.
            if len(recipe_list) == len(original_recipe_list):
                raise RuntimeError("could not build {}, aborting build".format(pkg))

        # outputs message, or does upload, depending on value of args.anaconda_upload
        if post in [True, None]:
            for f in built_packages:
                # TODO: could probably use a better check for pkg type than this...
                if f.endswith('.tar.bz2'):
                    handle_anaconda_upload(f, config=config)
                elif f.endswith('.whl'):
                    handle_pypi_upload(f, config=config)
                already_built.add(f)

    return built_packages


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
    cmd.extend(['upload', '--force'])
    if config.user:
        cmd.extend(['--user', config.user])
    cmd.append(path)
    try:
        subprocess.call(cmd)
    except:
        print(no_upload_message)
        raise


def handle_pypi_upload(f, config):
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

    args.append(f)
    try:
        utils.check_call_env(args)
    except:
        logging.getLogger(__name__).warn("wheel upload failed - is twine installed?"
                                         "  Is this package registered?")


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


def is_package_built(metadata):
    for d in metadata.config.bldpkgs_dirs:
        if not os.path.isdir(d):
            os.makedirs(d)
            update_index(d, metadata.config, could_be_mirror=False)
    index = get_build_index(config=metadata.config, subdir=metadata.config.host_subdir,
                            clear_cache=True)

    urls = [url_path(metadata.config.croot)] + get_rc_urls()
    if metadata.config.channel_urls:
        urls.extend(metadata.config.channel_urls)

    # will be empty if none found, and evalute to False
    return [url for url in urls
            if dist_str_in_index(index, url + '::' + metadata.pkg_fn())]
