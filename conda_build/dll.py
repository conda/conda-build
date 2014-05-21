#===============================================================================
# Imports
#===============================================================================
import os
import re
import sys

from abc import (
    ABCMeta,
    abstractmethod,
)

from os import (
    readlink,
)

from os.path import (
    join,
    islink,
    abspath,
    dirname,
    basename,
    normpath,
)

from subprocess import (
    check_output,
)

from collections import (
    defaultdict,
)

from conda.utils import (
    memoize,
)

from conda_build.config import (
    build_prefix,
)

#===============================================================================
# Globals
#===============================================================================
is_linux = (sys.platform.startswith('linux'))
is_darwin = (sys.platform == 'darwin')
is_win32 = (sys.platform == 'win32')

assert sum(int(i) for i in (is_linux, is_darwin, is_win32)) == 1

#===============================================================================
# Misc Helpers
#===============================================================================
def try_int(i):
    if not i:
        return
    try:
        i = int(i)
    except ValueError:
        return
    else:
        return i

def is_int(i):
    try:
        int(i)
    except ValueError:
        return False
    else:
        return True

def version_combinations(s):
    """
    >>> version_combinations('5.10.0')
    ['5.10.0', '5.10', '5']
    >>> version_combinations('3.2')
    ['3.2', '3']
    >>> version_combinations('6')
    ['6']
    """
    if '.' not in s:
        return [s] if try_int(s) else None

    ints = s.split('.')
    if not all(is_int(i) for i in ints):
        return None

    return [ '.'.join(ints[:x]) for x in reversed(range(1, len(ints)+1)) ]

def invert_defaultdict_by_value_len(d):
    i = {}
    for (k, v) in d.items():
        i.setdefault(len(v), []).append(k)
    return i

def package_name_providing_link_target(libname):
    # xxx todo: perhaps dispatch this inquiry to a server-side request that
    # can better answer the question of "are there *any* conda packages that
    # provide this dll to link against?".  For now, just return None.
    return None

#===============================================================================
# Path-related Helpers
#===============================================================================
def get_base_dir(path):
    p = path
    pc = p.count('/')
    assert p and p[0] == '/' and pc >= 1
    if p == '/' or pc == 1 or (pc == 2 and p[-1] == '/'):
        return '/'

    assert pc >= 2
    return dirname(p[:-1] if p[-1] == '/' else p) + '/'

def reduce_path(p):
    assert p and p[0] == '/'
    r = list()
    end = p.rfind('/')
    while end != -1:
        r.append(p[:end+1])
        end = p.rfind('/', 0, end)
    return r

def join_path(*args):
    return abspath(normpath(join(*args)))

