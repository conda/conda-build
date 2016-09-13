# (c) Continuum Analytics, Inc. / http://continuum.io
# All Rights Reserved
#
# conda is distributed under the terms of the BSD 3-clause license.
# Consult LICENSE.txt or http://opensource.org/licenses/BSD-3-Clause.

from __future__ import absolute_import, division, print_function

from collections import defaultdict
import logging
from operator import itemgetter
from os.path import abspath, join, dirname, exists, basename, isdir
import re
import sys
import tempfile

from .conda_interface import (iteritems, specs_from_args, plan, is_linked, linked_data, linked,
                              get_index)


from conda_build.os_utils.ldd import get_linkages, get_package_obj_files, get_untracked_obj_files
from conda_build.os_utils.macho import get_rpaths, human_filetype
from conda_build.utils import groupby, getter, comma_join, rm_rf


log = logging.getLogger(__file__)


def which_prefix(path):
    """
    given the path (to a (presumably) conda installed file) return the
    environment prefix in which the file in located
    """
    prefix = abspath(path)
    while True:
        if isdir(join(prefix, 'conda-meta')):
            # we found the it, so let's return it
            return prefix
        if prefix == dirname(prefix):
            # we cannot chop off any more directories, so we didn't find it
            return None
        prefix = dirname(prefix)


def which_package(path):
    """
    given the path (of a (presumably) conda installed file) iterate over
    the conda packages the file came from.  Usually the iteration yields
    only one package.
    """
    path = abspath(path)
    prefix = which_prefix(path)
    if prefix is None:
        raise RuntimeError("could not determine conda prefix from: %s" % path)
    for dist in linked(prefix):
        meta = is_linked(prefix, dist)
        if any(abspath(join(prefix, f)) == path for f in meta['files']):
            yield dist


def print_object_info(info, key):
    output_string = ""
    gb = groupby(key, info)
    for header in sorted(gb, key=str):
        output_string += header + "\n"
        for f_info in sorted(gb[header], key=getter('filename')):
            for data in sorted(f_info):
                if data == key:
                    continue
                if f_info[data] is None:
                    continue
                output_string += '  %s: %s\n' % (data, f_info[data])
            if len([i for i in f_info if f_info[i] is not None and i != key]) > 1:
                output_string += '\n'
        output_string += '\n'
    return output_string


class _untracked_package:
    def __str__(self):
        return "<untracked>"


untracked_package = _untracked_package()


def check_install(packages, platform=None, channel_urls=(), prepend=True,
                  minimal_hint=False):
    prefix = tempfile.mkdtemp('conda')
    try:
        specs = specs_from_args(packages)
        index = get_index(channel_urls=channel_urls, prepend=prepend,
                          platform=platform, prefix=prefix)
        actions = plan.install_actions(prefix, index, specs, pinned=False,
                                       minimal_hint=minimal_hint)
        plan.display_actions(actions, index)
        return actions
    finally:
        rm_rf(prefix)
    return None


def print_linkages(depmap, show_files=False):
    # Print system and not found last
    k = sorted(set(depmap.keys()) - {'system', 'not found'})
    all_deps = k if 'not found' not in depmap.keys() else k + ['system', 'not found']
    output_string = ""
    for dep in all_deps:
        output_string += "%s:\n" % dep
        if show_files:
            for lib, path, binary in sorted(depmap[dep]):
                output_string += "    %s (%s) from %s\n" % (lib, path, binary)
        else:
            for lib, path in sorted(set(map(itemgetter(0, 1), depmap[dep]))):
                output_string += "    %s (%s)\n" % (lib, path)
        output_string += "\n"
    return output_string


def replace_path(binary, path, prefix):
    if sys.platform.startswith('linux'):
        return abspath(path)
    elif sys.platform.startswith('darwin'):
        if path == basename(binary):
            return abspath(join(prefix, binary))
        if '@rpath' in path:
            rpaths = get_rpaths(join(prefix, binary))
            if not rpaths:
                return "NO LC_RPATH FOUND"
            else:
                for rpath in rpaths:
                    path1 = path.replace("@rpath", rpath)
                    path1 = path1.replace('@loader_path', join(prefix, dirname(binary)))
                    if exists(abspath(join(prefix, path1))):
                        path = path1
                        break
                else:
                    return 'not found'
        path = path.replace('@loader_path', join(prefix, dirname(binary)))
        if path.startswith('/'):
            return abspath(path)
        return 'not found'


