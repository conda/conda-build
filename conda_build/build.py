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
from .conda_interface import pkgs_dirs
from .conda_interface import envs_dirs, env_path_backup_var_exists, root_dir
from .conda_interface import display_actions, execute_actions, execute_plan, install_actions
from .conda_interface import get_index
from .conda_interface import PY3
from .conda_interface import package_cache
from .conda_interface import prefix_placeholder, linked, symlink_conda
from .conda_interface import url_path
from .conda_interface import Resolve, MatchSpec, Unsatisfiable
from .conda_interface import TemporaryDirectory
from .conda_interface import get_rc_urls, get_local_urls
from .conda_interface import VersionOrder
from .conda_interface import (PaddingError, LinkError, CondaError, NoPackagesFoundError,
                              NoPackagesFound, LockError)
from .conda_interface import text_type
from .conda_interface import CrossPlatformStLink
from .conda_interface import PathType, FileMode
from .conda_interface import EntityEncoder
from .conda_interface import dist_str_in_index, Dist

from conda_build import __version__
from conda_build import environ, source, tarcheck, utils
from conda_build.render import (parse_or_try_download, output_yaml, bldpkg_path,
                                render_recipe, reparse)
import conda_build.os_utils.external as external
from conda_build.post import (post_process, post_build,
                              fix_permissions, get_build_metadata)
from conda_build.index import update_index
from conda_build.create_test import (create_files, create_shell_files, create_r_files,
                                     create_py_files, create_pl_files, create_lua_files)
from conda_build.exceptions import indent
from conda_build.features import feature_list

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


def create_post_scripts(m, config):
    '''
    Create scripts to run after build step
    '''
    recipe_dir = m.path
    ext = '.bat' if utils.on_win else '.sh'
    for tp in 'pre-link', 'post-link', 'pre-unlink':
        src = join(recipe_dir, tp + ext)
        if not isfile(src):
            continue
        dst_dir = join(config.build_prefix,
                       'Scripts' if utils.on_win else 'bin')
        if not isdir(dst_dir):
            os.makedirs(dst_dir, 0o775)
        dst = join(dst_dir, '.%s-%s%s' % (m.name(), tp, ext))
        utils.copy_into(src, dst, config.timeout, locking=config.locking)
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
        try:
            mm = mmap.mmap(fi.fileno(), 0)
        except OSError:
            mm = fi

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


def get_run_dists(m, config):
    prefix = join(envs_dirs[0], '_run')
    utils.rm_rf(prefix)
    create_env(prefix, [ms.spec for ms in m.ms_depends('run')], config=config)
    return sorted(linked(prefix))


def copy_recipe(m, config):
    recipe_dir = join(config.info_dir, 'recipe')
    if config.include_recipe and m.include_recipe():
        try:
            os.makedirs(recipe_dir)
        except:
            pass

        if os.path.isdir(m.path):
            for fn in os.listdir(m.path):
                src_path = join(m.path, fn)
                dst_path = join(recipe_dir, fn)
                utils.copy_into(src_path, dst_path, timeout=config.timeout, locking=config.locking)

            # store the rendered meta.yaml file, plus information about where it came from
            #    and what version of conda-build created it
            original_recipe = os.path.join(m.path, 'meta.yaml')
        else:
            original_recipe = ""

        rendered_metadata = copy.deepcopy(m)
        # fill in build versions used
        build_deps = []
        # TODO: may be unnecessary after build_customization branch merge
        # we only care if we actually have build deps.  Otherwise, the environment will not be
        #    valid for inspection.
        if m.meta.get('requirements') and m.meta['requirements'].get('build'):
            build_deps = environ.Environment(m.config.build_prefix).package_specs()

        if not rendered_metadata.meta.get('build'):
            rendered_metadata.meta['build'] = {}
        # hard-code build string so that any future "renderings" can't go wrong based on user env
        rendered_metadata.meta['build']['string'] = m.build_id()

        rendered_metadata.meta['requirements'] = rendered_metadata.meta.get('requirements', {})
        rendered_metadata.meta['requirements']['build'] = build_deps

        # if source/path is relative, then the output package makes no sense at all.  The next
        #   best thing is to hard-code the absolute path.  This probably won't exist on any
        #   system other than the original build machine, but at least it will work there.
        if m.meta.get('source'):
            if 'path' in m.meta['source'] and not os.path.isabs(m.meta['source']['path']):
                rendered_metadata.meta['source']['path'] = os.path.normpath(
                    os.path.join(m.path, m.meta['source']['path']))
            elif ('git_url' in m.meta['source'] and not os.path.isabs(m.meta['source']['git_url'])):
                rendered_metadata.meta['source']['git_url'] = os.path.normpath(
                    os.path.join(m.path, m.meta['source']['git_url']))

        rendered = output_yaml(rendered_metadata)
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
                          timeout=config.timeout, locking=config.locking)


def copy_readme(m, config):
    readme = m.get_value('about/readme')
    if readme:
        src = join(config.work_dir, readme)
        if not isfile(src):
            sys.exit("Error: no readme file: %s" % readme)
        dst = join(config.info_dir, readme)
        utils.copy_into(src, dst, config.timeout, locking=config.locking)
        if os.path.split(readme)[1] not in {"README.md", "README.rst", "README"}:
            print("WARNING: anaconda.org only recognizes about/readme "
                  "as README.md and README.rst", file=sys.stderr)


