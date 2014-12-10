import requests
import os
import hashlib
import subprocess

tempdir = os.environ.get('TEMP', '/tmp')

def download_file(url):
    urlparts = requests.packages.urllib3.util.url.parse_url(url)
    # local_filename = urlparts.path.split('/')[-1]
    local_filename = "Miniconda.exe"

    print("Downloading %s" % local_filename)
    r = requests.get(url, stream=True)
    r.raise_for_status()

    dir_path = os.path.join(tempdir, 'download_cache')
    file_path = os.path.join(dir_path, local_filename)
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
    prefix = os.path.join(tempdir, 'miniconda')
    subprocess.call([path, '/S', '/D=%s' % prefix])
    subprocess.call([os.path.join(prefix, 'conda'), 'config', '--set', 'always_yes', 'yes'])
    subprocess.call([os.path.join(prefix, 'conda'), 'install', 'pytest', 'requests',
        'conda-build', '--quiet'])

def main():
    for url, md5 in [
        ('http://repo.continuum.io/miniconda/Miniconda-3.5.5-Windows-x86_64.exe', 'b6285db92cc042a44b2afaaf1a99b8cc'),
        ]:
        f = download_file(url)
        hashsum_file(f)

if __name__ == '__main__':
    main()
