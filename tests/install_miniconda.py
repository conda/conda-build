import sys
import os
import hashlib
import subprocess

import requests

tempdir = os.path.expanduser("~")


def rm_rf(path, max_retries=5):
    """
    Completely delete path

    max_retries is the number of times to retry on failure. The default is
    5. This only applies to deleting a directory.

    """
    import sys
    import logging
    import shutil
    import stat
    import time
    from os.path import islink, isfile, isdir

    on_win = bool(sys.platform == 'win32')
    log = logging.getLogger(__name__)

    if islink(path) or isfile(path):
        # Note that we have to check if the destination is a link because
        # exists('/path/to/dead-link') will return False, although
        # islink('/path/to/dead-link') is True.
        os.unlink(path)

    elif isdir(path):
        for i in range(max_retries):
            try:
                shutil.rmtree(path)
                return
            except OSError as e:
                msg = "Unable to delete %s\n%s\n" % (path, e)
                if on_win:
                    try:
                        def remove_readonly(func, path, excinfo):
                            os.chmod(path, stat.S_IWRITE)
                            func(path)
                        shutil.rmtree(path, onerror=remove_readonly)
                        return
                    except OSError as e1:
                        msg += "Retry with onerror failed (%s)\n" % e1

                    try:
                        subprocess.check_call(['cmd', '/c', 'rd', '/s', '/q', path])
                        return
                    except subprocess.CalledProcessError as e2:
                        msg += '%s\n' % e2
                log.debug(msg + "Retrying after %s seconds..." % i)
                time.sleep(i)
        # Final time. pass exceptions to caller.
        shutil.rmtree(path)

def download_file(url, md5):
    urlparts = requests.packages.urllib3.util.url.parse_url(url)
    local_filename = urlparts.path.split('/')[-1]

    r = requests.get(url, stream=True)
    r.raise_for_status()

    dir_path = os.path.join(tempdir, 'download_cache')
    file_path = os.path.join(dir_path, local_filename)

    print("Downloading %s to %s" % (local_filename, file_path))
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

    if os.path.exists(file_path):
        if hashsum_file(file_path) == md5:
            print("File %s already exists at %s" % (local_filename,
                file_path))
            return file_path
        else:
            print("MD5 mismatch. Downloading again.")

    size = int(r.headers.get('Content-Length'))
    with open(file_path, 'wb') as f:
        for i, chunk in enumerate(r.iter_content(chunk_size=2**20)):
            if chunk: # filter out keep-alive new chunks
                print("writing %s/%s MB" % (r.raw.tell()/2**20, size/2**20))
                f.write(chunk)
                f.flush()
    return file_path


def hashsum_file(path, mode='md5'):
    with open(path, 'rb') as fi:
        h = hashlib.new(mode)
        while True:
            chunk = fi.read(262144)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()

def install_miniconda(path):
    prefix = os.path.join(tempdir, 'conda-build-miniconda')
    print("Installing Miniconda %s to %s" % (path, prefix))

    rm_rf(prefix)
    os.makedirs(prefix)
    conda = os.path.join(prefix, 'Scripts', 'conda.exe')

    for cmd in [
        [path, '/S', '/D=%s' % prefix],
        [conda, 'info', '-a'],
        [conda, 'config', '--get'],
        [conda, 'config', '--set', 'always_yes', 'yes'],
        [conda, 'install', 'pytest', 'requests',
            'conda-build', '--quiet'],
        [conda, 'list'],
    ]:
        print(' '.join(cmd))
        subprocess.check_call(cmd)


def main():
    for url, md5 in [
        ('http://repo.continuum.io/miniconda/Miniconda-3.5.5-Windows-x86_64.exe', 'b6285db92cc042a44b2afaaf1a99b8cc'),
        ]:
        f = download_file(url, md5)
        install_miniconda(f)

if __name__ == '__main__':
    main()
