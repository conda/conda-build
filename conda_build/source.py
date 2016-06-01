from __future__ import absolute_import, division, print_function

import os
import re
import sys
from os.path import join, isdir, isfile, abspath, expanduser, basename
from shutil import copytree, copy2
from subprocess import check_call, Popen, PIPE, CalledProcessError, check_output
import locale
import time

from conda.fetch import download
from conda.install import move_to_trash
from conda.utils import hashsum_file

from conda_build import external
from conda_build.config import config
from conda_build.utils import rm_rf, tar_xf, unzip, safe_print_unicode


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

    fn = meta['fn'] if 'fn' in meta else basename(meta['url'])
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
        else:  # no break
            raise RuntimeError("Could not download %s" % fn)

    for tp in 'md5', 'sha1', 'sha256':
        if meta.get(tp) and hashsum_file(path, tp) != meta[tp]:
            raise RuntimeError("%s mismatch: '%s' != '%s'" %
                               (tp.upper(), hashsum_file(path, tp), meta[tp]))

    return path


def unpack(meta, verbose=False):
    ''' Uncompress a downloaded source. '''
    src_path = download_to_cache(meta)

    os.makedirs(WORK_DIR)
    if verbose:
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


def git_source(meta, recipe_dir, verbose=False):
    ''' Download a source from Git repo. '''
    if verbose:
        stdout = None
        stderr = None
    else:
        FNULL = open(os.devnull, 'w')
        stdout = FNULL
        stderr = FNULL

    if not isdir(GIT_CACHE):
        os.makedirs(GIT_CACHE)

    git = external.find_executable('git')
    if not git:
        sys.exit("Error: git is not installed")
    git_url = meta['git_url']
    git_depth = int(meta.get('git_depth', -1))
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
        if meta.get('git_rev', 'HEAD') != 'HEAD':
            check_call([git, 'fetch'], cwd=cache_repo, stdout=stdout, stderr=stderr)
        else:
            # Unlike 'git clone', fetch doesn't automatically update the cache's HEAD,
            # So here we explicitly store the remote HEAD in the cache's local refs/heads,
            # and then explicitly set the cache's HEAD.
            # This is important when the git repo is a local path like "git_url: ../",
            # but the user is working with a branch other than 'master' without
            # explicitly providing git_rev.
            check_call([git, 'fetch', 'origin', '+HEAD:_conda_cache_origin_head'],
                       cwd=cache_repo, stdout=stdout, stderr=stderr)
            check_call([git, 'symbolic-ref', 'HEAD', 'refs/heads/_conda_cache_origin_head'],
                       cwd=cache_repo, stdout=stdout, stderr=stderr)
    else:
        args = [git, 'clone', '--mirror']
        if git_depth > 0:
            args += ['--depth', str(git_depth)]

        check_call(args + [git_url, cache_repo_arg], cwd=recipe_dir, stdout=stdout, stderr=stderr)
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
    if checkout and verbose:
        print('checkout: %r' % checkout)

    check_call([git, 'clone', '--recursive', cache_repo_arg, WORK_DIR],
               stdout=stdout, stderr=stderr)
    if checkout:
        check_call([git, 'checkout', checkout], cwd=WORK_DIR, stdout=stdout, stderr=stderr)

    git_info(verbose=verbose)

    if not verbose:
        FNULL.close()

    return WORK_DIR


def git_info(fo=None, verbose=False):
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
        encoding = locale.getpreferredencoding()
        if not fo:
            encoding = sys.stdout.encoding
        encoding = encoding or 'utf-8'
        stdout = stdout.decode(encoding, 'ignore')
        stderr = stderr.decode(encoding, 'ignore')
        if check_error and stderr and stderr.strip():
            raise Exception("git error: %s" % stderr)
        if fo:
            fo.write(u'==> %s <==\n' % cmd)
            if verbose:
                fo.write(stdout + u'\n')
        else:
            if verbose:
                print(u'==> %s <==\n' % cmd)
                safe_print_unicode(stdout + u'\n')


