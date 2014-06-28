#===============================================================================
# Imports
#===============================================================================
from __future__ import (
    print_function,
)

import os
import sys
import shutil

from conda.compat import StringIO, with_metaclass

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
    PIPE,
    Popen,
)

from collections import (
    defaultdict,
)

from conda_build.external import (
    find_executable,
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

assert sum((is_linux, is_darwin, is_win32)) == 1

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
    if not all(i.isdigit() for i in ints):
        return None

    return [ '.'.join(ints[:x]) for x in reversed(range(1, len(ints)+1)) ]

def invert_defaultdict_by_value_len(d):
    i = defaultdict(list)
    for (k, v) in d.items():
        i[len(v)].append(k)
    return i

def package_name_providing_link_target(libname):
    # xxx todo: perhaps dispatch this inquiry to a server-side request that
    # can better answer the question of "are there *any* conda packages that
    # provide this dll to link against?".  For now, just return None.
    return None

#===============================================================================
# Path-related Helpers
#===============================================================================
def get_files(base):
    res = set()
    for root, dirs, files in os.walk(base):
        for fn in files:
            res.add(join(root, fn)[len(base) + 1:])
        for dn in dirs:
            path = join(root, dn)
            if islink(path):
                res.add(path[len(base) + 1:])
    return res

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

    p = path
    while '//' in p:
        p = p.replace('//', '/')

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
    seen = {}
    results = []
    lines = output.splitlines()
    pairs = [ line[1:].split(' => ') for line in lines ]
    for pair in pairs:
        if len(pair) == 1:
            # This will typically be the last /lib64/ld-linux-x86-64.so.2
            # entry (for example).
            continue
        (depname, target) = pair
        if depname in seen:
            # Seen in the wild: dependencies cropping up more than once.
            # Make sure they have consistent target values at the very least.
            last_target = seen[depname]
            assert target == last_target, (target, last_target)
        else:
            seen[depname] = target

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

def parse_otool_shared_libraries_output(output):
    """
    >>> from pprint import pprint
    >>> pprint(parse_otool_shared_libraries_output(sample_otool_output))
    [('libgfortran.2.dylib', '/usr/local/lib/libgfortran.2.dylib'),
     ('libSystem.B.dylib', '/usr/lib/libSystem.B.dylib')]
    """
    return [
        (basename(path), path)
            for path in (
                line[1:].split(' ')[0]
                    for line in output.splitlines()[1:]
            )
    ]

def parse_otool_install_name_output(output):
    """
    >>> from pprint import pprint
    >>> parse = parse_otool_install_name_output
    >>> output = sample_otool_install_name_output
    >>> pprint(parse(output))
    'libtcl8.5.dylib'
    """
    return output.splitlines()[1:][0]

def relative_path(library_path, target_dir):
    """
    >>> p = 'lib/python2.7/site-packages/rpy2/rinterface/_rinterface.so'
    >>> relative_path(p, 'lib')
    '../../../..'
    >>> relative_path(p, 'lib64/R/lib')
    '../../../../../lib64/R/lib'
    >>> relative_path(p, 'lib/python2.7/site-packages/rpy2/rinterface')
    '.'
    >>> relative_path('lib64/R/bin/exec/R', 'lib64/R/lib')
    '../../lib'
    >>> relative_path('lib64/R/lib/libRblas.so', 'lib64/R/lib')
    '.'
    """
    if dirname(library_path) == target_dir:
        return '.'

    paths = [ format_file(library_path), format_dir(target_dir) ]
    root = get_root_path(paths)

    #print("%s: %s: %s" % (library_path, target_dir, root))
    slashes = library_path.count('/')
    if root != '/':
        slashes -= 1
        suffix = target_dir.replace(root[1:-1], '')
        if suffix:
            slashes -= 1
    else:
        suffix = '/' + target_dir

    return normpath(slashes * '../') + suffix

def get_library_dependencies(dll):
    if is_linux:
        return ldd(dll)
    elif is_darwin:
        return otool.list_shared_libraries(dll)
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

        for (key, value) in kwds.items():
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
# Process Wrappers
#===============================================================================
class ProcessWrapper(object):
    def __init__(self, exe, *args, **kwds):
        self.exe      = exe
        self.rc       = int()
        self.cwd      = None
        self.wait     = True
        self.error    = str()
        self.output   = str()
        self.ostream  = kwds.get('ostream', sys.stdout)
        self.estream  = kwds.get('estream', sys.stderr)
        self.verbose  = kwds.get('verbose', False)
        self.safe_cmd = None
        self.exception_class = RuntimeError
        self.raise_exception_on_error = True

    def __getattr__(self, attr):
        if not attr.startswith('_') and not attr == 'trait_names':
            return lambda *args, **kwds: self.execute(attr, *args, **kwds)
        else:
            raise AttributeError(attr)

    def __call__(self, *args, **kwds):
        return self.execute(*args, **kwds)

    def build_command_line(self, exe, action, *args, **kwds):
        cmd  = [ exe, action ]
        for (k, v) in kwds.items():
            cmd.append(
                '-%s%s' % (
                    '-' if len(k) > 1 else '', k.replace('_', '-')
                )
            )
            if not isinstance(v, bool):
                cmd.append(v)
        cmd += list(args)
        return cmd

    def kill(self):
        self.p.kill()

    def execute(self, *args, **kwds):
        self.rc = 0
        self.error = ''
        self.output = ''

        self.cmd = self.build_command_line(self.exe, *args, **kwds)

        if self.verbose:
            cwd = self.cwd or os.getcwd()
            cmd = ' '.join(self.safe_cmd or self.cmd)
            self.ostream.write('%s>%s\n' % (cwd, cmd))

        self.p = Popen(self.cmd, executable=self.exe, cwd=self.cwd,
                       stdin=PIPE, stdout=PIPE, stderr=PIPE)
        if not self.wait:
            return

        self.outbuf = StringIO()
        self.errbuf = StringIO()

        while self.p.poll() is None:
            out = self.p.stdout.read().decode('utf-8')
            self.outbuf.write(out)
            if self.verbose and out:
                self.ostream.write(out)

            err = self.p.stderr.read().decode('utf-8')
            self.errbuf.write(err)
            if self.verbose and err:
                self.estream.write(err)

        self.rc = self.p.returncode
        self.error = self.errbuf.getvalue()
        self.output = self.outbuf.getvalue()
        if self.rc != 0 and self.raise_exception_on_error:
            if self.error:
                error = self.error
            elif self.output:
                error = 'no error info available, output:\n' + self.output
            else:
                error = 'no error info available'
            printable_cmd = ' '.join(self.safe_cmd or self.cmd)
            raise self.exception_class(printable_cmd, error)
        if self.output and self.output.endswith('\n'):
            self.output = self.output[:-1]

        return self.process_output(self.output)

    def process_output(self, output):
        return output

    def clone(self):
        return self.__class__(self.exe)

_build_cmd = ProcessWrapper.build_command_line

if is_linux:
    class _patchelf(ProcessWrapper):
        def build_command_line(self, exe, action, *args, **kwds):
            if action == 'set_rpath':
                action = '--force-rpath'
                args = list(args)
                args.insert(0, '--set-rpath')
            else:
                action = '--%s' % action.replace('_', '-')
            return _build_cmd(self, exe, action, *args, **kwds)

    patchelf = _patchelf(find_executable('patchelf'))

    class _ldd(ProcessWrapper):
        def process_output(self, output):
            return parse_ldd_output(output)

    ldd = _ldd(find_executable('ldd'))

elif is_darwin:
    class _install_name_tool(ProcessWrapper):
        def build_command_line(self, exe, action, *args, **kwds):
            action = '-%s' % action
            return _build_cmd(self, exe, action, *args, **kwds)

    install_name_tool = (
        _install_name_tool(find_executable('install_name_tool'))
    )

    class _otool(ProcessWrapper):
        action = None
        def build_command_line(self, exe, action, *args, **kwds):
            self.action = action
            if action == 'list_shared_libraries':
                action = '-L'
            elif action == 'list_load_commands':
                action = '-l'
            elif action == 'install_name':
                action = '-D'
            else:
                raise RuntimeError("unknown action: %s" % action)

            return _build_cmd(self, exe, action, *args, **kwds)

        def process_output(self, output):
            if self.action == 'list_shared_libraries':
                parser = parse_otool_shared_libraries_output
            elif self.action == 'install_name':
                parser = parse_otool_install_name_output
            elif self.action == 'list_load_commands':
                raise NotImplementedError()
            return parser(output)

    otool = _otool(find_executable('otool'))

elif is_win32:
    pass

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

class RelocationErrors(Exception):
    def __init__(self, errors):
        assert errors
        self.errors = errors
        self.message = 'Relocation errors:\n%s\n' % (
            '\n'.join(repr(e) for e in errors)
        )

class LinkError(Exception):
    pass

class RecipeCorrectButBuildScriptBroken(SlotObject, LinkError):
    __slots__ = (
        'dependent_library_name',
        'expected_link_target',
        'actual_link_target',
    )
    def __init__(self, *args):
        SlotObject.__init__(self, *args)
        self.message = repr(self)

class MissingPackageDependencyInRecipe(SlotObject, LinkError):
    __slots__ = (
        'dependent_library_name',
        'missing_package_dependency',
    )
    def __init__(self, *args):
        SlotObject.__init__(self, *args)
        self.message = repr(self)

class DynamicLibrary(with_metaclass(ABCMeta, LibraryDependencies)):
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

        self._reload_count = 0
        self.reload()

    def reload(self):
        self._reload_count += 1
        deps = get_library_dependencies(self.path)
        LibraryDependencies.__init__(self, deps, self.prefix)

        try:
            self._check_outside_targets()
        except RelocationErrors as e:
            if self._reload_count > 1:
                print("*** warning ***\n%s" % e.message)

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

        errors = []
        build_root = self.build_root
        for path in self.outside:
            name = basename(path)
            if name in build_root:
                cls = RecipeCorrectButBuildScriptBroken
                expected = build_root[name]
                actual = path
                errors.append(cls(name, expected, actual))
            else:
                package = package_name_providing_link_target(name)
                if not package:
                    continue
                cls = MissingPackageDependencyInRecipe
                errors.append(cls(name, package))

        if errors:
            raise RelocationErrors(errors)

    def _resolve_inside_and_missing_targets(self):

        rpaths = set()
        build_root = self.build_root
        forgiving = build_root.forgiving
        for attr in ('inside', 'missing'):
            libs = getattr(self, attr)
            for name in libs:
                p = build_root[name]
                if not p:
                    assert forgiving, p
                else:
                    rpaths.add(p)
                continue

        self.runtime_paths = rpaths

    def _resolve_relative_runtime_paths(self):
        #assert self.runtime_paths, repr(self)
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
    def make_relocatable(self, copy=False):
        # copy means break the hard link
        raise NotImplementedError()

class LinuxDynamicLibrary(DynamicLibrary):

    def ldd(self):
        return ldd(self.path)

    @property
    def current_rpath(self):
        return patchelf.print_rpath(self.path)

    @property
    def relocatable_rpath(self):
        return ':'.join('$ORIGIN/%s' % p for p in self.relative_runtime_paths)

    def make_relocatable(self, copy=False):
        (path, cur_rpath, new_rpath) = args = (
            self.path,
            self.current_rpath,
            self.relocatable_rpath,
        )

        if cur_rpath == new_rpath:
            if self.missing:
                args = [path, cur_rpath, self.missing]
                if not self.build_root.forgiving:
                    assert not self.missing, args
                else:
                    print("error: self.missing: %r" % args)
            return

        msg = 'patchelf: file: %s\n    old RPATH: %s\n    new RPATH: %s'
        print(msg % args)

        if copy:
            # Break the hard link
            shutil.copy2(path, path + '-copy')
            os.unlink(path)
            shutil.move(path + '-copy', path.rsplit('-copy', 1)[0])

        patchelf.set_rpath(new_rpath, path)

        # Check that RPATH was set properly.
        cur_rpath = self.current_rpath
        if cur_rpath != new_rpath:
            print("warning: RPATH didn't take!?\n%r" % [
                path,
                cur_rpath,
                new_rpath,
            ])
            if not self.build_root.forgiving:
                assert cur_rpath == new_rpath, (path, cur_rpath, new_rpath)

        # ....and that there are no missing libs.  If this fails after
        # correcting our RPATH, it means that the target lib that was
        # resolved via the new RPATH has got an incorrectly set RPATH.
        # This happened with rpy2; once the new RPATH logic was in
        # place, libR.so was getting resolved -- however, a subsequent
        # ldd against _rinterface.so was showing libRblas.so as missing.
        # The culprit was libR.so having an RPATH set to $ORIGIN/../../../lib
        # instead of what it should have been: $ORIGIN/../../../lib:$ORIGIN/.
        # The fix: rebuild R from scratch with this new dll logic in place to
        # ensure everything gets created with the right RPATHs.

        # Update: ok so it turns out all the R deps like libgfortran etc in
        # the system package don't have the correct RPATH set so this logic is
        # (correctly) flagging libs like /usr/lib64/libm.so.6.  Just print a
        # warning for now.
        try:
            self.reload()
        except RelocationErrors as e:
            print("*** warning ***\n    %s" % e.message)

        if self.missing:
            if not self.build_root.forgiving:
                assert not self.missing, (path, self.missing)
            else:
                print("still missing: %r" % self.missing)

class DarwinDynamicLibrary(DynamicLibrary):
    def make_relocatable(self, copy=False):
        raise NotImplementedError()

class Win32DynamicLibrary(DynamicLibrary):
    def make_relocatable(self, copy=False):
        raise NotImplementedError()

#===============================================================================
# Build Root Classes
#===============================================================================
class BuildRoot(SlotObject):
    __slots__ = (
        'prefix',
        'forgiving',
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

        'old_non_dll_paths',
        'new_non_dll_paths',
        'all_non_dll_paths',

        'old_dlls',
        'all_dlls',
        'all_dlls_by_len',
        'all_symlink_dlls',
        'all_symlink_dlls_by_len',
        'new_dlls',
    )

    _repr_exclude_ = set(__slots__[1:-1])

    def __init__(self, prefix=None, old_files=None, all_files=None,
                       forgiving=False, is_build=True, prefix_paths=True):
        self.forgiving = forgiving
        if not prefix:
            prefix = build_prefix
        self.prefix = prefix
        self.relative_start_ix = len(prefix)+1

        if prefix_paths:
            join_prefix = lambda f: join(prefix, f)
        else:
            join_prefix = lambda f: f

        if not old_files and is_build:
            # Ugh, this should be abstracted into a single interface that we
            # can use from both here and post.py/build.py.  Consider that an
            # xxx todo.
            from conda_build import source
            path = join(source.WORK_DIR, 'prefix_files.txt')
            with open(path, 'r') as f:
                old_files = set(l for l in f.read().splitlines() if l)
        self.old_files = old_files

        if not all_files:
            all_files = get_files(self.prefix)

        self.all_files = all_files
        self.all_paths = [ join_prefix(f) for f in self.all_files ]

        # Nice little cyclic dependency we're introducing here on post.py
        # (which is the thing that should be calling us).
        from conda_build.post import is_obj

        if is_build:
            self.new_files = self.all_files - self.old_files
        else:
            self.new_files = self.all_files
            self.new_paths = self.all_paths


        if is_build:
            self.old_paths = [ join_prefix(f) for f in self.old_files ]
            self.old_dll_paths = set(p for p in self.old_paths if is_obj(p))
            self.new_paths = [ join_prefix(f) for f in self.new_files ]
            self.all_dll_paths = set(
                p for p in self.all_paths
                    if p in self.old_dll_paths or is_obj(p)
            )
            self.new_dll_paths = self.all_dll_paths - self.old_dll_paths

            self.old_non_dll_paths = set(self.old_paths) - self.old_dll_paths
            self.new_non_dll_paths = set(self.new_paths) - self.new_dll_paths
            self.all_non_dll_paths = set(self.all_paths) - self.all_dll_paths
        else:
            self.old_paths = []
            self.old_dll_paths = set()
            self.all_dll_paths = set(p for p in self.all_paths if is_obj(p))
            self.new_dll_paths = self.all_dll_paths

            self.old_non_dll_paths = set()
            self.all_non_dll_paths = set(self.all_paths) - self.all_dll_paths
            self.new_non_dll_paths = self.all_non_dll_paths


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

        if is_build:
            self.old_dlls = [
                DynamicLibrary.create(p, build_root=self)
                    for p in sorted(self.old_dll_paths)
            ]

    def __getitem__(self, dll_name):
        targets = self.all_dlls.get(dll_name, self.all_symlink_dlls[dll_name])
        if len(targets) != 1:
            if not self.forgiving:
                assert len(targets) == 1, (dll_name, targets)
            else:
                #print("error: unresolved: %s" % dll_name)
                return

        target = targets[0]
        relative_target = target[self.relative_start_ix:]
        return dirname(relative_target)

    def __contains__(self, dll_name):
        return (
            dll_name in self.all_dlls or
            dll_name in self.all_symlink_dlls
        )

    def broken_libs(self, dlls=None):
        if not dlls:
            dlls = self.new_dlls

        missing = []
        for dll in dlls:
            dll.reload()
            for lib in dll.missing:
                missing.append((dll.relative, lib))

        return missing

    def verify(self, dlls=None):
        if not dlls:
            dlls = self.new_dlls
        print('Verifying libs are relocatable...')
        missing = self.broken_libs()
        for m in missing:
            (relative_path, lib) = m
            print('warning: broken lib: %s: dependency %s not found' % m)

    def make_relocatable(self, dlls=None, copy=False):
        if not dlls:
            dlls = self.new_dlls

        for dll in dlls:
            dll.make_relocatable(copy=copy)

    def post_build(self):
        self.make_relocatable()


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

sample_otool_output = """\
libgfortran.2.dylib:
	/usr/local/lib/libgfortran.2.dylib (compatibility version 3.0.0, current version 3.0.0)
	/usr/lib/libSystem.B.dylib (compatibility version 1.0.0, current version 88.3.9)"""

sample_otool_install_name_output = """\
/var/folders/7t/jhrygn4x5fz8hmf974g129w00000gn/T/tmpkKMou3/lib/libtcl8.5.dylib:
libtcl8.5.dylib"""

#===============================================================================
# Main
#===============================================================================
if __name__ == '__main__':
    import doctest
    doctest.testmod()

# vim:set ts=8 sw=4 sts=4 tw=78 et:
