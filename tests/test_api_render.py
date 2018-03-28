"""
This module tests the test API.  These are high-level integration tests.  Lower level unit tests
should go in test_render.py
"""

import os
import re

import mock
import pytest
import yaml

from conda_build import api, render
from conda_build.conda_interface import subdir, reset_context, cc_conda_build

from .utils import metadata_dir, thisdir


def test_render_need_download(testing_workdir, testing_config):
    # first, test that the download/render system renders all it can,
    #    and accurately returns its needs

    with pytest.raises((ValueError, SystemExit)):
        metadata, need_download, need_reparse_in_env = api.render(
            os.path.join(metadata_dir, "source_git_jinja2"),
            config=testing_config,
            no_download_source=True)[0]
        assert need_download
        assert need_reparse_in_env

    # Test that allowing source download lets it to the right thing.
    metadata, need_download, need_reparse_in_env = api.render(
        os.path.join(metadata_dir, "source_git_jinja2"),
        config=testing_config,
        no_download_source=False,
        finalize=False)[0]
    assert not need_download
    assert metadata.meta["package"]["version"] == "1.20.2"


def test_render_yaml_output(testing_workdir, testing_config):
    metadata, need_download, need_reparse_in_env = api.render(
        os.path.join(metadata_dir, "source_git_jinja2"),
        config=testing_config)[0]
    yaml_metadata = api.output_yaml(metadata)
    assert "package:" in yaml_metadata

    # writes file with yaml data in it
    api.output_yaml(metadata, os.path.join(testing_workdir, "output.yaml"))
    assert "package:" in open(os.path.join(testing_workdir, "output.yaml")).read()


def test_get_output_file_path(testing_workdir, testing_metadata):
    testing_metadata = render.finalize_metadata(testing_metadata)
    api.output_yaml(testing_metadata, 'recipe/meta.yaml')

    build_path = api.get_output_file_paths(os.path.join(testing_workdir, 'recipe'),
                                          config=testing_metadata.config,
                                          no_download_source=True)[0]
    assert build_path == os.path.join(testing_metadata.config.croot,
                                      testing_metadata.config.host_subdir,
                                      "test_get_output_file_path-1.0-1.tar.bz2")


def test_get_output_file_path_metadata_object(testing_metadata):
    testing_metadata.final = True
    build_path = api.get_output_file_paths(testing_metadata)[0]
    assert build_path == os.path.join(testing_metadata.config.croot,
                                      testing_metadata.config.host_subdir,
                "test_get_output_file_path_metadata_object-1.0-1.tar.bz2")


def test_get_output_file_path_jinja2(testing_workdir, testing_config):
    # If this test does not raise, it's an indicator that the workdir is not
    #    being cleaned as it should.
    recipe = os.path.join(metadata_dir, "source_git_jinja2")

    # First get metadata with a recipe that is known to need a download:
    with pytest.raises((ValueError, SystemExit)):
        build_path = api.get_output_file_paths(recipe,
                                               config=testing_config,
                                               no_download_source=True)[0]

    metadata, need_download, need_reparse_in_env = api.render(
        recipe,
        config=testing_config,
        no_download_source=False)[0]
    build_path = api.get_output_file_paths(metadata)[0]
    _hash = metadata.hash_dependencies()
    python = ''.join(metadata.config.variant['python'].split('.')[:2])
    assert build_path == os.path.join(testing_config.croot, testing_config.host_subdir,
                                      "conda-build-test-source-git-jinja2-1.20.2-"
                                      "py{0}{1}_0_g262d444.tar.bz2".format(python, _hash))


@mock.patch('conda_build.source')
def test_output_without_jinja_does_not_download(mock_source, testing_workdir, testing_config):
        api.get_output_file_path(os.path.join(metadata_dir, "source_git"),
                                              config=testing_config)[0]
        mock_source.provide.assert_not_called()


def test_pin_compatible_semver(testing_config):
    recipe_dir = os.path.join(metadata_dir, '_pin_compatible')
    metadata = api.render(recipe_dir, config=testing_config)[0][0]
    assert 'zlib >=1.2.8,<2.0a0' in metadata.get_value('requirements/run')