def format_path(path, is_dir=None):
    """
    >>> format_path('src', True)
    '/src/'

    >>> format_path('src', False)
    '/src'

    >>> format_path('src/foo', True)
    '/src/foo/'

    >>> format_path('///src///foo///mexico.txt//', False)
    '/src/foo/mexico.txt'

    >>> format_path('///src///foo///mexico.txt//')
    '/src/foo/mexico.txt/'

    >>> format_path('///src///foo///mexico.txt')
    '/src/foo/mexico.txt'

    >>> format_path(r'\\the\\quick\\brown\\fox.txt', False)
    '/\\\\the\\\\quick\\\\brown\\\\fox.txt'

    >>> format_path('/')
    '/'

    >>> format_path('/', True)
    '/'

    >>> format_path('/', False)
    Traceback (most recent call last):
        ...
    AssertionError

    >>> format_path('/a')
    '/a'

    >>> format_path('/ab')
    '/ab'

    >>> format_path(None)
    Traceback (most recent call last):
        ...
    AssertionError

    >>> format_path('//')
    Traceback (most recent call last):
        ...
    AssertionError

    >>> format_path('/', True)
    '/'

    # On Unix, '\' is a legitimate file name.  Trying to wrangle the right
    # escapes when testing '/' and '\' combinations is an absolute 'mare;
    # so we use ord() instead to compare numerical values of characters.
    >>> _w = lambda p: [ ord(c) for c in p ]
    >>> b = chr(92) # forward slash
    >>> f = chr(47) # backslash
    >>> foo = [102, 111, 111] # ord repr for 'foo'
    >>> b2 = b*2
    >>> _w(format_path('/'+b))
    [47, 92]

    >>> _w(format_path('/'+b2))
    [47, 92, 92]

    >>> _w(format_path('/'+b2, is_dir=False))
    [47, 92, 92]

    >>> _w(format_path('/'+b2, is_dir=True))
    [47, 92, 92, 47]

    >>> _w(format_path(b2*2))
    [47, 92, 92, 92, 92]

    >>> _w(format_path(b2*2, is_dir=True))
    [47, 92, 92, 92, 92, 47]

    >>> _w(format_path('/foo/'+b))
    [47, 102, 111, 111, 47, 92]

    >>> _w(format_path('/foo/'+b, is_dir=False))
    [47, 102, 111, 111, 47, 92]

    >>> _w(format_path('/foo/'+b, is_dir=True))
    [47, 102, 111, 111, 47, 92, 47]

    """
    assert (
        path and
        path not in ('//', '///') and
        is_dir in (True, False, None)
    )

    if path == '/':
        assert is_dir in (True, None)
        return '/'

    p = path
    while True:
        if re.search('//', p):
            p = p.replace('//', '/')
        else:
            break

    if p == '/':
        assert is_dir in (True, None)
        return '/'

    if p[0] != '/':
        p = '/' + p

    if is_dir is True:
        if p[-1] != '/':
            p += '/'
    elif is_dir is False:
        if p[-1] == '/':
            p = p[:-1]

    return p

def format_dir(path):
    return format_path(path, is_dir=True)

def format_file(path):
    return format_path(path, is_dir=False)

def assert_no_file_dir_clash(paths):
    """
    >>> assert_no_file_dir_clash('lskdjf')
    Traceback (most recent call last):
        ...
    AssertionError

    >>> assert_no_file_dir_clash(False)
    Traceback (most recent call last):
        ...
    AssertionError

    >>> assert_no_file_dir_clash(['/src/', '/src/'])
    Traceback (most recent call last):
        ...
    AssertionError

    >>> assert_no_file_dir_clash(['/src', '/src/'])
    Traceback (most recent call last):
        ...
    AssertionError

    >>> assert_no_file_dir_clash(['/sr', '/src/', '/srcb/'])
    >>>

    """
    assert paths and hasattr(paths, '__iter__')
    seen = set()
    for p in paths:
        assert not p in seen
        seen.add(p)

    assert all(
        (p[:-1] if p[-1] == '/' else p + '/') not in seen
            for p in paths
    )


def get_root_path(paths):
    """
    Given a list of paths (directories or files), return the root directory or
    an empty string if no root can be found.

    >>> get_root_path(['/src/', '/src/trunk/', '/src/trunk/test.txt'])
    '/src/'
    >>> get_root_path(['/src/', '/src/trk/', '/src/trk/test.txt', '/src/a'])
    '/src/'
    >>> get_root_path(['/', '/laksdjf', '/lkj'])
    '/'
    >>> get_root_path(['/'])
    '/'
    >>> get_root_path(['/a'])
    '/'
    >>>
    >>> get_root_path(['/src/trunk/foo.txt', '/src/tas/2009.01.00/foo.txt'])
    '/src/'
    >>> get_root_path(['/src/branches/foo/'])
    '/src/branches/foo/'

    >>> get_root_path(['',])
    Traceback (most recent call last):
        ...
    AssertionError

    >>> get_root_path(['lskdjf',])
    Traceback (most recent call last):
        ...
    AssertionError

    >>> get_root_path(['src/trunk/',])
    Traceback (most recent call last):
        ...
    AssertionError

    >>> get_root_path(['/src/trunk/', '/src/trunk'])
    Traceback (most recent call last):
        ...
    AssertionError
    """
    assert (
        hasattr(paths, '__iter__')   and
        #len(paths) >= 1              and
        all(d and d[0] == '/' for d in paths)
    )

    def _parts(p):
        parts = p.split('/')
        return parts if p[-1] == '/' else parts[:-1]

    paths = [ format_path(p) for p in paths ]
    assert_no_file_dir_clash(paths)

    common = _parts(paths[0])

    for j in range(1, len(paths)):
        parts =  _parts(paths[j])
        for i in range(len(common)):
            if i == len(parts) or common[i] != parts[i]:
                del common[i:]
                break
    if not common or (len(common) == 1 and common[0] == ''):
        return '/'

    return format_dir('/'.join(common))


