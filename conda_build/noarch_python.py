import os
import io
import sys
import json
import shutil
import locale
from os.path import basename, dirname, isdir, join, isfile

from conda_build.post import SHEBANG_PAT

ISWIN = sys.platform.startswith('win')


def _force_dir(dirname):
    if not isdir(dirname):
        os.makedirs(dirname)


def _error_exit(exit_message):
    sys.exit("[noarch_python] %s" % exit_message)


def rewrite_script(fn, prefix):
    """Take a file from the bin directory and rewrite it into the python-scripts
    directory after it passes some sanity checks for noarch pacakges"""

    # Load and check the source file for not being a binary
    src = join(prefix, 'Scripts' if ISWIN else 'bin', fn)
    with io.open(src, encoding=locale.getpreferredencoding()) as fi:
        try:
            data = fi.read()
        except UnicodeDecodeError:  # file is binary
            _error_exit("Noarch package contains binary script: %s" % fn)
    os.unlink(src)

    # Get rid of '-script.py' suffix on Windows
    if ISWIN and fn.endswith('-script.py'):
        fn = fn[:-10]

    # Check that it does have a #! python string, and skip it
    encoding = sys.stdout.encoding or 'utf8'

    m = SHEBANG_PAT.match(data.encode(encoding))
    if m and b'python' in m.group():
        new_data = data[data.find('\n') + 1:]
    elif ISWIN:
        new_data = data
    else:
        _error_exit("No python shebang in: %s" % fn)

    # Rewrite the file to the python-scripts directory
    dst_dir = join(prefix, 'python-scripts')
    _force_dir(dst_dir)
    with open(join(dst_dir, fn), 'w') as fo:
        fo.write(new_data)
    return fn


def handle_file(f, d, prefix):
    """Process a file for inclusion in a noarch python package.
    """
    path = join(prefix, f)

    # Ignore egg-info and pyc files.
    if f.endswith(('.egg-info', '.pyc', '.pyo')):
        os.unlink(path)

    # The presence of .so indicated this is not a noarch package
    elif f.endswith(('.so', '.dll', '.pyd', '.exe', '.dylib')):
        if f.endswith('.exe') and (isfile(f[:-4] + '-script.py') or
                                   basename(f[:-4]) in d['python-scripts']):
            os.unlink(path)  # this is an entry point with a matching xx-script.py
            return
        _error_exit("Error: Binary library or executable found: %s" % f)

    elif 'site-packages' in f:
        nsp = join(prefix, 'site-packages')
        _force_dir(nsp)

        g = f[f.find('site-packages'):]
        dst = join(prefix, g)
        dst_dir = dirname(dst)
        _force_dir(dst_dir)
        os.rename(path, dst)
        d['site-packages'].append(g[14:])

    # Treat scripts specially with the logic from above
    elif f.startswith(('bin/', 'Scripts')):
        fn = basename(path)
        fn = rewrite_script(fn, prefix)
        d['python-scripts'].append(fn)

    # Include examples in the metadata doc
    elif f.startswith(('Examples/', 'Examples\\')):
        d['Examples'].append(f[9:])
    else:
        _error_exit("Error: Don't know how to handle file: %s" % f)


def populate_files(m, files, prefix):
    d = {'dist': m.dist(),
         'site-packages': [],
         'python-scripts': [],
         'Examples': []}

    # Populate site-package, python-scripts, and Examples into above
    for f in files:
        handle_file(f, d, prefix)

    # Windows path conversion
    if ISWIN:
        for fns in (d['site-packages'], d['Examples']):
            for i, fn in enumerate(fns):
                fns[i] = fn.replace('\\', '/')

    # copy in windows exe shims if there are any python-scripts
    if d['python-scripts']:
        for fn in 'cli-32.exe', 'cli-64.exe':
            shutil.copyfile(join(dirname(__file__), fn), join(prefix, fn))

    return d


def transform(m, files, prefix):
    assert 'py_' in m.dist()

    bin_dir = join(prefix, 'bin')
    _force_dir(bin_dir)

    scripts_dir = join(prefix, 'Scripts')
    _force_dir(scripts_dir)

    name = m.name()

    # Create *nix prelink script
    # Note: it's important to use LF newlines or it wont work if we build on Win
    with open(join(bin_dir, '.%s-pre-link.sh' % name), 'wb') as fo:
        fo.write('''\
    #!/bin/bash
    $PREFIX/bin/python $SOURCE_DIR/link.py
    '''.encode('utf-8'))

    # Create windows prelink script (be nice and use Windows newlines)
    with open(join(scripts_dir, '.%s-pre-link.bat' % name), 'wb') as fo:
        fo.write('''\
    @echo off
    "%PREFIX%\\python.exe" "%SOURCE_DIR%\\link.py"
    '''.replace('\n', '\r\n').encode('utf-8'))

    d = populate_files(m, files, prefix)

    # Find our way to this directory
    this_dir = dirname(__file__)

    # Read the local _link.py
    with open(join(this_dir, '_link.py')) as fi:
        link_code = fi.read()

    # Write the package metadata, and bumper with code for linking
    with open(join(prefix, 'link.py'), 'w') as fo:
        fo.write('DATA = ')
        json.dump(d, fo, indent=2, sort_keys=True)
        fo.write('\n## END DATA\n\n')
        fo.write(link_code)
