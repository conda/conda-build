# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import json
import os
import platform
import re
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from conda.common.compat import on_mac

from conda_build import api, exceptions
from conda_build.metadata import MetaData
from conda_build.utils import ensure_list, package_has_file
from conda_build.variants import (
    combine_specs,
    dict_of_lists_to_list_of_dicts,
    filter_by_key_value,
    filter_combined_spec_to_used_keys,
    find_used_variables_in_batch_script,
    find_used_variables_in_shell_script,
    find_used_variables_in_text,
    get_package_variants,
    get_vars,
    list_of_dicts_to_dict_of_lists,
    validate_spec,
)

from .utils import variants_dir


@pytest.mark.parametrize(
    "variants",
    [
        (["1.2", "3.4"], "5.6"),
        ("1.2", ["3.4", "5.6"]),
    ],
)
def test_spec_priority_overriding(variants):
    name = "package"

    first, second = variants
    ordered_specs = {
        "first": {name: first},
        "second": {name: second},
    }

    combined = combine_specs(ordered_specs)[name]
    expected = ensure_list(second)
    assert len(combined) == len(expected)
    assert combined == expected


@pytest.mark.parametrize(
    "as_yaml",
    [
        pytest.param(True, id="yaml"),
        pytest.param(False, id="dict"),
    ],
)
def test_python_variants(testing_workdir, testing_config, as_yaml):
    """Python variants are treated differently in conda recipes. Instead of being pinned against a
    specific version they are converted into version ranges. E.g.:

    python 3.5 -> python >=3.5,<3.6.0a0
    otherPackages 3.5 -> otherPackages 3.5
    """
    variants = {"python": ["3.11", "3.12"]}
    testing_config.ignore_system_config = True

    # write variants to disk
    if as_yaml:
        variants_path = Path(testing_workdir, "variant_example.yaml")
        variants_path.write_text(yaml.dump(variants, default_flow_style=False))
        testing_config.variant_config_files = [str(variants_path)]

    # render the metadata
    metadata_tuples = api.render(
        os.path.join(variants_dir, "variant_recipe"),
        no_download_source=False,
        config=testing_config,
        # if variants were written to disk then don't pass it along
        variants=None if as_yaml else variants,
    )

    # we should have one package/metadata per python version
    assert len(metadata_tuples) == 2

    # Extract *python* run requirements (allow python_abi to exist)
    python_reqs = []
    for meta, _, _ in metadata_tuples:
        run_reqs = meta.meta["requirements"]["run"]
        python_reqs.extend([r for r in run_reqs if r.startswith("python ")])

    # We expect exactly two python requirements, one per variant
    assert len(python_reqs) == 2, f"Expected 2 python requirements, got {python_reqs}"

    # Check that the python requirements match the expected ranges
    expected = {
        "python >=3.11,<3.12.0a0",
        "python >=3.12,<3.13.0a0",
    }
    python_reqs_set = set(python_reqs)
    assert python_reqs_set == expected


def test_use_selectors_in_variants(testing_workdir, testing_config):
    testing_config.variant_config_files = [
        os.path.join(variants_dir, "selector_conda_build_config.yaml")
    ]
    get_package_variants(testing_workdir, testing_config)


@pytest.mark.xfail(
    reason=(
        "7/19/2017 Strange failure. Can't reproduce locally. Test runs fine "
        "with parallelism and everything. Test fails reproducibly on CI, but logging "
        "into appveyor after failed run, test passes."
        "1/9/2023 ignore_version doesn't work as advertised."
    )
)
def test_variant_with_ignore_version_reduces_matrix():
    metadata_tuples = api.render(
        os.path.join(variants_dir, "03_ignore_version_reduces_matrix"),
        variants={
            "packageA": ["1.2", "3.4"],
            "packageB": ["5.6", "7.8"],
            # packageB is ignored so that dimension should get collapsed
            "ignore_version": "packageB",
        },
        finalize=False,
    )
    assert len(metadata_tuples) == 2


def test_variant_with_numpy_pinned_has_matrix():
    recipe = os.path.join(variants_dir, "04_numpy_matrix_pinned")
    metadata_tuples = api.render(recipe, finalize=False)
    assert len(metadata_tuples) == 4


def test_pinning_in_build_requirements():
    recipe = os.path.join(variants_dir, "05_compatible")
    metadata = api.render(recipe)[0][0]
    build_requirements = metadata.meta["requirements"]["build"]
    # make sure that everything in the build deps is exactly pinned
    assert all(len(req.split(" ")) == 3 for req in build_requirements)


@pytest.mark.sanity
def test_no_satisfiable_variants_raises_error():
    recipe = os.path.join(variants_dir, "01_basic_templating")
    with pytest.raises(exceptions.DependencyNeedsBuildingError):
        api.render(recipe, permit_unsatisfiable_variants=False)
    api.render(recipe, permit_unsatisfiable_variants=True)


def test_zip_fields():
    """Zipping keys together allows people to tie different versions as sets of combinations."""
    variants = {
        "packageA": ["1.2", "3.4"],
        "packageB": ["5", "6"],
        "zip_keys": [("packageA", "packageB")],
    }
    zipped = dict_of_lists_to_list_of_dicts(variants)
    assert len(zipped) == 2
    assert zipped[0]["packageA"] == "1.2"
    assert zipped[0]["packageB"] == "5"
    assert zipped[1]["packageA"] == "3.4"
    assert zipped[1]["packageB"] == "6"

    # allow duplication of values, but lengths of lists must always match
    variants = {
        "packageA": ["1.2", "1.2"],
        "packageB": ["5", "6"],
        "zip_keys": [("packageA", "packageB")],
    }
    zipped = dict_of_lists_to_list_of_dicts(variants)
    assert len(zipped) == 2
    assert zipped[0]["packageA"] == "1.2"
    assert zipped[0]["packageB"] == "5"
    assert zipped[1]["packageA"] == "1.2"
    assert zipped[1]["packageB"] == "6"


