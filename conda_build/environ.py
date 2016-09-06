from __future__ import absolute_import, division, print_function

import logging
import multiprocessing
import os
import sys
import warnings
from collections import defaultdict
from os.path import join, normpath
import subprocess

# noqa here because PY3 is used only on windows, and trips up flake8 otherwise.
from .conda_interface import text_type, PY3  # noqa
from .conda_interface import root_dir, cc

from conda_build.os_utils import external
from conda_build import source
from conda_build import utils
from conda_build.features import feature_list
from conda_build.utils import prepend_bin_path

log = logging.getLogger(__file__)


def get_perl_ver(config):
    return str(config.CONDA_PERL)


def get_lua_ver(config):
    return str(config.CONDA_LUA)


def get_py_ver(config):
    return '.'.join(str(config.CONDA_PY))


def get_npy_ver(config):
    if config.CONDA_NPY:
        # Convert int -> string, e.g.
        #   17 -> '1.7'
        #   110 -> '1.10'
        conda_npy = str(config.CONDA_NPY)
        return conda_npy[0] + '.' + conda_npy[1:]
    return ''


def get_stdlib_dir(config):
    return join(config.build_prefix, 'Lib' if sys.platform == 'win32' else
                'lib/python%s' % get_py_ver(config))


def get_lua_include_dir(config):
    return join(config.build_prefix, "include")


def get_sp_dir(config):
    return join(get_stdlib_dir(config), 'site-packages')


def verify_git_repo(git_dir, git_url, config, expected_rev='HEAD'):
    env = os.environ.copy()
    if config.verbose:
        stderr = None
    else:
        FNULL = open(os.devnull, 'w')
        stderr = FNULL
        log.setLevel(logging.ERROR)

    if not expected_rev:
        return False

    OK = True

    env['GIT_DIR'] = git_dir
    try:
        # Verify current commit matches expected commit
        current_commit = subprocess.check_output(["git", "log", "-n1", "--format=%H"],
                                      env=env, stderr=stderr)
        current_commit = current_commit.decode('utf-8')
        expected_tag_commit = subprocess.check_output(["git", "log", "-n1", "--format=%H",
                                            expected_rev],
                                            env=env, stderr=stderr)
        expected_tag_commit = expected_tag_commit.decode('utf-8')

        if current_commit != expected_tag_commit:
            return False

        # Verify correct remote url. Need to find the git cache directory,
        # and check the remote from there.
        cache_details = subprocess.check_output(["git", "remote", "-v"], env=env,
                                     stderr=stderr)
        cache_details = cache_details.decode('utf-8')
        cache_dir = cache_details.split('\n')[0].split()[1]

        if not isinstance(cache_dir, str):
            # On Windows, subprocess env can't handle unicode.
            cache_dir = cache_dir.encode(sys.getfilesystemencoding() or 'utf-8')

        try:
            remote_details = subprocess.check_output(["git", "--git-dir", cache_dir,
                                                      "remote", "-v"],
                                                     env=env, stderr=stderr)
        except subprocess.CalledProcessError:
            if sys.platform == 'win32' and cache_dir.startswith('/'):
                cache_dir = utils.convert_unix_path_to_win(cache_dir)
            remote_details = subprocess.check_output(["git", "--git-dir", cache_dir,
                                                      "remote", "-v"],
                                                     env=env, stderr=stderr)
        remote_details = remote_details.decode('utf-8')
        remote_url = remote_details.split('\n')[0].split()[1]

        # on windows, remote URL comes back to us as cygwin or msys format.  Python doesn't
        # know how to normalize it.  Need to convert it to a windows path.
        if sys.platform == 'win32' and remote_url.startswith('/'):
            remote_url = utils.convert_unix_path_to_win(git_url)

        if os.path.exists(remote_url):
            # Local filepaths are allowed, but make sure we normalize them
            remote_url = normpath(remote_url)

        # If the current source directory in conda-bld/work doesn't match the user's
        # metadata git_url or git_rev, then we aren't looking at the right source.
        if not os.path.isdir(remote_url) and remote_url.lower() != git_url.lower():
            log.debug("remote does not match git_url")
            log.debug("Remote: " + remote_url.lower())
            log.debug("git_url: " + git_url.lower())
            OK = False
    except subprocess.CalledProcessError as error:
        log.warn("Error obtaining git information in verify_git_repo.  Error was: ")
        log.warn(str(error))
        OK = False
    finally:
        if not config.verbose:
            FNULL.close()
    return OK