def copy_license(m, config):
    license_file = m.get_value('about/license_file')
    if license_file:
        utils.copy_into(join(config.work_dir, license_file),
                        join(config.info_dir, 'LICENSE.txt'), config.timeout,
                        locking=config.locking)


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


def detect_and_record_prefix_files(m, files, prefix, config):
    files_with_prefix = get_files_with_prefix(m, files, prefix)
    binary_has_prefix_files = m.binary_has_prefix_files()
    text_has_prefix_files = m.has_prefix_files()
    is_noarch = (m.get_value('build/noarch_python') or is_noarch_python(m) or
                 m.get_value('build/noarch'))

    if files_with_prefix and not is_noarch:
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


def sanitize_channel(channel):
    return re.sub('\/t\/[a-zA-Z0-9\-]*\/', '/t/<TOKEN>/', channel)


def write_info_files_file(m, files, config):
    entry_point_scripts = m.get_value('build/entry_points')
    entry_point_script_names = get_entry_point_script_names(entry_point_scripts)

    mode_dict = {'mode': 'w', 'encoding': 'utf-8'} if PY3 else {'mode': 'wb'}
    with open(join(config.info_dir, 'files'), **mode_dict) as fo:
        if m.get_value('build/noarch_python'):
            fo.write('\n')
        elif is_noarch_python(m):
            for f in files:
                if f.find("site-packages") >= 0:
                    fo.write(f[f.find("site-packages"):] + '\n')
                elif f.startswith("bin") and (f not in entry_point_script_names):
                    fo.write(f.replace("bin", "python-scripts") + '\n')
                elif f.startswith("Scripts") and (f not in entry_point_script_names):
                    fo.write(f.replace("Scripts", "python-scripts") + '\n')
        else:
            for f in files:
                fo.write(f + '\n')


def write_link_json(m, config):
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
        with open(os.path.join(config.info_dir, "link.json"), 'w') as fh:
            fh.write(json.dumps(package_metadata, sort_keys=True, indent=2, separators=(',', ': ')))


def write_about_json(m, config):
    with open(join(config.info_dir, 'about.json'), 'w') as fo:
        d = {}
        for key in ('home', 'dev_url', 'doc_url', 'license_url',
                    'license', 'summary', 'description', 'license_family'):
            value = m.get_value('about/%s' % key)
            if value:
                d[key] = value

        bin_path = os.path.join(sys.prefix, "Scripts\\conda.exe" if utils.on_win else "bin/conda")

        # for sake of reproducibility, record some conda info
        conda_info = subprocess.check_output([bin_path, 'info', '--json', '-s'])
        if hasattr(conda_info, 'decode'):
            conda_info = conda_info.decode(utils.codec)
        conda_info = json.loads(conda_info)
        d['conda_version'] = conda_version
        d['conda_build_version'] = conda_build_version
        # conda env will be in most, but not necessarily all installations.
        #    Don't die if we don't see it.
        if 'conda_env_version' in conda_info:
            d['conda_env_version'] = conda_info['conda_env_version']
        d['offline'] = conda_info['offline']
        channels = conda_info['channels']
        stripped_channels = []
        for channel in channels:
            stripped_channels.append(sanitize_channel(channel))
        d['channels'] = stripped_channels
        # this information will only be present in conda 4.2.10+
        try:
            d['conda_private'] = conda_info['conda_private']
            d['env_vars'] = conda_info['env_vars']
        except KeyError:
            pass
        pkgs = subprocess.check_output([bin_path, 'list', '-n', 'root', '--json'])
        if hasattr(pkgs, 'decode'):
            pkgs = pkgs.decode(utils.codec)
        d['root_pkgs'] = json.loads(pkgs)
        json.dump(d, fo, indent=2, sort_keys=True)


def write_info_json(m, config):
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
            dist = m.dist()
            if hasattr(dists[0], 'version'):
                dist = Dist(dist)
            for dist in sorted(dists + [dist]):
                fo.write('%s\n' % '='.join(dist.split('::', 1)[-1].rsplit('-', 2)))
        if pin_depends == 'strict':
            info_index['depends'] = [' '.join(dist.split('::', 1)[-1].rsplit('-', 2))
                                     for dist in dists]

    # Deal with Python 2 and 3's different json module type reqs
    mode_dict = {'mode': 'w', 'encoding': 'utf-8'} if PY3 else {'mode': 'wb'}
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


def create_info_files(m, files, config, prefix):
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

    copy_recipe(m, config)
    copy_readme(m, config)
    copy_license(m, config)

    write_info_json(m, config)  # actually index.json
    write_about_json(m, config)
    write_link_json(m, config)

    write_info_files_file(m, files, config)

    files_with_prefix = get_files_with_prefix(m, files, prefix)
    create_info_files_json_v1(m, config.info_dir, prefix, files, files_with_prefix)

    detect_and_record_prefix_files(m, files, prefix, config)
    write_no_link(m, config, files)

    if m.get_value('source/git_url'):
        with io.open(join(config.info_dir, 'git'), 'w', encoding='utf-8') as fo:
            source.git_info(config, fo)

    if m.get_value('app/icon'):
        utils.copy_into(join(m.path, m.get_value('app/icon')),
                        join(config.info_dir, 'icon.png'),
                        config.timeout, locking=config.locking)
    return [f.replace(config.build_prefix + os.sep, '') for root, _, _ in os.walk(config.info_dir)
            for f in glob(os.path.join(root, '*'))]