def test_installable(channel='defaults'):
    success = True
    has_py = re.compile(r'py(\d)(\d)')
    for platform in ['osx-64', 'linux-32', 'linux-64', 'win-32', 'win-64']:
        log.info("######## Testing platform %s ########", platform)
        channels = [channel]
        index = get_index(channel_urls=channels, prepend=False, platform=platform)
        for _, rec in iteritems(index):
            # If we give channels at the command line, only look at
            # packages from those channels (not defaults).
            if channel != 'defaults' and rec.get('schannel', 'defaults') == 'defaults':
                continue
            name = rec['name']
            if name in {'conda', 'conda-build'}:
                # conda can only be installed in the root environment
                continue
            # Don't fail just because the package is a different version of Python
            # than the default.  We should probably check depends rather than the
            # build string.
            build = rec['build']
            match = has_py.search(build)
            assert match if 'py' in build else True, build
            if match:
                additional_packages = ['python=%s.%s' % (match.group(1), match.group(2))]
            else:
                additional_packages = []

            version = rec['version']
            log.info('Testing %s=%s', name, version)

            try:
                install_steps = check_install([name + '=' + version] + additional_packages,
                                                channel_urls=channels, prepend=False,
                                                platform=platform)
                success &= bool(install_steps)
            except KeyboardInterrupt:
                raise
            # sys.exit raises an exception that doesn't subclass from Exception
            except BaseException as e:
                success = False
                log.error("FAIL: %s %s on %s with %s (%s)", name, version,
                          platform, additional_packages, e)
    return success


def _installed(prefix):
    installed = linked_data(prefix)
    installed = {rec['name']: dist for dist, rec in iteritems(installed)}
    return installed


def _underlined_text(text):
    return str(text) + '\n' + '-' * len(str(text)) + '\n\n'


def inspect_linkages(packages, prefix=sys.prefix, untracked=False,
                     all_packages=False, show_files=False, groupby="package"):
    pkgmap = {}

    installed = _installed(prefix)

    if not packages and not untracked and not all_packages:
        raise ValueError("At least one package or --untracked or --all must be provided")

    if all_packages:
        packages = sorted(installed.keys())

    if untracked:
        packages.append(untracked_package)

    for pkg in packages:
        if pkg == untracked_package:
            dist = untracked_package
        elif pkg not in installed:
            sys.exit("Package %s is not installed in %s" % (pkg, prefix))
        else:
            dist = installed[pkg]

        if not sys.platform.startswith(('linux', 'darwin')):
            sys.exit("Error: conda inspect linkages is only implemented in Linux and OS X")

        if dist == untracked_package:
            obj_files = get_untracked_obj_files(prefix)
        else:
            obj_files = get_package_obj_files(dist, prefix)
        linkages = get_linkages(obj_files, prefix)
        depmap = defaultdict(list)
        pkgmap[pkg] = depmap
        depmap['not found'] = []
        for binary in linkages:
            for lib, path in linkages[binary]:
                path = replace_path(binary, path, prefix) if path not in {'',
                                                                            'not found'} else path
                if path.startswith(prefix):
                    deps = list(which_package(path))
                    if len(deps) > 1:
                        log.warn("Warning: %s comes from multiple packages: %s", path,
                                 comma_join(deps))
                    if not deps:
                        if exists(path):
                            depmap['untracked'].append((lib, path.split(prefix +
                                '/', 1)[-1], binary))
                        else:
                            depmap['not found'].append((lib, path.split(prefix +
                                '/', 1)[-1], binary))
                    for d in deps:
                        depmap[d].append((lib, path.split(prefix + '/',
                            1)[-1], binary))
                elif path == 'not found':
                    depmap['not found'].append((lib, path, binary))
                else:
                    depmap['system'].append((lib, path, binary))

    output_string = ""
    if groupby == 'package':
        for pkg in packages:
            output_string += _underlined_text(pkg)
            output_string += print_linkages(pkgmap[pkg], show_files=show_files)

    elif groupby == 'dependency':
        # {pkg: {dep: [files]}} -> {dep: {pkg: [files]}}
        inverted_map = defaultdict(lambda: defaultdict(list))
        for pkg in pkgmap:
            for dep in pkgmap[pkg]:
                if pkgmap[pkg][dep]:
                    inverted_map[dep][pkg] = pkgmap[pkg][dep]

        # print system and not found last
        k = sorted(set(inverted_map.keys()) - {'system', 'not found'})
        for dep in k + ['system', 'not found']:
            output_string += _underlined_text(dep)
            output_string += print_linkages(inverted_map[dep], show_files=show_files)

    else:
        raise ValueError("Unrecognized groupby: %s" % groupby)
    if hasattr(output_string, 'decode'):
        output_string = output_string.decode('utf-8')
    return output_string


def inspect_objects(packages, prefix=sys.prefix, groupby='package'):
    installed = _installed(prefix)

    output_string = ""
    for pkg in packages:
        if pkg == untracked_package:
            dist = untracked_package
        elif pkg not in installed:
            raise ValueError("Package %s is not installed in %s" % (pkg, prefix))
        else:
            dist = installed[pkg]

        output_string += _underlined_text(pkg)

        if not sys.platform.startswith('darwin'):
            sys.exit("Error: conda inspect objects is only implemented in OS X")

        if dist == untracked_package:
            obj_files = get_untracked_obj_files(prefix)
        else:
            obj_files = get_package_obj_files(dist, prefix)

        info = []
        for f in obj_files:
            f_info = {}
            path = join(prefix, f)
            f_info['filetype'] = human_filetype(path)
            f_info['rpath'] = ':'.join(get_rpaths(path))
            f_info['filename'] = f
            info.append(f_info)

        output_string += print_object_info(info, groupby)
    if hasattr(output_string, 'decode'):
        output_string = output_string.decode('utf-8')
    return output_string