def hg_source(meta, verbose=False):
    ''' Download a source from Mercurial repo. '''
    if verbose:
        stdout = None
        stderr = None
    else:
        FNULL = open(os.devnull, 'w')
        stdout = FNULL
        stderr = FNULL

    hg = external.find_executable('hg')
    if not hg:
        sys.exit('Error: hg not installed')
    hg_url = meta['hg_url']
    if not isdir(HG_CACHE):
        os.makedirs(HG_CACHE)
    hg_dn = hg_url.split(':')[-1].replace('/', '_')
    cache_repo = join(HG_CACHE, hg_dn)
    if isdir(cache_repo):
        check_call([hg, 'pull'], cwd=cache_repo, stdout=stdout, stderr=stderr)
    else:
        check_call([hg, 'clone', hg_url, cache_repo], stdout=stdout, stderr=stderr)
        assert isdir(cache_repo)

    # now clone in to work directory
    update = meta.get('hg_tag') or 'tip'
    if verbose:
        print('checkout: %r' % update)

    check_call([hg, 'clone', cache_repo, WORK_DIR], stdout=stdout, stderr=stderr)
    check_call([hg, 'update', '-C', update], cwd=WORK_DIR, stdout=stdout, stderr=stderr)

    if not verbose:
        FNULL.close()

    return WORK_DIR


def svn_source(meta, verbose=False):
    ''' Download a source from SVN repo. '''
    if verbose:
        stdout = None
        stderr = None
    else:
        FNULL = open(os.devnull, 'w')
        stdout = FNULL
        stderr = FNULL

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
        check_call([svn, 'up', '-r', svn_revision] + extra_args, cwd=cache_repo,
                   stdout=stdout, stderr=stderr)
    else:
        check_call([svn, 'co', '-r', svn_revision] + extra_args + [svn_url, cache_repo],
                   stdout=stdout, stderr=stderr)
        assert isdir(cache_repo)

    # now copy into work directory
    copytree(cache_repo, WORK_DIR, symlinks=True)

    if not verbose:
        FNULL.close()

    return WORK_DIR


def get_repository_info(recipe_path):
    """This tries to get information about where a recipe came from.  This is different
    from the source - you can have a recipe in svn that gets source via git."""
    if isdir(join(recipe_path, ".git")):
        origin = check_output(["git", "config", "--get", "remote.origin.url"])
        rev = check_output(["git", "rev-parse", "HEAD"])
        return "Origin {}, commit {}".format(origin, rev)
    elif isdir(join(recipe_path, ".hg")):
        origin = check_output(["hg", "paths", "default"])
        rev = check_output(["hg", "id"]).split()[0]
        return "Origin {}, commit {}".format(origin, rev)
    elif isdir(join(recipe_path, ".svn")):
        info = check_output(["svn", "info"])
        server = re.search("Repository Root: (.*)$", info, flags=re.M).group(1)
        revision = re.search("Revision: (.*)$", info, flags=re.M).group(1)
        return "{}, Revision {}".format(server, revision)
    else:
        return "{}, last modified {}".format(recipe_path,
                                             time.ctime(os.path.getmtime(
                                                 join(recipe_path, "meta.yaml"))))


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
        patch_args[-1] = _ensure_unix_line_endings(path)
    try:
        check_call([patch] + patch_args, cwd=src_dir)
    except CalledProcessError:
        # fallback to -p1, the git default
        patch_args[0] = '-p1'
        try:
            check_call([patch] + patch_args, cwd=src_dir)
        except CalledProcessError:
            sys.exit(1)
    if sys.platform == 'win32' and os.path.exists(patch_args[-1]):
        os.remove(patch_args[-1])  # clean up .patch_unix file


def provide(recipe_dir, meta, verbose=False, patch=True, dirty=False):
    """
    given a recipe_dir:
      - download (if necessary)
      - unpack
      - apply patches (if any)
    """

    if not dirty:
        if sys.platform == 'win32':
            if isdir(WORK_DIR):
                move_to_trash(WORK_DIR, '')
        else:
            rm_rf(WORK_DIR)

    if not os.path.exists(WORK_DIR):
        if any(k in meta for k in ('fn', 'url')):
            unpack(meta, verbose=verbose)
        elif 'git_url' in meta:
            git_source(meta, recipe_dir, verbose=verbose)
        # build to make sure we have a work directory with source in it.  We want to make sure that
        #    whatever version that is does not interfere with the test we run next.
        elif 'hg_url' in meta:
            hg_source(meta, verbose=verbose)
        elif 'svn_url' in meta:
            svn_source(meta, verbose=verbose)
        elif 'path' in meta:
            if verbose:
                print("Copying %s to %s" % (abspath(join(recipe_dir, meta.get('path'))), WORK_DIR))
            copytree(abspath(join(recipe_dir, meta.get('path'))), WORK_DIR)
        else:  # no source
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
