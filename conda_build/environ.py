from __future__ import absolute_import, division, print_function

import json
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
from .conda_interface import root_dir

from conda_build.os_utils import external
from conda_build import utils
from conda_build.features import feature_list
from conda_build.utils import prepend_bin_path, ensure_list


def get_perl_ver(config):
    return str(config.CONDA_PERL)


def get_lua_ver(config):
    return config.CONDA_LUA


def get_py_ver(config):
    return '.'.join(str(config.CONDA_PY))


def get_r_ver(config):
    return config.CONDA_R


def get_npy_ver(config):
    if config.CONDA_NPY:
        # Convert int -> string, e.g.
        #   17 -> '1.7'
        #   110 -> '1.10'
        conda_npy = str(config.CONDA_NPY)
        return conda_npy[0] + '.' + conda_npy[1:]
    return ''


def get_lua_include_dir(config):
    return join(config.build_prefix, "include")


def verify_git_repo(git_dir, git_url, config, expected_rev='HEAD'):
    env = os.environ.copy()
    log = logging.getLogger(__name__)
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
        current_commit = utils.check_output_env(["git", "log", "-n1", "--format=%H"],
                                                env=env, stderr=stderr)
        current_commit = current_commit.decode('utf-8')
        expected_tag_commit = utils.check_output_env(["git", "log", "-n1", "--format=%H",
                                                      expected_rev],
                                                     env=env, stderr=stderr)
        expected_tag_commit = expected_tag_commit.decode('utf-8')

        if current_commit != expected_tag_commit:
            return False

        # Verify correct remote url. Need to find the git cache directory,
        # and check the remote from there.
        cache_details = utils.check_output_env(["git", "remote", "-v"], env=env,
                                               stderr=stderr)
        cache_details = cache_details.decode('utf-8')
        cache_dir = cache_details.split('\n')[0].split()[1]

        if not isinstance(cache_dir, str):
            # On Windows, subprocess env can't handle unicode.
            cache_dir = cache_dir.encode(sys.getfilesystemencoding() or 'utf-8')

        try:
            remote_details = utils.check_output_env(["git", "--git-dir", cache_dir,
                                                     "remote", "-v"],
                                                     env=env, stderr=stderr)
        except subprocess.CalledProcessError:
            if sys.platform == 'win32' and cache_dir.startswith('/'):
                cache_dir = utils.convert_unix_path_to_win(cache_dir)
            remote_details = utils.check_output_env(["git", "--git-dir", cache_dir,
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
    log = logging.getLogger(__name__)

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
        output = utils.check_output_env(["git", "describe", "--tags", "--long", "HEAD"],
                                        env=env, cwd=os.path.dirname(repo),
                                        stderr=stderr).splitlines()[0]
        output = output.decode('utf-8')
        parts = output.rsplit('-', 2)
        if len(parts) == 3:
            d.update(dict(zip(keys, parts)))
    except subprocess.CalledProcessError:
        log.warn("Failed to obtain git tag information.  Are you using annotated tags?")

    try:
        # get the _full_ hash of the current HEAD
        output = utils.check_output_env(["git", "rev-parse", "HEAD"],
                                         env=env, cwd=os.path.dirname(repo),
                                         stderr=stderr).splitlines()[0]
        output = output.decode('utf-8')

        d['GIT_FULL_HASH'] = output
    except subprocess.CalledProcessError as error:
        log.warn("Error obtaining git commit information.  Error was: ")
        log.warn(str(error))

    # set up the build string
    if "GIT_DESCRIBE_NUMBER" in d and "GIT_DESCRIBE_HASH" in d:
        d['GIT_BUILD_STR'] = '{}_{}'.format(d["GIT_DESCRIBE_NUMBER"],
                                            d["GIT_DESCRIBE_HASH"])

    # issues on Windows with the next line of the command prompt being recorded here.
    assert not any("\n" in value for value in d.values())
    return d


def get_hg_build_info(repo):
    env = os.environ.copy()
    env['HG_DIR'] = repo
    env = {str(key): str(value) for key, value in env.items()}

    d = {}
    cmd = ["hg", "log", "--template",
           "{rev}|{node|short}|{latesttag}|{latesttagdistance}|{branch}",
           "--rev", "."]
    output = utils.check_output_env(cmd, env=env, cwd=os.path.dirname(repo))
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
    d.update(python_vars(config, prefix))
    d.update(perl_vars(config, prefix))
    d.update(lua_vars(config, prefix))
    d.update(r_vars(config, prefix))

    if m:
        d.update(meta_vars(m, config))

    # system
    d.update(system_vars(d, prefix, config))

    # features
    d.update({feat.upper(): str(int(value)) for feat, value in
              feature_list})

    return d


def conda_build_vars(prefix, config):
    src_dir = config.test_dir if os.path.basename(prefix)[:2] == '_t' else config.work_dir
    return {
        'CONDA_BUILD': '1',
        'PYTHONNOUSERSITE': '1',
        'CONDA_DEFAULT_ENV': config.build_prefix,
        'ARCH': str(config.arch),
        'PREFIX': prefix,
        'SYS_PREFIX': sys.prefix,
        'SYS_PYTHON': sys.executable,
        'SUBDIR': config.subdir,
        'SRC_DIR': src_dir,
        'HTTPS_PROXY': os.getenv('HTTPS_PROXY', ''),
        'HTTP_PROXY': os.getenv('HTTP_PROXY', ''),
        'DIRTY': '1' if config.dirty else '',
        'ROOT': root_dir,
    }


def python_vars(config, prefix):
    vars_ = {
            'CONDA_PY': str(config.CONDA_PY),
            'PY3K': str(config.PY3K),
            'PY_VER': get_py_ver(config),
            }
    if os.path.isfile(config.python_bin(prefix)):
        vars_.update({
            'PYTHON': config.python_bin(prefix),
            'STDLIB_DIR': utils.get_stdlib_dir(prefix),
            'SP_DIR': utils.get_site_packages(prefix),
        })
    # Only define these variables if '--numpy=X.Y' was provided,
    # otherwise any attempt to use them should be an error.
    if get_npy_ver(config):
        vars_['NPY_VER'] = get_npy_ver(config)
        vars_['CONDA_NPY'] = str(config.CONDA_NPY)
    return vars_


def perl_vars(config, prefix):
    vars_ = {
            'PERL_VER': get_perl_ver(config),
            'CONDA_PERL': str(config.CONDA_PERL),
             }
    if os.path.isfile(config.perl_bin(prefix)):
        vars_.update({
            'PERL': config.perl_bin(prefix),
        })
    return vars_


def lua_vars(config, prefix):
    vars_ = {
            'LUA_VER': get_lua_ver(config),
            'CONDA_LUA': str(config.CONDA_LUA),
             }
    lua = config.lua_bin(prefix)
    if os.path.isfile(lua):
        vars_.update({
            'LUA': lua,
            'LUA_INCLUDE_DIR': get_lua_include_dir(config),
        })
    return vars_


def r_vars(config, prefix):
    vars_ = {
            'R_VER': get_r_ver(config),
            'CONDA_R': str(config.CONDA_R),
            }
    r = config.r_bin(prefix)
    if os.path.isfile(r):
        vars_.update({
            'R': r,
        })
    return vars_


def meta_vars(meta, config):
    d = {}
    for var_name in ensure_list(meta.get_value('build/script_env', [])):
        value = os.getenv(var_name)
        if value is None:
            warnings.warn(
                "The environment variable '%s' is undefined." % var_name,
                UserWarning
            )
        else:
            d[var_name] = value

    git_dir = join(config.work_dir, '.git')
    hg_dir = join(config.work_dir, '.hg')

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

    # use `get_value` to prevent early exit while name is still unresolved during rendering
    d['PKG_NAME'] = meta.get_value('package/name')
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


def get_shlib_ext():
    # Return the shared library extension.
    if sys.platform == 'win32':
        return '.dll'
    elif sys.platform == 'darwin':
        return '.dylib'
    elif sys.platform.startswith('linux'):
        return '.so'
    else:
        raise NotImplementedError(sys.platform)


def windows_vars(prefix):
    library_prefix = join(prefix, 'Library')
    drive, tail = prefix.split(':')
    return {
        'SCRIPTS': join(prefix, 'Scripts'),
        'LIBRARY_PREFIX': library_prefix,
        'LIBRARY_BIN': join(library_prefix, 'bin'),
        'LIBRARY_INC': join(library_prefix, 'include'),
        'LIBRARY_LIB': join(library_prefix, 'lib'),
        'CYGWIN_PREFIX': ''.join(('/cygdrive/', drive.lower(), tail.replace('\\', '/'))),
        # see https://en.wikipedia.org/wiki/Environment_variable#Default_values
        'ALLUSERSPROFILE': os.getenv('ALLUSERSPROFILE'),
        'APPDATA': os.getenv('APPDATA'),
        'CommonProgramFiles': os.getenv('CommonProgramFiles'),
        'CommonProgramFiles(x86)': os.getenv('CommonProgramFiles(x86)'),
        'CommonProgramW6432': os.getenv('CommonProgramW6432'),
        'COMPUTERNAME': os.getenv('COMPUTERNAME'),
        'ComSpec': os.getenv('ComSpec'),
        'HOMEDRIVE': os.getenv('HOMEDRIVE'),
        'HOMEPATH': os.getenv('HOMEPATH'),
        'LOCALAPPDATA': os.getenv('LOCALAPPDATA'),
        'LOGONSERVER': os.getenv('LOGONSERVER'),
        'NUMBER_OF_PROCESSORS': os.getenv('NUMBER_OF_PROCESSORS'),
        'PATHEXT': os.getenv('PATHEXT'),
        'ProgramData': os.getenv('ProgramData'),
        'ProgramFiles': os.getenv('ProgramFiles'),
        'ProgramFiles(x86)': os.getenv('ProgramFiles(x86)'),
        'ProgramW6432': os.getenv('ProgramW6432'),
        'PROMPT': os.getenv('PROMPT'),
        'PSModulePath': os.getenv('PSModulePath'),
        'PUBLIC': os.getenv('PUBLIC'),
        'SystemDrive': os.getenv('SystemDrive'),
        'SystemRoot': os.getenv('SystemRoot'),
        'TEMP': os.getenv('TEMP'),
        'TMP': os.getenv('TMP'),
        'USERDOMAIN': os.getenv('USERDOMAIN'),
        'USERNAME': os.getenv('USERNAME'),
        'USERPROFILE': os.getenv('USERPROFILE'),
        'windir': os.getenv('windir'),
    }


def unix_vars(prefix):
    return {
        'HOME': os.getenv('HOME', 'UNKNOWN'),
        'PKG_CONFIG_PATH': join(prefix, 'lib', 'pkgconfig'),
        'CMAKE_GENERATOR': 'Unix Makefiles',
    }


def osx_vars(compiler_vars, config):
    OSX_ARCH = 'i386' if config.arch == 32 else 'x86_64'
    MACOSX_DEPLOYMENT_TARGET = os.environ.get('MACOSX_DEPLOYMENT_TARGET', '10.7')

    compiler_vars['CFLAGS'] += ' -arch {0}'.format(OSX_ARCH)
    compiler_vars['CXXFLAGS'] += ' -arch {0}'.format(OSX_ARCH)
    compiler_vars['LDFLAGS'] += ' -arch {0}'.format(OSX_ARCH)
    # 10.7 install_name_tool -delete_rpath causes broken dylibs, I will revisit this ASAP.
    # rpath = ' -Wl,-rpath,%(PREFIX)s/lib' % d # SIP workaround, DYLD_* no longer works.
    # d['LDFLAGS'] = ldflags + rpath + ' -arch %(OSX_ARCH)s' % d
    return {
        'OSX_ARCH': OSX_ARCH,
        'MACOSX_DEPLOYMENT_TARGET': MACOSX_DEPLOYMENT_TARGET,
    }


def linux_vars(compiler_vars, prefix, config):
    compiler_vars['LD_RUN_PATH'] = prefix + '/lib'
    if config.arch == 32:
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

    d['SHLIB_EXT'] = get_shlib_ext()

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


class InvalidEnvironment(Exception):
    pass


# Stripped-down Environment class from conda-tools ( https://github.com/groutr/conda-tools )
# Vendored here to avoid the whole dependency for just this bit.
def _load_json(path):
    with open(path, 'r') as fin:
        x = json.load(fin)
    return x


def _load_all_json(path):
    """
    Load all json files in a directory.  Return dictionary with filenames mapped to json
    dictionaries.
    """
    root, _, files = next(os.walk(path))
    result = {}
    for f in files:
        if f.endswith('.json'):
            result[f] = _load_json(join(root, f))
    return result


class Environment(object):
    def __init__(self, path):
        """
        Initialize an Environment object.

        To reflect changes in the underlying environment, a new Environment object should be
        created.
        """
        self.path = path
        self._meta = join(path, 'conda-meta')
        if os.path.isdir(path) and os.path.isdir(self._meta):
            self._packages = {}
        else:
            raise InvalidEnvironment('Unable to load environment {}'.format(path))

    def _read_package_json(self):
        if not self._packages:
            self._packages = _load_all_json(self._meta)

    def package_specs(self):
        """
        List all package specs in the environment.
        """
        self._read_package_json()
        json_objs = self._packages.values()
        specs = []
        for i in json_objs:
            p, v, b = i['name'], i['version'], i['build']
            specs.append('{} {} {}'.format(p, v, b))
        return specs
