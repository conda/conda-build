import os
import io
import sys
import json
import shutil
import locale
from os.path import basename, dirname, isdir, join

from conda_build.config import config
from conda_build.post import SHEBANG_PAT


def _force_dir(dirname):
    if not isdir(dirname):
        os.makedirs(dirname)


def _error_exit(exit_message):
    sys.exit("[noarch_python] %s" % exit_message)


def rewrite_script(fn):
    """Take a file from the bin directory and rewrite it into the python-scripts
    directory after it passes some sanity checks for noarch pacakges"""

    # Load and check the source file for not being a binary
    src = join(config.build_prefix, 'bin', fn)
    with io.open(src, encoding=locale.getpreferredencoding()) as fi:
        try:
            data = fi.read()
        except UnicodeDecodeError:  # file is binary
            _error_exit("Noarch package contains binary script: %s" % fn)
    os.unlink(src)

    # Check that it does have a #! python string
    m = SHEBANG_PAT.match(data)
    if not (m and 'python' in m.group()):
        _error_exit("No python shebang in: %s" % fn)

    # Rewrite the file to the python-scripts directory after skipping the #! line
    new_data = data[data.find('\n') + 1:]
    dst_dir = join(config.build_prefix, 'python-scripts')
    _force_dir(dst_dir)
    with open(join(dst_dir, fn), 'w') as fo:
        fo.write(new_data)


def handle_file(f, d):
    """Process a file for inclusion in a noarch python package.
    """
    path = join(config.build_prefix, f)

    # Ignore egg-info and pyc files.
    if f.endswith(('.egg-info', '.pyc')):
        os.unlink(path)

    # The presence of .so indicated this is not a noarch package
    elif f.endswith('.so'):
        _error_exit("Error: Shared object file found: %s" % f)

    elif 'site-packages' in f:
        nsp = join(config.build_prefix, 'site-packages')
        _force_dir(nsp)

        g = f[f.find('site-packages'):]
        dst = join(config.build_prefix, g)
        dst_dir = dirname(dst)
        _force_dir(dst_dir)
        os.rename(path, dst)
        d['site-packages'].append(g[14:])

    # Treat scripts specially with the logic from above
    elif f.startswith('bin/'):
        fn = basename(path)
        rewrite_script(fn)
        d['python-scripts'].append(fn)

    # Include examples in the metadata doc
    elif f.startswith('Examples/'):
        d['Examples'].append(f[9:])

    else:
        _error_exit("Error: Don't know how to handle file: %s" % f)


def transform(m, files):
    assert 'py_' in m.dist()
    if sys.platform == 'win32':
        _error_exit("Error: Python noarch packages can't currently "
                    "be created on Windows systems.")

    prefix = config.build_prefix
    name = m.name()

    # Create *nix prelink script
    with open(join(prefix, 'bin/.%s-pre-link.sh' % name), 'w') as fo:
        fo.write('''\
#!/bin/bash
$PREFIX/bin/python $SOURCE_DIR/link.py
''')

    scripts_dir = join(prefix, 'Scripts')
    _force_dir(scripts_dir)

    # Create windows prelink script
    with open(join(scripts_dir, '.%s-pre-link.bat' % name), 'w') as fo:
        fo.write('''\
@echo off
"%PREFIX%\\python.exe" "%SOURCE_DIR%\\link.py"
''')

    d = {'dist': m.dist(),
         'site-packages': [],
         'python-scripts': [],
         'Examples': []}

    # Populate site-package, python-scripts, and Examples into above
    for f in files:
        handle_file(f, d)

    # Find our way to this directory
    this_dir = dirname(__file__)

    # copy in windows exe shims if there are any python-scripts
    if d['python-scripts']:
        for fn in 'cli-32.exe', 'cli-64.exe':
            shutil.copyfile(join(this_dir, fn), join(prefix, fn))

    # Read the local _link.py
    with open(join(this_dir, '_link.py')) as fi:
        link_code = fi.read()

    # Write the package metadata, and bumper with code for linking
    with open(join(prefix, 'link.py'), 'w') as fo:
        fo.write('DATA = ')
        json.dump(d, fo, indent=2, sort_keys=True)
        fo.write('\n## END DATA\n\n')
        fo.write(link_code)
