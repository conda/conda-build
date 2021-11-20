import contextlib
import filelock
import os
import subprocess
import sys

import pytest

from conda_build.exceptions import BuildLockError
import conda_build.utils as utils


def makefile(name, contents=""):
    name = os.path.abspath(name)
    path = os.path.dirname(name)

    if not os.path.exists(path):
        os.makedirs(path)

    with open(name, 'w') as f:
        f.write(contents)


@pytest.mark.skipif(utils.on_win, reason="only unix has python version in site-packages path")
def test_get_site_packages():
    # https://github.com/conda/conda-build/issues/1055#issuecomment-250961576
    # crazy unreal python version that should show up in a second
    crazy_path = os.path.join('/dummy', 'lib', 'python8.2', 'site-packages')
    site_packages = utils.get_site_packages('/dummy', '8.2')
    assert site_packages == crazy_path


def test_prepend_sys_path():
    path = sys.path[:]
    with utils.sys_path_prepended(sys.prefix):
        assert sys.path != path
        assert sys.path[1].startswith(sys.prefix)


def test_copy_source_tree(namespace_setup):
    dst = os.path.join(namespace_setup, 'dest')
    utils.copy_into(os.path.join(namespace_setup, 'namespace'), dst)
    assert os.path.isfile(os.path.join(dst, 'package', 'module.py'))


def test_merge_namespace_trees(namespace_setup):
    dep = os.path.join(namespace_setup, 'other_tree', 'namespace', 'package', 'dependency.py')
    makefile(dep)

    utils.copy_into(os.path.join(namespace_setup, 'other_tree'), namespace_setup)
    assert os.path.isfile(os.path.join(namespace_setup, 'namespace', 'package',
                                                'module.py'))
    assert os.path.isfile(dep)


@pytest.fixture(scope='function')
def namespace_setup(testing_workdir, request):
    namespace = os.path.join(testing_workdir, 'namespace')
    package = os.path.join(namespace, 'package')
    makefile(os.path.join(package, "module.py"))
    return testing_workdir


@pytest.mark.sanity
def test_disallow_merge_conflicts(namespace_setup, testing_config):
    duplicate = os.path.join(namespace_setup, 'dupe', 'namespace', 'package', 'module.py')
    makefile(duplicate)
    with pytest.raises(IOError):
        utils.merge_tree(os.path.dirname(duplicate), os.path.join(namespace_setup, 'namespace',
                                                 'package'))


@pytest.mark.sanity
def test_disallow_in_tree_merge(testing_workdir):
    with open('testfile', 'w') as f:
        f.write("test")
    with pytest.raises(AssertionError):
        utils.merge_tree(testing_workdir, os.path.join(testing_workdir, 'subdir'))


def test_relative_default():
    for f, r in [
            ('bin/python', '../lib'),
            ('lib/libhdf5.so', '.'),
            ('lib/python2.6/foobar.so', '..'),
            ('lib/python2.6/lib-dynload/zlib.so', '../..'),
            ('lib/python2.6/site-packages/pyodbc.so', '../..'),
            ('lib/python2.6/site-packages/bsdiff4/core.so', '../../..'),
            ('xyz', './lib'),
            ('bin/somedir/cmd', '../../lib'),
    ]:
        assert utils.relative(f) == r


def test_relative_lib():
    for f, r in [
            ('bin/python', '../lib'),
            ('lib/libhdf5.so', '.'),
            ('lib/python2.6/foobar.so', '..'),
            ('lib/python2.6/lib-dynload/zlib.so', '../..'),
            ('lib/python2.6/site-packages/pyodbc.so', '../..'),
            ('lib/python2.6/site-packages/bsdiff3/core.so', '../../..'),
            ('xyz', './lib'),
            ('bin/somedir/cmd', '../../lib'),
            ('bin/somedir/somedir2/cmd', '../../../lib'),
    ]:
        assert utils.relative(f, 'lib') == r


def test_relative_subdir():
    for f, r in [
            ('lib/libhdf5.so', './sub'),
            ('lib/sub/libhdf5.so', '.'),
            ('bin/python', '../lib/sub'),
            ('bin/somedir/cmd', '../../lib/sub'),
    ]:
        assert utils.relative(f, 'lib/sub') == r


def test_relative_prefix():
    for f, r in [
            ('xyz', '.'),
            ('a/xyz', '..'),
            ('a/b/xyz', '../..'),
            ('a/b/c/xyz', '../../..'),
            ('a/b/c/d/xyz', '../../../..'),
    ]:
        assert utils.relative(f, '.') == r


