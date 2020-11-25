from __future__ import absolute_import, division, print_function

import io
import locale
import os
from os.path import join, isdir, isfile, abspath, basename, exists, normpath, expanduser
import re
import shutil
from subprocess import CalledProcessError
import sys
import tempfile
import time

from .conda_interface import download, TemporaryDirectory
from .conda_interface import hashsum_file

from conda_build.os_utils import external
from conda_build.conda_interface import url_path, CondaHTTPError
from conda_build.utils import (decompressible_exts, tar_xf, safe_print_unicode, copy_into, on_win, ensure_list,
                               check_output_env, check_call_env, convert_path_for_cygwin_or_msys2,
                               get_logger, rm_rf, LoggingContext)


log = get_logger(__name__)
if on_win:
    from conda_build.utils import convert_unix_path_to_win

if sys.version_info[0] == 3:
    from urllib.parse import urljoin
else:
    from urlparse import urljoin

git_submod_re = re.compile(r'(?:.+)\.(.+)\.(?:.+)\s(.+)')
ext_re = re.compile(r"(.*?)(\.(?:tar\.)?[^.]+)$")


def append_hash_to_fn(fn, hash_value):
    return ext_re.sub(r"\1_{}\2".format(hash_value[:10]), fn)


def download_to_cache(cache_folder, recipe_path, source_dict, verbose=False):
    ''' Download a source to the local cache. '''
    if verbose:
        log.info('Source cache directory is: %s' % cache_folder)
    if not isdir(cache_folder) and not os.path.islink(cache_folder):
        os.makedirs(cache_folder)

    source_urls = source_dict['url']
    if not isinstance(source_urls, list):
        source_urls = [source_urls]
    unhashed_fn = fn = source_dict['fn'] if 'fn' in source_dict else basename(source_urls[0])
    hash_added = False
    for hash_type in ('md5', 'sha1', 'sha256'):
        if hash_type in source_dict:
            if source_dict[hash_type] in (None, ""):
                raise ValueError('Empty {} hash provided for {}'.format(hash_type, fn))
            fn = append_hash_to_fn(fn, source_dict[hash_type])
            hash_added = True
            break
    else:
        log.warn("No hash (md5, sha1, sha256) provided for {}.  Source download forced.  "
                 "Add hash to recipe to use source cache.".format(unhashed_fn))
    path = join(cache_folder, fn)
    if isfile(path):
        if verbose:
            log.info('Found source in cache: %s' % fn)
    else:
        if verbose:
            log.info('Downloading source to cache: %s' % fn)

        for url in source_urls:
            if "://" not in url:
                if url.startswith('~'):
                    url = expanduser(url)
                if not os.path.isabs(url):
                    url = os.path.normpath(os.path.join(recipe_path, url))
                url = url_path(url)
            else:
                if url.startswith('file:///~'):
                    url = 'file:///' + expanduser(url[8:]).replace('\\', '/')
            try:
                if verbose:
                    log.info("Downloading %s" % url)
                with LoggingContext():
                    download(url, path)
            except CondaHTTPError as e:
                log.warn("Error: %s" % str(e).strip())
                rm_rf(path)
            except RuntimeError as e:
                log.warn("Error: %s" % str(e).strip())
                rm_rf(path)
            else:
                if verbose:
                    log.info("Success")
                break
        else:  # no break
            rm_rf(path)
            raise RuntimeError("Could not download %s" % url)

    hashed = None
    for tp in ('md5', 'sha1', 'sha256'):
        if tp in source_dict:
            expected_hash = source_dict[tp]
            hashed = hashsum_file(path, tp)
            if expected_hash != hashed:
                rm_rf(path)
                raise RuntimeError("%s mismatch: '%s' != '%s'" %
                           (tp.upper(), hashed, expected_hash))
            break

    # this is really a fallback.  If people don't provide the hash, we still need to prevent
    #    collisions in our source cache, but the end user will get no benefit from the cache.
    if not hash_added:
        if not hashed:
            hashed = hashsum_file(path, 'sha256')
        dest_path = append_hash_to_fn(path, hashed)
        if not os.path.isfile(dest_path):
            shutil.move(path, dest_path)
        path = dest_path

    return path, unhashed_fn


def hoist_single_extracted_folder(nested_folder):
    """Moves all files/folders one level up.

    This is for when your archive extracts into its own folder, so that we don't need to
    know exactly what that folder is called."""
    parent = os.path.dirname(nested_folder)
    flist = os.listdir(nested_folder)
    with TemporaryDirectory() as tmpdir:
        for entry in flist:
            shutil.move(os.path.join(nested_folder, entry), os.path.join(tmpdir, entry))
        rm_rf(nested_folder)
        for entry in flist:
            shutil.move(os.path.join(tmpdir, entry), os.path.join(parent, entry))