def test_resolved_packages_recipe(testing_config):
    recipe_dir = os.path.join(metadata_dir, '_resolved_packages_host_build')
    metadata = api.render(recipe_dir, config=testing_config)[0][0]
    run_requirements = set(x.split()[0] for x in metadata.get_value('requirements/run'))
    for package in [
        'python',  # direct dependency
        'curl',  # direct dependency
        'zlib',  # indirect dependency of curl and python
        'xz',  # indirect dependency of python
    ]:
        assert package in run_requirements


def test_host_entries_finalized(testing_config):
    recipe = os.path.join(metadata_dir, '_host_entries_finalized')
    metadata = api.render(recipe, config=testing_config)
    assert len(metadata) == 2
    outputs = api.get_output_file_paths(recipe, config=testing_config)
    assert any('py27' in out for out in outputs)
    assert any('py36' in out for out in outputs)


def test_hash_no_apply_to_custom_build_string(testing_metadata, testing_workdir):
    testing_metadata.meta['build']['string'] = 'steve'
    testing_metadata.meta['requirements']['build'] = ['zlib 1.2.8']

    api.output_yaml(testing_metadata, 'meta.yaml')
    metadata = api.render(testing_workdir)[0][0]

    assert metadata.build_id() == 'steve'


def test_pin_depends(testing_config):
    """This is deprecated functionality - replaced by the more general variants pinning scheme"""
    recipe = os.path.join(metadata_dir, '_pin_depends_strict')
    m = api.render(recipe, config=testing_config)[0][0]
    # the recipe python is not pinned, but having pin_depends set will force it to be.
    assert any(re.search('python\s+[23]\.', dep) for dep in m.meta['requirements']['run'])


def test_cross_recipe_with_only_build_section(testing_config):
    recipe = os.path.join(metadata_dir, '_cross_prefix_elision')
    metadata = api.render(recipe, config=testing_config, bypass_env_check=True)[0][0]
    assert metadata.config.host_subdir != subdir
    assert metadata.config.build_prefix == metadata.config.host_prefix
    assert metadata.config.build_is_host
    recipe = os.path.join(metadata_dir, '_cross_prefix_elision_compiler_used')
    metadata = api.render(recipe, config=testing_config, bypass_env_check=True)[0][0]
    assert metadata.config.host_subdir != subdir
    assert metadata.config.build_prefix != metadata.config.host_prefix
    assert not metadata.config.build_is_host


def test_setting_condarc_vars_with_env_var_expansion(testing_workdir):
    os.makedirs('config')
    # python won't be used - the stuff in the recipe folder will override it
    python_versions = ['2.6', '3.4', '3.10']
    config = {'python': python_versions,
              'bzip2': ['0.9', '1.0']}
    with open(os.path.join('config', 'conda_build_config.yaml'), 'w') as f:
        yaml.dump(config, f, default_flow_style=False)

    cc_conda_build_backup = cc_conda_build.copy()
    # hacky equivalent of changing condarc
    # careful, this is global and affects other tests!  make sure to clear it!
    cc_conda_build.update({'config_file': '${TEST_WORKDIR}/config/conda_build_config.yaml'})

    os.environ['TEST_WORKDIR'] = testing_workdir
    try:
        m = api.render(os.path.join(thisdir, 'test-recipes', 'variants', '19_used_variables'),
                    bypass_env_check=True, finalize=False)[0][0]
        # this one should have gotten clobbered by the values in the recipe
        assert m.config.variant['python'] not in python_versions
        # this confirms that we loaded the config file correctly
        assert len(m.config.squished_variants['bzip2']) == 2
    finally:
        cc_conda_build.clear()
        cc_conda_build.update(cc_conda_build_backup)


def test_self_reference_run_exports_pin_subpackage_picks_up_version_correctly():
    recipe = os.path.join(metadata_dir, '_self_reference_run_exports')
    m = api.render(recipe)[0][0]
    run_exports = m.meta.get('build', {}).get('run_exports', [])
    assert run_exports
    assert len(run_exports) == 1
    assert run_exports[0].split()[1] == '>=1.0.0,<2.0a0'


def test_run_exports_with_pin_compatible_in_subpackages(testing_config):
    recipe = os.path.join(metadata_dir, '_run_exports_in_outputs')
    ms = api.render(recipe, config=testing_config)
    for m, _, _ in ms:
        if m.name().startswith('gfortran_'):
            run_exports = set(m.meta.get('build', {}).get('run_exports', {}).get('strong', []))
            assert len(run_exports) == 1
            assert all(len(export.split()) > 1 for export in run_exports), run_exports