def get_short_path(m, target_file):
    entry_point_script_names = get_entry_point_script_names(m.get_value('build/entry_points'))
    if is_noarch_python(m):
        if target_file.find("site-packages") >= 0:
            return target_file[target_file.find("site-packages"):]
        elif target_file.startswith("bin") and (target_file not in entry_point_script_names):
            return target_file.replace("bin", "python-scripts")
        elif target_file.startswith("Scripts") and (target_file not in entry_point_script_names):
            return target_file.replace("Scripts", "python-scripts")
        else:
            return target_file
    elif m.get_value('build/noarch_python'):
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
    if islink(path):
        return PathType.softlink
    return PathType.hardlink


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


def get_build_index(config, clear_cache=True):
    # priority: local by croot (can vary), then channels passed as args,
    #     then channels from config.
    urls = [url_path(config.croot)] + list(config.channel_urls)
    index = get_index(channel_urls=urls,
                      prepend=not config.override_channels,
                      use_local=False,
                      use_cache=not clear_cache)
    return index


def recursive_req_folders(folders, start_specs, index):
    """Get folders """
    for folder in start_specs:
        folder = folder.replace(" ", '-')
        matching_keys = {key: val for key, val in index.items() if key.startswith(folder)}
        for key, val in matching_keys.items():
            recursive_req_folders(folders, val['requires'], index)
        folders.extend([key.replace('.tar.bz2', "") for key in matching_keys.keys()])
    return folders


def create_env(prefix, specs, config, clear_cache=True, retry=0):
    '''
    Create a conda envrionment for the given prefix and specs.
    '''
    if config.debug:
        logging.getLogger("conda_build").setLevel(logging.DEBUG)
        external_logger_context = utils.LoggingContext(logging.DEBUG)
    else:
        logging.getLogger("conda_build").setLevel(logging.INFO)
        external_logger_context = utils.LoggingContext(logging.ERROR)

    with external_logger_context:
        log = logging.getLogger(__name__)

        specs = list(specs)
        for feature, value in feature_list:
            if value:
                specs.append('%s@' % feature)

        if specs:  # Don't waste time if there is nothing to do
            log.debug("Creating environment in %s", prefix)
            log.debug(str(specs))

            with utils.path_prepended(prefix):
                locks = []
                try:
                    if config.locking:
                        _pkgs_dirs = pkgs_dirs[:1]
                        locked_folders = _pkgs_dirs + list(config.bldpkgs_dirs)
                        for folder in locked_folders:
                            if not os.path.isdir(folder):
                                os.makedirs(folder)
                            lock = utils.get_lock(folder, timeout=config.timeout)
                            if not folder.endswith('pkgs'):
                                update_index(folder, config=config, lock=lock,
                                             could_be_mirror=False)
                            locks.append(lock)
                        # lock used to generally indicate a conda operation occurring
                        locks.append(utils.get_lock('conda-operation', timeout=config.timeout))

                    with utils.try_acquire_locks(locks, timeout=config.timeout):
                        index = get_build_index(config=config, clear_cache=True)
                        actions = install_actions(prefix, index, specs)
                        if config.disable_pip:
                            actions['LINK'] = [spec for spec in actions['LINK'] if not spec.startswith('pip-')]  # noqa
                            actions['LINK'] = [spec for spec in actions['LINK'] if not spec.startswith('setuptools-')]  # noqa
                        display_actions(actions, index)
                        if utils.on_win:
                            for k, v in os.environ.items():
                                os.environ[k] = str(v)
                        execute_actions(actions, index, verbose=config.debug)
                        warn_on_old_conda_build(index=index)
                except (SystemExit, PaddingError, LinkError, CondaError) as exc:
                    if (("too short in" in str(exc) or
                            re.search('post-link failed for: .*openssl', str(exc)) or
                            isinstance(exc, PaddingError)) and
                            config.prefix_length > 80):
                        if config.prefix_length_fallback:
                            log.warn("Build prefix failed with prefix length %d",
                                     config.prefix_length)
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

                            create_env(prefix, specs, config=config,
                                        clear_cache=clear_cache)
                        else:
                            raise
                    # conda sometimes gets files deleted out from under itself.  Retry.
                    #    The reason why we treat the "minimum conda version" text this way is that
                    #    it occurs with info/files is missing.  That's also a symptom of these
                    #    weird I/O issues that happen with parallel conda-build jobs.
                    elif ('lock' in str(exc) or 'requires a minimum conda version' in str(exc) or
                          'Cannot link a source that does not exist' in str(exc)):
                        if retry < config.max_env_retry:
                            log.warn("failed to create env, retrying.  exception was: %s", str(exc))
                            create_env(prefix, specs, config=config,
                                    clear_cache=clear_cache, retry=retry + 1)
                    else:
                        raise
                # HACK: some of the time, conda screws up somehow and incomplete packages result.
                #    Just retry.
                except (AssertionError, IOError, ValueError, RuntimeError, LockError) as exc:
                    if retry < config.max_env_retry:
                        log.warn("failed to create env, retrying.  exception was: %s", str(exc))
                        create_env(prefix, specs, config=config,
                                   clear_cache=clear_cache, retry=retry + 1)
                    else:
                        log.error("Failed to create env, max retries exceeded.")
                        raise

    # ensure prefix exists, even if empty, i.e. when specs are empty
    if not isdir(prefix):
        os.makedirs(prefix)
    if utils.on_win:
        shell = "cmd.exe"
    else:
        shell = "bash"
    symlink_conda(prefix, sys.prefix, shell)