def unpack(source_dict, src_dir, cache_folder, recipe_path, croot, verbose=False,
           timeout=900, locking=True):
    ''' Uncompress a downloaded source. '''
    src_path, unhashed_fn = download_to_cache(cache_folder, recipe_path, source_dict, verbose)

    if not isdir(src_dir):
        os.makedirs(src_dir)
    if verbose:
        print("Extracting download")
    with TemporaryDirectory(dir=croot) as tmpdir:
        unhashed_dest = os.path.join(tmpdir, unhashed_fn)
        if src_path.lower().endswith(decompressible_exts):
            tar_xf(src_path, tmpdir)
        else:
            # In this case, the build script will need to deal with unpacking the source
            print("Warning: Unrecognized source format. Source file will be copied to the SRC_DIR")
            copy_into(src_path, unhashed_dest, timeout, locking=locking)
        if src_path.lower().endswith('.whl'):
            # copy wheel itself *and* unpack it
            # This allows test_files or about.license_file to locate files in the wheel,
            # as well as `pip install name-version.whl` as install command
            copy_into(src_path, unhashed_dest, timeout, locking=locking)
        flist = os.listdir(tmpdir)
        folder = os.path.join(tmpdir, flist[0])
        # Hoisting is destructive of information, in CDT packages, a single top level
        # folder of /usr64 must not be discarded.
        if len(flist) == 1 and os.path.isdir(folder) and 'no_hoist' not in source_dict:
            hoist_single_extracted_folder(folder)
        flist = os.listdir(tmpdir)
        for f in flist:
            shutil.move(os.path.join(tmpdir, f), os.path.join(src_dir, f))


