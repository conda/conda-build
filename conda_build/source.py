from __future__ import absolute_import, division, print_function

from contextlib import contextmanager
import locale
import logging
import os
import re
import sys
from os.path import join, isdir, isfile, abspath, expanduser, basename, exists
from subprocess import check_call, Popen, PIPE, check_output, CalledProcessError
import time

from .conda_interface import download
from .conda_interface import hashsum_file

from conda_build.os_utils import external
from conda_build.utils import tar_xf, unzip, safe_print_unicode, copy_into

log = logging.getLogger(__file__)


def get_dir(config):
    if os.path.isdir(config.work_dir):
        lst = [fn for fn in os.listdir(config.work_dir) if not fn.startswith('.')]
        if len(lst) == 1:
            dir_path = join(config.work_dir, lst[0])
            if isdir(dir_path):
                return dir_path
    return config.work_dir


def download_to_cache(meta, config):
    ''' Download a source to the local cache. '''
    print('Source cache directory is: %s' % config.src_cache)
    if not isdir(config.src_cache):
        os.makedirs(config.src_cache)

    fn = meta['fn'] if 'fn' in meta else basename(meta['url'])
    path = join(config.src_cache, fn)
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


def unpack(meta, config):
    ''' Uncompress a downloaded source. '''
    src_path = download_to_cache(meta, config)

    if not isdir(config.work_dir):
        os.makedirs(config.work_dir)
    if config.verbose:
        print("Extracting download")
    if src_path.lower().endswith(('.tar.gz', '.tar.bz2', '.tgz', '.tar.xz',
            '.tar', 'tar.z')):
        tar_xf(src_path, get_dir(config))
    elif src_path.lower().endswith('.zip'):
        unzip(src_path, get_dir(config))
    else:
        # In this case, the build script will need to deal with unpacking the source
        print("Warning: Unrecognized source format. Source file will be copied to the SRC_DIR")
        copy_into(src_path, get_dir(config), config)


def git_source(meta, recipe_dir, config):
    ''' Download a source from Git repo. '''
    if config.verbose:
        stdout = None
        stderr = None
    else:
        FNULL = open(os.devnull, 'w')
        stdout = FNULL
        stderr = FNULL

    if not isdir(config.git_cache):
        os.makedirs(config.git_cache)

    git = external.find_executable('git', config.build_prefix)
    if not git:
        sys.exit("Error: git is not installed")
    git_url = meta['git_url']
    git_depth = int(meta.get('git_depth', -1))
    if git_url.startswith('.'):
        # It's a relative path from the conda recipe
        cwd = os.getcwd()
        os.chdir(recipe_dir)
        git_dn = abspath(expanduser(git_url))
        git_dn = "_".join(git_dn.split(os.path.sep)[1:])
        git_url = abspath(expanduser(git_url))
        os.chdir(cwd)
    else:
        git_dn = git_url.split(':')[-1].replace('/', '_')
    cache_repo = cache_repo_arg = join(config.git_cache, git_dn)
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

        check_call(args + [git_url, cache_repo_arg], stdout=stdout, stderr=stderr)
        assert isdir(cache_repo)

    # now clone into the work directory
    checkout = meta.get('git_rev')
    # if rev is not specified, and the git_url is local,
    # assume the user wants the current HEAD
    if not checkout and git_url.startswith('.'):
        process = Popen(["git", "rev-parse", "HEAD"],
                        stdout=PIPE, cwd=git_url, stderr=stderr)
        output = process.communicate()[0].strip()
        checkout = output.decode('utf-8')
    if checkout and config.verbose:
        print('checkout: %r' % checkout)

    check_call([git, 'clone', cache_repo_arg, config.work_dir], stdout=stdout, stderr=stderr)
    if checkout:
        check_call([git, 'checkout', checkout], cwd=config.work_dir, stdout=stdout, stderr=stderr)

    # Submodules must be updated after checkout.
    check_call([git, 'submodule', 'update', '--init', '--recursive'],
               cwd=config.work_dir, stdout=stdout, stderr=stderr)

    git_info(config=config)

    if not config.verbose:
        FNULL.close()

    return config.work_dir