def get_installed_conda_build_version():
    root_linked = linked(root_dir)
    vers_inst = [dist.split('::', 1)[-1].rsplit('-', 2)[1] for dist in root_linked
        if dist.split('::', 1)[-1].rsplit('-', 2)[0] == 'conda-build']
    if not len(vers_inst) == 1:
        logging.getLogger(__name__).warn("Could not detect installed version of conda-build")
        return None
    return vers_inst[0]


def get_conda_build_index_versions(index):
    r = Resolve(index)
    pkgs = []
    try:
        pkgs = r.get_pkgs(MatchSpec('conda-build'))
    except (NoPackagesFound, NoPackagesFoundError):
        logging.getLogger(__name__).warn("Could not find any versions of conda-build "
                                         "in the channels")
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


def filter_files(files_list, prefix, filter_patterns=('(.*[\\\\/])?\.git[\\\\/].*',
                                                      'conda-meta.*',
                                                      '(.*)?\.DS_Store.*')):
    """Remove things like .git from the list of files to be copied"""
    for pattern in filter_patterns:
        r = re.compile(pattern)
        files_list = set(files_list) - set(filter(r.match, files_list))
    return [f.replace(prefix + os.path.sep, '') for f in files_list
            if (not os.path.isdir(os.path.join(prefix, f)) or
                os.path.islink(os.path.join(prefix, f)))]


def post_process_files(m, initial_prefix_files):
    get_build_metadata(m, config=m.config)
    create_post_scripts(m, config=m.config)

    # this is new-style noarch, with a value of 'python'
    if not is_noarch_python(m):
        utils.create_entry_points(m.get_value('build/entry_points'), config=m.config)
    current_prefix_files = prefix_files(prefix=m.config.build_prefix)

    post_process(sorted(current_prefix_files - initial_prefix_files),
                    prefix=m.config.build_prefix,
                    config=m.config,
                    preserve_egg_dir=bool(m.get_value('build/preserve_egg_dir')),
                    noarch=m.get_value('build/noarch'),
                    skip_compile_pyc=m.get_value('build/skip_compile_pyc'))

    # The post processing may have deleted some files (like easy-install.pth)
    current_prefix_files = prefix_files(prefix=m.config.build_prefix)
    new_files = sorted(current_prefix_files - initial_prefix_files)
    new_files = filter_files(new_files, prefix=m.config.build_prefix)
    if any(m.config.meta_dir in join(m.config.build_prefix, f) for f in new_files):
        meta_files = (tuple(f for f in new_files if m.config.meta_dir in
                join(m.config.build_prefix, f)),)
        sys.exit(indent("""Error: Untracked file(s) %s found in conda-meta directory.
This error usually comes from using conda in the build script.  Avoid doing this, as it
can lead to packages that include their dependencies.""" % meta_files))
    post_build(m, new_files, prefix=m.config.build_prefix, build_python=m.config.build_python,
               croot=m.config.croot)

    entry_point_script_names = get_entry_point_script_names(m.get_value('build/entry_points'))
    if is_noarch_python(m):
        pkg_files = [fi for fi in new_files if fi not in entry_point_script_names]
    else:
        pkg_files = new_files

    # the legacy noarch
    if m.get_value('build/noarch_python'):
        noarch_python.transform(m, new_files, m.config.build_prefix)
    # new way: build/noarch: python
    elif is_noarch_python(m):
        noarch_python.populate_files(m, pkg_files, m.config.build_prefix, entry_point_script_names)

    current_prefix_files = prefix_files(prefix=m.config.build_prefix)
    new_files = current_prefix_files - initial_prefix_files
    fix_permissions(new_files, m.config.build_prefix)

    return new_files