#===============================================================================
# Library-related Helpers
#===============================================================================
def possible_link_target_names(dll):
    """
    >>> possible_link_target_names('libvtk.so.5.10.1')
    ['libvtk.so.5.10.1', 'libvtk.so.5.10', 'libvtk.so.5', 'libvtk.so']
    >>> possible_link_target_names('libQt.4.7.5.dylib')
    ['libQt.4.7.5.dylib', 'libQt.4.7.dylib', 'libQt.4.dylib', 'libQt.dylib']
    >>> possible_link_target_names('foo')
    ['foo']
    >>> possible_link_target_names('kernel32.dll')
    ['kernel32.dll']
    """

    targets = None

    if dll.endswith('.dylib') and dll.count('.') > 1:
        # if dll = 'libQtXml.4.7.5.dylib', head = 'libQtXml', vers = '4.7.5'
        h_ix = dll.find('.')
        t_ix = dll.rfind('.')
        head = dll[:h_ix]
        vers = dll[h_ix+1:t_ix]

        versions = version_combinations(vers)
        if versions:
            targets = [ '%s.%s.dylib' % (head, v) for v in versions ]
            targets.append('%s.dylib' % head)

    elif '.so.' in dll:

        # if dll == 'libvtkverdict.so.5.10.1', tail == '5.10.1'
        (head, sep, tail) = dll.partition('.so.')

        versions = version_combinations(tail)
        if versions:
            targets = [ '%s.so.%s' % (head, v) for v in versions ]
            targets.append('%s.so' % head)

    if not targets:
        targets = [dll]

    return targets

def parse_ldd_output(output):
    """
    >>> from pprint import pprint
    >>> pprint(parse_ldd_output(sample_ldd_output))
    [('libgfortran.so.1', '/home/r/miniconda/envs/_build/lib/libgfortran.so.1'),
     ('libRblas.so', None),
     ('libm.so.6', '/home/r/miniconda/envs/_build/lib/libm.so.6'),
     ('libreadline.so.6', '/home/r/miniconda/envs/_build/lib/libreadline.so.6'),
     ('libncurses.so.5', '/usr/lib64/libncurses.so.5'),
     ('librt.so.1', '/lib64/librt.so.1'),
     ('libdl.so.2', '/lib64/libdl.so.2'),
     ('libgomp.so.1', '/usr/lib64/libgomp.so.1'),
     ('libpthread.so.0', '/lib64/libpthread.so.0'),
     ('libc.so.6', '/lib64/libc.so.6')]
    """
    seen = set()
    results = []
    lines = output.splitlines()
    pairs = [ line[1:].split(' => ') for line in lines ]
    for pair in pairs:
        if len(pair) == 1:
            # This will typically be the last /lib64/ld-linux-x86-64.so.2
            # entry (for example).
            continue
        (depname, target) = pair
        assert depname not in seen, (depname, seen)
        seen.add(depname)
        if target.startswith(' (0x'):
            continue
        elif target == 'not found':
            results.append((depname, None))
            continue

        target = target[:target.rfind(' ')]

        if target[0] == '/' and '..' in target:
            target = abspath(normpath(target))

        results.append((depname, target))

    return results

