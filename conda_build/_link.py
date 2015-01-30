import os
import sys
import json
import shutil
from os.path import basename, dirname, exists, isdir, join
from distutils.sysconfig import get_python_lib


THIS_DIR = dirname(__file__)

PY_TMPL = """\
if __name__ == '__main__':
    import sys
    from %s import %s

    sys.exit(%s())
"""

prefix = sys.prefix
python = sys.executable


def _link(src, dst):
    try:
        os.link(src, dst)
        # on Windows os.link raises AttributeError
    except (OSError, AttributeError):
        shutil.copy2(src, dst)


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def link_files(src_root, dst_root, files):
    for f in files:
        src = join(src_root, f)
        dst = join(dst_root, f)
        dst_dir = dirname(dst)
        if not isdir(dst_dir):
            os.makedirs(dst_dir)
        if exists(dst):
            _unlink(dst)
        _link(src, dst)


def unlink_files(root, files):
    dst_dirs1 = set()
    for f in files:
        path = join(root, f)
        _unlink(path)
        dst_dirs1.add(dirname(path))

    dst_dirs2 = set()
    for path in dst_dirs1:
        while len(path) > len(prefix):
            dst_dirs2.add(path)
            path = dirname(path)

    for path in sorted(dst_dirs2, key=len, reverse=True):
        try:
            os.rmdir(path)
        except OSError: # directory might not exist or not be empty
            pass


def create_script(path):
    if sys.platform == 'win32':
        shutil.copyfile(join(THIS_DIR, 'bin', basename(path)),
                        path + '-script.py', 'w')
        shutil.copyfile(join(THIS_DIR,
                             'cli-%d.exe' % (8 * tuple.__itemsize__)),
                        path + '.exe')
    else:
        with open(join(THIS_DIR, 'bin', basename(path))) as fi:
            data = fi.read()
        with open(path, 'w') as fo:
            fo.write('#!%s\n' % python)
            fo.write(data)
        os.chmod(path, int('755', 8))


def create_scripts(files, remove=False):
    if not files:
        return
    bin_dir = join(prefix, 'Scripts' if sys.platform == 'win32' else 'bin')
    if not isdir(bin_dir):
        os.mkdir(bin_dir)
    for fn in files:
        path = join(bin_dir, fn)
        if remove:
            if sys.platform == 'win32':
                _unlink(path + '-script.py')
                _unlink(path + '.exe')
            else:
                _unlink(path)
        else:
            create_script(path)


def read_data():
    with open(join(THIS_DIR, 'data.json')) as fi:
        return json.load(fi)


def link():
    d = read_data()

    create_scripts(d['bin'])

    link_files(join(THIS_DIR, 'site-packages'),
               join(prefix, get_python_lib()),
               d['site-packages'])

    link_files(join(THIS_DIR, 'Examples'),
               join(prefix, 'Examples'),
               d['Examples'])


def unlink():
    d = read_data()

    create_scripts(d['bin'], remove=True)

    unlink_files(join(prefix, get_python_lib()),
                 d['site-packages'])

    unlink_files(join(prefix, 'Examples'),
                 d['Examples'])


def main():
    from optparse import OptionParser
    p = OptionParser()
    p.add_option("--unlink", action="store_true")
    p.add_option("--verbose", action="store_true")
    opts, args = p.parse_args()

    if opts.unlink:
        unlink()
    else:
        link()


if __name__ == '__main__':
    main()
