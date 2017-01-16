import os
import subprocess
import unittest

import pytest

from conda_build.conda_interface import MatchSpec

from conda_build.metadata import select_lines, handle_config_version, MetaData
from .utils import testing_workdir, test_config, test_metadata, thisdir, metadata_dir


def test_uses_vcs_in_metadata(testing_workdir, test_metadata):
    test_metadata.meta_path = os.path.join(testing_workdir, 'meta.yaml')
    with open(test_metadata.meta_path, 'w') as f:
        f.write('http://hg.something.com')
    assert not test_metadata.uses_vcs_in_meta
    assert not test_metadata.uses_vcs_in_build
    with open(test_metadata.meta_path, 'w') as f:
        f.write('hg something something')
    assert not test_metadata.uses_vcs_in_meta
    assert test_metadata.uses_vcs_in_build
    with open(test_metadata.meta_path, 'w') as f:
        f.write('hg.exe something something')
    assert not test_metadata.uses_vcs_in_meta
    assert test_metadata.uses_vcs_in_build
    with open(test_metadata.meta_path, 'w') as f:
        f.write('HG_WEEEEE')
    assert test_metadata.uses_vcs_in_meta
    assert not test_metadata.uses_vcs_in_build


def test_select_lines():
    lines = """
test
test [abc] no
test [abc] # no

test [abc]
 'quoted # [abc] '
 "quoted # [abc] yes "
test # stuff [abc] yes
test {{ JINJA_VAR[:2] }}
test {{ JINJA_VAR[:2] }} # stuff [abc] yes
test {{ JINJA_VAR[:2] }} # stuff yes [abc]
test {{ JINJA_VAR[:2] }} # [abc] stuff yes
{{ environ["test"] }}  # [abc]
"""

    assert select_lines(lines, {'abc': True}) == """
test
test [abc] no
test [abc] # no

test
 'quoted'
 "quoted"
test
test {{ JINJA_VAR[:2] }}
test {{ JINJA_VAR[:2] }}
test {{ JINJA_VAR[:2] }}
test {{ JINJA_VAR[:2] }}
{{ environ["test"] }}
"""
    assert select_lines(lines, {'abc': False}) == """
test
test [abc] no
test [abc] # no

test {{ JINJA_VAR[:2] }}
"""


class HandleConfigVersionTests(unittest.TestCase):

    def test_python(self):
        for spec, ver, res_spec in [
                ('python', '3.4', 'python 3.4*'),
                ('python 2.7.8', '2.7', 'python 2.7.8'),
                ('python 2.7.8', '3.5', 'python 2.7.8'),
                ('python 2.7.8', None, 'python 2.7.8'),
                ('python', None, 'python'),
                ('python x.x', '2.7', 'python 2.7*'),
                ('python', '27', 'python 2.7*'),
                ('python', 27, 'python 2.7*'),
        ]:
            ms = MatchSpec(spec)
            self.assertEqual(handle_config_version(ms, ver),
                             MatchSpec(res_spec))

        self.assertRaises(RuntimeError,
                          handle_config_version,
                          MatchSpec('python x.x'), None)

    def test_numpy(self):
        for spec, ver, res_spec, kwargs in [
                ('numpy', None, 'numpy', {}),
                ('numpy', 18, 'numpy 1.8*', {'dep_type': 'build'}),
                ('numpy', 18, 'numpy', {'dep_type': 'run'}),
                ('numpy', 110, 'numpy', {}),
                ('numpy x.x', 17, 'numpy 1.7*', {}),
                ('numpy x.x', 110, 'numpy 1.10*', {}),
                ('numpy 1.9.1', 18, 'numpy 1.9.1', {}),
                ('numpy 1.9.0 py27_2', None, 'numpy 1.9.0 py27_2', {}),
        ]:
            ms = MatchSpec(spec)
            self.assertEqual(handle_config_version(ms, ver, **kwargs),
                             MatchSpec(res_spec))

        self.assertRaises(RuntimeError,
                          handle_config_version,
                          MatchSpec('numpy x.x'), None)


def test_disallow_leading_period_in_version(test_metadata):
    test_metadata.meta['package']['version'] = '.ste.ve'
    with pytest.raises(AssertionError):
        test_metadata.version()


def test_disallow_dash_in_features(test_metadata):
    test_metadata.meta['build']['features'] = ['abc']
    test_metadata.parse_again()
    with pytest.raises(ValueError):
        test_metadata.meta['build']['features'] = ['ab-c']
        test_metadata.parse_again()


def test_append_section_data(test_metadata):
    test_metadata.config.append_sections_file = os.path.join(thisdir, 'test-append.yaml')
    test_metadata.parse_again()
    assert len(test_metadata.meta['requirements']['build']) == 2
    assert 'frank' in test_metadata.meta['requirements']['build']