def test_relative_2():
    for f, r in [
            ('a/b/c/d/libhdf5.so', '../..'),
            ('a/b/c/libhdf5.so', '..'),
            ('a/b/libhdf5.so', '.'),
            ('a/libhdf5.so', './b'),
            ('x/x/libhdf5.so', '../../a/b'),
            ('x/b/libhdf5.so', '../../a/b'),
            ('x/libhdf5.so', '../a/b'),
            ('libhdf5.so', './a/b'),
    ]:
        assert utils.relative(f, 'a/b') == r


def test_relative_3():
    for f, r in [
            ('a/b/c/d/libhdf5.so', '..'),
            ('a/b/c/libhdf5.so', '.'),
            ('a/b/libhdf5.so', './c'),
            ('a/libhdf5.so', './b/c'),
            ('libhdf5.so', './a/b/c'),
            ('a/b/x/libhdf5.so', '../c'),
            ('a/x/x/libhdf5.so', '../../b/c'),
            ('x/x/x/libhdf5.so', '../../../a/b/c'),
            ('x/x/libhdf5.so', '../../a/b/c'),
            ('x/libhdf5.so', '../a/b/c'),
    ]:
        assert utils.relative(f, 'a/b/c') == r


def test_relative_4():
    for f, r in [
            ('a/b/c/d/libhdf5.so', '.'),
            ('a/b/c/x/libhdf5.so', '../d'),
            ('a/b/x/x/libhdf5.so', '../../c/d'),
            ('a/x/x/x/libhdf5.so', '../../../b/c/d'),
            ('x/x/x/x/libhdf5.so', '../../../../a/b/c/d'),
    ]:
        assert utils.relative(f, 'a/b/c/d') == r


def test_expand_globs(testing_workdir):
    sub_dir = os.path.join(testing_workdir, 'sub1')
    os.mkdir(sub_dir)
    ssub_dir = os.path.join(sub_dir, 'ssub1')
    os.mkdir(ssub_dir)
    files = ['abc', 'acb',
             os.path.join(sub_dir, 'def'),
             os.path.join(sub_dir, 'abc'),
             os.path.join(ssub_dir, 'ghi'),
             os.path.join(ssub_dir, 'abc')]
    for f in files:
        with open(f, 'w') as _f:
            _f.write('weee')

    # Test dirs
    exp = utils.expand_globs([os.path.join('sub1', 'ssub1')], testing_workdir)
    assert sorted(exp) == sorted([os.path.sep.join(('sub1', 'ssub1', 'ghi')),
                                  os.path.sep.join(('sub1', 'ssub1', 'abc'))])

    # Test files
    exp = sorted(utils.expand_globs(['abc', files[2]], testing_workdir))
    assert exp == sorted(['abc', os.path.sep.join(('sub1', 'def'))])

    # Test globs
    exp = sorted(utils.expand_globs(['a*', '*/*f', '**/*i'], testing_workdir))
    assert exp == sorted(['abc', 'acb', os.path.sep.join(('sub1', 'def')),
                          os.path.sep.join(('sub1', 'ssub1', 'ghi'))])


def test_filter_files():
    # Files that should be filtered out.
    files_list = [
        ".git/a",
        "something/.git/a",
        ".git\\a",
        "something\\.git\\a",
        "file.la",
        "something/file.la",
        "python.exe.conda_trash",
        "bla.dll.conda_trash_1",
        "bla.dll.conda_trash.conda_trash",
    ]
    assert not utils.filter_files(files_list, "")

    # Files that should *not* be filtered out.
    # Example of valid 'x.git' directory:
    #    lib/python3.4/site-packages/craftr/stl/craftr.utils.git/Craftrfile
    files_list = ['a', 'x.git/a', 'something/x.git/a',
                  'x.git\\a', 'something\\x.git\\a', 'something/.gitmodules',
                  'some/template/directory/.gitignore', 'another.lab',
                  'miniconda_trashcan.py', 'conda_trash_avoider.py']
    assert len(utils.filter_files(files_list, '')) == len(files_list)


@pytest.mark.serial
def test_logger_filtering(caplog, capfd):
    import logging
    log = utils.get_logger(__name__, level=logging.DEBUG)
    log.debug('test debug message')
    log.info('test info message')
    log.info('test duplicate message')
    log.info('test duplicate message')
    log.warn('test warn message')
    log.error('test error message')
    out, err = capfd.readouterr()
    assert 'test debug message' in out
    assert 'test info message' in out
    assert 'test warn message' not in out
    assert 'test error message' not in out
    assert 'test debug message' not in err
    assert 'test info message' not in err
    assert 'test warn message' in err
    assert 'test error message' in err
    assert caplog.text.count('duplicate') == 1
    log.removeHandler(logging.StreamHandler(sys.stdout))
    log.removeHandler(logging.StreamHandler(sys.stderr))


def test_logger_config_from_file(testing_workdir, caplog, capfd, mocker):
    test_file = os.path.join(testing_workdir, 'build_log_config.yaml')
    with open(test_file, 'w') as f:
        f.write("""
version: 1
formatters:
  simple:
    format: '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
handlers:
  console:
    class: logging.StreamHandler
    level: WARN
    formatter: simple
    stream: ext://sys.stdout
loggers:
  {}:
    level: WARN
    handlers: [console]
    propagate: no
root:
  level: DEBUG
  handlers: [console]
""".format(__name__))
    cc_conda_build = mocker.patch.object(utils, 'cc_conda_build')
    cc_conda_build.get.return_value = test_file
    log = utils.get_logger(__name__)
    # default log level is INFO, but our config file should set level to DEBUG
    log.warn('test message')
    # output should have gone to stdout according to config above.
    out, err = capfd.readouterr()
    assert 'test message' in out
    # make sure that it is not in stderr - this is testing override of defaults.
    assert 'test message' not in err


def test_ensure_valid_spec():
    assert utils.ensure_valid_spec('python') == 'python'
    assert utils.ensure_valid_spec('python 2.7') == 'python 2.7.*'
    assert utils.ensure_valid_spec('python 2.7.2') == 'python 2.7.2.*'
    assert utils.ensure_valid_spec('python 2.7.12 0') == 'python 2.7.12 0'
    assert utils.ensure_valid_spec('python >=2.7,<2.8') == 'python >=2.7,<2.8'
    assert utils.ensure_valid_spec('numpy x.x') == 'numpy x.x'
    assert utils.ensure_valid_spec(utils.MatchSpec('numpy x.x')) == utils.MatchSpec('numpy x.x')


def test_insert_variant_versions(testing_metadata):
    testing_metadata.meta['requirements']['build'] = ['python', 'numpy 1.13']
    testing_metadata.config.variant = {'python': '2.7', 'numpy': '1.11'}
    utils.insert_variant_versions(testing_metadata.meta.get('requirements', {}),
                                  testing_metadata.config.variant, 'build')
    # this one gets inserted
    assert 'python 2.7.*' in testing_metadata.meta['requirements']['build']
    # this one should not be altered
    assert 'numpy 1.13' in testing_metadata.meta['requirements']['build']
    # the overall length does not change
    assert len(testing_metadata.meta['requirements']['build']) == 2


def test_subprocess_stats_call(testing_workdir):
    stats = {}
    utils.check_call_env(['hostname'], stats=stats, cwd=testing_workdir)
    assert stats
    stats = {}
    out = utils.check_output_env(['hostname'], stats=stats, cwd=testing_workdir)
    assert out
    assert stats
    with pytest.raises(subprocess.CalledProcessError):
        utils.check_call_env(['bash', '-c', 'exit 1'], cwd=testing_workdir)


def test_try_acquire_locks(testing_workdir):
    # Acquiring two unlocked locks should succeed.
    lock1 = filelock.FileLock(os.path.join(testing_workdir, 'lock1'))
    lock2 = filelock.FileLock(os.path.join(testing_workdir, 'lock2'))
    with utils.try_acquire_locks([lock1, lock2], timeout=1):
        pass

    # Acquiring the same lock twice should fail.
    lock1_copy = filelock.FileLock(os.path.join(testing_workdir, 'lock1'))
    # Also verify that the error message contains the word "lock", since we rely
    # on this elsewhere.
    with pytest.raises(BuildLockError, match='Failed to acquire all locks'):
        with utils.try_acquire_locks([lock1, lock1_copy], timeout=1):
            pass

def test_get_lock(testing_workdir):
    lock1 = utils.get_lock(os.path.join(testing_workdir, 'lock1'))
    lock2 = utils.get_lock(os.path.join(testing_workdir, 'lock2'))

    # Different folders should get different lock files.
    assert lock1.lock_file != lock2.lock_file

    # Same folder should get the same lock file.
    lock1_copy = utils.get_lock(os.path.join(testing_workdir, 'lock1'))
    assert lock1.lock_file == lock1_copy.lock_file

    # ...even when not normalized
    lock1_unnormalized = utils.get_lock(os.path.join(testing_workdir, 'foo', '..', 'lock1'))
    assert lock1.lock_file == lock1_unnormalized.lock_file