def bundle_conda(output, metadata, config, env, **kw):
    log = logging.getLogger(__name__)
    log.info('Packaging %s', metadata.dist())
    files = output.get('files', [])
    if not files and output.get('script'):
        interpreter = output.get('script_interpreter')
        if not interpreter:
            interpreter = guess_interpreter(output['script'])
        initial_files = prefix_files(config.build_prefix)
        utils.check_call_env(interpreter.split(' ') +
                    [os.path.join(metadata.path, output['script'])],
                    cwd=config.build_prefix, env=env)
    else:
        # we exclude the list of files that we want to keep, so post-process picks them up as "new"
        keep_files = set(utils.expand_globs(files, config.build_prefix))
        pfx_files = set(prefix_files(config.build_prefix))
        initial_files = set(item for item in (pfx_files - keep_files)
                            if not any(keep_file.startswith(item) for keep_file in keep_files))

    files = post_process_files(metadata, initial_files)

    output_filename = ('-'.join([output['name'], metadata.version(),
                                 metadata.build_id()]) + '.tar.bz2')
    # first filter is so that info_files does not pick up ignored files
    files = filter_files(files, prefix=config.build_prefix)
    create_info_files(metadata, files, config=config, prefix=config.build_prefix)
    for ext in ('.py', '.r', '.pl', '.lua', '.sh'):
        test_dest_path = os.path.join(config.info_dir, 'recipe', 'run_test' + ext)
        script = output.get('test', {}).get('script')
        if script and script.endswith(ext):
            utils.copy_into(os.path.join(metadata.path, output['test']['script']),
                            test_dest_path, config.timeout, locking=config.locking)
        elif os.path.isfile(test_dest_path) and metadata.meta.get('extra', {}).get('parent_recipe'):
            # the test belongs to the parent recipe.  Don't include it in subpackages.
            utils.rm_rf(test_dest_path)
    # here we add the info files into the prefix, so we want to re-collect the files list
    files = set(prefix_files(config.build_prefix)) - initial_files
    files = filter_files(files, prefix=config.build_prefix)

    # lock the output directory while we build this file
    # create the tarball in a temporary directory to minimize lock time
    with TemporaryDirectory() as tmp:
        tmp_path = os.path.join(tmp, os.path.basename(output_filename))
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
        for f in sorted(files, key=order):
            t.add(join(config.build_prefix, f), f)
        t.close()

        # we're done building, perform some checks
        tarcheck.check_all(tmp_path)
        if not getattr(config, "noverify", False):
            verifier = Verify()
            ignore_scripts = config.ignore_package_verify_scripts if \
                             config.ignore_package_verify_scripts else None
            run_scripts = config.run_package_verify_scripts if \
                          config.run_package_verify_scripts else None
            verifier.verify_package(ignore_scripts=ignore_scripts, run_scripts=run_scripts,
                                    path_to_package=tmp_path)
        if config.output_folder:
            output_folder = os.path.join(config.output_folder, metadata.config.subdir)
        else:
            output_folder = metadata.config.bldpkgs_dir
        final_output = os.path.join(output_folder, output_filename)
        if os.path.isfile(final_output):
            os.remove(final_output)
        print(final_output)
        utils.copy_into(tmp_path, final_output, config.timeout, locking=config.locking)

    update_index(os.path.dirname(output_folder), config=config)

    # HACK: conda really wants a noarch folder to be around.  Create it as necessary.
    if os.path.basename(output_folder) != 'noarch':
        try:
            os.makedirs(os.path.join(os.path.dirname(output_folder), 'noarch'))
        except OSError:
            pass
        update_index(os.path.join(os.path.dirname(output_folder), 'noarch'), config=config)

    # remove files from build prefix.  This is so that they can be included in other packages.  If
    #     we were to leave them in place, then later scripts meant to also include them may not.
    for f in files:
        if not os.path.isabs(f):
            f = os.path.abspath(os.path.normpath(os.path.join(metadata.config.build_prefix, f)))
        utils.rm_rf(f)
    return final_output


def bundle_wheel(output, metadata, config, env):
    import pip
    with TemporaryDirectory() as tmpdir, utils.tmp_chdir(config.work_dir):
        pip.main(['wheel', '--wheel-dir', tmpdir, '--no-deps', '.'])
        wheel_file = glob(os.path.join(tmpdir, "*.whl"))[0]
        if config.output_folder:
            output_folder = os.path.join(config.output_folder, metadata.config.subdir)
        else:
            output_folder = metadata.config.bldpkgs_dir
        utils.copy_into(wheel_file, output_folder, locking=config.locking)
    return os.path.join(output_folder, os.path.basename(wheel_file))


bundlers = {
    'conda': bundle_conda,
    'wheel': bundle_wheel,
}


