import os
import sys
import shutil
from os.path import dirname, exists, isdir, join, normpath


THIS_DIR = dirname(__file__)
PREFIX = normpath(sys.prefix)
if sys.platform == 'win32':
    BIN_DIR = join(PREFIX, 'Scripts')
    SITE_PACKAGES = 'Lib/site-packages'
else:
    BIN_DIR = join(PREFIX, 'bin')
    SITE_PACKAGES = 'lib/python%s/site-packages' % sys.version[:3]

# the list of these files is going to be store in info/_files
FILES = []


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
        src = join(THIS_DIR, src_root, f)
        dst = join(PREFIX, dst_root, f)
        dst_dir = dirname(dst)
        if not isdir(dst_dir):
            os.makedirs(dst_dir)
        if exists(dst):
            _unlink(dst)
        _link(src, dst)
        FILES.append('%s/%s' % (dst_root, f))


def create_script(fn):
    path = join(BIN_DIR, fn)
    src = join(THIS_DIR, 'python-scripts', fn)
    if sys.platform == 'win32':
        shutil.copyfile(src, path + '-script.py')
        FILES.append('Scripts/%s-script.py' % fn)
        shutil.copyfile(join(THIS_DIR,
                             'cli-%d.exe' % (8 * tuple.__itemsize__)),
                        path + '.exe')
        FILES.append('Scripts/%s.exe' % fn)
    else:
        with open(src) as fi:
            data = fi.read()
        with open(path, 'w') as fo:
            fo.write('#!%s\n' % normpath(sys.executable))
            fo.write(data)
        os.chmod(path, int('755', 8))
        FILES.append('bin/%s' % fn)


def create_scripts(files):
    if not files:
        return
    if not isdir(BIN_DIR):
        os.mkdir(BIN_DIR)
    for fn in files:
        create_script(fn)


def link():
    create_scripts(DATA['python-scripts'])
    link_files('site-packages', SITE_PACKAGES, DATA['site-packages'])
    link_files('Examples', 'Examples', DATA['Examples'])


def main():
    link()
    with open(join(PREFIX, 'conda-meta',
                   '%s.files' % DATA['dist']), 'w') as fo:
        for f in FILES:
            fo.write('%s\n' % f)


if __name__ == '__main__':
    main()
