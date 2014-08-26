#===============================================================================
# Imports
#===============================================================================
from __future__ import (
    print_function,
)

import os
import sys
import shutil
import operator

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

from conda_build.utils import (
    SlotObject,
    is_linux,
    is_darwin,
    is_win32,
)

from conda_build.external import (
    find_executable,
)

from conda_build.config import (
    build_prefix,
)

from conda_build.link import (
    ExternalLinkage,
    RecipeCorrectButBuildScriptBroken,
    BrokenLinkage,
)


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

def package_name_providing_link_target(libname):
    # xxx todo: perhaps dispatch this inquiry to a server-side request that
    # can better answer the question of "are there *any* conda packages that
    # provide this dll to link against?".  For now, just return None.
    return None

#===============================================================================
# Path-related Helpers
#===============================================================================
def get_files(base):
    '''
    Use os.walk to create a set of all files inside a path
    '''
    res = set()
    for root, dirs, files in os.walk(base):
        for fn in files:
            res.add(join(root, fn)[len(base) + 1:])
        for dn in dirs:
            path = join(root, dn)
            if islink(path):
                res.add(path[len(base) + 1:])
    return res

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
    ''' Given a library path, return a list of paths to libraries linked

    Dispatch to the OS approriate shared library tool
    '''

    if is_linux:
        return ldd(dll)
    elif is_darwin:
        return otool.list_shared_libraries(dll)
    else:
        raise NotImplementedError()


#===============================================================================
# Process Wrappers
#===============================================================================
class ProcessWrapper(object):
    ''' Helper class to execute a command in the OS shell

    Executes the specified command and returns stdout
    '''

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
    """ Base class to categorize status of dependencies

    Attributes:
        inside: satisfied dependencies whose path starts with prefix
        outside: satisfied dependencies whose path does not start with prefix
        missing: unsatisfied dependencies (whose path doesn't exist)
    """

    __slots__ = (
        'inside',
        'outside',
        'missing',
    )

    _repr_exclude_ = (
        'inside',
    )

    def __init__(self, deps, prefix=None):
        ''' Init LibraryDependencies with categorization of dependencies

        Dependencies are one of {inside, outside, missing}.

        Args:
            deps: List of tuples, each tuple is (depname, path_to_depname).  If
                path_to_depname is None, the depedency is missing
            prefix: String of path to build prefix.  Paths that start with
                prefix are considered "inside"
        '''

        if not prefix:
            prefix = build_prefix

        inside, outside, missing = self.categorize_dependencies(deps, prefix)
        self.inside = inside
        self.outside = outside
        self.missing = missing

    @staticmethod
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


class DynamicLibrary(with_metaclass(ABCMeta, LibraryDependencies)):
    ''' Representation of a library and its dependencies

    Utilizes LibraryDependencies superclass to categorize dependencies as one of
    {inside, outside, missing}.

    Attributes:
        prefix: prefix to library paths considered to be 'inside'
        build_root: BuildRoot that contains this DynamicLibrary
        link_errors: list of 'LinkError's due to *this* libraries dependencies
        runtime_paths: list of paths to dependencies *inside* build root
        relative_runtime_paths: relative paths to each element of runtime_paths
        relative: relative path to the build dir
        path: absolute path to the build dir
    '''

    __slots__ = LibraryDependencies.__slots__ + (
        'path',
        'prefix',
        'relative',
        'build_root',
        'link_errors',
        'runtime_paths',
        'relative_runtime_paths',
    )

    _repr_exclude_ = (
        'build_root',
        'link_errors',
        'runtime_paths',
        'relative_runtime_paths',
    )

    def __init__(self, path, build_root):
        ''' rely on call to self.reload() to call LibraryDependencies.__init__
        '''

        self.prefix = build_root.prefix
        self.build_root = build_root
        self.link_errors = []
        self.runtime_paths = None
        self.relative_runtime_paths = None
        self.path, self.relative = self.arbitrate_relative(path, self.prefix)
        self.name = basename(self.path)
        self._reload_count = 0
        self.reload()

    @staticmethod
    def arbitrate_relative(path, prefix):
        is_absolute = path.startswith(prefix)
        if is_absolute:
            path = path
            relative = path.replace(prefix, '')[1:]
        else:
            relative = path
            path = '/'.join((prefix, path))
        return path, relative

    def reload(self):
        ''' Reprocess dependencies for link errors and runtime paths

        Based on a freshly read list of dependencies and resulting
        LibraryDependencies' {inside, outside, missing} fields.
        '''

        self.link_errors = []
        self._reload_count += 1
        deps = get_library_dependencies(self.path)
        LibraryDependencies.__init__(self, deps, self.prefix)

        self._process_outside_targets()
        self._process_missing_targets()
        self._resolve_inside_targets()
        self._resolve_relative_runtime_paths()

    def _process_outside_targets(self):
        ''' Update 'link_errors' to account for external linkages
        '''
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
        #
        # Update: initial work has been done to detect whether or not a
        # library is being provided by a conda package.  However, it will be
        # better to keep this logic separate, so, for now, we accumulate link
        # errors and assume someone downstream will handle it if they want to.

        build_root = self.build_root
        link_errors = self.link_errors
        for path in self.outside:
            name = basename(path)
            if self.allowed_outside(name):
                continue
            args = (self, name, path)
            cls = ExternalLinkage
            if name in build_root:
                expected = build_root[name]
                args = args + (expected,)
                cls = RecipeCorrectButBuildScriptBroken
            link_errors.append(cls(*args))

    def _process_missing_targets(self):
        ''' Update 'link_errors' to account for broken linkages
        '''
        for name in self.missing:
            self.link_errors.append(BrokenLinkage(self, name))

    def _resolve_inside_targets(self):
        ''' set 'runtime_paths'

        to unique list of runtime dependencies inside build root
        '''

        build_root = self.build_root
        rpaths = set(map(build_root.__getitem__, self.inside))
        assert all(rpaths)
        self.runtime_paths = rpaths

    def _resolve_relative_runtime_paths(self):
        ''' set 'relative_runtime_paths'
        '''

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
    def allowed_outside(self, path):
        """
        This method is invoked for each library being linked to outside of the
        build prefix (e.g. /usr/lib64/libc.so.6).  Subclasses should implement
        and return True/False depending on whether that is an approved library
        to live outside.
        """
        raise NotImplementedError()

    @abstractmethod
    def make_relocatable(self, copy=False):
        # copy means break the hard link
        raise NotImplementedError()

