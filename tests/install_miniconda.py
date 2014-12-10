import requests
import os
import hashlib
import subprocess

tempdir = os.environ.get('TEMP', '/tmp')

def download_file(url, md5):
    urlparts = requests.packages.urllib3.util.url.parse_url(url)
    local_filename = urlparts.path.split('/')[-1]

    r = requests.get(url, stream=True)
    r.raise_for_status()

    dir_path = os.path.join(tempdir, 'download_cache')
    file_path = os.path.join(dir_path, local_filename)
    if os.path.exists(file_path):
        if hashsum_file(file_path) == md5:
            print("File %s already exists at %s" % (local_filename,
                file_path))
            return file_path
        else:
            print("MD5 mismatch. Downloading again.")

    print("Downloading %s to %s" % (local_filename, file_path))
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    if os.path.exists(file_path):
        return file_path
    with open(file_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=1024):
            if chunk: # filter out keep-alive new chunks
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
    from conda.install import rm_rf

    prefix = os.path.join(tempdir, 'miniconda')
    print("Installing Miniconda %s to %s" % (path, prefix))

    rm_rf(prefix)
    for cmd in [
    [path, '/S', '/D=%s' % prefix],
    [os.path.join(prefix, 'Scripts', 'conda.exe'), 'config', '--set', 'always_yes', 'yes'],
    [os.path.join(prefix, 'Scripts', 'conda.exe'), 'install', 'pytest', 'requests',
    'conda-build', '--quiet'],
        ]:
        print(' '.join(cmd))
        subprocess.call(cmd)

def main():
    for url, md5 in [
        ('http://repo.continuum.io/miniconda/Miniconda-3.5.5-Windows-x86_64.exe', 'b6285db92cc042a44b2afaaf1a99b8cc'),
        ]:
        f = download_file(url, md5)
        install_miniconda(f)

if __name__ == '__main__':
    main()