def git_info(config, fo=None):
    ''' Print info about a Git repo. '''
    assert isdir(config.work_dir)

    # Ensure to explicitly set GIT_DIR as some Linux machines will not
    # properly execute without it.
    env = os.environ.copy()
    env['GIT_DIR'] = join(get_dir(config), '.git')
    env = {str(key): str(value) for key, value in env.items()}
    for cmd, check_error in [
            ('git log -n1', True),
            ('git describe --tags --dirty', False),
            ('git status', True)]:
        p = Popen(cmd.split(), stdout=PIPE, stderr=PIPE, cwd=get_dir(config), env=env)
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
            if config.verbose:
                fo.write(stdout + u'\n')
        else:
            if config.verbose:
                print(u'==> %s <==\n' % cmd)
                safe_print_unicode(stdout + u'\n')


def hg_source(meta, config):
    ''' Download a source from Mercurial repo. '''
    if config.verbose:
        stdout = None
        stderr = None
    else:
        FNULL = open(os.devnull, 'w')
        stdout = FNULL
        stderr = FNULL

    hg = external.find_executable('hg', config.build_prefix)
    if not hg:
        sys.exit('Error: hg not installed')
    hg_url = meta['hg_url']
    if not isdir(config.hg_cache):
        os.makedirs(config.hg_cache)
    hg_dn = hg_url.split(':')[-1].replace('/', '_')
    cache_repo = join(config.hg_cache, hg_dn)
    if isdir(cache_repo):
        check_call([hg, 'pull'], cwd=cache_repo, stdout=stdout, stderr=stderr)
    else:
        check_call([hg, 'clone', hg_url, cache_repo], stdout=stdout, stderr=stderr)
        assert isdir(cache_repo)

    # now clone in to work directory
    update = meta.get('hg_tag') or 'tip'
    if config.verbose:
        print('checkout: %r' % update)

    check_call([hg, 'clone', cache_repo, config.work_dir], stdout=stdout, stderr=stderr)
    check_call([hg, 'update', '-C', update], cwd=get_dir(config), stdout=stdout, stderr=stderr)

    if not config.verbose:
        FNULL.close()

    return config.work_dir


def svn_source(meta, config):
    ''' Download a source from SVN repo. '''
    if config.verbose:
        stdout = None
        stderr = None
    else:
        FNULL = open(os.devnull, 'w')
        stdout = FNULL
        stderr = FNULL

    def parse_bool(s):
        return str(s).lower().strip() in ('yes', 'true', '1', 'on')

    svn = external.find_executable('svn', config.build_prefix)
    if not svn:
        sys.exit("Error: svn is not installed")
    svn_url = meta['svn_url']
    svn_revision = meta.get('svn_rev') or 'head'
    svn_ignore_externals = parse_bool(meta.get('svn_ignore_externals') or 'no')
    if not isdir(config.svn_cache):
        os.makedirs(config.svn_cache)
    svn_dn = svn_url.split(':', 1)[-1].replace('/', '_').replace(':', '_')
    cache_repo = join(config.svn_cache, svn_dn)
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
    copy_into(cache_repo, config.work_dir, config, symlinks=True)

    if not config.verbose:
        FNULL.close()

    return config.work_dir


def get_repository_info(recipe_path):
    """This tries to get information about where a recipe came from.  This is different
    from the source - you can have a recipe in svn that gets source via git."""
    try:
        if exists(join(recipe_path, ".git")):
            origin = check_output(["git", "config", "--get", "remote.origin.url"], cwd=recipe_path)
            rev = check_output(["git", "rev-parse", "HEAD"], cwd=recipe_path)
            return "Origin {}, commit {}".format(origin, rev)
        elif isdir(join(recipe_path, ".hg")):
            origin = check_output(["hg", "paths", "default"], cwd=recipe_path)
            rev = check_output(["hg", "id"], cwd=recipe_path).split()[0]
            return "Origin {}, commit {}".format(origin, rev)
        elif isdir(join(recipe_path, ".svn")):
            info = check_output(["svn", "info"], cwd=recipe_path)
            server = re.search("Repository Root: (.*)$", info, flags=re.M).group(1)
            revision = re.search("Revision: (.*)$", info, flags=re.M).group(1)
            return "{}, Revision {}".format(server, revision)
        else:
            return "{}, last modified {}".format(recipe_path,
                                             time.ctime(os.path.getmtime(
                                                 join(recipe_path, "meta.yaml"))))
    except CalledProcessError:
        log.debug("Failed to checkout source in " + recipe_path)
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


