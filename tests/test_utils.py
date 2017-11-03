import os
import stat
import sys
import unittest
import zipfile

import pytest

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


def test_disallow_merge_conflicts(namespace_setup, testing_config):
    duplicate = os.path.join(namespace_setup, 'dupe', 'namespace', 'package', 'module.py')
    makefile(duplicate)
    with pytest.raises(IOError):
        utils.merge_tree(os.path.dirname(duplicate), os.path.join(namespace_setup, 'namespace',
                                                 'package'))


@pytest.mark.skipif(utils.on_win, reason="only unix has full os.chmod capabilities")
def test_unzip(testing_workdir):
    with open('file_with_execute_permission', 'w') as f:
        f.write("test")
    file_path = os.path.join(testing_workdir, 'file_with_execute_permission')
    current_permissions = os.stat(file_path).st_mode
    os.chmod(file_path, current_permissions | stat.S_IXUSR)
    with zipfile.ZipFile('test.zip', 'w') as z:
        z.write('file_with_execute_permission')
    utils.unzip('test.zip', 'unpack')
    unpacked_path = os.path.join('unpack', 'file_with_execute_permission')
    assert os.path.isfile(unpacked_path)
    st_mode = os.stat(unpacked_path).st_mode
    assert st_mode & stat.S_IXUSR


def test_disallow_in_tree_merge(testing_workdir):
    with open('testfile', 'w') as f:
        f.write("test")
    with pytest.raises(AssertionError):
        utils.merge_tree(testing_workdir, os.path.join(testing_workdir, 'subdir'))


class TestUtils(unittest.TestCase):

    def test_relative_default(self):
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
            self.assertEqual(utils.relative(f), r)

    def test_relative_lib(self):
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
            self.assertEqual(utils.relative(f, 'lib'), r)

    def test_relative_subdir(self):
        for f, r in [
                ('lib/libhdf5.so', './sub'),
                ('lib/sub/libhdf5.so', '.'),
                ('bin/python', '../lib/sub'),
                ('bin/somedir/cmd', '../../lib/sub'),
        ]:
            self.assertEqual(utils.relative(f, 'lib/sub'), r)

    def test_relative_prefix(self):
        for f, r in [
                ('xyz', '.'),
                ('a/xyz', '..'),
                ('a/b/xyz', '../..'),
                ('a/b/c/xyz', '../../..'),
                ('a/b/c/d/xyz', '../../../..'),
        ]:
            self.assertEqual(utils.relative(f, '.'), r)

    def test_relative_2(self):
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
            self.assertEqual(utils.relative(f, 'a/b'), r)

    def test_relative_3(self):
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
            self.assertEqual(utils.relative(f, 'a/b/c'), r)

    def test_relative_4(self):
        for f, r in [
                ('a/b/c/d/libhdf5.so', '.'),
                ('a/b/c/x/libhdf5.so', '../d'),
                ('a/b/x/x/libhdf5.so', '../../c/d'),
                ('a/x/x/x/libhdf5.so', '../../../b/c/d'),
                ('x/x/x/x/libhdf5.so', '../../../../a/b/c/d'),
        ]:
            self.assertEqual(utils.relative(f, 'a/b/c/d'), r)


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
    assert sorted(exp) == sorted(['sub1/ssub1/ghi', 'sub1/ssub1/abc'])

    # Test files
    exp = sorted(utils.expand_globs(['abc', files[2]], testing_workdir))
    assert exp == sorted(['abc', 'sub1/def'])

    # Test globs
    exp = sorted(utils.expand_globs(['a*', '*/*f', '**/*i'], testing_workdir))
    assert exp == sorted(['abc', 'acb', 'sub1/def', 'sub1/ssub1/ghi'])


def test_filter_files():
    # Files that should be filtered out.
    files_list = ['.git/a', 'something/.git/a', '.git\\a', 'something\\.git\\a']
    assert not utils.filter_files(files_list, '')

    # Files that should *not* be filtered out.
    # Example of valid 'x.git' directory:
    #    lib/python3.4/site-packages/craftr/stl/craftr.utils.git/Craftrfile
    files_list = ['a', 'x.git/a', 'something/x.git/a',
                  'x.git\\a', 'something\\x.git\\a']
    assert len(utils.filter_files(files_list, '')) == len(files_list)


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
