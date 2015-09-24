from __future__ import absolute_import, division, print_function

import os
import sys
from os.path import join, isdir, isfile, abspath, expanduser
from shutil import copytree, copy2
from subprocess import check_call, Popen, PIPE
import locale

from conda.fetch import download
from conda.utils import hashsum_file

from conda_build import external
from conda_build.config import config
from conda_build.utils import rm_rf, tar_xf, unzip


SRC_CACHE = join(config.croot, 'src_cache')
GIT_CACHE = join(config.croot, 'git_cache')
HG_CACHE = join(config.croot, 'hg_cache')
SVN_CACHE = join(config.croot, 'svn_cache')
WORK_DIR = join(config.croot, 'work')


def get_dir():
    if not isdir(WORK_DIR):
        os.makedirs(WORK_DIR)
    lst = [fn for fn in os.listdir(WORK_DIR) if not fn.startswith('.')]
    if len(lst) == 1:
        dir_path = join(WORK_DIR, lst[0])
        if isdir(dir_path):
            return dir_path
    return WORK_DIR


def download_to_cache(meta):
    ''' Download a source to the local cache. '''
    print('Source cache directory is: %s' % SRC_CACHE)
    if not isdir(SRC_CACHE):
        os.makedirs(SRC_CACHE)

    fn = meta['fn']
    path = join(SRC_CACHE, fn)

    if isfile(path):
        print('Found source in cache: %s' % fn)
    else:
        print('Downloading source to cache: %s' % fn)
        if not isinstance(meta['url'], list):
            meta['url'] = [meta['url']]

        for url in meta['url']:
            try:
                print("Downloading %s" % url)
                download(url, path)
            except RuntimeError as e:
                print("Error: %s" % str(e).strip(), file=sys.stderr)
            else:
                print("Success")
                break
        else: # no break
            raise RuntimeError("Could not download %s" % fn)

    for tp in 'md5', 'sha1', 'sha256':
        if meta.get(tp) and hashsum_file(path, tp) != meta[tp]:
            raise RuntimeError("%s mismatch: '%s' != '%s'" %
                               (tp.upper(), hashsum_file(path, tp), meta[tp]))

    return path


def unpack(meta):
    ''' Uncompress a downloaded source. '''
    src_path = download_to_cache(meta)

    os.makedirs(WORK_DIR)
    print("Extracting download")
    if src_path.lower().endswith(('.tar.gz', '.tar.bz2', '.tgz', '.tar.xz',
        '.tar', 'tar.z')):
        tar_xf(src_path, WORK_DIR)
    elif src_path.lower().endswith('.zip'):
        unzip(src_path, WORK_DIR)
    else:
        # In this case, the build script will need to deal with unpacking the source
        print("Warning: Unrecognized source format. Source file will be copied to the SRC_DIR")
        copy2(src_path, WORK_DIR)


def git_source(meta, recipe_dir):
    ''' Download a source from Git repo. '''
    if not isdir(GIT_CACHE):
        os.makedirs(GIT_CACHE)

    git = external.find_executable('git')
    if not git:
        sys.exit("Error: git is not installed")
    git_url = meta['git_url']
    git_depth = int(meta.get_value('build/git_depth', -1))
    if git_url.startswith('.'):
        # It's a relative path from the conda recipe
        os.chdir(recipe_dir)
        git_dn = abspath(expanduser(git_url))
        git_dn = "_".join(git_dn.split(os.path.sep)[1:])
    else:
        git_dn = git_url.split(':')[-1].replace('/', '_')
    cache_repo = cache_repo_arg = join(GIT_CACHE, git_dn)
    if sys.platform == 'win32':
        is_cygwin = 'cygwin' in git.lower()
        cache_repo_arg = cache_repo_arg.replace('\\', '/')
        if is_cygwin:
            cache_repo_arg = '/cygdrive/c/' + cache_repo_arg[3:]

    # update (or create) the cache repo
    if isdir(cache_repo):
        check_call([git, 'fetch'], cwd=cache_repo)
    else:
        args = [git, 'clone', '--mirror']
        if git_depth > 0:
            args += ['--depth', git_depth]

        check_call(args + [git_url, cache_repo_arg],  cwd=recipe_dir)
        assert isdir(cache_repo)

    # now clone into the work directory
    checkout = meta.get('git_rev')
    # if rev is not specified, and the git_url is local,
    # assume the user wants the current HEAD
    if not checkout and git_url.startswith('.'):
        process = Popen(["git", "rev-parse", "HEAD"],
                    stdout=PIPE, stderr=PIPE,
                               cwd=git_url)
        output = process.communicate()[0].strip()
        checkout = output.decode('utf-8')
    if checkout:
        print('checkout: %r' % checkout)

    check_call([git, 'clone', '--recursive', cache_repo_arg, WORK_DIR])
    if checkout:
        check_call([git, 'checkout', checkout], cwd=WORK_DIR)

    git_info()
    return WORK_DIR