def relative_path(library_path, target_dir):
    """
    >>> dll = 'lib/python2.7/site-packages/rpy2/rinterface/_rinterface.so'
    >>> relative_path(dll, 'lib')
    '../../../..'
    >>> relative_path(dll, 'lib64/R/lib')
    '../../../../../lib64/R/lib'
    >>> relative_path(dll, 'lib/python2.7/site-packages/rpy2/rinterface')
    ''
    """
    if dirname(library_path) == target_dir:
        return ''

    paths = [ format_file(library_path), format_dir(target_dir) ]
    root = get_root_path(paths)

    slashes = library_path.count('/')
    if root != '/':
        slashes -= 1
        suffix = ''
    else:
        suffix = '/' + target_dir

    return normpath(slashes * '../') + suffix

def get_library_dependencies(dll):
    if is_linux:
        return parse_ldd_output(check_output(['ldd', dll]))
    else:
        raise NotImplementedError()

def categorize_dependencies(deps, build_root):
    inside = set()
    outside = set()
    missing = set()

    for (depname, target) in deps:
        if not target:
            missing.add(depname)
        elif target.startswith(build_root):
            inside.add(depname)
        else:
            outside.add(depname)

    return (inside, outside, missing)


#===============================================================================
# Helper Classes
#===============================================================================
class SlotObject(object):
    # Subclasses need to define __slots__
    _default_ = None

    _to_dict_prefix_ = ''
    _to_dict_suffix_ = ''
    _to_dict_exclude_ = set()

    # Defaults to _to_dict_exclude_ if not set.
    _repr_exclude_ = set()

    def __init__(self, *args, **kwds):
        seen = set()
        slots = list(self.__slots__)
        args = [ a for a in args ]
        while args:
            (key, value) = (slots.pop(0), args.pop(0))
            seen.add(key)
            setattr(self, key, value)

        for (key, value) in kwds.iteritems():
            seen.add(key)
            setattr(self, key, value)

        for slot in self.__slots__:
            if slot not in seen:
                setattr(self, slot, self._default_)

        return

    def _to_dict(self, prefix=None, suffix=None, exclude=None):
        prefix = prefix or self._to_dict_prefix_
        suffix = suffix or self._to_dict_suffix_
        exclude = exclude or self._to_dict_exclude_
        return {
            '%s%s%s' % (prefix, key, suffix): getattr(self, key)
                for key in self.__slots__
                     if key not in exclude
        }

    def __repr__(self):
        slots = self.__slots__
        exclude = self._repr_exclude_ or self._to_dict_exclude_

        q = lambda v: v if (not v or isinstance(v, int)) else '"%s"' % v
        return "<%s %s>" % (
            self.__class__.__name__,
            ', '.join(
                '%s=%s' % (k, q(v))
                    for (k, v) in (
                        (k, getattr(self, k))
                            for k in slots
                                if k not in exclude
                    )
                )
        )

#===============================================================================
# Dynamic Library Classes
#===============================================================================
class LibraryDependencies(SlotObject):
    __slots__ = (
        'inside',
        'outside',
        'missing',
    )

    def __init__(self, deps, prefix=None):
        if not prefix:
            prefix = build_prefix

        inside = set()
        outside = set()
        missing = set()

        for (depname, target) in deps:
            if not target:
                missing.add(depname)
            elif target.startswith(prefix):
                inside.add(depname)
            else:
                outside.add(target)

        self.inside = inside
        self.outside = outside
        self.missing = missing

class LinkError_RecipeCorrectButBuildScriptBroken(SlotObject, BaseException):
    __slots__ = (
        'dependent_library_name',
        'expected_link_target',
        'actual_link_target',
    )
    def __init__(self, *args):
        SlotObject.__init__(self, *args)
        self.message = repr(self)

