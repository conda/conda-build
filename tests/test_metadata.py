import os
import subprocess
import sys

import pytest

from conda_build.metadata import select_lines, MetaData
from .utils import thisdir, metadata_dir


def test_uses_vcs_in_metadata(testing_workdir, testing_metadata):
    testing_metadata.meta_path = os.path.join(testing_workdir, 'meta.yaml')
    with open(testing_metadata.meta_path, 'w') as f:
        f.write('http://hg.something.com')
    assert not testing_metadata.uses_vcs_in_meta
    assert not testing_metadata.uses_vcs_in_build
    with open(testing_metadata.meta_path, 'w') as f:
        f.write('hg something something')
    assert not testing_metadata.uses_vcs_in_meta
    assert testing_metadata.uses_vcs_in_build
    with open(testing_metadata.meta_path, 'w') as f:
        f.write('hg.exe something something')
    assert not testing_metadata.uses_vcs_in_meta
    assert testing_metadata.uses_vcs_in_build
    with open(testing_metadata.meta_path, 'w') as f:
        f.write('HG_WEEEEE')
    assert testing_metadata.uses_vcs_in_meta
    assert not testing_metadata.uses_vcs_in_build


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


def test_disallow_leading_period_in_version(testing_metadata):
    testing_metadata.meta['package']['version'] = '.ste.ve'
    with pytest.raises(AssertionError):
        testing_metadata.version()


def test_disallow_dash_in_features(testing_metadata):
    testing_metadata.meta['build']['features'] = ['abc']
    testing_metadata.parse_again()
    with pytest.raises(ValueError):
        testing_metadata.meta['build']['features'] = ['ab-c']
        testing_metadata.parse_again()


def test_append_section_data(testing_metadata):
    testing_metadata.final = False
    testing_metadata.parse_again()
    requirements_len = len(testing_metadata.meta['requirements']['build'])
    testing_metadata.config.append_sections_file = os.path.join(thisdir, 'test-append.yaml')
    testing_metadata.final = False
    testing_metadata.parse_again()
    assert len(testing_metadata.meta['requirements']['build']) == requirements_len + 1
    assert 'frank' in testing_metadata.meta['requirements']['build']


def test_clobber_section_data(testing_metadata):
    testing_metadata.config.clobber_sections_file = os.path.join(thisdir, 'test-clobber.yaml')
    testing_metadata.final = False
    testing_metadata.parse_again()
    # a field that should be clobbered
    testing_metadata.meta['about']['summary'] = 'yep'
    # a field that should stay the same
    testing_metadata.meta['about']['home'] = 'sweet home'


def test_build_bootstrap_env_by_name(testing_metadata):
    assert not any("git" in pkg for pkg in testing_metadata.meta["requirements"]["build"]), \
        testing_metadata.meta["requirements"]["build"]
    try:
        cmd = "conda create -y -n conda_build_bootstrap_test git"
        subprocess.check_call(cmd.split())
        testing_metadata.config.bootstrap = "conda_build_bootstrap_test"
        testing_metadata.final = False
        testing_metadata.parse_again()
        assert any("git" in pkg for pkg in testing_metadata.meta["requirements"]["build"]), \
            testing_metadata.meta["requirements"]["build"]
    finally:
        cmd = "conda remove -y -n conda_build_bootstrap_test --all"
        subprocess.check_call(cmd.split())


def test_build_bootstrap_env_by_path(testing_metadata):
    assert not any("git" in pkg for pkg in testing_metadata.meta["requirements"]["build"]), \
        testing_metadata.meta["requirements"]["build"]
    path = os.path.join(thisdir, "conda_build_bootstrap_test")
    try:
        cmd = "conda create -y -p {} git".format(path)
        subprocess.check_call(cmd.split())
        testing_metadata.config.bootstrap = path
        testing_metadata.final = False
        testing_metadata.parse_again()
        assert any("git" in pkg for pkg in testing_metadata.meta["requirements"]["build"]), \
            testing_metadata.meta["requirements"]["build"]
    finally:
        cmd = "conda remove -y -p {} --all".format(path)
        subprocess.check_call(cmd.split())


@pytest.mark.parametrize('py_ver', [('2.7', 'vs2008'),
                                    ('3.4', 'vs2010'),
                                    ('3.5', 'vs2015'), ])
def test_native_compiler_metadata_win(testing_config, py_ver, mocker):
    variant = {'python': py_ver[0]}
    testing_config._platform = 'win'
    metadata = MetaData(os.path.join(metadata_dir, '_compiler_jinja2'), config=testing_config,
                        variant=variant)
    assert py_ver[1] in metadata.meta['requirements']['build']


def test_native_compiler_metadata_linux(testing_config, mocker):
    testing_config._platform = 'linux'
    metadata = MetaData(os.path.join(metadata_dir, '_compiler_jinja2'), config=testing_config)
    assert 'gcc' in metadata.meta['requirements']['build']
    assert 'g++' in metadata.meta['requirements']['build']
    assert 'gfortran' in metadata.meta['requirements']['build']


def test_native_compiler_metadata_osx(testing_config, mocker):
    testing_config._platform = 'osx'
    metadata = MetaData(os.path.join(metadata_dir, '_compiler_jinja2'), config=testing_config)
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


def test_hash_build_id(testing_metadata):
    assert testing_metadata._hash_dependencies() == 'hfe63493'
    assert testing_metadata.build_id() == 'py{}{}hfe63493_1'.format(sys.version_info.major,
                                                               sys.version_info.minor)


def test_hash_build_id_key_order(testing_metadata):
    deps = testing_metadata.meta['requirements']['build'][:]

    # first, prepend
    newdeps = deps[:]
    newdeps.insert(0, 'steve')
    testing_metadata.meta['requirements']['build'] = newdeps
    hash_pre = testing_metadata._hash_dependencies()

    # next, append
    newdeps = deps[:]
    newdeps.append('steve')
    testing_metadata.meta['requirements']['build'] = newdeps
    hash_post = testing_metadata._hash_dependencies()

    # make sure they match
    assert hash_pre == hash_post


def test_hash_applies_to_custom_build_string(testing_metadata):
    testing_metadata.meta['build']['string'] = 'steve'
    assert testing_metadata.build_id() == 'stevehfe63493'