@contextlib.contextmanager
def _generate_tmp_tree():
    # dirA
    # |\- dirB
    # |   |\- fileA
    # |   \-- fileB
    # \-- dirC
    #     |\- fileA
    #     \-- fileB
    import shutil
    import tempfile

    try:
        tmp = os.path.realpath(os.path.normpath(tempfile.mkdtemp()))

        dA = os.path.join(tmp, "dirA")
        dB = os.path.join(dA, "dirB")
        dC = os.path.join(dA, "dirC")
        for d in (dA, dB, dC):
            os.mkdir(d)

        f1 = os.path.join(dB, "fileA")
        f2 = os.path.join(dB, "fileB")
        f3 = os.path.join(dC, "fileA")
        f4 = os.path.join(dC, "fileB")
        for f in (f1, f2, f3, f4):
            makefile(f)

        yield tmp, (dA, dB, dC), (f1, f2, f3, f4)
    finally:
        shutil.rmtree(tmp)


def test_rec_glob():
    with _generate_tmp_tree() as (tmp, _, (f1, f2, f3, f4)):
        assert sorted(utils.rec_glob(tmp, "fileA")) == [f1, f3]
        assert sorted(utils.rec_glob(tmp, ("fileA", "fileB"), ignores="dirB")) == [f3, f4]
        assert sorted(utils.rec_glob(tmp, "fileB", ignores=("dirC",))) == [f2]


def test_find_recipe():
    with _generate_tmp_tree() as (tmp, (dA, dB, dC), (f1, f2, f3, f4)):
        f5 = os.path.join(tmp, "meta.yaml")
        f6 = os.path.join(dA, "meta.yml")
        f7 = os.path.join(dB, "conda.yaml")
        f8 = os.path.join(dC, "conda.yml")

        # check that each of these are valid recipes
        for f in (f5, f6, f7, f8):
            makefile(f)
            assert utils.find_recipe(tmp) == f
            os.remove(f)


def test_find_recipe_relative():
    with _generate_tmp_tree() as (tmp, (dA, dB, dC), (f1, f2, f3, f4)):
        f5 = os.path.join(dA, "meta.yaml")
        makefile(f5)

        # check that even when given a relative recipe path we still return
        # the absolute path
        saved = os.getcwd()
        os.chdir(tmp)
        try:
            assert utils.find_recipe("dirA") == f5
        finally:
            os.chdir(saved)


def test_find_recipe_no_meta():
    with _generate_tmp_tree() as (tmp, _, (f1, f2, f3, f4)):
        # no meta files in tmp
        with pytest.raises(IOError):
            utils.find_recipe(tmp)


def test_find_recipe_file():
    with _generate_tmp_tree() as (tmp, _, (f1, f2, f3, f4)):
        f5 = os.path.join(tmp, "meta.yaml")
        makefile(f5)
        # file provided is valid meta
        assert utils.find_recipe(f5) == f5


def test_find_recipe_file_bad():
    with _generate_tmp_tree() as (tmp, _, (f1, f2, f3, f4)):
        # file provided is not valid meta
        with pytest.raises(IOError):
            utils.find_recipe(f1)


def test_find_recipe_multipe_base():
    with _generate_tmp_tree() as (tmp, (dA, dB, dC), (f1, f2, f3, f4)):
        f5 = os.path.join(tmp, "meta.yaml")
        f6 = os.path.join(dB, "meta.yaml")
        f7 = os.path.join(dC, "conda.yaml")
        for f in (f5, f6, f7):
            makefile(f)
        # multiple meta files, use the one in base level
        assert utils.find_recipe(tmp) == f5


def test_find_recipe_multipe_bad():
    with _generate_tmp_tree() as (tmp, (dA, dB, dC), (f1, f2, f3, f4)):
        f5 = os.path.join(dB, "meta.yaml")
        f6 = os.path.join(dC, "conda.yaml")
        for f in (f5, f6):
            makefile(f)

        # nothing in base
        with pytest.raises(IOError):
            utils.find_recipe(tmp)

        f7 = os.path.join(tmp, "meta.yaml")
        f8 = os.path.join(tmp, "conda.yaml")
        for f in (f7, f8):
            makefile(f)

        # too many in base
        with pytest.raises(IOError):
            utils.find_recipe(tmp)