class LinkError_MissingPackageDependencyInRecipe(SlotObject, BaseException):
    __slots__ = (
        'dependent_library_name',
        'missing_package_dependency',
    )
    def __init__(self, *args):
        SlotObject.__init__(self, *args)
        self.message = repr(self)

class DynamicLibrary(LibraryDependencies):
    __metaclass__ = ABCMeta
    __slots__ = LibraryDependencies.__slots__ + (
        'path',
        'prefix',
        'relative',
        'build_root',
        'runtime_paths',
        'relative_runtime_paths',
    )

    def __init__(self, path, build_root):
        self.path = path
        self.prefix = build_root.prefix
        self.relative = path.replace(self.prefix, '')[1:]
        self.build_root = build_root

        deps = get_library_dependencies(path)
        LibraryDependencies.__init__(self, deps, self.prefix)

        self._check_outside_targets()
        self._resolve_inside_and_missing_targets()
        self._resolve_relative_runtime_paths()

    def _check_outside_targets(self):
        # For targets outside the build root, we want to make sure the target
        # isn't something that should actually be linking to within the build
        # prefix.  For now, we just check for targets that also appear in the
        # build prefix... which helps if you've set the meta.yaml dependencies
        # correctly but balked your build.
        #
        # We can improve this down the track such that conda has awareness of
        # *all* deps (i.e. every .so of every official package), such that we
        # could detect the (arguably more common) situation where a recipe is
        # missing the required dependencies.
        #
        # (Further down the track, I'd like to see this sort of awareness
        # harnessed to build tools that help automate the writing of recipes;
        # the less domain knowledge you need to leverage the power of conda
        # build, the more widespread the adoption.)

        build_root = self.build_root
        for path in self.outside:
            name = basename(path)
            if name in build_root:
                cls = LinkError_RecipeCorrectButBuildScriptBroken
                expected = build_root[name]
                actual = path
                raise cls(name, expected, actual)
            else:
                package = package_name_providing_link_target(name)
                if not package:
                    continue
                cls = LinkError_MissingPackageDependencyInRecipe
                raise cls(name, package)

    def _resolve_inside_and_missing_targets(self):

        build_root = self.build_root
        rpaths = set()
        for attr in ('inside', 'missing'):
            libs = getattr(self, attr)
            for name in libs:
                rpaths.add(build_root[name])
                continue

        self.runtime_paths = rpaths

    def _resolve_relative_runtime_paths(self):
        assert self.runtime_paths, repr(self)
        self.relative_runtime_paths = [
            relative_path(self.relative, target)
                for target in self.runtime_paths
        ]


    @classmethod
    def create(cls, *args, **kwds):
        # Poor man's multidispatch.
        if is_linux:
            cls = LinuxDynamicLibrary
        elif is_darwin:
            cls = DarwinDynamicLibrary
        else:
            cls = Win32DynamicLibrary
        return cls(*args, **kwds)

    @abstractmethod
    def make_relocatable(self):
        raise NotImplementedError()

    @property
    @memoize
    def rpath(self):
        pass


class LinuxDynamicLibrary(DynamicLibrary):
    def make_relocatable(self):
        raise NotImplementedError()

class DarwinDynamicLibrary(DynamicLibrary):
    def make_relocatable(self):
        raise NotImplementedError()

class Win32DynamicLibrary(DynamicLibrary):
    def make_relocatable(self):
        raise NotImplementedError()

#===============================================================================
# Build Root
#===============================================================================