def git_mirror_checkout_recursive(git, mirror_dir, checkout_dir, git_url, git_cache, git_ref=None,
                                  git_depth=-1, is_top_level=True, verbose=True):
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
        stderr = None
    else:
        FNULL = open(os.devnull, 'wb')
        stdout = FNULL
        stderr = FNULL

    if not mirror_dir.startswith(git_cache + os.sep):
        sys.exit("Error: Attempting to mirror to %s which is outside of GIT_CACHE %s"
                 % (mirror_dir, git_cache))

    # This is necessary for Cygwin git and m2-git, although it is fixed in newer MSYS2.
    git_mirror_dir = convert_path_for_cygwin_or_msys2(git, mirror_dir).rstrip('/')
    git_checkout_dir = convert_path_for_cygwin_or_msys2(git, checkout_dir).rstrip('/')

    # Set default here to catch empty dicts
    git_ref = git_ref or 'HEAD'

    mirror_dir = mirror_dir.rstrip('/')
    if not isdir(os.path.dirname(mirror_dir)):
        os.makedirs(os.path.dirname(mirror_dir))
    if isdir(mirror_dir):
        try:
            if git_ref != 'HEAD':
                check_call_env([git, 'fetch'], cwd=mirror_dir, stdout=stdout, stderr=stderr)
            else:
                # Unlike 'git clone', fetch doesn't automatically update the cache's HEAD,
                # So here we explicitly store the remote HEAD in the cache's local refs/heads,
                # and then explicitly set the cache's HEAD.
                # This is important when the git repo is a local path like "git_url: ../",
                # but the user is working with a branch other than 'master' without
                # explicitly providing git_rev.
                check_call_env([git, 'fetch', 'origin', '+HEAD:_conda_cache_origin_head'],
                           cwd=mirror_dir, stdout=stdout, stderr=stderr)
                check_call_env([git, 'symbolic-ref', 'HEAD', 'refs/heads/_conda_cache_origin_head'],
                           cwd=mirror_dir, stdout=stdout, stderr=stderr)
        except CalledProcessError:
            msg = ("Failed to update local git cache. "
                   "Deleting local cached repo: {} ".format(mirror_dir))
            print(msg)

            # Maybe the failure was caused by a corrupt mirror directory.
            # Delete it so the user can try again.
            shutil.rmtree(mirror_dir)
            raise
    else:
        args = [git, 'clone', '--mirror']
        if git_depth > 0:
            args += ['--depth', str(git_depth)]
        try:
            check_call_env(args + [git_url, git_mirror_dir], stdout=stdout, stderr=stderr)
        except CalledProcessError:
            # on windows, remote URL comes back to us as cygwin or msys format.  Python doesn't
            # know how to normalize it.  Need to convert it to a windows path.
            if sys.platform == 'win32' and git_url.startswith('/'):
                git_url = convert_unix_path_to_win(git_url)

            if os.path.exists(git_url):
                # Local filepaths are allowed, but make sure we normalize them
                git_url = normpath(git_url)
            check_call_env(args + [git_url, git_mirror_dir], stdout=stdout, stderr=stderr)
        assert isdir(mirror_dir)

    # Our git_ref can be anything, a branch, a tag or just a commit. Try to find a reference
    # on a tag or a branch (in that order) if we can because if we do that we can clone just
    # that reference saving time.
    ref_is_sha1 = False
    try:
        sha1 = check_output_env([git, 'show-ref',  '-s', git_ref], cwd=git_mirror_dir)
    except:
        # It is likely we were passed a sha1 in the first place. Find a branch or tag that
        # sha1 is on.
        tags = check_output_env([git, 'tag', '--contains', git_ref], cwd=git_mirror_dir).\
            decode('utf-8').splitlines()
        tags = [t.strip() for t in tags]
        branches = check_output_env([git, 'branch', '--contains', git_ref], cwd=git_mirror_dir).\
            decode('utf-8').splitlines()
        # Not sure what the * represents.
        branches = [b.replace('* ', ' ').strip() for b in branches]
        if len(tags) or len(branches):
            if is_top_level:
                print("For {}, the git_tag {} is not a tag or a branch, found sha1 on:\nTag(s): {}\nBranch(es): {}".
                      format(git_url, git_ref, tags, branches))
        else:
            log.warning("For {}, the git_tag (sha1) {} was not found on any tag or branch, will clone everything".
                        format(git_url, git_ref))
        if len(tags):
            git_ref = tags[0]
        elif len(branches):
            git_ref = branches[0]
        else:
            ref_is_sha1 = True

    # Now clone from mirror_dir into checkout_dir. We save a lot of time by using --depth 1
    check_call_env([git, 'clone', git_mirror_dir, git_checkout_dir] +
                   ['--depth', '1', '--branch', git_ref] if not ref_is_sha1 else [],
                   stdout=stdout, stderr=stderr)

    # https://stackoverflow.com/a/43759576
    # check_call_env([git, 'clone', '--depth', '1',
    #                 'file://' + git_mirror_dir, git_checkout_dir] + ['--branch', git_ref] if git_ref else [],
    #                stdout=stdout, stderr=stderr)
    # check_call_env([git, 'clone', '--depth', '1',
    #                 '-c', 'remote.origin.fetch=+refs/changes/*:refs/remotes/origin/changes/*',
    #                'file://' + git_mirror_dir, git_checkout_dir])
    if is_top_level:
        checkout = git_ref
        if git_url.startswith('.'):
            output = check_output_env([git, "rev-parse", checkout], stdout=stdout, stderr=stderr)
            checkout = output.decode('utf-8')
        if verbose:
            print('git checkout: {} => {}'.format(checkout, checkout_dir))
        if checkout:
            check_call_env([git, 'checkout', checkout],
                           cwd=checkout_dir, stdout=stdout, stderr=stderr)

    # submodules may have been specified using relative paths.
    # Those paths are relative to git_url, and will not exist
    # relative to mirror_dir, unless we do some work to make
    # it so.
    try:
        submodules_list = check_output_env([git, 'submodule', 'status'],
                                           stderr=stdout, cwd=checkout_dir).decode('utf-8').splitlines()
        submodules_list2 = check_output_env([git, 'config', '--file', '.gitmodules', '--get-regexp',
                                             '.*path|.*url'], stderr=stdout, cwd=checkout_dir).decode('utf-8').splitlines()
        # We get 2 entries per submodule in submodules_list2, path, and url.
        assert len(submodules_list)*2 == len(submodules_list2)
    except CalledProcessError:
        submodules_list = []
        submodules_list2 = []
    submodules = {}
    for sm in submodules_list:
        reggie = re.compile('.([0-9a-f]*) (\S+)')
        m = reggie.match(sm)
        groups = m.groups()
        submod_sha1 = groups[0]
        submod_path = groups[1]
        submodules[submod_path] = {}
        sm_attrs = submodules[submod_path]
        sm_attrs['sha1'] = submod_sha1
        sm_attrs['path'] = submod_path
    for sm2, sm3 in zip(submodules_list2[::2], submodules_list2[1::2]):
        m2 = git_submod_re.match(sm2)
        m3 = git_submod_re.match(sm3)
        if m3 and m3.group(2)[0] == '.':
            submod_path = m2.group(2)
            sm_attrs = submodules[submod_path]
            assert sm_attrs
            sm_attrs['rel_path'] = m2.group(2)
            sm_attrs['url'] = urljoin(git_url + '/', m3.group(2))
            sm_attrs['mirror_dir'] = os.path.normpath(os.path.join(mirror_dir, sm_attrs['rel_path']))
    if verbose:
        for sm_name, sm_attrs in submodules.items():
            import json
            print('Relative submodule {} found:\n{}'.format(sm_name, json.dumps(sm_attrs, indent=2)))
    for sm_name, sm_attrs in submodules.items():
        with TemporaryDirectory() as temp_checkout_dir:
            git_mirror_checkout_recursive(git, sm_attrs['mirror_dir'], temp_checkout_dir,
                                          sm_attrs['url'],
                                          git_cache=git_cache, git_ref=sm_attrs['sha1'],
                                          git_depth=git_depth, is_top_level=False,
                                          verbose=verbose)
    if is_top_level:
        # Now that all relative-URL-specified submodules are locally mirrored to
        # relatively the same place we can go ahead and checkout the submodules.
        check_call_env([git, 'submodule', 'update', '--init',
                    '--recursive'], cwd=checkout_dir, stdout=stdout, stderr=stderr)
        git_info(checkout_dir, None, git=git, verbose=verbose)
    if not verbose:
        FNULL.close()


def git_source(source_dict, git_cache, src_dir, recipe_path=None, verbose=True):
    ''' Download a source from a Git repo (or submodule, recursively) '''
    if not isdir(git_cache):
        os.makedirs(git_cache)

    git = external.find_executable('git')
    if not git:
        sys.exit("Error: git is not installed in your root environment or as a build requirement.")

    git_depth = int(source_dict.get('git_depth', -1))
    git_ref = source_dict.get('git_rev') or 'HEAD'

    git_url = source_dict['git_url']
    if git_url.startswith('~'):
        git_url = os.path.expanduser(git_url)
    if git_url.startswith('.'):
        # It's a relative path from the conda recipe
        git_url = abspath(normpath(os.path.join(recipe_path, git_url)))
        if sys.platform == 'win32':
            git_dn = git_url.replace(':', '_')
        else:
            git_dn = git_url[1:]
    else:
        git_dn = git_url.split('://')[-1].replace('/', os.sep)
        if git_dn.startswith(os.sep):
            git_dn = git_dn[1:]
        git_dn = git_dn.replace(':', '_')
    mirror_dir = join(git_cache, git_dn)
    git_mirror_checkout_recursive(
        git, mirror_dir, src_dir, git_url, git_cache=git_cache, git_ref=git_ref,
        git_depth=git_depth, is_top_level=True, verbose=verbose)
    return git