def test_clobber_section_data(test_metadata):
    test_metadata.config.clobber_sections_file = os.path.join(thisdir, 'test-clobber.yaml')
    test_metadata.parse_again()
    # a field that should be clobbered
    test_metadata.meta['about']['summary'] = 'yep'
    # a field that should stay the same
    test_metadata.meta['about']['home'] = 'sweet home'


def test_build_bootstrap_env_by_name(test_metadata):
    assert not any("git" in pkg for pkg in test_metadata.meta["requirements"]["build"]), test_metadata.meta["requirements"]["build"]
    try:
        cmd = "conda create -y -n conda_build_bootstrap_test git"
        subprocess.check_call(cmd.split())
        test_metadata.config.bootstrap = "conda_build_bootstrap_test"
        test_metadata.parse_again()
        assert any("git" in pkg for pkg in test_metadata.meta["requirements"]["build"]), test_metadata.meta["requirements"]["build"]
    finally:
        cmd = "conda remove -y -n conda_build_bootstrap_test --all"
        subprocess.check_call(cmd.split())


def test_build_bootstrap_env_by_path(test_metadata):
    assert not any("git" in pkg for pkg in test_metadata.meta["requirements"]["build"]), test_metadata.meta["requirements"]["build"]
    path = os.path.join(thisdir, "conda_build_bootstrap_test")
    try:
        cmd = "conda create -y -p {} git".format(path)
        subprocess.check_call(cmd.split())
        test_metadata.config.bootstrap = path
        test_metadata.parse_again()
        assert any("git" in pkg for pkg in test_metadata.meta["requirements"]["build"]), test_metadata.meta["requirements"]["build"]
    finally:
        cmd = "conda remove -y -p {} --all".format(path)
        subprocess.check_call(cmd.split())


@pytest.mark.parametrize('py_ver', [('2.7', 'vs2008'),
                                    ('3.4', 'vs2010'),
                                    ('3.5', 'vs2015'), ])
def test_native_compiler_metadata_win(test_config, py_ver):
    test_config.platform = 'win'
    variant = {'python': py_ver[0]}
    metadata = MetaData(os.path.join(metadata_dir, '_compiler_jinja2'), config=test_config, variant=variant)
    assert py_ver[1] in metadata.meta['requirements']['build']


def test_native_compiler_metadata_linux(test_config):
    test_config.platform = 'linux'
    metadata = MetaData(os.path.join(metadata_dir, '_compiler_jinja2'), config=test_config)
    assert 'gcc' in metadata.meta['requirements']['build']
    assert 'g++' in metadata.meta['requirements']['build']
    assert 'gfortran' in metadata.meta['requirements']['build']


def test_native_compiler_metadata_osx(test_config):
    test_config.platform = 'osx'
    metadata = MetaData(os.path.join(metadata_dir, '_compiler_jinja2'), config=test_config)
    assert 'gcc' in metadata.meta['requirements']['build']
    assert 'g++' in metadata.meta['requirements']['build']
    assert 'gfortran' in metadata.meta['requirements']['build']


def test_compiler_metadata_cross_compiler():
    variant = {'c_compiler': 'c-compiler-linux',
               'cxx_compiler': 'cxx-compiler-linux',
               'fortran_compiler': 'fortran-compiler-linux',
               'target_platform': 'macos'}
    metadata = MetaData(os.path.join(metadata_dir, '_compiler_jinja2'), variant=variant)
    assert 'c-compiler-linux_macos' in metadata.meta['requirements']['build']
    assert 'cxx-compiler-linux_macos' in metadata.meta['requirements']['build']
    assert 'fortran-compiler-linux_macos' in metadata.meta['requirements']['build']


def test_hash_build_id(test_metadata):
    assert test_metadata._hash_dependencies() == 'h8302'
    assert test_metadata.build_id() == 'py27h8302_1'


def test_hash_build_id_key_order(test_metadata):
    deps = test_metadata.meta['requirements']['build'][:]

    # first, prepend
    newdeps = deps[:]
    newdeps.insert(0, 'steve')
    test_metadata.meta['requirements']['build'] = newdeps
    hash_pre = test_metadata._hash_dependencies()

    # next, append
    newdeps = deps[:]
    newdeps.append('steve')
    test_metadata.meta['requirements']['build'] = newdeps
    hash_post = test_metadata._hash_dependencies()

    # make sure they match
    assert hash_pre == hash_post


def test_hash_applies_to_custom_build_string(test_metadata):
    test_metadata.meta['build']['string'] = 'steve'
    assert test_metadata.build_id() == 'steveh8302'


def test_disallow_leading_period_in_version(test_metadata):
    test_metadata.meta['package']['version'] = '.ste.ve'
    with pytest.raises(AssertionError):
        test_metadata.version()


def test_disallow_dash_in_features(test_metadata):
    test_metadata.meta['build']['features'] = ['abc']
    test_metadata.parse_again()
    with pytest.raises(ValueError):
        test_metadata.meta['build']['features'] = ['ab-c']
        test_metadata.parse_again()