def _guess_patch_strip_level(filesstr, src_dir):
    """ Determine the patch strip level automatically. """
    maxlevel = None
    files = {filestr.encode(errors='ignore') for filestr in filesstr}
    src_dir = src_dir.encode(errors='ignore')
    for file in files:
        numslash = file.count(b'/')
        maxlevel = numslash if not maxlevel else min(maxlevel, numslash)
    if maxlevel == 0:
        patchlevel = 0
    else:
        histo = dict()
        histo = {i: 0 for i in range(maxlevel + 1)}
        for file in files:
            parts = file.split(b'/')
            for level in range(maxlevel + 1):
                if os.path.exists(join(src_dir, *parts[-len(parts) + level:])):
                    histo[level] += 1
        order = sorted(histo, key=histo.get, reverse=True)
        if histo[order[0]] == histo[order[1]]:
            print("Patch level ambiguous, selecting least deep")
        patchlevel = min([key for key, value
                          in histo.items() if value == histo[order[0]]])
    return patchlevel


def _source_files_from_patch_file(path):
    re_files = re.compile('^(?:---|\+\+\+) ([^\n\t]+)')
    files = set()
    with open(path) as f:
        files = {m.group(1) for l in f.readlines()
                 for m in [re_files.search(l)]
                 if m and m.group(1) != '/dev/null'}
    return files


def apply_patch(src_dir, path, config):
    print('Applying patch: %r' % path)
    if not isfile(path):
        sys.exit('Error: no such patch: %s' % path)

    patch = external.find_executable('patch', config.build_prefix)
    if patch is None:
        sys.exit("""\
Error:
    Did not find 'patch' in: %s
    You can install 'patch' using apt-get, yum (Linux), Xcode (MacOSX),
    or conda, m2-patch (Windows),
""" % (os.pathsep.join(external.dir_paths)))
    files = _source_files_from_patch_file(path)
    patch_strip_level = _guess_patch_strip_level(files, src_dir)
    patch_args = ['-p%d' % patch_strip_level, '-i', path]
    if sys.platform == 'win32':
        patch_args[-1] = _ensure_unix_line_endings(path)
    check_call([patch] + patch_args, cwd=src_dir)
    if sys.platform == 'win32' and os.path.exists(patch_args[-1]):
        os.remove(patch_args[-1])  # clean up .patch_unix file


def provide(recipe_dir, meta, config, patch=True):
    """
    given a recipe_dir:
      - download (if necessary)
      - unpack
      - apply patches (if any)
    """

    if any(k in meta for k in ('fn', 'url')):
        unpack(meta, config=config)
    elif 'git_url' in meta:
        git_source(meta, recipe_dir, config=config)
    # build to make sure we have a work directory with source in it.  We want to make sure that
    #    whatever version that is does not interfere with the test we run next.
    elif 'hg_url' in meta:
        hg_source(meta, config=config)
    elif 'svn_url' in meta:
        svn_source(meta, config=config)
    elif 'path' in meta:
        if config.verbose:
            print("Copying %s to %s" % (abspath(join(recipe_dir,
                                                     meta.get('path'))),
                                        config.work_dir))
        # careful here: we set test path to be outside of conda-build root in setup.cfg.
        #    If you don't do that, this is a recursive function
        copy_into(abspath(join(recipe_dir, meta.get('path'))), config.work_dir, config)
    else:  # no source
        if not isdir(config.work_dir):
            os.makedirs(config.work_dir)

    if patch:
        src_dir = get_dir(config)
        for patch in meta.get('patches', []):
            apply_patch(src_dir, join(recipe_dir, patch), config)
    return config.work_dir


if __name__ == '__main__':
    print(provide('.',
                  {'url': 'http://pypi.python.org/packages/source/b/bitarray/bitarray-0.8.0.tar.gz',
                   'git_url': 'git@github.com:ilanschnell/bitarray.git',
                   'git_tag': '0.5.2'}))