# Why not use get_git_info instead?
def git_info(src_dir, build_prefix, git=None, verbose=True, fo=None):
    ''' Print info about a Git repo. '''
    assert isdir(src_dir)

    if not git:
        git = external.find_executable('git', build_prefix)
    if not git:
        log.warn("git not installed in root environment.  Skipping recording of git info.")
        return

    if verbose:
        stderr = None
    else:
        FNULL = open(os.devnull, 'wb')
        stderr = FNULL

    # Ensure to explicitly set GIT_DIR as some Linux machines will not
    # properly execute without it.
    env = os.environ.copy()
    env['GIT_DIR'] = join(src_dir, '.git')
    env = {str(key): str(value) for key, value in env.items()}
    for cmd, check_error in (
            ((git, 'log', '-n1'), True),
            ((git, 'describe', '--tags', '--dirty'), False),
            ((git, 'status'), True)):
        try:
            stdout = check_output_env(cmd, stderr=stderr, cwd=src_dir, env=env)
        except CalledProcessError as e:
            if check_error:
                raise Exception("git error: %s" % str(e))
        encoding = locale.getpreferredencoding()
        if not fo:
            encoding = sys.stdout.encoding
        encoding = encoding or 'utf-8'
        if hasattr(stdout, 'decode'):
            stdout = stdout.decode(encoding, 'ignore')
        if fo:
            fo.write(u'==> {} <==\n'.format(' '.join(cmd)))
            if verbose:
                fo.write(stdout + u'\n')
        else:
            if verbose:
                print(u'==> {} <==\n'.format(' '.join(cmd)))
                safe_print_unicode(stdout + u'\n')


def hg_source(source_dict, src_dir, hg_cache, verbose):
    ''' Download a source from Mercurial repo. '''
    if verbose:
        stdout = None
        stderr = None
    else:
        FNULL = open(os.devnull, 'wb')
        stdout = FNULL
        stderr = FNULL

    hg_url = source_dict['hg_url']
    if not isdir(hg_cache):
        os.makedirs(hg_cache)
    hg_dn = hg_url.split(':')[-1].replace('/', '_')
    cache_repo = join(hg_cache, hg_dn)
    if isdir(cache_repo):
        check_call_env(['hg', 'pull'], cwd=cache_repo, stdout=stdout, stderr=stderr)
    else:
        check_call_env(['hg', 'clone', hg_url, cache_repo], stdout=stdout, stderr=stderr)
        assert isdir(cache_repo)

    # now clone in to work directory
    update = source_dict.get('hg_tag') or 'tip'
    if verbose:
        print('checkout: %r' % update)

    check_call_env(['hg', 'clone', cache_repo, src_dir], stdout=stdout,
                   stderr=stderr)
    check_call_env(['hg', 'update', '-C', update], cwd=src_dir, stdout=stdout,
                   stderr=stderr)

    if not verbose:
        FNULL.close()

    return src_dir


def svn_source(source_dict, src_dir, svn_cache, verbose=True, timeout=900, locking=True):
    ''' Download a source from SVN repo. '''
    if verbose:
        stdout = None
        stderr = None
    else:
        FNULL = open(os.devnull, 'wb')
        stdout = FNULL
        stderr = FNULL

    def parse_bool(s):
        return str(s).lower().strip() in ('yes', 'true', '1', 'on')

    svn_url = source_dict['svn_url']
    svn_revision = source_dict.get('svn_rev') or 'head'
    svn_ignore_externals = parse_bool(source_dict.get('svn_ignore_externals') or 'no')
    if not isdir(svn_cache):
        os.makedirs(svn_cache)
    svn_dn = svn_url.split(':', 1)[-1].replace('/', '_').replace(':', '_')
    cache_repo = join(svn_cache, svn_dn)
    if svn_ignore_externals:
        extra_args = ['--ignore-externals']
    else:
        extra_args = []
    if isdir(cache_repo):
        check_call_env(['svn', 'up', '-r', svn_revision] + extra_args, cwd=cache_repo,
                       stdout=stdout, stderr=stderr)
    else:
        check_call_env(['svn', 'co', '-r', svn_revision] + extra_args + [svn_url, cache_repo],
                       stdout=stdout, stderr=stderr)
        assert isdir(cache_repo)

    # now copy into work directory
    copy_into(cache_repo, src_dir, timeout, symlinks=True, locking=locking)

    if not verbose:
        FNULL.close()

    return src_dir


def get_repository_info(recipe_path):
    """This tries to get information about where a recipe came from.  This is different
    from the source - you can have a recipe in svn that gets source via git."""
    try:
        if exists(join(recipe_path, ".git")):
            origin = check_output_env(["git", "config", "--get", "remote.origin.url"],
                                      cwd=recipe_path)
            rev = check_output_env(["git", "rev-parse", "HEAD"], cwd=recipe_path)
            return "Origin {}, commit {}".format(origin, rev)
        elif isdir(join(recipe_path, ".hg")):
            origin = check_output_env(["hg", "paths", "default"], cwd=recipe_path)
            rev = check_output_env(["hg", "id"], cwd=recipe_path).split()[0]
            return "Origin {}, commit {}".format(origin, rev)
        elif isdir(join(recipe_path, ".svn")):
            info = check_output_env(["svn", "info"], cwd=recipe_path)
            info = info.decode("utf-8")  # Py3 returns a byte string, but re needs unicode or str.
            server = re.search("Repository Root: (.*)$", info, flags=re.M).group(1)
            revision = re.search("Revision: (.*)$", info, flags=re.M).group(1)
            return "{}, Revision {}".format(server, revision)
        else:
            return "{}, last modified {}".format(recipe_path,
                                             time.ctime(os.path.getmtime(
                                                 join(recipe_path, "meta.yaml"))))
    except CalledProcessError:
        get_logger(__name__).debug("Failed to checkout source in " + recipe_path)
        return "{}, last modified {}".format(recipe_path,
                                             time.ctime(os.path.getmtime(
                                                 join(recipe_path, "meta.yaml"))))


def _ensure_unix_line_endings(path, dest=None):
    """Replace windows line endings with Unix.  Return path to modified file."""
    if not dest:
        dest = os.path.join(tempfile.mkdtemp(), os.path.basename(path) + "_lf")
    with open(path, "rb") as inputfile:
        with open(dest, "wb") as outputfile:
            for line in inputfile:
                outputfile.write(line.replace(b"\r\n", b"\n"))
    return dest


def _ensure_win_line_endings(path, dest=None):
    """Replace unix line endings with win.  Return path to modified file."""
    if not dest:
        dest = os.path.join(tempfile.mkdtemp(), os.path.basename(path) + "_lf")
    with open(path, "rb") as inputfile:
        with open(dest, "wb") as outputfile:
            for line in inputfile:
                outputfile.write(line.replace(b"\n", b"\r\n"))
    return dest


def _guess_patch_strip_level(filesstr, src_dir):
    """ Determine the patch strip level automatically. """
    maxlevel = None
    files = {filestr.encode(errors='ignore') for filestr in filesstr}
    src_dir = src_dir.encode(errors='ignore')
    for file in files:
        numslash = file.count(b'/')
        maxlevel = numslash if maxlevel is None else min(maxlevel, numslash)
    if maxlevel == 0:
        patchlevel = 0
        guessed = False
    else:
        histo = {i: 0 for i in range(maxlevel + 1)}
        for file in files:
            parts = file.split(b'/')
            for level in range(maxlevel + 1):
                if os.path.exists(join(src_dir, *parts[-len(parts) + level:])):
                    histo[level] += 1
                # TODO :: Detect file creation and add 1 when we do not have a file but
                #         we wish to create one. If the file already exists we should not
                #         add 1.
        order = sorted(histo, key=histo.get, reverse=True)
        min_histo = 0
        if histo[order[0]] == histo[order[1]]:
            if histo[order[0]] == 0:
                # No files were detected at all. Assume patch level is 1.
                log.warning("Unable to determine patch level as no files matched, assuming 1")
                return 1, True
            else:
                log.warning("Unable to determine patch level accurately, guessing least deep above 0")
                guessed = True
                min_histo = 1
                del histo[0]
        else:
            guessed = False
        patchlevel = min([key for key, value
                          in histo.items() if value == histo[order[min_histo]]])
    return patchlevel, guessed


def _get_patch_file_details(path):
    re_files = re.compile(r'^(?:---|\+\+\+) ([^\n\t]+)')
    files = []
    with io.open(path, errors='ignore') as f:
        files = []
        first_line = True
        is_git_format = True
        for line in f.readlines():
            if first_line and not re.match(r'From [0-9a-f]{40}', line):
                is_git_format = False
            first_line = False
            m = re_files.search(line)
            if m and m.group(1) != '/dev/null':
                files.append(m.group(1))
            elif is_git_format and line.startswith('git') and not line.startswith('git --diff'):
                is_git_format = False
    return (files, is_git_format)


def _patch_attributes_debug(pa, rel_path, build_prefix):
    return "[[ {}{}{}{}{}{}{}{}{}{} ]] - [[ {:>71} ]]".format(
        'R' if pa['reversible'] else '-',
        'A' if pa['applicable'] else '-',
        'Y' if pa['patch_exe'].startswith(build_prefix) else '-',
        'M' if not pa['amalgamated'] else '-',
        'D' if pa['dry_runnable'] else '-',
        str(pa['level']),
        'L' if not pa['level_ambiguous'] else '-',
        'O' if not pa['offsets'] else '-',
        'V' if not pa['fuzzy'] else '-',
        'E' if not pa['stderr'] else '-',
        rel_path[-71:])


def _patch_attributes_debug_print(attributes):
    if len(attributes):
        print("Patch analysis gives:")
        print("\n".join(attributes))
        print("\nKey:\n")
        print("R :: Reversible                       A :: Applicable\n"
              "Y :: Build-prefix patch in use        M :: Minimal, non-amalgamated\n"
              "D :: Dry-runnable                     N :: Patch level (1 is preferred)\n"
              "L :: Patch level not-ambiguous        O :: Patch applies without offsets\n"
              "V :: Patch applies without fuzz       E :: Patch applies without emitting to stderr\n")


def _get_patch_attributes(path, patch_exe, git_exe, src_dir, submodules, stdout, stderr, retained_tmpdir=None):
    from collections import OrderedDict

    files_list, is_git_format = _get_patch_file_details(path)
    files = set(files_list)
    amalgamated = False
    if len(files_list) != len(files):
        amalgamated = True
    strip_level, strip_level_guessed = _guess_patch_strip_level(files, src_dir)
    submodule = None
    reldir = ''
    if git_exe and is_git_format:
        patching_exe = git_exe
        if strip_level > 0:
            files2 = []
            for a_file in files:
                # For a submodule we'll have a strip level of 2. The first strip is the standard
                # git a/ or b/ prefix proxies for the containing folder. But we could have a
                # submodule nested in a more deep folder, e.g.:
                # git submodule add ../submodule submodule/in/deeper/location
                folders = a_file.split('/')
                stripped_reldir = '/'.join(folders[0:1])
                if stripped_reldir and a_file.startswith(stripped_reldir + '/'):
                    files2.append(a_file[len(stripped_reldir)+1:])
                else:
                    files2.append(a_file)
        else:
            files2 = list(files)

    # Even if we are not using git for patching here (this should be per-recipe configurable)
    # we can still use it to hint our patching process.
    # original_strip_level = strip_level
    if len(submodules) and strip_level > 0:
        # We allow the submodule infix (with an extra a or b) to be specified as an extr
        # level for git patches. This may not always be correct. It could be one when we
        # let the submodule into that patch file names. Qt5 is an example of that. The
        # goal is that patch -p can also be used for these patches should we prefer to.
        # We may want to add 1
        for file in files2:
            if reldir:
                break
            for sm_path, sm_attribs in submodules.items():
                if file.startswith(sm_attribs['path']+'/'):
                    submodule = {sm_path: sm_attribs}
                    reldir = submodule[sm_path]['path']
                    strip_level = (reldir.count('/') + 1) if reldir else 0
                    break
        # This can be used to force patch to be used instead of git. Both must always work.
        # TODO :: User selection of this and a test that using either git or patch to do the
        #         job succeeds.
        # reldir = ''
        # strip_level = original_strip_level
        # patching_exe = patch_exe
    else:
        reldir = ''
        patching_exe = patch_exe
        files = set(f.split('/', strip_level)[-1] for f in files)
    if not patching_exe:
        log.error("No patching program (tried patch and git).")

    # Defaults
    result = {'patch': path,
              'reldir': reldir,
              'submodule': submodule,
              'files': files,
              'patch_exe': patching_exe,
              'format': 'git' if is_git_format else 'generic',
              # If these remain 'unknown' we had no patch program to test with.
              'dry_runnable': None,
              'applicable': None,
              'reversible': None,
              'amalgamated': amalgamated,
              'offsets': None,
              'fuzzy': None,
              'stderr': None,
              'level': strip_level,
              'level_ambiguous': strip_level_guessed,
              'args': []}

    crlf = False
    lf = False
    with io.open(path, errors='ignore') as f:
        _content = f.read()
        for line in _content.split('\n'):
            if line.startswith((' ', '+', '-')):
                if line.endswith('\r'):
                    crlf = True
                else:
                    lf = True
    result['line_endings'] = 'mixed' if (crlf and lf) else 'crlf' if crlf else 'lf'


    class noop_context(object):
        value = None

        def __init__(self, value):
            self.value = value

        def __enter__(self):
            return self.value

        def __exit__(self, exc, value, tb):
            return

    fmts = OrderedDict(native=['--binary'],
                          lf=[],
                          crlf=[])
    if patch_exe:
        # Good, we have a patch executable so we can perform some checks:
        with noop_context(retained_tmpdir) if retained_tmpdir else TemporaryDirectory() as tmpdir:
            # Make all the fmts.
            result['patches'] = {}
            for fmt, _ in fmts.items():
                new_patch = os.path.join(tmpdir, os.path.basename(path) + '.{}'.format(fmt))
                if fmt == 'native':
                    try:
                        shutil.copy2(path, new_patch)
                    except:
                        shutil.copy(path, new_patch)
                elif fmt == 'lf':
                    _ensure_unix_line_endings(path, new_patch)
                elif fmt == 'crlf':
                    _ensure_win_line_endings(path, new_patch)
                result['patches'][fmt] = new_patch

            tmp_src_dir = os.path.join(tmpdir, 'src_dir')

            def copy_to_be_patched_files(src_dir, tmp_src_dir, files):
                try:
                    shutil.rmtree(tmp_src_dir)
                except:
                    pass
                for file in files:
                    dst = os.path.join(tmp_src_dir, file)
                    dst_dir = os.path.dirname(dst)
                    try:
                        os.makedirs(dst_dir)
                    except:
                        if not os.path.exists(dst_dir):
                            raise
                    # Patches can create and delete files.
                    if os.path.exists(os.path.join(src_dir, file)):
                        shutil.copy2(os.path.join(src_dir, file), dst)

            copy_to_be_patched_files(src_dir, tmp_src_dir, files)
            checks = OrderedDict(dry_runnable=['--dry-run'],
                                 applicable=[],
                                 reversible=['-R'])
            for check_name, extra_args in checks.items():
                for fmt, fmt_args in fmts.items():
                    patch_args = ['-Np{}'.format(result['level']),
                                  '-i', result['patches'][fmt]] + extra_args + fmt_args
                    try:
                        env = os.environ.copy()
                        env['LC_ALL'] = 'C'
                        from subprocess import Popen, PIPE
                        process = Popen([patch_exe] + patch_args,
                                        cwd=tmp_src_dir,
                                        stdout=PIPE,
                                        stderr=PIPE,
                                        shell=False)
                        output, error = process.communicate()
                        result['offsets'] = b'offset' in output
                        result['fuzzy'] = b'fuzz' in output
                        result['stderr'] = bool(error)
                        if stdout:
                            stdout.write(output)
                        if stderr:
                            stderr.write(error)
                    except Exception as e:
                        print(e)
                        result[check_name] = False
                        pass
                    else:
                        result[check_name] = fmt
                        # Save the first one found.
                        if check_name == 'applicable' and not result['args']:
                            result['args'] = patch_args
                        break

    if not retained_tmpdir and 'patches' in result:
        del result['patches']

    return result


def apply_one_patch(src_dir, recipe_dir, rel_path, config, git_exe=None, submodules=[]):
    path = os.path.join(recipe_dir, rel_path)
    def try_apply_patch(patch, patch_args, cwd, stdout, stderr):
        # An old reference: https://unix.stackexchange.com/a/243748/34459
        #
        # I am worried that '--ignore-whitespace' may be destructive. If so we should
        # avoid passing it, particularly in the initial (most likely to succeed) calls.
        #
        # From here-in I define a 'native' patch as one which has:
        # 1. LF for the patch block metadata.
        # 2. CRLF or LF for the actual patched lines matching those of the source lines.
        #
        # Calls to a raw 'patch' are destructive in various ways:
        # 1. It leaves behind .rej and .orig files
        # 2. If you pass it a patch with incorrect CRLF changes and do not pass --binary and
        #    if any of those blocks *can* be applied, then the whole file gets written out with
        #    LF.  This cannot be reversed either; the text changes will be reversed but not
        #    line-feed changes (since all line-endings get changed, not just those of the of
        #    patched lines)
        # 3. If patching fails, the bits that succeeded remain, so patching is not at all
        #    atomic.
        #
        # We do our best to mitigate this by figuring out how to apply patches against a copy of
        # the tree of the files that it modifies.
        #
        # At the end of the day, either patch or git (if the conditions are right) can be used
        # to finally apply the patches. Git is preferred, but these checks are done with plain
        # old patch anyway. It would be nice not to require patch I suppose but that seems a bit
        # like make-work.
        #
        import tempfile
        temp_name = os.path.join(tempfile.gettempdir(), next(tempfile._get_candidate_names()))
        base_patch_args = ['--no-backup-if-mismatch', '--batch'] + patch_args
        try:
            try_patch_args = base_patch_args[:]
            try_patch_args.append('--dry-run')
            log.debug("dry-run applying with\n{} {}".format(patch, try_patch_args))
            check_call_env([patch] + try_patch_args, cwd=cwd, stdout=stdout, stderr=stderr)
            # You can use this to pretend the patch failed so as to test reversal!
            # raise CalledProcessError(-1, ' '.join([patch] + patch_args))
        except Exception as e:
            raise e
        else:
            check_call_env([patch] + base_patch_args, cwd=cwd, stdout=stdout, stderr=stderr)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    exception = None
    if not isfile(path):
        raise RuntimeError('Error: no such patch: %s' % path)

    if config.verbose:
        stdout = None
        stderr = None
    else:
        FNULL = open(os.devnull, 'wb')
        stdout = FNULL
        stderr = FNULL

    attributes_output = ""
    patch_exe = external.find_executable('patch', config.build_prefix)
    if not len(patch_exe):
        patch_exe = external.find_executable('patch', config.host_prefix)
        if not len(patch_exe):
            patch_exe = ''
    with TemporaryDirectory() as tmpdir:
        patch_attributes = _get_patch_attributes(path, patch_exe, git_exe, src_dir, submodules, stdout, stderr, tmpdir)
        attributes_output += _patch_attributes_debug(patch_attributes, rel_path, config.build_prefix)
        # sub_folder is a deliberately git-agnostic name.
        sub_folder = os.path.join(src_dir, patch_attributes['reldir'])
        apply_with_git = git_exe and patch_attributes['format'] == 'git' and 'git' in patch_attributes['patch_exe']
        if config.verbose:
            print('Applying patch: {} in {} with {}'.format(path, sub_folder, git_exe if apply_with_git else patch_exe))
        if apply_with_git:
            # Prevents git from asking interactive questions,
            # also necessary to achieve sha1 reproducibility;
            # as is --committer-date-is-author-date. By this,
            # we mean a round-trip of git am/git format-patch
            # gives the same file.
            git_env = os.environ
            git_env['GIT_COMMITTER_NAME'] = 'conda-build'
            git_env['GIT_COMMITTER_EMAIL'] = 'conda@conda-build.org'
            # collect the patches on a per-submodule basis.
            check_call_env([git_exe, 'am', '-3', '--committer-date-is-author-date', path],
                           cwd=sub_folder, stdout=stdout, stderr=stderr, env=git_env)
            config.git_commits_since_tag += 1
        else:
            if patch_exe is None or len(patch_exe) == 0:
                errstr = ("""\
            Error:
                Cannot use 'git' (not a git repo and/or patch) and did not find 'patch' in: %s
                You can install 'patch' using apt-get, yum (Linux), Xcode (MacOSX),
                or conda, m2-patch (Windows),
            """ % (os.pathsep.join(external.dir_paths)))
                raise RuntimeError(errstr)
            patch_args = patch_attributes['args']

            if config.verbose:
                print('Applying patch: {} with args:\n{}'.format(path, patch_args))

            try:
                try_apply_patch(patch_exe, patch_args,
                                cwd=sub_folder, stdout=stdout, stderr=stderr)
            except Exception as e:
                exception = e
        if exception:
            raise exception
    return attributes_output


def apply_patch(src_dir, patch, config, git_exe=None):
    apply_one_patch(src_dir, os.path.dirname(patch), os.path.basename(patch), config, git_exe=git_exe)


def provide(metadata):
    """
    given a recipe_dir:
      - download (if necessary)
      - unpack
      - apply patches (if any)
    """
    meta = metadata.get_section('source')
    if not os.path.isdir(metadata.config.build_folder):
        os.makedirs(metadata.config.build_folder)
    git_exe = None

    if hasattr(meta, 'keys'):
        dicts = [meta]
    else:
        dicts = meta

    try:
        for source_dict in dicts:
            folder = source_dict.get('folder')
            src_dir = os.path.join(metadata.config.work_dir, folder if folder else '')
            if any(k in source_dict for k in ('fn', 'url')):
                unpack(source_dict, src_dir, metadata.config.src_cache, recipe_path=metadata.path,
                    croot=metadata.config.croot, verbose=metadata.config.verbose,
                    timeout=metadata.config.timeout, locking=metadata.config.locking)
            elif 'git_url' in source_dict:
                git_exe = git_source(source_dict, metadata.config.git_cache, src_dir, metadata.path,
                                     verbose=metadata.config.verbose)
            # build to make sure we have a work directory with source in it. We
            #    want to make sure that whatever version that is does not
            #    interfere with the test we run next.
            elif 'hg_url' in source_dict:
                hg_source(source_dict, src_dir, metadata.config.hg_cache,
                        verbose=metadata.config.verbose)
            elif 'svn_url' in source_dict:
                svn_source(source_dict, src_dir, metadata.config.svn_cache,
                        verbose=metadata.config.verbose, timeout=metadata.config.timeout,
                        locking=metadata.config.locking)
            elif 'path' in source_dict:
                source_path = os.path.expanduser(source_dict['path'])
                path = normpath(abspath(join(metadata.path, source_path)))
                path_via_symlink = 'path_via_symlink' in source_dict
                if path_via_symlink and not folder:
                    print("WARNING: `path_via_symlink` is too dangerous without specifying a folder,\n"
                          "  conda could end up changing - or deleting - your local source code!\n"
                          "  Going to make copies instead. When using `path_via_symlink` you should\n"
                          "  also take care to run the build outside of your local source code folder(s)\n"
                          "  unless that is your intention.")
                    path_via_symlink = False
                    sys.exit(1)
                if path_via_symlink:
                    src_dir_symlink = os.path.dirname(src_dir)
                    if not isdir(src_dir_symlink):
                        os.makedirs(src_dir_symlink)
                    if metadata.config.verbose:
                        print("Creating sybmolic link pointing to %s at %s" % (path, src_dir))
                    os.symlink(path, src_dir)
                else:
                    if metadata.config.verbose:
                        print("Copying %s to %s" % (path, src_dir))
                    # careful here: we set test path to be outside of conda-build root in setup.cfg.
                    #    If you don't do that, this is a recursive function
                    copy_into(path, src_dir, metadata.config.timeout, symlinks=True,
                            locking=metadata.config.locking, clobber=True)
            else:  # no source
                if not isdir(src_dir):
                    os.makedirs(src_dir)

            patches = ensure_list(source_dict.get('patches', []))
            patch_attributes_output = []
            submodules = {}
            if git_exe:
                submodules_list = check_output_env([git_exe, 'submodule', 'status', '--recursive'],
                                                   cwd=src_dir).decode('utf-8').splitlines()
                reggie = re.compile(' ([0-9a-f]*) (\S+) \((\S+)\)')
                submodules = {}
                for sm in submodules_list:
                    m = reggie.match(sm)
                    groups = m.groups()
                    submodules[groups[1]] = {'sha1': groups[0],
                                             'path': groups[1],
                                             'branch': groups[2]}
                if len(submodules):
                    # We sort by longest checkout path so we find deepest submodule that matches first.
                    # e.g. you could have sub1 and sub1/sub1 as infixes (a/sub1, a/sub1/sub1) and both would
                    # match. For a patch to a file listed as a/sub1/sub1, we want that to match in the
                    # deeper folder (sub1/sub1) and not in the less deep one (sub1).
                    from collections import OrderedDict
                    submodules = OrderedDict(sorted(submodules.items(), key=lambda x: -len(x[1]['path'])))

            for patch in patches:
                patch_attributes_output += [apply_one_patch(src_dir, metadata.path, patch, metadata.config,
                                                            git_exe, submodules)]
            _patch_attributes_debug_print(patch_attributes_output)

    except CalledProcessError:
        shutil.move(metadata.config.work_dir, metadata.config.work_dir + '_failed_provide')
        raise

    return metadata.config.work_dir
