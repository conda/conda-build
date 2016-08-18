from __future__ import absolute_import, division, print_function

import os
import logging
import re
import sys
from os.path import join, isdir, isfile, abspath, expanduser, basename
from shutil import copytree, copy2
from subprocess import check_call, Popen, PIPE, check_output, CalledProcessError
if sys.version_info[0] == 3:
    from urllib.parse import urljoin
else:
    from urlparse import urljoin
import locale
import time
from conda.compat import TemporaryDirectory

from .conda_interface import download
from .conda_interface import hashsum_file

from conda_build import external
from conda_build.config import config
from conda_build.utils import tar_xf, unzip, safe_print_unicode

SRC_CACHE = join(config.croot, 'src_cache')
GIT_CACHE = join(config.croot, 'git_cache')
HG_CACHE = join(config.croot, 'hg_cache')
SVN_CACHE = join(config.croot, 'svn_cache')
WORK_DIR = join(config.croot, 'work')
git_submod_re = re.compile(r'(?:.+)\.(.+)\.(?:.+)\s(.+)')

log = logging.getLogger(__file__)


def get_dir():
    if os.path.isdir(WORK_DIR):
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

    if not isdir(WORK_DIR):
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


def git_mirror_checkout_recursive(git, mirror_dir, checkout_dir, git_url, git_ref=None, git_depth=-1, is_top_level=True, verbose=True):
    """ Mirror (and checkout) a Git repository recursively.

        It's not possible to use `git submodule` on a bare
        repository, so the checkout must be done before we
        know which submodules there are.

        Worse, submodules can be identified by using either
        absolute URLs or relative paths.  If relative paths
        are used those need to be relocated upon mirroring,
        but you could end up with `../../../../blah` and in
        that case conda-build could be tricked into writing
        to the root of the drive and overwriting the system
        folders unless steps are taken to prevent that.
    """

    if verbose:
        stdout = None
    else:
        FNULL = open(os.devnull, 'w')
        stdout = FNULL
    if not mirror_dir.startswith(GIT_CACHE + os.sep):
        sys.exit("Error: Attempting to mirror to %s which is outside of GIT_CACHE %s" % (mirror_dir, GIT_CACHE))
    if not isdir(os.path.dirname(mirror_dir)):
        os.makedirs(os.path.dirname(mirror_dir))
    mirror_dir_arg = mirror_dir
    if sys.platform == 'win32' and 'cygwin' in git.lower():
        mirror_dir_arg = '/cygdrive/c/' + mirror_dir[3:].replace('\\', '/')
    if isdir(mirror_dir):
        if git_ref != 'HEAD':
            check_call([git, 'fetch'], cwd=mirror_dir, stdout=stdout)
        else:
            # Unlike 'git clone', fetch doesn't automatically update the cache's HEAD,
            # So here we explicitly store the remote HEAD in the cache's local refs/heads,
            # and then explicitly set the cache's HEAD.
            # This is important when the git repo is a local path like "git_url: ../",
            # but the user is working with a branch other than 'master' without
            # explicitly providing git_rev.
            check_call([git, 'fetch', 'origin', '+HEAD:_conda_cache_origin_head'],
                       cwd=mirror_dir, stdout=stdout)
            check_call([git, 'symbolic-ref', 'HEAD', 'refs/heads/_conda_cache_origin_head'],
                       cwd=mirror_dir, stdout=stdout)
    else:
        args = [git, 'clone', '--mirror']
        if git_depth > 0:
            args += ['--depth', str(git_depth)]
        check_call(args + [git_url, mirror_dir_arg], stdout=stdout)
        assert isdir(mirror_dir)

    # Now clone from mirror_dir into checkout_dir.
    check_call([git, 'clone', mirror_dir_arg, checkout_dir], stdout=stdout)
    if is_top_level:
        checkout = git_ref
        if git_url.startswith('.'):
            process = Popen(["git", "rev-parse", checkout],
                            stdout=PIPE, cwd=git_url)
            output = process.communicate()[0].strip()
            checkout = output.decode('utf-8')
        if verbose:
            print('checkout: %r' % checkout)
        if checkout:
            check_call([git, 'checkout', checkout],
                       cwd=checkout_dir, stdout=stdout)

    # submodules may have been specified using relative paths.
    # Those paths are relative to git_url, and will not exist
    # relative to mirror_dir, unless we do some work to make
    # it so.
    try:
        submodules = check_output([git, 'config', '--file', '.gitmodules', '--get-regexp',
                                   'url'], stderr=stdout, cwd=checkout_dir).decode('utf-8').splitlines()
    except:
        submodules = []
    for submodule in submodules:
        matches = git_submod_re.match(submodule)
        if matches and matches.group(2)[0] == '.':
            submod_name = matches.group(1)
            submod_rel_path = matches.group(2)
            submod_url = urljoin(git_url + '/', submod_rel_path)
            submod_mirror_dir = os.path.normpath(
                os.path.join(mirror_dir, submod_rel_path))
            if verbose:
                print('Relative submodule %s found: url is %s, submod_mirror_dir is %s' % (
                      submod_name, submod_url, submod_mirror_dir))
            with TemporaryDirectory() as temp_checkout_dir:
                git_mirror_checkout_recursive(git, submod_mirror_dir, temp_checkout_dir, submod_url,
                                              git_ref, git_depth, False, verbose)

    if is_top_level:
        # Now that all relative-URL-specified submodules are locally mirrored to
        # relatively the same place we can go ahead and checkout the submodules.
        check_call([git, 'submodule', 'update', '--init',
                    '--recursive'], cwd=checkout_dir, stdout=stdout)
        git_info(verbose=verbose)
    if not verbose:
        FNULL.close()


def git_source(meta, recipe_dir, verbose=False):
    ''' Download a source from a Git repo (or submodule, recursively) '''
    if not isdir(GIT_CACHE):
        os.makedirs(GIT_CACHE)

    git = external.find_executable('git')
    if not git:
        sys.exit("Error: git is not installed")

    git_url = meta['git_url']
    git_depth = int(meta.get('git_depth', -1))
    git_ref = meta.get('git_rev', 'HEAD')

    if git_url.startswith('.'):
        # It's a relative path from the conda recipe
        os.chdir(recipe_dir)
        if sys.platform == 'win32':
            git_dn = abspath(expanduser(git_url)).replace(':', '_')
        else:
            git_dn = abspath(expanduser(git_url))[1:]
    else:
        git_dn = git_url.split('://')[-1].replace('/', os.sep)
        if git_dn.startswith(os.sep):
            git_dn = git_dn[1:]
    mirror_dir = join(GIT_CACHE, git_dn)
    git_mirror_checkout_recursive(
        git, mirror_dir, WORK_DIR, git_url, git_ref, git_depth, True, verbose)
    return git


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
    try:
        if isdir(join(recipe_path, ".git")):
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


def _get_patch_file_details(path):
    re_files = re.compile('^(?:---|\+\+\+) ([^\n\t]+)')
    files = set()
    with open(path) as f:
        files = []
        first_line = True
        is_git_format = True
        for l in f.readlines():
            if first_line and not re.match('From [0-9a-f]{40}', l):
                is_git_format = False
            first_line = False
            m = re_files.search(l)
            if m and m.group(1) != '/dev/null':
                files.append(m.group(1))
            elif is_git_format and l.startswith('git') and not l.startswith('git --diff'):
                is_git_format = False
    return (files, is_git_format)


def apply_patch(src_dir, path, git=None):
    if not isfile(path):
        sys.exit('Error: no such patch: %s' % path)

    files, is_git_format = _get_patch_file_details(path)
    if git and is_git_format:
        # Prevents git from asking interactive questions,
        # also necessary to achieve sha1 reproducibility;
        # as is --committer-date-is-author-date. By this,
        # we mean a round-trip of git am/git format-patch
        # gives the same file.
        git_env = os.environ
        git_env['GIT_COMMITTER_NAME'] = 'conda-build'
        git_env['GIT_COMMITTER_EMAIL'] = 'conda@conda-build.org'
        check_call([git, 'am', '--committer-date-is-author-date', path],
                   cwd=src_dir, stdout=None, env=git_env)
    else:
        print('Applying patch: %r' % path)
        patch = external.find_executable('patch')
        if patch is None:
            sys.exit("""\
        Error:
            Cannot use 'git' (not a git repo and/or patch) and did not find 'patch' in: %s
            You can install 'patch' using apt-get, yum (Linux), Xcode (MacOSX),
            or conda, m2-patch (Windows),
        """ % (os.pathsep.join(external.dir_paths)))
        patch_strip_level = _guess_patch_strip_level(files, src_dir)
        patch_args = ['-p%d' % patch_strip_level, '-i', path]
        if sys.platform == 'win32':
            patch_args[-1] = _ensure_unix_line_endings(path)
        check_call([patch] + patch_args, cwd=src_dir)
        if sys.platform == 'win32' and os.path.exists(patch_args[-1]):
            os.remove(patch_args[-1])  # clean up .patch_unix file


def provide(recipe_dir, meta, verbose=False, patch=True):
    """
    given a recipe_dir:
      - download (if necessary)
      - unpack
      - apply patches (if any)
    """

    git = None
    if any(k in meta for k in ('fn', 'url')):
        unpack(meta, verbose=verbose)
    elif 'git_url' in meta:
        git = git_source(meta, recipe_dir, verbose=verbose)
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
        if not isdir(WORK_DIR):
            os.makedirs(WORK_DIR)

    if patch:
        src_dir = get_dir()
        for patch in meta.get('patches', []):
            apply_patch(src_dir, join(recipe_dir, patch), git)


if __name__ == '__main__':
    print(provide('.',
                  {'url': 'http://pypi.python.org/packages/source/b/bitarray/bitarray-0.8.0.tar.gz',
                   'git_url': 'git@github.com:ilanschnell/bitarray.git',
                   'git_tag': '0.5.2'}))