def get_git_info(repo, config):
    """
    Given a repo to a git repo, return a dictionary of:
      GIT_DESCRIBE_TAG
      GIT_DESCRIBE_NUMBER
      GIT_DESCRIBE_HASH
      GIT_FULL_HASH
      GIT_BUILD_STR
    from the output of git describe.
    :return:
    """
    d = {}

    if config.verbose:
        stderr = None
    else:
        FNULL = open(os.devnull, 'w')
        stderr = FNULL
        log.setLevel(logging.ERROR)

    # grab information from describe
    env = os.environ.copy()
    env['GIT_DIR'] = repo
    keys = ["GIT_DESCRIBE_TAG", "GIT_DESCRIBE_NUMBER", "GIT_DESCRIBE_HASH"]

    try:
        output = subprocess.check_output(["git", "describe", "--tags", "--long", "HEAD"],
                                         env=env, cwd=os.path.dirname(repo),
                                         stderr=stderr).splitlines()[0]
        output = output.decode('utf-8')

        parts = output.rsplit('-', 2)
        if len(parts) == 3:
            d.update(dict(zip(keys, parts)))

        # get the _full_ hash of the current HEAD
        output = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                         env=env, cwd=os.path.dirname(repo),
                                         stderr=stderr).splitlines()[0]
        output = output.decode('utf-8')

        d['GIT_FULL_HASH'] = output
        # set up the build string
        if "GIT_DESCRIBE_NUMBER" in d and "GIT_DESCRIBE_HASH" in d:
            d['GIT_BUILD_STR'] = '{}_{}'.format(d["GIT_DESCRIBE_NUMBER"],
                                                d["GIT_DESCRIBE_HASH"])

        # issues on Windows with the next line of the command prompt being recorded here.
        assert not any("\n" in value for value in d.values())

    except subprocess.CalledProcessError as error:
        log.warn("Error obtaining git information in get_git_info.  Error was: ")
        log.warn(str(error))
    return d


def get_hg_build_info(repo):
    env = os.environ.copy()
    env['HG_DIR'] = repo
    env = {str(key): str(value) for key, value in env.items()}

    d = {}
    cmd = ["hg", "log", "--template",
           "{rev}|{node|short}|{latesttag}|{latesttagdistance}|{branch}",
           "--rev", "."]
    output = subprocess.check_output(cmd, env=env, cwd=os.path.dirname(repo))
    output = output.decode('utf-8')
    rev, short_id, tag, distance, branch = output.split('|')
    if tag != 'null':
        d['HG_LATEST_TAG'] = tag
    if branch == "":
        branch = 'default'
    d['HG_BRANCH'] = branch
    d['HG_NUM_ID'] = rev
    d['HG_LATEST_TAG_DISTANCE'] = distance
    d['HG_SHORT_ID'] = short_id
    d['HG_BUILD_STR'] = '{}_{}'.format(d['HG_NUM_ID'], d['HG_SHORT_ID'])
    return d


def get_dict(config, m=None, prefix=None):
    if not prefix:
        prefix = config.build_prefix

    # conda-build specific vars
    d = conda_build_vars(prefix, config)

    # languages
    d.update(python_vars(config))
    d.update(perl_vars(config))
    d.update(lua_vars(config))

    if m:
        d.update(meta_vars(m, config))

    # system
    d.update(system_vars(d, prefix, config))

    # features
    d.update({feat.upper(): str(int(value)) for feat, value in
              feature_list})

    return d


def conda_build_vars(prefix, config):
    return {
        'CONDA_BUILD': '1',
        'PYTHONNOUSERSITE': '1',
        'CONDA_DEFAULT_ENV': config.build_prefix,
        'ARCH': str(config.bits),
        'PREFIX': prefix,
        'SYS_PREFIX': sys.prefix,
        'SYS_PYTHON': sys.executable,
        'SUBDIR': config.subdir,
        'SRC_DIR': source.get_dir(config),
        'HTTPS_PROXY': os.getenv('HTTPS_PROXY', ''),
        'HTTP_PROXY': os.getenv('HTTP_PROXY', ''),
        'DIRTY': '1' if config.dirty else '',
        'ROOT': root_dir,
    }


def python_vars(config):
    d = {
        'PYTHON': config.build_python,
        'PY3K': str(config.PY3K),
        'STDLIB_DIR': get_stdlib_dir(config),
        'SP_DIR': get_sp_dir(config),
        'PY_VER': get_py_ver(config),
        'CONDA_PY': str(config.CONDA_PY),
    }
    # Only define these variables if '--numpy=X.Y' was provided,
    # otherwise any attempt to use them should be an error.
    if get_npy_ver(config):
        d['NPY_VER'] = get_npy_ver(config)
        d['CONDA_NPY'] = str(config.CONDA_NPY)
    return d


def perl_vars(config):
    return {
        'PERL_VER': get_perl_ver(config),
    }


def lua_vars(config):
    lua = config.build_lua
    if lua:
        return {
            'LUA': lua,
            'LUA_INCLUDE_DIR': get_lua_include_dir(config),
            'LUA_VER': get_lua_ver(config),
        }
    else:
        return {}