def git_info(fo=None):
    ''' Print info about a Git repo. '''
    assert isdir(WORK_DIR)

    # Ensure to explicitly set GIT_DIR as some Linux machines will not
    # properly execute without it.
    env = os.environ.copy()
    env['GIT_DIR'] = join(WORK_DIR, '.git')
    env = {str(key): str(value) for key, value in env.items()}
    for cmd, check_error in [
                ('git log -n1', True),
                ('git describe --tags --dirty', False),
                ('git status', True)]:
        p = Popen(cmd.split(), stdout=PIPE, stderr=PIPE, cwd=WORK_DIR, env=env)
        stdout, stderr = p.communicate()
        encoding = locale.getpreferredencoding() or 'utf-8'
        stdout = stdout.decode(encoding, 'ignore')
        stderr = stderr.decode(encoding, 'ignore')
        if check_error and stderr and stderr.strip():
            raise Exception("git error: %s" % stderr)
        if fo:
            fo.write(u'==> %s <==\n' % cmd)
            fo.write(stdout + u'\n')
        else:
            print(u'==> %s <==\n' % cmd)
            print(stdout + u'\n')


def hg_source(meta):
    ''' Download a source from Mercurial repo. '''
    hg = external.find_executable('hg')
    if not hg:
        sys.exit('Error: hg not installed')
    hg_url = meta['hg_url']
    if not isdir(HG_CACHE):
        os.makedirs(HG_CACHE)
    hg_dn = hg_url.split(':')[-1].replace('/', '_')
    cache_repo = join(HG_CACHE, hg_dn)
    if isdir(cache_repo):
        check_call([hg, 'pull'], cwd=cache_repo)
    else:
        check_call([hg, 'clone', hg_url, cache_repo])
        assert isdir(cache_repo)

    # now clone in to work directory
    update = meta.get('hg_tag') or 'tip'
    print('checkout: %r' % update)

    check_call([hg, 'clone', cache_repo, WORK_DIR])
    check_call([hg, 'update', '-C', update], cwd=WORK_DIR)
    return WORK_DIR



def svn_source(meta):
    ''' Download a source from SVN repo. '''
    def parse_bool(s):
        return str(s).lower().strip() in ('yes', 'true', '1', 'on')

    svn = external.find_executable('svn')
    if not svn:
        sys.exit("Error: svn is not installed")
    svn_url = meta['svn_url']
    svn_revision = meta.get('svn_rev') or 'head'
    svn_ignore_externals = parse_bool(meta.get('svn_ignore_externals') or 'no')
    if not isdir(SVN_CACHE):
        os.makedirs(SVN_CACHE)
    svn_dn = svn_url.split(':', 1)[-1].replace('/', '_').replace(':', '_')
    cache_repo = join(SVN_CACHE, svn_dn)
    if svn_ignore_externals:
        extra_args = ['--ignore-externals']
    else:
        extra_args = []
    if isdir(cache_repo):
        check_call([svn, 'up', '-r', svn_revision] + extra_args, cwd=cache_repo)
    else:
        check_call([svn, 'co', '-r', svn_revision] + extra_args + [svn_url,
                                                                   cache_repo])
        assert isdir(cache_repo)

    # now copy into work directory
    copytree(cache_repo, WORK_DIR)
    return WORK_DIR


def _ensure_unix_line_endings(path):
    """Replace windows line endings with Unix.  Return path to modified file."""
    out_path = path + "_unix"
    with open(path) as inputfile:
        with open(out_path, "w") as outputfile:
            for line in inputfile:
                outputfile.write(line.replace("\r\n", "\n"))
    return out_path

def apply_patch(src_dir, path):
    print('Applying patch: %r' % path)
    if not isfile(path):
        sys.exit('Error: no such patch: %s' % path)

    patch = external.find_executable('patch')
    if patch is None:
        sys.exit("""\
Error:
    Did not find 'patch' in: %s
    You can install 'patch' using apt-get, yum (Linux), Xcode (MacOSX),
    or conda, cygwin (Windows),
""" % (os.pathsep.join(external.dir_paths)))
    patch_args = ['-p0', '-i', path]
    if sys.platform == 'win32':
        patch_args[-1] =  _ensure_unix_line_endings(path)
    check_call([patch, ] + patch_args, cwd=src_dir)


def provide(recipe_dir, meta, patch=True):
    """
    given a recipe_dir:
      - download (if necessary)
      - unpack
      - apply patches (if any)
    """
    print("Removing old work directory")
    rm_rf(WORK_DIR)
    if 'fn' in meta:
        unpack(meta)
    elif 'git_url' in meta:
        git_source(meta, recipe_dir)
    elif 'hg_url' in meta:
        hg_source(meta)
    elif 'svn_url' in meta:
        svn_source(meta)
    elif 'path' in meta:
        print("Copying %s to %s" % (abspath(join(recipe_dir, meta.get('path'))), WORK_DIR))
        copytree(abspath(join(recipe_dir, meta.get('path'))), WORK_DIR)
    else: # no source
        os.makedirs(WORK_DIR)

    if patch:
        src_dir = get_dir()
        for patch in meta.get('patches', []):
            apply_patch(src_dir, join(recipe_dir, patch))


if __name__ == '__main__':
    print(provide('.',
                  {'url': 'http://pypi.python.org/packages/source/b/bitarray/bitarray-0.8.0.tar.gz',
                   'git_url': 'git@github.com:ilanschnell/bitarray.git',
                   'git_tag': '0.5.2'}))