def test_validate_spec():
    """
    Basic spec validation checking for bad characters, bad zip_keys, missing keys,
    duplicate keys, and zip_key fields length mismatch.
    """
    spec = {
        # normal expansions
        "foo": [1.2, 3.4],
        # zip_keys are the values that need to be expanded as a set
        "zip_keys": [["bar", "baz"], ["qux", "quux", "quuz"]],
        "bar": [1, 2, 3],
        "baz": [2, 4, 6],
        "qux": [4, 5],
        "quux": [8, 10],
        "quuz": [12, 15],
        # extend_keys are those values which we do not expand
        "extend_keys": ["corge"],
        "corge": 42,
    }
    # valid spec
    validate_spec("spec", spec)

    spec2 = dict(spec)
    spec2["bad-char"] = "bad-char"
    # invalid characters
    with pytest.raises(ValueError):
        validate_spec("spec[bad_char]", spec2)

    spec3 = dict(spec, zip_keys="bad_zip_keys")
    # bad zip_keys
    with pytest.raises(ValueError):
        validate_spec("spec[bad_zip_keys]", spec3)

    spec4 = dict(spec, zip_keys=[["bar", "baz"], ["qux", "quux"], ["quuz", "missing"]])
    # zip_keys' zip_group has key missing from spec
    with pytest.raises(ValueError):
        validate_spec("spec[missing_key]", spec4)

    spec5 = dict(spec, zip_keys=[["bar", "baz"], ["qux", "quux", "quuz"], ["quuz"]])
    # zip_keys' zip_group has duplicate key
    with pytest.raises(ValueError):
        validate_spec("spec[duplicate_key]", spec5)

    spec6 = dict(spec, baz=[4, 6])
    # zip_keys' zip_group key fields have same length
    with pytest.raises(ValueError):
        validate_spec("spec[duplicate_key]", spec6)


def test_cross_compilers():
    recipe = os.path.join(variants_dir, "09_cross")
    metadata_tuples = api.render(
        recipe,
        permit_unsatisfiable_variants=True,
        finalize=False,
        bypass_env_check=True,
    )
    assert len(metadata_tuples) == 3


def test_variants_in_output_names():
    recipe = os.path.join(variants_dir, "11_variant_output_names")
    outputs = api.get_output_file_paths(recipe)
    assert len(outputs) == 4


def test_variants_in_versions_with_setup_py_data():
    recipe = os.path.join(variants_dir, "12_variant_versions")
    outputs = api.get_output_file_paths(recipe)
    assert len(outputs) == 2
    assert any(
        os.path.basename(pkg).startswith("my_package-470.470") for pkg in outputs
    )
    assert any(
        os.path.basename(pkg).startswith("my_package-480.480") for pkg in outputs
    )


def test_git_variables_with_variants(testing_config):
    recipe = os.path.join(variants_dir, "13_git_vars")
    metadata = api.render(
        recipe, config=testing_config, finalize=False, bypass_env_check=True
    )[0][0]
    assert metadata.version() == "1.20.2"
    assert metadata.build_number() == 0


def test_variant_input_with_zip_keys_keeps_zip_keys_list():
    spec = {
        "scipy": ["0.17", "0.19"],
        "sqlite": ["3"],
        "zlib": ["1.2"],
        "xz": ["5"],
        "zip_keys": ["sqlite", "zlib", "xz"],
        "pin_run_as_build": {"python": {"min_pin": "x.x", "max_pin": "x.x"}},
    }
    vrnts = dict_of_lists_to_list_of_dicts(spec)
    assert len(vrnts) == 2
    assert vrnts[0].get("zip_keys") == spec["zip_keys"]


@pytest.mark.serial
@pytest.mark.xfail(sys.platform == "win32", reason="console readout issues on appveyor")
def test_ensure_valid_spec_on_run_and_test(testing_config, caplog):
    testing_config.debug = True
    testing_config.verbose = True
    recipe = os.path.join(variants_dir, "14_variant_in_run_and_test")
    api.render(recipe, config=testing_config)

    text = caplog.text
    assert "Adding .* to spec 'pytest  3.2'" in text
    assert "Adding .* to spec 'click  6'" in text
    assert "Adding .* to spec 'pytest-cov  2.3'" not in text
    assert "Adding .* to spec 'pytest-mock  1.6'" not in text


@pytest.mark.skipif(
    on_mac and platform.machine() == "arm64",
    reason="Unsatisfiable dependencies for M1 MacOS: {'bzip2=1.0.6'}",
)
def test_serial_builds_have_independent_configs(testing_config):
    recipe = os.path.join(variants_dir, "17_multiple_recipes_independent_config")
    recipes = [os.path.join(recipe, dirname) for dirname in ("a", "b")]
    outputs = api.build(recipes, config=testing_config)
    index_json = json.loads(package_has_file(outputs[0], "info/index.json"))
    assert "bzip2 >=1,<1.0.7.0a0" in index_json["depends"]
    index_json = json.loads(package_has_file(outputs[1], "info/index.json"))
    assert "bzip2 >=1.0.6,<2.0a0" in index_json["depends"]


def test_subspace_selection(testing_config):
    recipe = os.path.join(variants_dir, "18_subspace_selection")
    testing_config.variant = {"a": "coffee"}
    metadata_tuples = api.render(
        recipe, config=testing_config, finalize=False, bypass_env_check=True
    )
    # there are two entries with a==coffee, so we should end up with 2 variants
    assert len(metadata_tuples) == 2
    # ensure that the zipped keys still agree
    assert (
        sum(metadata.config.variant["b"] == "123" for metadata, _, _ in metadata_tuples)
        == 1
    )
    assert (
        sum(metadata.config.variant["b"] == "abc" for metadata, _, _ in metadata_tuples)
        == 1
    )
    assert (
        sum(
            metadata.config.variant["b"] == "concrete"
            for metadata, _, _ in metadata_tuples
        )
        == 0
    )
    assert (
        sum(
            metadata.config.variant["c"] == "mooo" for metadata, _, _ in metadata_tuples
        )
        == 1
    )
    assert (
        sum(
            metadata.config.variant["c"] == "baaa" for metadata, _, _ in metadata_tuples
        )
        == 1
    )
    assert (
        sum(
            metadata.config.variant["c"] == "woof" for metadata, _, _ in metadata_tuples
        )
        == 0
    )

    # test compound selection
    testing_config.variant = {"a": "coffee", "b": "123"}
    metadata_tuples = api.render(
        recipe, config=testing_config, finalize=False, bypass_env_check=True
    )
    # there are two entries with a==coffee, but one with both 'coffee' for a, and '123' for b,
    #     so we should end up with 1 variants
    assert len(metadata_tuples) == 1
    # ensure that the zipped keys still agree
    assert (
        sum(metadata.config.variant["b"] == "123" for metadata, _, _ in metadata_tuples)
        == 1
    )
    assert (
        sum(metadata.config.variant["b"] == "abc" for metadata, _, _ in metadata_tuples)
        == 0
    )
    assert (
        sum(
            metadata.config.variant["b"] == "concrete"
            for metadata, _, _ in metadata_tuples
        )
        == 0
    )
    assert (
        sum(
            metadata.config.variant["c"] == "mooo" for metadata, _, _ in metadata_tuples
        )
        == 1
    )
    assert (
        sum(
            metadata.config.variant["c"] == "baaa" for metadata, _, _ in metadata_tuples
        )
        == 0
    )
    assert (
        sum(
            metadata.config.variant["c"] == "woof" for metadata, _, _ in metadata_tuples
        )
        == 0
    )

    # test when configuration leads to no valid combinations - only c provided, and its value
    #   doesn't match any other existing values of c, so it's then ambiguous which zipped
    #   values to choose
    testing_config.variant = {"c": "not an animal"}
    with pytest.raises(ValueError):
        api.render(recipe, config=testing_config, finalize=False, bypass_env_check=True)

    # all zipped keys provided by the new variant.  It should clobber the old one.
    testing_config.variant = {"a": "some", "b": "new", "c": "animal"}
    metadata_tuples = api.render(
        recipe, config=testing_config, finalize=False, bypass_env_check=True
    )
    assert len(metadata_tuples) == 1
    assert metadata_tuples[0][0].config.variant["a"] == "some"
    assert metadata_tuples[0][0].config.variant["b"] == "new"
    assert metadata_tuples[0][0].config.variant["c"] == "animal"


def test_get_used_loop_vars():
    metadata = api.render(
        os.path.join(variants_dir, "19_used_variables"),
        finalize=False,
        bypass_env_check=True,
    )[0][0]
    # conda_build_config.yaml has 4 loop variables defined, but only 3 are used.
    #   python and zlib are both implicitly used (depend on name matching), while
    #   some_package is explicitly used as a jinja2 variable
    assert metadata.get_used_loop_vars() == {"python", "some_package"}
    # these are all used vars - including those with only one value (and thus not loop vars)
    assert metadata.get_used_vars() == {
        "python",
        "some_package",
        "zlib",
        "pthread_stubs",
        "target_platform",
        "cdt_name",
        "cdt_arch",
    }


def test_get_used_loop_vars_jinja2():
    metadata = api.render(
        os.path.join(variants_dir, "jinja2_used_variables"),
        finalize=False,
        bypass_env_check=True,
    )
    # 4 CLANG_VERSION values x 2 VCVER values - one skipped because of jinja2 conditionals
    assert len(metadata) == 7
    for m, _, _ in metadata:
        assert m.get_used_loop_vars(force_top_level=False) == {"CLANG_VERSION", "VCVER"}
        assert m.get_used_loop_vars(force_top_level=True) == {
            "CL_VERSION",
            "CLANG_VERSION",
            "VCVER",
        }
        assert m.get_used_vars(force_top_level=False) == {
            "CLANG_VERSION",
            "VCVER",
            "FOO",
            "target_platform",
        }
        assert m.get_used_vars(force_top_level=True) == {
            "CLANG_VERSION",
            "CL_VERSION",
            "VCVER",
            "FOO",
            "FOOBAR",
            "target_platform",
        }


def test_reprovisioning_source():
    api.render(os.path.join(variants_dir, "20_reprovision_source"))


def test_reduced_hashing_behavior(testing_config):
    # recipes using any compiler jinja2 function need a hash
    metadata = api.render(
        os.path.join(variants_dir, "26_reduced_hashing", "hash_yes_compiler"),
        finalize=False,
        bypass_env_check=True,
    )[0][0]
    assert "c_compiler" in metadata.get_hash_contents(), (
        "hash contents should contain c_compiler"
    )
    assert re.search(
        "h[0-9a-f]{%d}" % testing_config.hash_length,  # noqa: UP031
        metadata.build_id(),
    ), "hash should be present when compiler jinja2 function is used"

    # recipes that use some variable in conda_build_config.yaml to control what
    #     versions are present at build time also must have a hash (except
    #     python, r_base, and the other stuff covered by legacy build string
    #     behavior)
    metadata = api.render(
        os.path.join(variants_dir, "26_reduced_hashing", "hash_yes_pinned"),
        finalize=False,
        bypass_env_check=True,
    )[0][0]
    assert "zlib" in metadata.get_hash_contents()
    assert re.search("h[0-9a-f]{%d}" % testing_config.hash_length, metadata.build_id())  # noqa: UP031

    # anything else does not get a hash
    metadata = api.render(
        os.path.join(variants_dir, "26_reduced_hashing", "hash_no_python"),
        finalize=False,
        bypass_env_check=True,
    )[0][0]
    assert not metadata.get_hash_contents()
    assert not re.search(
        "h[0-9a-f]{%d}" % testing_config.hash_length,  # noqa: UP031
        metadata.build_id(),
    )


def test_variants_used_in_jinja2_conditionals():
    metadata_tuples = api.render(
        os.path.join(variants_dir, "21_conditional_sections"),
        finalize=False,
        bypass_env_check=True,
    )
    assert len(metadata_tuples) == 2
    assert (
        sum(
            metadata.config.variant["blas_impl"] == "mkl"
            for metadata, _, _ in metadata_tuples
        )
        == 1
    )
    assert (
        sum(
            metadata.config.variant["blas_impl"] == "openblas"
            for metadata, _, _ in metadata_tuples
        )
        == 1
    )


def test_build_run_exports_act_on_host(caplog):
    """Regression test for https://github.com/conda/conda-build/issues/2559"""
    api.render(
        os.path.join(variants_dir, "22_run_exports_rerendered_for_other_variants"),
        platform="win",
        arch="64",
    )
    assert "failed to get package records, retrying" not in caplog.text


def test_detect_variables_in_build_and_output_scripts():
    metadata_tuples = api.render(
        os.path.join(variants_dir, "24_test_used_vars_in_scripts"),
        platform="linux",
        arch="64",
    )
    for metadata, _, _ in metadata_tuples:
        if metadata.name() == "test_find_used_variables_in_scripts":
            used_vars = metadata.get_used_vars()
            assert used_vars
            assert "SELECTOR_VAR" in used_vars
            assert "OUTPUT_SELECTOR_VAR" not in used_vars
            assert "BASH_VAR1" in used_vars
            assert "BASH_VAR2" in used_vars
            assert "BAT_VAR" not in used_vars
            assert "OUTPUT_VAR" not in used_vars
        else:
            used_vars = metadata.get_used_vars()
            assert used_vars
            assert "SELECTOR_VAR" not in used_vars
            assert "OUTPUT_SELECTOR_VAR" in used_vars
            assert "BASH_VAR1" not in used_vars
            assert "BASH_VAR2" not in used_vars
            assert "BAT_VAR" not in used_vars
            assert "OUTPUT_VAR" in used_vars
    # on windows, we find variables in bat scripts as well as shell scripts
    metadata_tuples = api.render(
        os.path.join(variants_dir, "24_test_used_vars_in_scripts"),
        platform="win",
        arch="64",
    )
    for metadata, _, _ in metadata_tuples:
        if metadata.name() == "test_find_used_variables_in_scripts":
            used_vars = metadata.get_used_vars()
            assert used_vars
            assert "SELECTOR_VAR" in used_vars
            assert "OUTPUT_SELECTOR_VAR" not in used_vars
            assert "BASH_VAR1" in used_vars
            assert "BASH_VAR2" in used_vars
            # bat is in addition to bash, not instead of
            assert "BAT_VAR" in used_vars
            assert "OUTPUT_VAR" not in used_vars
        else:
            used_vars = metadata.get_used_vars()
            assert used_vars
            assert "SELECTOR_VAR" not in used_vars
            assert "OUTPUT_SELECTOR_VAR" in used_vars
            assert "BASH_VAR1" not in used_vars
            assert "BASH_VAR2" not in used_vars
            assert "BAT_VAR" not in used_vars
            assert "OUTPUT_VAR" in used_vars


def test_target_platform_looping():
    outputs = api.get_output_file_paths(
        os.path.join(variants_dir, "25_target_platform_looping"),
        platform="win",
        arch="64",
    )
    assert len(outputs) == 2


def test_numpy_used_variable_looping():
    outputs = api.get_output_file_paths(os.path.join(variants_dir, "numpy_used"))
    assert len(outputs) == 4


def test_exclusive_config_files():
    with open("conda_build_config.yaml", "w") as f:
        yaml.dump({"abc": ["someval"], "cwd": ["someval"]}, f, default_flow_style=False)
    os.makedirs("config_dir")
    with open(os.path.join("config_dir", "config-0.yaml"), "w") as f:
        yaml.dump(
            {"abc": ["super_0"], "exclusive_0": ["0"], "exclusive_both": ["0"]},
            f,
            default_flow_style=False,
        )
    with open(os.path.join("config_dir", "config-1.yaml"), "w") as f:
        yaml.dump(
            {"abc": ["super_1"], "exclusive_1": ["1"], "exclusive_both": ["1"]},
            f,
            default_flow_style=False,
        )
    exclusive_config_files = (
        os.path.join("config_dir", "config-0.yaml"),
        os.path.join("config_dir", "config-1.yaml"),
    )
    metadata = api.render(
        os.path.join(variants_dir, "exclusive_config_file"),
        exclusive_config_files=exclusive_config_files,
    )[0][0]
    variant = metadata.config.variant
    # is cwd ignored?
    assert "cwd" not in variant
    # did we load the exclusive configs?
    assert variant["exclusive_0"] == "0"
    assert variant["exclusive_1"] == "1"
    # does later exclusive config override initial one?
    assert variant["exclusive_both"] == "1"
    # does recipe config override exclusive?
    assert "unique_to_recipe" in variant
    assert variant["abc"] == "123"


def test_exclusive_config_file():
    with open("conda_build_config.yaml", "w") as f:
        yaml.dump({"abc": ["someval"], "cwd": ["someval"]}, f, default_flow_style=False)
    os.makedirs("config_dir")
    with open(os.path.join("config_dir", "config.yaml"), "w") as f:
        yaml.dump(
            {"abc": ["super"], "exclusive": ["someval"]}, f, default_flow_style=False
        )
    metadata = api.render(
        os.path.join(variants_dir, "exclusive_config_file"),
        exclusive_config_file=os.path.join("config_dir", "config.yaml"),
    )[0][0]
    variant = metadata.config.variant
    # is cwd ignored?
    assert "cwd" not in variant
    # did we load the exclusive config
    assert "exclusive" in variant
    # does recipe config override exclusive?
    assert "unique_to_recipe" in variant
    assert variant["abc"] == "123"


@pytest.mark.skipif(
    on_mac and platform.machine() == "arm64",
    reason="M1 Mac-specific file system error related to this test",
)
def test_inner_python_loop_with_output(testing_config):
    outputs = api.get_output_file_paths(
        os.path.join(variants_dir, "test_python_as_subpackage_loop"),
        config=testing_config,
    )
    outputs = [os.path.basename(out) for out in outputs]
    assert len(outputs) == 5
    assert len([out for out in outputs if out.startswith("tbb-2018")]) == 1
    assert len([out for out in outputs if out.startswith("tbb-devel-2018")]) == 1
    assert len([out for out in outputs if out.startswith("tbb4py-2018")]) == 3

    testing_config.variant_config_files = [
        os.path.join(
            variants_dir, "test_python_as_subpackage_loop", "config_with_zip.yaml"
        )
    ]
    outputs = api.get_output_file_paths(
        os.path.join(variants_dir, "test_python_as_subpackage_loop"),
        config=testing_config,
    )
    outputs = [os.path.basename(out) for out in outputs]
    assert len(outputs) == 5
    assert len([out for out in outputs if out.startswith("tbb-2018")]) == 1
    assert len([out for out in outputs if out.startswith("tbb-devel-2018")]) == 1
    assert len([out for out in outputs if out.startswith("tbb4py-2018")]) == 3

    testing_config.variant_config_files = [
        os.path.join(
            variants_dir, "test_python_as_subpackage_loop", "config_with_zip.yaml"
        )
    ]
    outputs = api.get_output_file_paths(
        os.path.join(variants_dir, "test_python_as_subpackage_loop"),
        config=testing_config,
        platform="win",
        arch=64,
    )
    outputs = [os.path.basename(out) for out in outputs]
    assert len(outputs) == 5
    assert len([out for out in outputs if out.startswith("tbb-2018")]) == 1
    assert len([out for out in outputs if out.startswith("tbb-devel-2018")]) == 1
    assert len([out for out in outputs if out.startswith("tbb4py-2018")]) == 3


def test_variant_as_dependency_name(testing_config):
    metadata_tuples = api.render(
        os.path.join(variants_dir, "27_requirements_host"), config=testing_config
    )
    assert len(metadata_tuples) == 2


def test_custom_compiler():
    recipe = os.path.join(variants_dir, "28_custom_compiler")
    metadata_tuples = api.render(
        recipe,
        permit_unsatisfiable_variants=True,
        finalize=False,
        bypass_env_check=True,
    )
    assert len(metadata_tuples) == 3


def test_different_git_vars():
    recipe = os.path.join(variants_dir, "29_different_git_vars")
    metadata_tuples = api.render(recipe)
    versions = [metadata[0].version() for metadata in metadata_tuples]
    assert "1.20.0" in versions
    assert "1.21.11" in versions


@pytest.mark.skipif(
    sys.platform != "linux", reason="recipe uses a unix specific script"
)
def test_top_level_finalized(testing_config):
    # see https://github.com/conda/conda-build/issues/3618
    recipe = os.path.join(variants_dir, "30_top_level_finalized")
    outputs = api.build(recipe, config=testing_config)
    xzcat_output = package_has_file(outputs[0], "xzcat_output")
    assert "5.6" in xzcat_output


def test_variant_subkeys_retained():
    metadata = api.render(
        os.path.join(variants_dir, "31_variant_subkeys"),
        finalize=False,
        bypass_env_check=True,
    )[0][0]
    found_replacements = False
    from conda_build.build import get_all_replacements

    for variant in metadata.config.variants:
        found_replacements = get_all_replacements(variant)
    assert len(found_replacements), "Did not find replacements"
    metadata.final = False
    outputs = metadata.get_output_metadata_set(permit_unsatisfiable_variants=False)
    get_all_replacements(outputs[0][1].config.variant)


@pytest.mark.parametrize(
    "internal_defaults, low_prio_config, high_prio_config, expected",
    [
        pytest.param(
            {"pkg_1": "1.0"},
            {"pkg_1": "1.1"},
            {"pkg_1": ["1.1", "1.2"], "pkg_2": ["1.1"]},
            [{"pkg_1": "1.1", "pkg_2": "1.1"}, {"pkg_1": "1.2", "pkg_2": "1.1"}],
            id="basic",
        ),
        pytest.param(
            {"pkg_1": "1.0"},
            {"pkg_1": "1.1"},
            {
                "pkg_1": ["1.1", "1.2"],
                "pkg_2": ["1.1", "1.2"],
                "zip_keys": [["pkg_1", "pkg_2"]],
            },
            [
                {"pkg_1": "1.1", "pkg_2": "1.1", "zip_keys": [["pkg_1", "pkg_2"]]},
                {"pkg_1": "1.2", "pkg_2": "1.2", "zip_keys": [["pkg_1", "pkg_2"]]},
            ],
            id="zip_keys",
        ),
    ],
)
def test_zip_key_filtering(
    internal_defaults, low_prio_config, high_prio_config, expected
):
    combined_spec = {
        **low_prio_config,
        **high_prio_config,
    }
    specs = {
        "internal_defaults": internal_defaults,
        "low_prio_config": low_prio_config,
        "high_prio_config": high_prio_config,
    }

    assert filter_combined_spec_to_used_keys(combined_spec, specs=specs) == expected


def test_get_vars():
    variants = [
        {
            "python": "3.12",
            "nodejs": "20",
            "zip_keys": [],  # ignored
        },
        {"python": "3.12", "nodejs": "18"},
        {"python": "3.12", "nodejs": "20"},
    ]

    assert get_vars(variants) == {"nodejs"}


@pytest.mark.parametrize(
    "vars,text,found_vars",
    [
        # basic tests
        (
            ("python", "python_min"),
            "{{ python }}",
            {"python"},
        ),
        (
            ("python", "python_min"),
            "{{ python_min }}",
            {"python_min"},
        ),
        (
            ("python", "python_min"),
            "{{python_min}}",
            {"python_min"},
        ),
        # filters and other text
        (
            ("python", "python_min"),
            "python {{ python_min }}",
            {"python_min"},
        ),
        (
            ("python", "python_min"),
            "python {{ python }}",
            {"python"},
        ),
        (
            ("python", "python_min"),
            "python {{ python|lower }}",
            {"python"},
        ),
        (
            ("python", "python_min"),
            "{{ python_min|lower }}",
            {"python_min"},
        ),
        (
            ("python", "python_min"),
            "{{python_min|lower}}",
            {"python_min"},
        ),
        # pin_* statements
        (
            ("python", "python_min"),
            "{{ pin_compatible('python') }}",
            {"python"},
        ),
        (
            ("python", "python_min"),
            "{{ pin_compatible('python', max_pin='x.x') }}",
            {"python"},
        ),
        (
            ("python", "python_min"),
            "{{ pin_compatible('python_min') }}",
            {"python_min"},
        ),
        (
            ("python", "python_min"),
            "{{ pin_compatible('python_min', max_pin='x.x') }}",
            {"python_min"},
        ),
        (
            ("python", "python_min"),
            "{{pin_compatible('python_min', max_pin='x.x')}}",
            {"python_min"},
        ),
        (
            ("zlib", "ace"),
            "{% set p = zlib.replace('.', '') %}",
            {"zlib"},
        ),
        (
            ("zlib", "xz", "ace"),
            "{% set p = azlib.replace('.', '') ~ xz ~ 'a' %}",
            {"xz"},
        ),
        (
            ("zlib", "xz", "ace"),
            "{%set p = azlib.replace('.', '') ~ xz ~ 'a'%}",
            {"xz"},
        ),
    ],
)
def test_find_used_variables_in_text(vars, text, found_vars):
    assert find_used_variables_in_text(vars, text) == found_vars