def meta_vars(meta, config):
    d = {}
    for var_name in meta.get_value('build/script_env', []):
        value = os.getenv(var_name)
        if value is None:
            warnings.warn(
                "The environment variable '%s' is undefined." % var_name,
                UserWarning
            )
        else:
            d[var_name] = value

    git_dir = join(source.get_dir(config), '.git')
    hg_dir = join(source.get_dir(config), '.hg')

    if not isinstance(git_dir, str):
        # On Windows, subprocess env can't handle unicode.
        git_dir = git_dir.encode(sys.getfilesystemencoding() or 'utf-8')

    if external.find_executable('git', config.build_prefix) and os.path.exists(git_dir):
        git_url = meta.get_value('source/git_url')

        if os.path.exists(git_url):
            if sys.platform == 'win32':
                git_url = utils.convert_unix_path_to_win(git_url)
            # If git_url is a relative path instead of a url, convert it to an abspath
            git_url = normpath(join(meta.path, git_url))

        _x = False

        if git_url:
            _x = verify_git_repo(git_dir,
                                 git_url,
                                 config,
                                 meta.get_value('source/git_rev', 'HEAD'))

        if _x or meta.get_value('source/path'):
            d.update(get_git_info(git_dir, config))

    elif external.find_executable('hg', config.build_prefix) and os.path.exists(hg_dir):
        d.update(get_hg_build_info(hg_dir))

    d['PKG_NAME'] = meta.name()
    d['PKG_VERSION'] = meta.version()
    d['PKG_BUILDNUM'] = str(meta.build_number())
    d['PKG_BUILD_STRING'] = str(meta.build_id())
    d['RECIPE_DIR'] = meta.path
    return d


def get_cpu_count():
    if sys.platform == "darwin":
        # multiprocessing.cpu_count() is not reliable on OSX
        # See issue #645 on github.com/conda/conda-build
        out, _ = subprocess.Popen('sysctl -n hw.logicalcpu', shell=True,
                         stdout=subprocess.PIPE).communicate()
        return out.decode('utf-8').strip()
    else:
        try:
            return str(multiprocessing.cpu_count())
        except NotImplementedError:
            return "1"


def windows_vars(prefix):
    library_prefix = join(prefix, 'Library')
    drive, tail = prefix.split(':')
    return {
        'SCRIPTS': join(prefix, 'Scripts'),
        'LIBRARY_PREFIX': library_prefix,
        'LIBRARY_BIN': join(library_prefix, 'bin'),
        'LIBRARY_INC': join(library_prefix, 'include'),
        'LIBRARY_LIB': join(library_prefix, 'lib'),
        'R': join(prefix, 'Scripts', 'R.exe'),
        'CYGWIN_PREFIX': ''.join(('/cygdrive/', drive.lower(), tail.replace('\\', '/')))
    }


def unix_vars(prefix):
    return {
        'HOME': os.getenv('HOME', 'UNKNOWN'),
        'PKG_CONFIG_PATH': join(prefix, 'lib', 'pkgconfig'),
        'CMAKE_GENERATOR': 'Unix Makefiles',
        'R': join(prefix, 'bin', 'R'),
    }


def osx_vars(compiler_vars, config):
    OSX_ARCH = 'i386' if config.bits == 32 else 'x86_64'
    compiler_vars['CFLAGS'] += ' -arch {0}'.format(OSX_ARCH)
    compiler_vars['CXXFLAGS'] += ' -arch {0}'.format(OSX_ARCH)
    compiler_vars['LDFLAGS'] += ' -arch {0}'.format(OSX_ARCH)
    # 10.7 install_name_tool -delete_rpath causes broken dylibs, I will revisit this ASAP.
    # rpath = ' -Wl,-rpath,%(PREFIX)s/lib' % d # SIP workaround, DYLD_* no longer works.
    # d['LDFLAGS'] = ldflags + rpath + ' -arch %(OSX_ARCH)s' % d
    return {
        'OSX_ARCH': OSX_ARCH,
        'MACOSX_DEPLOYMENT_TARGET': '10.7',
    }


def linux_vars(compiler_vars, prefix, config):
    compiler_vars['LD_RUN_PATH'] = prefix + '/lib'
    if config.bits == 32:
        compiler_vars['CFLAGS'] += ' -m32'
        compiler_vars['CXXFLAGS'] += ' -m32'
    return {}


def system_vars(env_dict, prefix, config):
    d = dict()
    compiler_vars = defaultdict(text_type)

    if 'MAKEFLAGS' in os.environ:
        d['MAKEFLAGS'] = os.environ['MAKEFLAGS']

    if 'CPU_COUNT' in os.environ:
        d['CPU_COUNT'] = os.environ['CPU_COUNT']
    else:
        d['CPU_COUNT'] = get_cpu_count()

    if "LANG" in os.environ:
        d['LANG'] = os.environ['LANG']
    d['PATH'] = os.environ.copy()['PATH']
    if not config.activate:
        d = prepend_bin_path(d, prefix)

    if sys.platform == 'win32':
        d.update(windows_vars(prefix))
    else:
        d.update(unix_vars(prefix))

    if sys.platform == 'darwin':
        d.update(osx_vars(compiler_vars, config))
    elif sys.platform.startswith('linux'):
        d.update(linux_vars(compiler_vars, prefix, config))

    # make sure compiler_vars get appended to anything already set, including build/script_env
    for key in compiler_vars:
        if key in env_dict:
            compiler_vars[key] += env_dict[key]
    d.update(compiler_vars)

    return d


if __name__ == '__main__':
    e = get_dict(cc)
    for k in sorted(e):
        assert isinstance(e[k], str), k
        print('%s=%s' % (k, e[k]))
