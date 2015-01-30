import os
import sys
import json
import shutil
from os.path import dirname, exists, isdir, join
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


def create_entry_point(path, module, func):
    pyscript = PY_TMPL % (module, func, func)
    if sys.platform == 'win32':
        with open(path + '-script.py', 'w') as fo:
            fo.write(pyscript)
        shutil.copyfile(join(THIS_DIR,
                             'cli-%d.exe' % (8 * tuple.__itemsize__)),
                        path + '.exe')
    else:
        with open(path, 'w') as fo:
            fo.write('#!%s\n' % python)
            fo.write(pyscript)
        os.chmod(path, int('755', 8))


def create_entry_points(items, remove=False):
    if not items:
        return
    bin_dir = join(prefix, 'Scripts' if sys.platform == 'win32' else 'bin')
    if not isdir(bin_dir):
        os.mkdir(bin_dir)
    for cmd, module, func in items:
        path = join(bin_dir, cmd)
        if remove:
            if sys.platform == 'win32':
                _unlink(path + '-script.py')
                _unlink(path + '.exe')
            else:
                _unlink(path)
        else:
            create_entry_point(path, module, func)


def read_data():
    with open(join(THIS_DIR, 'data.json')) as fi:
        return json.load(fi)


def link():
    d = read_data()
    create_entry_points(d['entry_points'])
    link_files(join(THIS_DIR, 'site-packages'),
               join(prefix, get_python_lib()),
               d['site-packages'])


def unlink():
    d = read_data()
    create_entry_points(d['entry_points'], remove=True)


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