def build(m, config, post=None, need_source_download=True, need_reparse_in_env=False):
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

    with utils.path_prepended(config.build_prefix):
        env = environ.get_dict(config=config, m=m)
    env["CONDA_BUILD_STATE"] = "BUILD"
    if env_path_backup_var_exists:
        env["CONDA_PATH_BACKUP"] = os.environ["CONDA_PATH_BACKUP"]

    if config.skip_existing:
        package_exists = is_package_built(m, config)
        if package_exists:
            print(m.dist(), "is already built in {0}, skipping.".format(package_exists))
            return []

    built_packages = []

    if post in [False, None]:
        print("BUILD START:", m.dist())
        if m.uses_jinja and (need_source_download or need_reparse_in_env):
            print("    (actual version deferred until further download or env creation)")

        specs = [ms.spec for ms in m.ms_depends('build')]
        if any(out.get('type') == 'wheel' for out in m.meta.get('outputs', [])):
            specs.extend(['pip', 'wheel'])
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
            with utils.path_prepended(config.build_prefix):
                m, need_source_download, need_reparse_in_env = parse_or_try_download(m,
                                                                no_download_source=False,
                                                                force_download=True,
                                                                config=config)
            m.final = True
            assert not need_source_download, "Source download failed.  Please investigate."
            if m.uses_jinja:
                print("BUILD START (revised):", m.dist())

        if need_reparse_in_env:
            reparse(m, config=config)
            m.final = True
            print("BUILD START (revised):", m.dist())

        print("Package:", m.dist())

        # get_dir here might be just work, or it might be one level deeper,
        #    dependening on the source.
        src_dir = config.work_dir
        if isdir(src_dir):
            print("source tree in:", src_dir)
        else:
            print("no source - creating empty work folder")
            os.makedirs(src_dir)

        utils.rm_rf(config.info_dir)
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
                import conda_build.windows as windows
                windows.build(m, build_file, config=config)
            else:
                build_file = join(m.path, 'build.sh')

                # There is no sense in trying to run an empty build script.
                if isfile(build_file) or script:
                    with utils.path_prepended(config.build_prefix):
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
                            bf.write('source "{conda_root}activate" "{build_prefix}" &> '
                                        '/dev/null\n'.format(conda_root=utils.root_script_dir +
                                                            os.path.sep,
                                                            build_prefix=config.build_prefix))
                            bf.write(data)
                    else:
                        if not isfile(work_file):
                            utils.copy_into(build_file, work_file, config.timeout,
                                            locking=config.locking)
                    os.chmod(work_file, 0o766)

                    if isfile(work_file):
                        cmd = [shell_path, '-x', '-e', work_file]
                        # this should raise if any problems occur while building
                        utils.check_call_env(cmd, env=env, cwd=src_dir)

    if post in [True, None]:
        with open(join(m.config.build_folder, 'prefix_files.txt'), 'r') as f:
            initial_files = set(f.read().splitlines())

        files = prefix_files(prefix=m.config.build_prefix) - initial_files
        outputs = m.get_output_metadata_set(files=files)

        output_folders = set()
        for (output_dict, m) in outputs:
            built_package = bundlers[output_dict.get('type', 'conda')](output_dict, m, config, env)
            built_packages.append(built_package)
            output_folders.add(os.path.dirname(built_package))

        for folder in output_folders:
            update_index(folder, config, could_be_mirror=False)

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