#===============================================================================
# Build Root Classes
#===============================================================================
class BuildRoot(SlotObject):
    __slots__ = (
        'prefix',
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

        'old_dlls',
        'all_dlls',
        'all_dlls_by_len',
        'all_symlink_dlls',
        'all_symlink_dlls_by_len',
        'new_dlls',
    )

    _repr_exclude_ = set(__slots__[1:-1])

    def __init__(self, prefix=None, old_files=None, all_files=None):
        if not prefix:
            prefix = build_prefix
        self.prefix = prefix
        self.relative_start_ix = len(prefix)+1

        if not old_files:
            # Ugh, this should be abstracted into a single interface that we
            # can use from both here and post.py/build.py.  Consider that an
            # xxx todo.
            from conda_build import source
            path = join(source.WORK_DIR, 'prefix_files.txt')
            with open(path, 'r') as f:
                old_files = set(l for l in f.read().splitlines() if l)
        self.old_files = old_files

        if not all_files:
            from conda_build.build import prefix_files
            all_files = prefix_files()
        self.all_files = all_files

        self.new_files = self.all_files - self.old_files

        # Nice little cyclic dependency we're introducing here on post.py
        # (which is the thing that should be calling us).
        from conda_build.post import is_obj

        self.old_paths = [ join(prefix, f) for f in self.old_files ]
        self.all_paths = [ join(prefix, f) for f in self.all_files ]
        self.new_paths = [ join(prefix, f) for f in self.new_files ]

        self.old_dll_paths = set(p for p in self.old_paths if is_obj(p))
        self.all_dll_paths = set(
            p for p in self.all_paths
                if p in self.old_dll_paths or is_obj(p)
        )

        self.new_dll_paths = self.all_dll_paths - self.old_dll_paths

        self.all_dlls = defaultdict(list)
        for path in self.all_dll_paths:
            name = basename(path)
            self.all_dlls[name].append(path)

        self.all_symlink_dll_paths = [
            p for p in self.all_paths
                if islink(p) and basename(readlink(p)) in self.all_dlls
        ]

        self.all_symlink_dlls = defaultdict(list)
        for path in self.all_symlink_dll_paths:
            name = basename(path)
            self.all_symlink_dlls[name].append(path)

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

    def __getitem__(self, dll_name):
        targets = self.all_dlls.get(dll_name, self.all_symlink_dlls[dll_name])
        assert len(targets) == 1, (dll_name, targets)
        target = targets[0]
        relative_target = target[self.relative_start_ix:]
        return dirname(relative_target)

    def __contains__(self, dll_name):
        return (
            dll_name in self.all_dlls or
            dll_name in self.all_symlink_dlls
        )


    def run_post(self):
        pass


#===============================================================================
# Sample Outputs
#===============================================================================
sample_ldd_output = """
	linux-vdso.so.1 =>  (0x00007fff3dffd000)
	libgfortran.so.1 => /home/r/miniconda/envs/_build/lib64/R/lib/../../../lib/libgfortran.so.1 (0x00002aec231ae000)
	libRblas.so => not found
	libm.so.6 => /home/r/miniconda/envs/_build/lib64/R/lib/../../../lib/libm.so.6 (0x00002aec2345a000)
	libreadline.so.6 => /home/r/miniconda/envs/_build/lib64/R/lib/../../../lib/libreadline.so.6 (0x00002aec236dd000)
	libncurses.so.5 => /usr/lib64/libncurses.so.5 (0x00002aec2391f000)
	librt.so.1 => /lib64/librt.so.1 (0x00002aec23b7c000)
	libdl.so.2 => /lib64/libdl.so.2 (0x00002aec23d85000)
	libgomp.so.1 => /usr/lib64/libgomp.so.1 (0x00002aec23f8a000)
	libpthread.so.0 => /lib64/libpthread.so.0 (0x00002aec24198000)
	libc.so.6 => /lib64/libc.so.6 (0x00002aec243b4000)
	/lib64/ld-linux-x86-64.so.2 (0x0000003739c00000)"""

#===============================================================================
# Main
#===============================================================================
if __name__ == '__main__':
    import doctest
    doctest.testmod()

# vim:set ts=8 sw=4 sts=4 tw=78 et:
