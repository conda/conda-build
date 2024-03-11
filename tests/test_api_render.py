# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
"""
This module tests the test API.  These are high-level integration tests.  Lower level unit tests
should go in test_render.py
"""
import os
import re

import pytest
import yaml
from conda.common.compat import on_win

from conda_build import api, render
from conda_build.conda_interface import cc_conda_build, subdir

from .utils import metadata_dir, variants_dir


def test_render_need_download(testing_config):
    # first, test that the download/render system renders all it can,
    #    and accurately returns its needs

    with pytest.raises((ValueError, SystemExit)):
        metadata, need_download, need_reparse_in_env = api.render(
            os.path.join(metadata_dir, "source_git_jinja2"),
            config=testing_config,
            no_download_source=True,
        )[0]
        assert need_download
        assert need_reparse_in_env

    # Test that allowing source download lets it to the right thing.
    metadata, need_download, need_reparse_in_env = api.render(
        os.path.join(metadata_dir, "source_git_jinja2"),
        config=testing_config,
        no_download_source=False,
        finalize=False,
    )[0]
    assert not need_download
    assert metadata.meta["package"]["version"] == "1.20.2"


def test_render_yaml_output(testing_workdir, testing_config):
    metadata, need_download, need_reparse_in_env = api.render(
        os.path.join(metadata_dir, "source_git_jinja2"), config=testing_config
    )[0]
    yaml_metadata = api.output_yaml(metadata)
    assert "package:" in yaml_metadata

    # writes file with yaml data in it
    api.output_yaml(metadata, os.path.join(testing_workdir, "output.yaml"))
    assert "package:" in open(os.path.join(testing_workdir, "output.yaml")).read()


def test_get_output_file_path(testing_workdir, testing_metadata):
    testing_metadata = render.finalize_metadata(testing_metadata)
    api.output_yaml(testing_metadata, "recipe/meta.yaml")

    build_path = api.get_output_file_paths(
        os.path.join(testing_workdir, "recipe"),
        config=testing_metadata.config,
        no_download_source=True,
    )[0]
    assert build_path == os.path.join(
        testing_metadata.config.croot,
        testing_metadata.config.host_subdir,
        "test_get_output_file_path-1.0-1.tar.bz2",
    )


def test_get_output_file_path_metadata_object(testing_metadata):
    testing_metadata.final = True
    build_path = api.get_output_file_paths(testing_metadata)[0]
    assert build_path == os.path.join(
        testing_metadata.config.croot,
        testing_metadata.config.host_subdir,
        "test_get_output_file_path_metadata_object-1.0-1.tar.bz2",
    )


def test_get_output_file_path_jinja2(testing_config):
    # If this test does not raise, it's an indicator that the workdir is not
    #    being cleaned as it should.
    recipe = os.path.join(metadata_dir, "source_git_jinja2")

    # First get metadata with a recipe that is known to need a download:
    with pytest.raises((ValueError, SystemExit)):
        build_path = api.get_output_file_paths(
            recipe, config=testing_config, no_download_source=True
        )[0]

    metadata, need_download, need_reparse_in_env = api.render(
        recipe, config=testing_config, no_download_source=False
    )[0]
    build_path = api.get_output_file_paths(metadata)[0]
    _hash = metadata.hash_dependencies()
    python = "".join(metadata.config.variant["python"].split(".")[:2])
    assert build_path == os.path.join(
        testing_config.croot,
        testing_config.host_subdir,
        f"conda-build-test-source-git-jinja2-1.20.2-py{python}{_hash}_0_g262d444.tar.bz2",
    )


def test_output_without_jinja_does_not_download(mocker, testing_config):
    mock = mocker.patch("conda_build.source")
    api.get_output_file_paths(
        os.path.join(metadata_dir, "source_git"), config=testing_config
    )
    mock.assert_not_called()


def test_pin_compatible_semver(testing_config):
    recipe_dir = os.path.join(metadata_dir, "_pin_compatible")
    metadata = api.render(recipe_dir, config=testing_config)[0][0]
    assert "zlib >=1.2.11,<2.0a0" in metadata.get_value("requirements/run")


@pytest.mark.slow
@pytest.mark.xfail(on_win, reason="Defaults channel has conflicting vc packages")
def test_resolved_packages_recipe(testing_config):
    recipe_dir = os.path.join(metadata_dir, "_resolved_packages_host_build")
    metadata = api.render(recipe_dir, config=testing_config)[0][0]
    assert all(len(pkg.split()) == 3 for pkg in metadata.get_value("requirements/run"))
    run_requirements = {x.split()[0] for x in metadata.get_value("requirements/run")}
    for package in [
        "curl",  # direct dependency
        "numpy",  # direct dependency
        "zlib",  # indirect dependency of curl
        "python",  # indirect dependency of numpy
    ]:
        assert package in run_requirements


@pytest.mark.slow
def test_host_entries_finalized(testing_config):
    recipe = os.path.join(metadata_dir, "_host_entries_finalized")
    metadata = api.render(recipe, config=testing_config)
    assert len(metadata) == 2
    outputs = api.get_output_file_paths(metadata)
    assert any("py27" in out for out in outputs)
    assert any("py39" in out for out in outputs)


def test_hash_no_apply_to_custom_build_string(testing_metadata, testing_workdir):
    testing_metadata.meta["build"]["string"] = "steve"
    testing_metadata.meta["requirements"]["build"] = ["zlib 1.2.8"]

    api.output_yaml(testing_metadata, "meta.yaml")
    metadata = api.render(testing_workdir)[0][0]

    assert metadata.build_id() == "steve"


def test_pin_depends(testing_config):
    """This is deprecated functionality - replaced by the more general variants pinning scheme"""
    recipe = os.path.join(metadata_dir, "_pin_depends_strict")
    m = api.render(recipe, config=testing_config)[0][0]
    # the recipe python is not pinned, but having pin_depends set will force it to be.
    assert any(
        re.search(r"python\s+[23]\.", dep) for dep in m.meta["requirements"]["run"]
    )


def test_cross_recipe_with_only_build_section(testing_config):
    recipe = os.path.join(metadata_dir, "_cross_prefix_elision_compiler_used")
    metadata = api.render(recipe, config=testing_config, bypass_env_check=True)[0][0]
    assert metadata.config.host_subdir != subdir
    assert metadata.config.build_prefix != metadata.config.host_prefix
    assert not metadata.build_is_host


def test_cross_info_index_platform(testing_config):
    recipe = os.path.join(metadata_dir, "_cross_build_unix_windows")
    metadata = api.render(recipe, config=testing_config, bypass_env_check=True)[0][0]
    info_index = metadata.info_index()
    assert metadata.config.host_subdir != subdir
    assert metadata.config.host_subdir == info_index["subdir"]
    assert metadata.config.host_platform != metadata.config.platform
    assert metadata.config.host_platform == info_index["platform"]


def test_noarch_with_platform_deps(testing_workdir, testing_config):
    recipe_path = os.path.join(metadata_dir, "_noarch_with_platform_deps")
    build_ids = {}
    for subdir_ in ["linux-64", "linux-aarch64", "linux-ppc64le", "osx-64", "win-64"]:
        platform, arch = subdir_.split("-")
        m = api.render(
            recipe_path, config=testing_config, platform=platform, arch=arch
        )[0][0]
        build_ids[subdir_] = m.build_id()

    # one hash for each platform, plus one for the archspec selector
    assert len(set(build_ids.values())) == 4
    assert build_ids["linux-64"] == build_ids["linux-aarch64"]
    assert (
        build_ids["linux-64"] != build_ids["linux-ppc64le"]
    )  # not the same due to archspec


def test_noarch_with_no_platform_deps(testing_workdir, testing_config):
    recipe_path = os.path.join(metadata_dir, "_noarch_with_no_platform_deps")
    build_ids = set()
    for platform in ["osx", "linux", "win"]:
        m = api.render(recipe_path, config=testing_config, platform=platform)[0][0]
        build_ids.add(m.build_id())

    assert len(build_ids) == 1