def clean_pkg_cache(dist, config):
    _pkgs_dirs = pkgs_dirs[:1]
    locks = []
    if config.locking:
        locks = [utils.get_lock(folder, timeout=config.timeout) for folder in _pkgs_dirs]
    with utils.try_acquire_locks(locks, timeout=config.timeout):
        rmplan = [
            'RM_EXTRACTED {0} local::{0}'.format(dist),
            'RM_FETCHED {0} local::{0}'.format(dist),
        ]
        execute_plan(rmplan)

        # Conda does not seem to do a complete cleanup sometimes.  This is supplemental.
        #   Conda's cleanup is still necessary - it keeps track of its own in-memory
        #   list of downloaded things.
        for folder in _pkgs_dirs:
            try:
                assert not os.path.exists(os.path.join(folder, dist))
                assert not os.path.exists(os.path.join(folder, dist + '.tar.bz2'))
                for pkg_id in [dist, 'local::' + dist]:
                    assert pkg_id not in package_cache()
            except AssertionError:
                log = logging.getLogger(__name__)
                log.debug("Conda caching error: %s package remains in cache after removal", dist)
                log.debug("manually removing to compensate")
                cache = package_cache()
                keys = [key for key in cache.keys() if dist in key]
                for pkg_id in keys:
                    if pkg_id in cache:
                        del cache[pkg_id]
                for entry in glob(os.path.join(folder, dist + '*')):
                    utils.rm_rf(entry)


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

    if hasattr(recipedir_or_package_or_metadata, 'config'):
        metadata = recipedir_or_package_or_metadata
        config = metadata.config
    else:
        recipe_dir, need_cleanup = utils.get_recipe_abspath(recipedir_or_package_or_metadata)
        config.need_cleanup = need_cleanup

        # This will create a new local build folder if and only if config doesn't already have one.
        #   What this means is that if we're running a test immediately after build, we use the one
        #   that the build already provided
        metadata, _, _ = render_recipe(recipe_dir, config=config)
        # this recipe came from an extracted tarball.
        if need_cleanup:
            # ensure that the local location of the package is indexed, so that conda can find the
            #    local package
            local_location = os.path.dirname(recipedir_or_package_or_metadata)
            # strip off extra subdir folders
            for platform in ('win', 'linux', 'osx'):
                if os.path.basename(local_location).startswith(platform + "-"):
                    local_location = os.path.dirname(local_location)
            update_index(local_location, config=config)
            if not os.path.abspath(local_location):
                local_location = os.path.normpath(os.path.abspath(
                    os.path.join(os.getcwd(), local_location)))
            local_url = url_path(local_location)
            # channel_urls is an iterable, but we don't know if it's a tuple or list.  Don't know
            #    how to add elements.
            config.channel_urls = list(config.channel_urls)
            config.channel_urls.insert(0, local_url)
            if (metadata.meta.get('test') and metadata.meta['test'].get('source_files') and
                    not os.listdir(config.work_dir)):
                source.provide(metadata, config=config)

    warn_on_use_of_SRC_DIR(metadata)

    config.compute_build_id(metadata.name())

    clean_pkg_cache(metadata.dist(), config)

    test_package_name = (recipedir_or_package_or_metadata.dist()
                         if hasattr(recipedir_or_package_or_metadata, 'dist')
                         else recipedir_or_package_or_metadata)

    create_files(config.test_dir, metadata, config)
    # Make Perl or Python-specific test files
    pl_files = create_pl_files(config.test_dir, metadata)
    py_files = create_py_files(config.test_dir, metadata)
    r_files = create_r_files(config.test_dir, metadata)
    lua_files = create_lua_files(config.test_dir, metadata)
    shell_files = create_shell_files(config.test_dir, metadata, config)
    if not any([py_files, shell_files, pl_files, lua_files, r_files]):
        print("Nothing to test for:", test_package_name)
        return True

    print("TEST START:", test_package_name)

    if config.remove_work_dir:
        # Needs to come after create_files in case there's test/source_files
        print("Deleting work directory,", config.work_dir)
        utils.rm_rf(config.work_dir)
    else:
        log.warn("Not removing work directory after build.  Your package may depend on files in "
                 "the work directory that are not included with your package")

    get_build_metadata(metadata, config=config)
    specs = ['%s %s %s' % (metadata.name(), metadata.version(), metadata.build_id())]

    # add packages listed in the run environment and test/requires
    specs.extend(ms.spec for ms in metadata.ms_depends('run'))
    specs += utils.ensure_list(metadata.get_value('test/requires', []))

    if py_files:
        # as the tests are run by python, ensure that python is installed.
        # (If they already provided python as a run or test requirement,
        #  this won't hurt anything.)
        specs += ['python %s.*' % environ.get_py_ver(config)]
    if pl_files:
        # as the tests are run by perl, we need to specify it
        specs += ['perl %s.*' % environ.get_perl_ver(config)]
    if lua_files:
        # not sure how this shakes out
        specs += ['lua %s.*' % environ.get_lua_ver(config)]
    if r_files:
        # not sure how this shakes out
        specs += ['r-base %s.*' % environ.get_r_ver(config)]

    create_env(config.test_prefix, specs, config=config)

    with utils.path_prepended(config.test_prefix):
        env = environ.get_dict(config=config, m=metadata, prefix=config.test_prefix)
        env["CONDA_BUILD_STATE"] = "TEST"
        if env_path_backup_var_exists:
            env["CONDA_PATH_BACKUP"] = os.environ["CONDA_PATH_BACKUP"]

    if not config.activate:
        # prepend bin (or Scripts) directory
        env = utils.prepend_bin_path(env, config.test_prefix, prepend_prefix=True)

        if utils.on_win:
            env['PATH'] = config.test_prefix + os.pathsep + env['PATH']

    for varname in 'CONDA_PY', 'CONDA_NPY', 'CONDA_PERL', 'CONDA_LUA':
        env[varname] = str(getattr(config, varname) or '')

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
            test_python = config.test_python
            # use pythonw for import tests when osx_is_app is set
            if metadata.get_value('build/osx_is_app') and sys.platform == 'darwin':
                test_python = test_python + 'w'
            tf.write('"{python}" -s "{test_file}"\n'.format(
                python=config.test_python,
                test_file=join(config.test_dir, 'run_test.py')))
            if utils.on_win:
                tf.write("if errorlevel 1 exit 1\n")
        if pl_files:
            tf.write('"{perl}" "{test_file}"\n'.format(
                perl=config.perl_bin(config.test_prefix),
                test_file=join(config.test_dir, 'run_test.pl')))
            if utils.on_win:
                tf.write("if errorlevel 1 exit 1\n")
        if lua_files:
            tf.write('"{lua}" "{test_file}"\n'.format(
                lua=config.lua_bin(config.test_prefix),
                test_file=join(config.test_dir, 'run_test.lua')))
            if utils.on_win:
                tf.write("if errorlevel 1 exit 1\n")
        if r_files:
            tf.write('"{r}" "{test_file}"\n'.format(
                r=config.r_bin(config.test_prefix),
                test_file=join(config.test_dir, 'run_test.r')))
            if utils.on_win:
                tf.write("if errorlevel 1 exit 1\n")
        if shell_files:
            test_file = join(config.test_dir, 'run_test.' + suffix)
            if utils.on_win:
                tf.write('call "{test_file}"\n'.format(test_file=test_file))
                if utils.on_win:
                    tf.write("if errorlevel 1 exit 1\n")
            else:
                # TODO: Run the test/commands here instead of in run_test.py
                tf.write('"{shell_path}" -x -e "{test_file}"\n'.format(shell_path=shell_path,
                                                                       test_file=test_file))
    if utils.on_win:
        cmd = ['cmd.exe', "/d", "/c", test_script]
    else:
        cmd = [shell_path, '-x', '-e', test_script]
    try:
        utils.check_call_env(cmd, env=env, cwd=config.test_dir)
    except subprocess.CalledProcessError:
        tests_failed(metadata, move_broken=move_broken, broken_dir=config.broken_dir, config=config)

    if need_cleanup:
        utils.rm_rf(recipe_dir)

    print("TEST END:", test_package_name)
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


