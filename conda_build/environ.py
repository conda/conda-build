from __future__ import absolute_import, division, print_function

import os
import sys
from os.path import join, normpath, isabs
import subprocess
import multiprocessing
import warnings

import conda.config as cc

from conda_build.config import config

from conda_build import source
from conda_build.scripts import prepend_bin_path


def get_perl_ver():
    return str(config.CONDA_PERL)

def get_py_ver():
    return '.'.join(str(config.CONDA_PY))

def get_npy_ver():
    if config.CONDA_NPY:
        # Convert int -> string, e.g.
        #   17 -> '1.7'
        #   110 -> '1.10'
        conda_npy = str(config.CONDA_NPY)
        return conda_npy[0] + '.' + conda_npy[1:]
    return ''

def get_stdlib_dir():
    return join(config.build_prefix, 'Lib' if sys.platform == 'win32' else
                                'lib/python%s' % get_py_ver())

def get_sp_dir():
    return join(get_stdlib_dir(), 'site-packages')

def get_git_build_info(src_dir, git_url, expected_rev):
    expected_rev = expected_rev or 'master'
    env = os.environ.copy()
    d = {}
    git_dir = join(src_dir, '.git')
    if not os.path.exists(git_dir):
        return d

    env['GIT_DIR'] = git_dir
    try:
        # Verify current commit matches expected commit
        current_commit = subprocess.check_output(["git", "log", "-n1", "--format=%H"], env=env)
        current_commit = current_commit.decode('utf-8')
        expected_tag_commit = subprocess.check_output(["git", "log", "-n1", "--format=%H", expected_rev], env=env)
        expected_tag_commit = expected_tag_commit.decode('utf-8')

        # Verify correct remote url.
        # (Need to find the git cache directory, and check the remote from there.)
        cache_details = subprocess.check_output(["git", "remote", "-v"], env=env)
        cache_details = cache_details.decode('utf-8')
        cache_dir = cache_details.split('\n')[0].split()[1]
        assert "conda-bld/git_cache" in cache_dir

        env['GIT_DIR'] = cache_dir
        remote_details = subprocess.check_output(["git", "remote", "-v"], env=env)
        remote_details = remote_details.decode('utf-8')
        remote_url = remote_details.split('\n')[0].split()[1]
        if '://' not in remote_url:
            # Local filepaths are allowed, but make sure we normalize them
            remote_url = normpath(remote_url)

        # If the current source directory in conda-bld/work doesn't match the user's
        # metadata git_url or git_rev, then we aren't looking at the right source.
        if remote_url != git_url or current_commit != expected_tag_commit:
            return d
    except subprocess.CalledProcessError:
        return d

    env['GIT_DIR'] = git_dir

    # grab information from describe
    key_name = lambda a: "GIT_DESCRIBE_{}".format(a)
    keys = [key_name("TAG"), key_name("NUMBER"), key_name("HASH")]
    env = {str(key): str(value) for key, value in env.items()}
    process = subprocess.Popen(["git", "describe", "--tags", "--long", "HEAD"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=env)
    output = process.communicate()[0].strip()
    output = output.decode('utf-8')
    parts = output.rsplit('-', 2)
    parts_length = len(parts)
    if parts_length == 3:
        d.update(dict(zip(keys, parts)))
    # get the _full_ hash of the current HEAD
    process = subprocess.Popen(["git", "rev-parse", "HEAD"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=env)
    output = process.communicate()[0].strip()
    output = output.decode('utf-8')
    d['GIT_FULL_HASH'] = output
    # set up the build string
    if key_name('NUMBER') in d and key_name('HASH') in d:
        d['GIT_BUILD_STR'] = '{}_{}'.format(d[key_name('NUMBER')],
                                            d[key_name('HASH')])

    return d

def get_hg_build_info(src_dir):
    env = os.environ.copy()
    env['HG_DIR'] = join(src_dir, '.hg')
    env = {str(key): str(value) for key, value in env.items()}
    
    d = {}
    cmd = ["hg", "log", "--template",
           "{rev}|{node|short}|{latesttag}|{latesttagdistance}|{branch}",
           "--rev", "."]
    process = subprocess.Popen(cmd,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=env,
                               cwd=src_dir)
    output = process.communicate()[0].strip()
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

def get_dict(m=None, prefix=None):
    if not prefix:
        prefix = config.build_prefix

    python = config.build_python
    d = {'CONDA_BUILD': '1', 'PYTHONNOUSERSITE': '1'}
    d['CONDA_DEFAULT_ENV'] = config.build_prefix
    d['ARCH'] = str(cc.bits)
    d['PREFIX'] = prefix
    d['PYTHON'] = python
    d['PY3K'] = str(config.PY3K)
    d['STDLIB_DIR'] = get_stdlib_dir()
    d['SP_DIR'] = get_sp_dir()
    d['SYS_PREFIX'] = sys.prefix
    d['SYS_PYTHON'] = sys.executable
    d['PERL_VER'] = get_perl_ver()
    d['PY_VER'] = get_py_ver()
    if get_npy_ver():
        d['NPY_VER'] = get_npy_ver()
    d['SRC_DIR'] = source.get_dir()
    if "LANG" in os.environ:
        d['LANG'] = os.environ['LANG']
    if "HTTPS_PROXY" in os.environ:
        d['HTTPS_PROXY'] = os.environ['HTTPS_PROXY']
    if "HTTP_PROXY" in os.environ:
        d['HTTP_PROXY'] = os.environ['HTTP_PROXY']

    if m:
        for var_name in m.get_value('build/script_env', []):
            value = os.getenv(var_name)
            if value is None:
                warnings.warn(
                    "The environment variable '%s' is undefined." % var_name,
                    UserWarning
                )
            else:
                d[var_name] = value

    if sys.platform == "darwin":
        # multiprocessing.cpu_count() is not reliable on OSX
        # See issue #645 on github.com/conda/conda-build
        out, err = subprocess.Popen('sysctl -n hw.logicalcpu', shell=True, stdout=subprocess.PIPE).communicate()
        d['CPU_COUNT'] = out.decode('utf-8').strip()
    else:
        try:
            d['CPU_COUNT'] = str(multiprocessing.cpu_count())
        except NotImplementedError:
            d['CPU_COUNT'] = "1"

    if m and m.get_value('source/git_url'):
        git_url = m.get_value('source/git_url')
        if '://' not in git_url:
            # If git_url is a relative path instead of a url, convert it to an abspath
            if not isabs(git_url):
                git_url = join(m.path, git_url)
            git_url = normpath(join(m.path, git_url))
        d.update(**get_git_build_info(d['SRC_DIR'],
                                      git_url,
                                      m.get_value('source/git_rev')))

    d['PATH'] = dict(os.environ)['PATH']
    d = prepend_bin_path(d, prefix)

    if os.path.isdir(os.path.join(d['SRC_DIR'], '.hg')):
        d.update(**get_hg_build_info(d['SRC_DIR']))


    if sys.platform == 'win32':         # -------- Windows
        d['SCRIPTS'] = join(prefix, 'Scripts')
        d['LIBRARY_PREFIX'] = join(prefix, 'Library')
        d['LIBRARY_BIN'] = join(d['LIBRARY_PREFIX'], 'bin')
        d['LIBRARY_INC'] = join(d['LIBRARY_PREFIX'], 'include')
        d['LIBRARY_LIB'] = join(d['LIBRARY_PREFIX'], 'lib')

        drive, tail = prefix.split(':')
        d['CYGWIN_PREFIX'] = ''.join(['/cygdrive/', drive.lower(), tail.replace('\\', '/')])

        d['R'] = join(prefix, 'Scripts', 'R.exe')
    else:                               # -------- Unix
        d['HOME'] = os.getenv('HOME', 'UNKNOWN')
        d['PKG_CONFIG_PATH'] = join(prefix, 'lib', 'pkgconfig')
        d['R'] = join(prefix, 'bin', 'R')

    cflags = d.get('CFLAGS', '') # in case CFLAGS was added in the `script_env` section above
    cxxflags = d.get('CXXFLAGS', '')
    ldflags = d.get('LDFLAGS', '')

    if sys.platform == 'darwin':         # -------- OSX
        d['OSX_ARCH'] = 'i386' if cc.bits == 32 else 'x86_64'
        d['CFLAGS'] = cflags + ' -arch %(OSX_ARCH)s' % d
        d['CXXFLAGS'] = cxxflags + ' -arch %(OSX_ARCH)s' % d
        d['LDFLAGS'] = ldflags + ' -arch %(OSX_ARCH)s' % d
        d['MACOSX_DEPLOYMENT_TARGET'] = '10.6'

    elif sys.platform.startswith('linux'):      # -------- Linux
        d['LD_RUN_PATH'] = prefix + '/lib'
        if cc.bits == 32:
            d['CFLAGS'] = cflags + ' -m32'
            d['CXXFLAGS'] = cxxflags + ' -m32'

    if m:
        d['PKG_NAME'] = m.name()
        d['PKG_VERSION'] = m.version()
        d['PKG_BUILDNUM'] = str(m.build_number())
        d['PKG_BUILD_STRING'] = str(m.build_id())
        d['RECIPE_DIR'] = m.path

    return d


if __name__ == '__main__':
    e = get_dict()
    for k in sorted(e):
        assert isinstance(e[k], str), k
        print('%s=%s' % (k, e[k]))