def test_setting_condarc_vars_with_env_var_expansion(testing_workdir):
    os.makedirs("config")
    # python won't be used - the stuff in the recipe folder will override it
    python_versions = ["2.6", "3.4", "3.11"]
    config = {"python": python_versions, "bzip2": ["0.9", "1.0"]}
    with open(os.path.join("config", "conda_build_config.yaml"), "w") as f:
        yaml.dump(config, f, default_flow_style=False)

    cc_conda_build_backup = cc_conda_build.copy()
    # hacky equivalent of changing condarc
    # careful, this is global and affects other tests!  make sure to clear it!
    cc_conda_build.update(
        {"config_file": "${TEST_WORKDIR}/config/conda_build_config.yaml"}
    )

    os.environ["TEST_WORKDIR"] = testing_workdir
    try:
        m = api.render(
            os.path.join(variants_dir, "19_used_variables"),
            bypass_env_check=True,
            finalize=False,
        )[0][0]
        # this one should have gotten clobbered by the values in the recipe
        assert m.config.variant["python"] not in python_versions
        # this confirms that we loaded the config file correctly
        assert len(m.config.squished_variants["bzip2"]) == 2
    finally:
        cc_conda_build.clear()
        cc_conda_build.update(cc_conda_build_backup)


def test_self_reference_run_exports_pin_subpackage_picks_up_version_correctly():
    recipe = os.path.join(metadata_dir, "_self_reference_run_exports")
    m = api.render(recipe)[0][0]
    run_exports = m.meta.get("build", {}).get("run_exports", [])
    assert run_exports
    assert len(run_exports) == 1
    assert run_exports[0].split()[1] == ">=1.0.0,<2.0a0"


def test_run_exports_with_pin_compatible_in_subpackages(testing_config):
    recipe = os.path.join(metadata_dir, "_run_exports_in_outputs")
    ms = api.render(recipe, config=testing_config)
    for m, _, _ in ms:
        if m.name().startswith("gfortran_"):
            run_exports = set(
                m.meta.get("build", {}).get("run_exports", {}).get("strong", [])
            )
            assert len(run_exports) == 1
            # len after splitting should be more than one because of pin_compatible.  If it's only zlib, we've lost the
            #    compatibility bound info.  This is generally due to lack of rendering of an output, such that the
            #    compatibility bounds just aren't added in.
            assert all(len(export.split()) > 1 for export in run_exports), run_exports


def test_ignore_build_only_deps():
    ms = api.render(
        os.path.join(variants_dir, "python_in_build_only"),
        bypass_env_check=True,
        finalize=False,
    )
    assert len(ms) == 1


def test_merge_build_host_build_key():
    m = api.render(os.path.join(metadata_dir, "_no_merge_build_host"))[0][0]
    assert not any("bzip2" in dep for dep in m.meta["requirements"]["run"])


def test_merge_build_host_empty_host_section():
    m = api.render(os.path.join(metadata_dir, "_empty_host_avoids_merge"))[0][0]
    assert not any("bzip2" in dep for dep in m.meta["requirements"]["run"])


def test_pin_expression_works_with_prereleases(testing_config):
    recipe = os.path.join(metadata_dir, "_pinning_prerelease")
    ms = api.render(recipe, config=testing_config)
    assert len(ms) == 2
    m = next(m_[0] for m_ in ms if m_[0].meta["package"]["name"] == "bar")
    assert "foo >=3.10.0.rc1,<3.11.0a0" in m.meta["requirements"]["run"]


def test_pin_expression_works_with_python_prereleases(testing_config):
    recipe = os.path.join(metadata_dir, "_pinning_prerelease_python")
    ms = api.render(recipe, config=testing_config)
    assert len(ms) == 2
    m = next(m_[0] for m_ in ms if m_[0].meta["package"]["name"] == "bar")
    assert "python >=3.10.0rc1,<3.11.0a0" in m.meta["requirements"]["run"]