def test_find_used_variables_in_shell_script(tmp_path: Path) -> None:
    variants = ("FOO", "BAR", "BAZ", "QUX")
    (script := tmp_path / "script.sh").write_text(
        f"${variants[0]}\n${{{variants[1]}}}\n${{{{{variants[2]}}}}}\n$${variants[3]}\n"
    )
    assert find_used_variables_in_shell_script(variants, script) == {"FOO", "BAR"}


def test_find_used_variables_in_batch_script(tmp_path: Path) -> None:
    variants = ("FOO", "BAR", "BAZ", "QUX")
    (script := tmp_path / "script.sh").write_text(
        f"%{variants[0]}%\n%%{variants[1]}%%\n${variants[2]}\n${{{variants[3]}}}\n"
    )
    assert find_used_variables_in_batch_script(variants, script) == {"FOO", "BAR"}


def test_combine_specs_zip_lengths():
    from collections import OrderedDict

    # test case extracted from issue #5416
    specs = OrderedDict(
        [
            (
                "internal_defaults",
                {
                    "c_compiler": "gcc",
                    "cpu_optimization_target": "nocona",
                    "cran_mirror": "https://cran.r-project.org",
                    "cxx_compiler": "gxx",
                    "extend_keys": [
                        "pin_run_as_build",
                        "ignore_version",
                        "ignore_build_only_deps",
                        "extend_keys",
                    ],
                    "fortran_compiler": "gfortran",
                    "ignore_build_only_deps": ["python", "numpy"],
                    "ignore_version": [],
                    "lua": "5",
                    "numpy": "1.23",
                    "perl": "5.26.2",
                    "pin_run_as_build": {
                        "python": {"max_pin": "x.x", "min_pin": "x.x"},
                        "r-base": {"max_pin": "x.x", "min_pin": "x.x"},
                    },
                    "python": "3.11",
                    "r_base": "3.5",
                    "target_platform": "linux-64",
                },
            ),
            (
                "/tmp/tmp0wue6mdn/info/recipe/conda_build_config.yaml",
                {
                    "VERBOSE_AT": "V=1",
                    "VERBOSE_CM": "VERBOSE=1",
                    "blas_impl": "openblas",
                    "boost": "1.82",
                    "boost_cpp": "1.82",
                    "bzip2": "1.0",
                    "c_compiler": "gcc",
                    "c_compiler_version": "11.2.0",
                    "cairo": "1.16",
                    "channel_targets": "defaults",
                    "clang_variant": "clang",
                    "cpu_optimization_target": "nocona",
                    "cran_mirror": "https://mran.microsoft.com/snapshot/2018-01-01",
                    "cuda_compiler": "cuda-nvcc",
                    "cuda_compiler_version": "12.4",
                    "cudatoolkit": "11.8",
                    "cudnn": "8.9.2.26",
                    "cxx_compiler": "gxx",
                    "cxx_compiler_version": "11.2.0",
                    "cyrus_sasl": "2.1.28",
                    "dbus": "1",
                    "expat": "2",
                    "extend_keys": [
                        "pin_run_as_build",
                        "extend_keys",
                        "ignore_build_only_deps",
                        "ignore_version",
                    ],
                    "fontconfig": "2.14",
                    "fortran_compiler": "gfortran",
                    "fortran_compiler_version": "11.2.0",
                    "freetype": "2.10",
                    "g2clib": "1.6",
                    "geos": "3.8.0",
                    "giflib": "5",
                    "glib": "2",
                    "gmp": "6.2",
                    "gnu": "2.12.2",
                    "gpu_variant": "cuda-11",
                    "gst_plugins_base": "1.14",
                    "gstreamer": "1.14",
                    "harfbuzz": "4.3.0",
                    "hdf4": "4.2",
                    "hdf5": "1.12.1",
                    "hdfeos2": "2.20",
                    "hdfeos5": "5.1",
                    "icu": "73",
                    "ignore_build_only_deps": ["python", "numpy"],
                    "jpeg": "9",
                    "libcurl": "8.1.1",
                    "libdap4": "3.19",
                    "libffi": "3.4",
                    "libgd": "2.3.3",
                    "libgdal": "3.6.2",
                    "libgsasl": "1.10",
                    "libkml": "1.3",
                    "libnetcdf": "4.8",
                    "libpng": "1.6",
                    "libprotobuf": "3.20.3",
                    "libtiff": "4.2",
                    "libwebp": "1.3.2",
                    "libxml2": "2.10",
                    "libxslt": "1.1",
                    "llvm_variant": "llvm",
                    "lua": "5",
                    "lzo": "2",
                    "mkl": "2023.*",
                    "mpfr": "4",
                    "numpy": "1.21",
                    "openblas": "0.3.21",
                    "openjpeg": "2.3",
                    "openssl": "3.0",
                    "perl": "5.34",
                    "pin_run_as_build": {
                        "libboost": {"max_pin": "x.x.x"},
                        "python": {"max_pin": "x.x", "min_pin": "x.x"},
                        "r-base": {"max_pin": "x.x", "min_pin": "x.x"},
                    },
                    "pixman": "0.40",
                    "proj": "9.3.1",
                    "proj4": "5.2.0",
                    "python": "3.9",
                    "python_impl": "cpython",
                    "python_implementation": "cpython",
                    "r_base": "3.5",
                    "r_implementation": "r-base",
                    "r_version": "3.5.0",
                    "readline": "8.1",
                    "rust_compiler": "rust",
                    "rust_compiler_version": "1.71.1",
                    "sqlite": "3",
                    "target_platform": "linux-64",
                    "tk": "8.6",
                    "xz": "5",
                    "zip_keys": [["python", "numpy"]],
                    "zlib": "1.2",
                    "zstd": "1.5.2",
                },
            ),
            (
                "config.variant",
                {
                    "__cuda": "__cuda >=11.8",
                    "blas_impl": "openblas",
                    "c_compiler": "gcc",
                    "c_compiler_version": "11.2.0",
                    "channel_targets": "defaults",
                    "cudatoolkit": "11.8",
                    "cudnn": "8.9.2.26",
                    "cxx_compiler": "gxx",
                    "cxx_compiler_version": "11.2.0",
                    "gpu_variant": "cuda-11",
                    "libprotobuf": "3.20.3",
                    "numpy": "1.21",
                    "openblas": "0.3.21",
                    "target_platform": "linux-64",
                },
            ),
        ]
    )

    combine_specs(specs, log_output=True)


