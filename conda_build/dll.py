#===============================================================================
# Imports
#===============================================================================
import sys

from abc import (
    ABCMeta,
    abstractmethod,
)

from os.path import (
    join,
    abspath,
    normpath,
    basename,
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
                outside.add(depname)

        self.inside = inside
        self.outside = outside
        self.missing = missing

class DynamicLibrary(LibraryDependencies):
    __metaclass__ = ABCMeta
    __slots__ = LibraryDependencies.__slots__ + (
        'path',
        'prefix',
        'relative',
    )

    def __init__(self, path, prefix=None):
        if not prefix:
            prefix = build_prefix

        self.path = path
        self.prefix = prefix
        self.relative = path.replace(prefix, '')

        deps = get_library_dependencies(path)
        LibraryDependencies.__init__(self, deps, prefix)

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
    def runtime_path_dependencies(self):
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

        'old_files',
        'all_files',
        'new_files',

        'old_paths',
        'all_paths',
        'new_paths',

        'old_dll_paths',
        'all_dll_paths',
        'new_dll_paths',

        'old_dlls',
        'all_dlls',
        'new_dlls',
    )

    _repr_exclude_ = set(__slots__[1:-1])

    def __init__(self, prefix=None, old_files=None, all_files=None):
        if not prefix:
            prefix = build_prefix
        self.prefix = prefix

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

        self.old_paths = (join(prefix, f) for f in self.old_files)
        self.all_paths = (join(prefix, f) for f in self.all_files)
        self.new_paths = (join(prefix, f) for f in self.new_files)

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

        self.new_dlls = [
            DynamicLibrary.create(p, prefix)
                for p in sorted(self.new_dll_paths)
        ]

        # xxx todo: enumerate over each new dll and looking for dodgy 'outside'
        # links that indicate missing deps in the yaml, or 'missing' libs that
        # we need to find equivalents for in all_dlls (and thus set an rpath
        # with multiple paths).


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