def build_tree(recipe_list, config, build_only=False, post=False, notest=False,
               need_source_download=True, need_reparse_in_env=False):

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
    built_packages = []
    retried_recipes = []

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
            config = metadata.config
            # this code is duplicated below because we need to be sure that the build id is set
            #    before downloading happens - or else we lose where downloads are
            if config.set_build_id:
                config.compute_build_id(metadata.name(), reset=True)
            recipe_parent_dir = ""
            to_build_recursive.append(metadata.name())
        else:
            recipe_parent_dir = os.path.dirname(recipe)
            recipe = recipe.rstrip("/").rstrip("\\")
            to_build_recursive.append(os.path.basename(recipe))

            metadata, need_source_download, need_reparse_in_env = render_recipe(recipe,
                                                                    config=config)
        if not getattr(config, "noverify", False):
            verifier = Verify()
            ignore_scripts = config.ignore_recipe_verify_scripts if \
                config.ignore_recipe_verify_scripts else None
            run_scripts = config.run_recipe_verify_scripts if \
                config.run_recipe_verify_scripts else None
            verifier.verify_recipe(ignore_scripts=ignore_scripts, run_scripts=run_scripts,
                                   rendered_meta=metadata.meta, recipe_dir=metadata.path)

        if metadata.name() not in metadata.config.build_folder and metadata.config.set_build_id:
            metadata.config.compute_build_id(metadata.name(), reset=True)
        try:
            with config:
                packages_from_this = build(metadata, post=post,
                                           need_source_download=need_source_download,
                                           need_reparse_in_env=need_reparse_in_env,
                                           config=config)
                if not notest and packages_from_this:
                    for pkg in packages_from_this:
                        if pkg.endswith('.tar.bz2'):
                            # we only know how to test conda packages
                            try:
                                test(pkg, config=config)
                            # IOError means recipe was not included with package. metadata instead
                            except IOError:
                                test(metadata, config=config)
                        built_packages.append(pkg)
        except (NoPackagesFound, NoPackagesFoundError, Unsatisfiable, CondaError) as e:
            error_str = str(e)
            skip_names = ['python', 'r']
            add_recipes = []
            # add the failed one back in at the beginning - but its deps may come before it
            recipe_list.extendleft([recipe])
            for line in error_str.splitlines():
                if not line.startswith('  - '):
                    continue
                pkg = line.lstrip('  - ').split(' -> ')[-1]
                pkg = pkg.strip().split(' ')[0]

                if pkg in to_build_recursive:
                    raise RuntimeError("Can't build {0} due to environment creation error:\n"
                                       .format(recipe) + error_str + "\n" + extra_help)

                if pkg in skip_names:
                    to_build_recursive.append(pkg)
                    extra_help = """Typically if a conflict is with the Python or R
packages, the other package needs to be rebuilt
(e.g., a conflict with 'python 3.5*' and 'x' means
'x' isn't build for Python 3.5 and needs to be rebuilt."""

                recipe_glob = glob(os.path.join(recipe_parent_dir, pkg))
                if recipe_glob:
                    for recipe_dir in recipe_glob:
                        print(("Missing dependency {0}, but found" +
                                " recipe directory, so building " +
                                "{0} first").format(pkg))
                        add_recipes.append(recipe_dir)
                else:
                    raise RuntimeError("Can't build {0} due to unsatisfiable dependencies:\n{1}"
                                       .format(recipe, error_str) + "\n\n" + extra_help)
            if retried_recipes.count(recipe) >= len(metadata.ms_depends('build')):
                raise RuntimeError("Can't build {0} due to environment creation error:\n"
                                    .format(recipe) + error_str + "\n" + extra_help)
            retried_recipes.append(recipe)
            recipe_list.extendleft(add_recipes)

    if post in [True, None]:
        # TODO: could probably use a better check for pkg type than this...
        tarballs = [f for f in built_packages if f.endswith('.tar.bz2')]
        wheels = [f for f in built_packages if f.endswith('.whl')]
        handle_anaconda_upload(tarballs, config=config)
        handle_pypi_upload(wheels, config=config)
    return built_packages


def handle_anaconda_upload(paths, config):
    from conda_build.os_utils.external import find_executable

    paths = utils.ensure_list(paths)

    upload = False
    # this is the default, for no explicit argument.
    # remember that anaconda_upload takes defaults from condarc
    if config.anaconda_upload is None:
        pass
    elif config.token or config.user:
        upload = True
    # rc file has uploading explicitly turned off
    elif config.anaconda_upload is False:
        print("# Automatic uploading is disabled")
        upload = False
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
    cmd.extend(['upload', '--force'])
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
                logging.getLogger(__name__).warn("wheel upload failed - is twine installed?"
                                                "  Is this package registered?")
                logging.getLogger(__name__).warn("Wheel file left in {}".format(f))

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
    package_exists = [url for url in urls
                      if dist_str_in_index(index, url + '::' + metadata.pkg_fn())]
    return package_exists or dist_str_in_index(index, metadata.pkg_fn())


def is_noarch_python(meta):
    return str(meta.get_value('build/noarch')).lower() == "python"