def test_list_of_dicts_to_dict_of_lists():
    variants = [
        {
            "python": "3.11",
            "numpy": "2",
            "c_compiler": "gcc",
            "channels": ["conda-forge"],
            "pin_run_as_build": {"python": {"max_pin": "x.x"}},
            "zip_keys": [["python", "numpy"]],
        },
        {
            "python": "3.12",
            "numpy": "2",
            "c_compiler": "gcc",
            "channels": ["conda-forge", "local"],
            "pin_run_as_build": {"numpy": {"max_pin": "x"}},
            "zip_keys": [["python", "numpy"]],
        },
        {
            "python": "3.12",
            "numpy": "2",
            "c_compiler": "clang",
            "channels": ["conda-forge"],
            "pin_run_as_build": {"python": {"max_pin": "x.x"}},
            "zip_keys": [["python", "numpy"]],
        },
    ]
    squished = list_of_dicts_to_dict_of_lists(variants)
    assert list(squished) == [
        "python",
        "numpy",
        "c_compiler",
        "channels",
        "pin_run_as_build",
        "zip_keys",
    ]
    # zipped keys are deduplicated together, keeping the pairs
    assert sorted(zip(squished["python"], squished["numpy"])) == [
        ("3.11", "2"),
        ("3.12", "2"),
    ]
    assert sorted(squished["c_compiler"]) == ["clang", "gcc"]
    assert isinstance(squished["c_compiler"], list)
    assert squished["channels"] == {"conda-forge", "local"}
    assert squished["pin_run_as_build"] == {
        "python": {"max_pin": "x.x"},
        "numpy": {"max_pin": "x"},
    }
    assert squished["zip_keys"] == [["python", "numpy"]]


def test_list_of_dicts_to_dict_of_lists_uneven_keys():
    variants = [
        {"python": "3.11", "cuda": None},
        {"python": "3.12", "blas": "openblas"},
        {"python": "3.12", "cuda": "12", "blas": ["mkl"]},
    ]
    squished = list_of_dicts_to_dict_of_lists(variants)
    assert list(squished) == ["python", "cuda", "blas", "zip_keys"]
    assert sorted(squished["python"]) == ["3.11", "3.12"]
    # None adds no value
    assert squished["cuda"] == ["12"]
    # a list value turns the collected values into a set
    assert squished["blas"] == {"openblas", "mkl"}
    assert squished["zip_keys"] == []


def test_list_of_dicts_to_dict_of_lists_empty():
    assert list_of_dicts_to_dict_of_lists([]) is None


@pytest.mark.parametrize(
    "values, expected_type",
    [
        pytest.param(["3.11", ["3.12"]], set, id="scalar-list"),
        pytest.param([["3.11"], "3.12"], list, id="list-scalar"),
        pytest.param(["3.11", ["3.12"], "3.11"], list, id="scalar-list-scalar"),
    ],
)
def test_list_of_dicts_to_dict_of_lists_mixed_values(values, expected_type):
    variants = [{"python": value} for value in values]

    squished = list_of_dicts_to_dict_of_lists(variants)

    assert isinstance(squished["python"], expected_type)
    assert len(squished["python"]) == 2
    assert set(squished["python"]) == {"3.11", "3.12"}


def test_list_of_dicts_to_dict_of_lists_passthrough_values():
    variants = [
        {
            "ignore_build_only_deps": ["python", "numpy"],
            "pin_run_as_build": {"python": {"max_pin": "x.x"}},
        },
        {
            "ignore_build_only_deps": ["numpy", "setuptools"],
            "pin_run_as_build": {"numpy": {"max_pin": "x.x"}},
        },
        {
            "ignore_build_only_deps": [],
            "pin_run_as_build": {"python": {"max_pin": "x"}},
        },
    ]
    original = deepcopy(variants)

    squished = list_of_dicts_to_dict_of_lists(variants)

    assert squished["ignore_build_only_deps"] == {"python", "numpy", "setuptools"}
    assert squished["pin_run_as_build"] == {
        "python": {"max_pin": "x"},
        "numpy": {"max_pin": "x.x"},
    }
    assert variants == original


def test_list_of_dicts_to_dict_of_lists_multiple_zip_groups():
    variants = dict_of_lists_to_list_of_dicts(
        {
            "python": ["3.11", "3.12", "3.13"],
            "is_python_min": ["true", "false", "false"],
            "c_compiler": ["gcc", "clang"],
            "c_compiler_version": ["14", "19"],
            "blas_impl": ["openblas", "mkl"],
            "zip_keys": [
                ["python", "is_python_min"],
                ["c_compiler", "c_compiler_version"],
            ],
        }
    )
    original = deepcopy(variants)
    assert len(variants) == 12

    squished = list_of_dicts_to_dict_of_lists(variants)

    assert len(squished["python"]) == len(squished["is_python_min"]) == 3
    assert set(zip(squished["python"], squished["is_python_min"])) == {
        ("3.11", "true"),
        ("3.12", "false"),
        ("3.13", "false"),
    }
    assert len(squished["c_compiler"]) == len(squished["c_compiler_version"]) == 2
    assert set(zip(squished["c_compiler"], squished["c_compiler_version"])) == {
        ("gcc", "14"),
        ("clang", "19"),
    }
    assert set(squished["blas_impl"]) == {"openblas", "mkl"}
    assert squished["zip_keys"] == [
        ["python", "is_python_min"],
        ["c_compiler", "c_compiler_version"],
    ]
    assert variants == original


@pytest.mark.benchmark
@pytest.mark.parametrize("size", [1000, 4000])
@pytest.mark.parametrize("kind", ["zipped", "scalar", "list"])
def test_list_of_dicts_to_dict_of_lists_benchmark(size, kind):
    variants = [{"version": str(i)} for i in range(size)]
    if kind == "zipped":
        for i, variant in enumerate(variants):
            variant["abi"] = str(i % 2)
            variant["zip_keys"] = [["version", "abi"]]
    elif kind == "list":
        for variant in variants:
            variant["version"] = [variant["version"]]

    squished = list_of_dicts_to_dict_of_lists(variants)

    assert len(squished["version"]) == size


def test_get_vars_compares_mixed_types():
    variants = [
        {"python": "3.12", "numpy": 2, "build": "1", "zip_keys": []},
        {"python": "3.12", "numpy": "2", "build": "1", "zip_keys": []},
    ]
    # 2 != "2", whichever side compares
    assert get_vars(variants) == {"numpy"}
    assert get_vars(variants, subset={"python", "build"}) == set()


def test_filter_by_key_value():
    variants = [
        {"python": "3.11"},
        {"python": "3.12"},
        {"python": None},
        {"numpy": "2"},
    ]
    assert filter_by_key_value(variants, "python", ["3.12"], "test") == [
        {"python": "3.12"}
    ]
    # a dict of values selects nothing out
    assert filter_by_key_value(variants, "python", {"3.12": 1}, "test") is variants


def _used_projection(variants, used_vars):
    return sorted(
        json.dumps({k: v for k, v in variant.items() if k in used_vars}, sort_keys=True)
        for variant in variants
    )


@pytest.mark.parametrize(
    "specs, used_vars, varying_vars",
    [
        pytest.param(
            {
                "internal_defaults": {"python": "3.12"},
                "config": {
                    "python": ["3.11", "3.12"],
                    "unused_1": ["a", "b", "c"],
                    "unused_2": ["1", "2"],
                },
            },
            {"python"},
            {"python"},
            id="basic",
        ),
        pytest.param(
            {
                "internal_defaults": {},
                "config": {
                    "used": ["1", "2"],
                    "zipped": ["x", "y"],
                    "unused_1": ["a", "b"],
                    "unused_2": ["c", "d"],
                    "zip_keys": [["used", "zipped"], ["unused_1", "unused_2"]],
                },
            },
            {"used"},
            {"used", "zipped"},
            id="zip_keys",
        ),
        pytest.param(
            {
                "internal_defaults": {},
                "low_prio": {
                    "used": ["1", "2"],
                    "unused_1": ["a", "b", "c"],
                    "unused_2": ["1", "2", "3"],
                    "zip_keys": [["unused_1", "unused_2"]],
                },
                # selects a subspace of the zipped unused keys
                "high_prio": {"unused_1": ["c"]},
            },
            {"used"},
            {"used"},
            id="subspace_of_unused_zip_keys",
        ),
        pytest.param(
            {
                "internal_defaults": {},
                "config": {"unused_1": ["a", "b"], "unused_2": ["c", "d"]},
            },
            set(),
            set(),
            id="nothing_used",
        ),
    ],
)
def test_filter_combined_spec_to_used_keys_reduces_unused_keys(
    specs, used_vars, varying_vars
):
    combined_spec = combine_specs(specs, log_output=False)
    full = filter_combined_spec_to_used_keys(combined_spec, specs=specs)
    reduced = filter_combined_spec_to_used_keys(
        combined_spec, specs=specs, used_vars=used_vars
    )

    # the same variants of the used keys (and those zipped with them), without
    # duplicates
    assert _used_projection(reduced, varying_vars) == sorted(
        set(_used_projection(full, varying_vars))
    )
    assert len(reduced) == len(set(_used_projection(full, varying_vars)))
    # every variant has all keys, unused keys keep their value from the full matrix
    assert reduced[0] == full[0]
    unused = {k: v for k, v in full[0].items() if k not in varying_vars}
    for variant in reduced:
        assert variant.keys() == full[0].keys()
        assert {k: variant[k] for k in unused} == unused


def test_get_possibly_used_vars(testing_config):
    recipe = os.path.join(variants_dir, "24_test_used_vars_in_scripts")
    keys = [
        "BASH_VAR1",
        "BASH_VAR2",
        "BAT_VAR",
        "OUTPUT_VAR",
        "SELECTOR_VAR",
        "OUTPUT_SELECTOR_VAR",
        "python",
        "target_platform",
        "channel_sources",
        "c_compiler",
        "cdt_name",
        "unused_var",
    ]
    for platform_ in ("linux", "win"):
        testing_config.platform = platform_
        metadata = api.render(
            recipe, config=testing_config, finalize=False, bypass_env_check=True
        )[0][0]
        possibly_used = metadata.get_possibly_used_vars(keys)
        for metadata_ in (
            om
            for _, om in metadata.get_output_metadata_set(
                permit_undefined_jinja=True, bypass_env_check=True
            )
        ):
            assert metadata_.get_used_vars() & set(keys) <= possibly_used
        assert possibly_used == set(keys) - {
            "c_compiler",
            "cdt_name",
            "unused_var",
            "channel_sources",
        }

        # callers can ask for keys to be exploded regardless of the recipe
        metadata.config.explode_variant_keys = ["channel_sources", "unused_var"]
        assert metadata.get_possibly_used_vars(keys) == possibly_used | {
            "channel_sources",
            "unused_var",
        }


def test_unused_variant_keys_not_exploded(testing_config):
    recipe = os.path.join(variants_dir, "24_test_used_vars_in_scripts")
    variants = {"unused_1": ["a", "b", "c"], "unused_2": ["1", "2", "3"]}
    metadata_tuples = api.render(
        recipe,
        config=testing_config,
        variants=variants,
        finalize=False,
        bypass_env_check=True,
    )
    for metadata, _, _ in metadata_tuples:
        assert {
            (variant["unused_1"], variant["unused_2"])
            for variant in metadata.config.input_variants
        } == {("a", "1")}

    # the same as when the full matrix is exploded
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(MetaData, "get_possibly_used_vars", lambda self, keys: None)
        full_tuples = api.render(
            recipe,
            config=testing_config,
            variants=variants,
            finalize=False,
            bypass_env_check=True,
        )
    assert len(full_tuples[0][0].config.input_variants) == 9 * len(
        metadata_tuples[0][0].config.input_variants
    )

    def _summary(tuples):
        return sorted(
            (
                om.dist(),
                tuple(sorted((k, om.config.variant[k]) for k in om.get_used_vars())),
            )
            for m, _, _ in tuples
            for _, om in m.get_output_metadata_set(
                permit_undefined_jinja=True, bypass_env_check=True
            )
        )

    assert _summary(metadata_tuples) == _summary(full_tuples)