class LinuxDynamicLibrary(DynamicLibrary):
    external = (
        'libc.so',
        'libdl.so',
        'librt.so',
        'libexpat.so',
        'libncurses.so',
        'libpthread.so',
        'ld-linux-x86-64.so',
    )

    x11 = (
        'libX',
        'libfontconfig',
    )

    def __init__(self, path, build_root, extra_external=None):
        extra_external = build_root.extra_external
        if extra_external:
            assert not isinstance(extra_external, str)
            self.external += tuple(extra_external)
        super(LinuxDynamicLibrary, self).__init__(path, build_root)

    def allowed_outside(self, name):
        if name.startswith(self.x11):
            return bool(self.build_root.allow_x11)
        else:
            return name.startswith(self.external)

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
            # Ok, we've seen some oddities on CentOS 5 where the RPATH just
            # doesn't seem to take.  That is, the patchelf.set_rpath() call
            # above completes just fine, but self.current_rpath (which calls
            # patchelf.read_rpath()) doesn't reflect the new RPATH.  However,
            # it appears the RPATH *is* actually set correctly -- at least, we
            # think it is.  (Which would suggest a kernel race bug in the
            # filesystem/cache/memory-management parts, one would think.)
            #
            # That's a bit wishy-washy.  It'd be nice to conclusively know
            # that the RPATH *does* get set correctly, it just sometimes
            # doesn't get reported immediately as being set correctly.  So,
            # the plan is... let's do a little loop that tries re-checking the
            # RPATH a few more times.  If it's still not set at the end, break
            # into a debugger, which, if nothing else, is a convenient way to
            # pause execution so that we could start a separate shell and call
            # patchelf/readelf manually.  If *they* report the RPATH not being
            # set properly, that's just as interesting/useful as the opposite.

            # Update: with the code below in place, it appears that the theory
            # above is correct: RPATH is being set just fine, there's just a
            # race issue with regards to a subsequent patchelf.read_rpath()
            # invocation returning the old RPATH instead of the new one (or in
            # some cases, just returns an empty RPATH).
            #
            # The uname output from the Linux VM I tested this on:
            #   Linux centos5x64.home.trent.me 2.6.18-371.el5 #1 SMP \
            #   Tue Oct 1 08:35:08 EDT 2013 x86_64 x86_64 x86_64 GNU/Linux
            #
            # I would see this output every 5-6 times I'd run the post logic
            # against a pre-built r:
            #
            # patchelf: file: /home/r/miniconda/envs/_build/lib64/R/modules/lapack.so
            #     old RPATH: /home/r/miniconda/envs/_build/lib
            #     new RPATH: $ORIGIN/../../../lib
            # [attempt: 1]: warning: RPATH didn't take, retrying after 1s...
            #     path: /home/r/miniconda/envs/_build/lib64/R/modules/lapack.so
            #     cur_rpath:
            #     new_rpath: $ORIGIN/../../../lib
            # [attempt: 1]: success: RPATH change detected
            #
            # Every time it happened, it was against a different file, and it
            # only took one attempt for the new RPATH to be run.  Definitely a
            # race issue IMO.
            #
            # Let's leave all this commentary and re-try code in place, as
            # it'll be a useful reference for people down the track that run
            # into this problem.

            def print_rpath_attempt():
                print(
                    "%s: warning: RPATH didn't take, retrying after %ds...\n"
                    "    path: %s\n"
                    "    cur_rpath: %s\n"
                    "    new_rpath: %s" % (
                        prefix,
                        nap,
                        path,
                        cur_rpath,
                        new_rpath,
                    )
                )

            import time
            correct = False
            for (attempt, nap) in enumerate((1, 2, 4, 8), 1):
                prefix = "[attempt: %d]" % attempt
                print_rpath_attempt()
                time.sleep(nap)
                cur_rpath = self.current_rpath
                if cur_rpath == new_rpath:
                    print("%s: success: RPATH change detected" % prefix)
                    correct = True
                    break

            if not correct:
                msg = "Failed to set RPATH.  See what patchelf/readelf says."
                print(msg)
                sys.exit(dedent('''
                    CONDA BUILD: %s
                    EXITING!!!
                    ''' % msg)).strip()

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

        # Update 2: plan is to handle these link errors elsewhere, so, just
        # calling self.reload() is enough for now.  We'll assume downstream
        # can take care of it.
        self.reload()

class DarwinDynamicLibrary(DynamicLibrary):
    def allowed_outside(self, path):
        raise NotImplementedError()

    def make_relocatable(self, copy=False):
        raise NotImplementedError()

class Win32DynamicLibrary(DynamicLibrary):
    def allowed_outside(self, path):
        raise NotImplementedError()

    def make_relocatable(self, copy=False):
        raise NotImplementedError()


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
