# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import json
import os
import platform
import re
import sys
from pathlib import Path

import pytest
import yaml
from conda.common.compat import on_mac

from conda_build import api, exceptions
from conda_build.utils import ensure_list, package_has_file
from conda_build.variants import (
    combine_specs,
    dict_of_lists_to_list_of_dicts,
    filter_combined_spec_to_used_keys,
    get_package_variants,
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
    variants = {"python": ["3.10", "3.11"]}
    testing_config.ignore_system_config = True

    # write variants to disk
    if as_yaml:
        variants_path = Path(testing_workdir, "variant_example.yaml")
        variants_path.write_text(yaml.dump(variants, default_flow_style=False))
        testing_config.variant_config_files = [str(variants_path)]

    # render the metadata
    metadata = api.render(
        os.path.join(variants_dir, "variant_recipe"),
        no_download_source=False,
        config=testing_config,
        # if variants were written to disk then don't pass it along
        variants=None if as_yaml else variants,
    )

    # we should have one package/metadata per python version
    assert len(metadata) == 2
    # there should only be one run requirement for each package/metadata
    assert len(metadata[0][0].meta["requirements"]["run"]) == 1
    assert len(metadata[1][0].meta["requirements"]["run"]) == 1
    # the run requirements should be python ranges
    assert {
        *metadata[0][0].meta["requirements"]["run"],
        *metadata[1][0].meta["requirements"]["run"],
    } == {"python >=3.10,<3.11.0a0", "python >=3.11,<3.12.0a0"}


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
    metadata = api.render(
        os.path.join(variants_dir, "03_ignore_version_reduces_matrix"),
        variants={
            "packageA": ["1.2", "3.4"],
            "packageB": ["5.6", "7.8"],
            # packageB is ignored so that dimension should get collapsed
            "ignore_version": "packageB",
        },
        finalize=False,
    )
    assert len(metadata) == 2


def test_variant_with_numpy_pinned_has_matrix():
    recipe = os.path.join(variants_dir, "04_numpy_matrix_pinned")
    metadata = api.render(recipe, finalize=False)
    assert len(metadata) == 4


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
    ms = api.render(
        recipe,
        permit_unsatisfiable_variants=True,
        finalize=False,
        bypass_env_check=True,
    )
    assert len(ms) == 3


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
    m = api.render(
        recipe, config=testing_config, finalize=False, bypass_env_check=True
    )[0][0]
    assert m.version() == "1.20.2"
    assert m.build_number() == 0


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
    ms = api.render(
        recipe, config=testing_config, finalize=False, bypass_env_check=True
    )
    # there are two entries with a==coffee, so we should end up with 2 variants
    assert len(ms) == 2
    # ensure that the zipped keys still agree
    assert sum(m.config.variant["b"] == "123" for m, _, _ in ms) == 1
    assert sum(m.config.variant["b"] == "abc" for m, _, _ in ms) == 1
    assert sum(m.config.variant["b"] == "concrete" for m, _, _ in ms) == 0
    assert sum(m.config.variant["c"] == "mooo" for m, _, _ in ms) == 1
    assert sum(m.config.variant["c"] == "baaa" for m, _, _ in ms) == 1
    assert sum(m.config.variant["c"] == "woof" for m, _, _ in ms) == 0

    # test compound selection
    testing_config.variant = {"a": "coffee", "b": "123"}
    ms = api.render(
        recipe, config=testing_config, finalize=False, bypass_env_check=True
    )
    # there are two entries with a==coffee, but one with both 'coffee' for a, and '123' for b,
    #     so we should end up with 1 variants
    assert len(ms) == 1
    # ensure that the zipped keys still agree
    assert sum(m.config.variant["b"] == "123" for m, _, _ in ms) == 1
    assert sum(m.config.variant["b"] == "abc" for m, _, _ in ms) == 0
    assert sum(m.config.variant["b"] == "concrete" for m, _, _ in ms) == 0
    assert sum(m.config.variant["c"] == "mooo" for m, _, _ in ms) == 1
    assert sum(m.config.variant["c"] == "baaa" for m, _, _ in ms) == 0
    assert sum(m.config.variant["c"] == "woof" for m, _, _ in ms) == 0

    # test when configuration leads to no valid combinations - only c provided, and its value
    #   doesn't match any other existing values of c, so it's then ambiguous which zipped
    #   values to choose
    testing_config.variant = {"c": "not an animal"}
    with pytest.raises(ValueError):
        ms = api.render(
            recipe, config=testing_config, finalize=False, bypass_env_check=True
        )

    # all zipped keys provided by the new variant.  It should clobber the old one.
    testing_config.variant = {"a": "some", "b": "new", "c": "animal"}
    ms = api.render(
        recipe, config=testing_config, finalize=False, bypass_env_check=True
    )
    assert len(ms) == 1
    assert ms[0][0].config.variant["a"] == "some"
    assert ms[0][0].config.variant["b"] == "new"
    assert ms[0][0].config.variant["c"] == "animal"


def test_get_used_loop_vars():
    m = api.render(
        os.path.join(variants_dir, "19_used_variables"),
        finalize=False,
        bypass_env_check=True,
    )[0][0]
    # conda_build_config.yaml has 4 loop variables defined, but only 3 are used.
    #   python and zlib are both implicitly used (depend on name matching), while
    #   some_package is explicitly used as a jinja2 variable
    assert m.get_used_loop_vars() == {"python", "some_package"}
    # these are all used vars - including those with only one value (and thus not loop vars)
    assert m.get_used_vars() == {
        "python",
        "some_package",
        "zlib",
        "pthread_stubs",
        "target_platform",
    }


def test_reprovisioning_source():
    api.render(os.path.join(variants_dir, "20_reprovision_source"))


def test_reduced_hashing_behavior(testing_config):
    # recipes using any compiler jinja2 function need a hash
    m = api.render(
        os.path.join(variants_dir, "26_reduced_hashing", "hash_yes_compiler"),
        finalize=False,
        bypass_env_check=True,
    )[0][0]
    assert (
        "c_compiler" in m.get_hash_contents()
    ), "hash contents should contain c_compiler"
    assert re.search(
        "h[0-9a-f]{%d}" % testing_config.hash_length, m.build_id()
    ), "hash should be present when compiler jinja2 function is used"

    # recipes that use some variable in conda_build_config.yaml to control what
    #     versions are present at build time also must have a hash (except
    #     python, r_base, and the other stuff covered by legacy build string
    #     behavior)
    m = api.render(
        os.path.join(variants_dir, "26_reduced_hashing", "hash_yes_pinned"),
        finalize=False,
        bypass_env_check=True,
    )[0][0]
    assert "zlib" in m.get_hash_contents()
    assert re.search("h[0-9a-f]{%d}" % testing_config.hash_length, m.build_id())

    # anything else does not get a hash
    m = api.render(
        os.path.join(variants_dir, "26_reduced_hashing", "hash_no_python"),
        finalize=False,
        bypass_env_check=True,
    )[0][0]
    assert not m.get_hash_contents()
    assert not re.search("h[0-9a-f]{%d}" % testing_config.hash_length, m.build_id())


def test_variants_used_in_jinja2_conditionals():
    ms = api.render(
        os.path.join(variants_dir, "21_conditional_sections"),
        finalize=False,
        bypass_env_check=True,
    )
    assert len(ms) == 2
    assert sum(m.config.variant["blas_impl"] == "mkl" for m, _, _ in ms) == 1
    assert sum(m.config.variant["blas_impl"] == "openblas" for m, _, _ in ms) == 1


def test_build_run_exports_act_on_host(caplog):
    """Regression test for https://github.com/conda/conda-build/issues/2559"""
    api.render(
        os.path.join(variants_dir, "22_run_exports_rerendered_for_other_variants"),
        platform="win",
        arch="64",
    )
    assert "failed to get install actions, retrying" not in caplog.text


def test_detect_variables_in_build_and_output_scripts():
    ms = api.render(
        os.path.join(variants_dir, "24_test_used_vars_in_scripts"),
        platform="linux",
        arch="64",
    )
    for m, _, _ in ms:
        if m.name() == "test_find_used_variables_in_scripts":
            used_vars = m.get_used_vars()
            assert used_vars
            assert "SELECTOR_VAR" in used_vars
            assert "OUTPUT_SELECTOR_VAR" not in used_vars
            assert "BASH_VAR1" in used_vars
            assert "BASH_VAR2" in used_vars
            assert "BAT_VAR" not in used_vars
            assert "OUTPUT_VAR" not in used_vars
        else:
            used_vars = m.get_used_vars()
            assert used_vars
            assert "SELECTOR_VAR" not in used_vars
            assert "OUTPUT_SELECTOR_VAR" in used_vars
            assert "BASH_VAR1" not in used_vars
            assert "BASH_VAR2" not in used_vars
            assert "BAT_VAR" not in used_vars
            assert "OUTPUT_VAR" in used_vars
    # on windows, we find variables in bat scripts as well as shell scripts
    ms = api.render(
        os.path.join(variants_dir, "24_test_used_vars_in_scripts"),
        platform="win",
        arch="64",
    )
    for m, _, _ in ms:
        if m.name() == "test_find_used_variables_in_scripts":
            used_vars = m.get_used_vars()
            assert used_vars
            assert "SELECTOR_VAR" in used_vars
            assert "OUTPUT_SELECTOR_VAR" not in used_vars
            assert "BASH_VAR1" in used_vars
            assert "BASH_VAR2" in used_vars
            # bat is in addition to bash, not instead of
            assert "BAT_VAR" in used_vars
            assert "OUTPUT_VAR" not in used_vars
        else:
            used_vars = m.get_used_vars()
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
    output = api.render(
        os.path.join(variants_dir, "exclusive_config_file"),
        exclusive_config_files=exclusive_config_files,
    )[0][0]
    variant = output.config.variant
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
    output = api.render(
        os.path.join(variants_dir, "exclusive_config_file"),
        exclusive_config_file=os.path.join("config_dir", "config.yaml"),
    )[0][0]
    variant = output.config.variant
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
    outputs = api.render(
        os.path.join(variants_dir, "27_requirements_host"), config=testing_config
    )
    assert len(outputs) == 2


def test_custom_compiler():
    recipe = os.path.join(variants_dir, "28_custom_compiler")
    ms = api.render(
        recipe,
        permit_unsatisfiable_variants=True,
        finalize=False,
        bypass_env_check=True,
    )
    assert len(ms) == 3


def test_different_git_vars():
    recipe = os.path.join(variants_dir, "29_different_git_vars")
    ms = api.render(recipe)
    versions = [m[0].version() for m in ms]
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
    assert "5.2.3" in xzcat_output


def test_variant_subkeys_retained():
    m = api.render(
        os.path.join(variants_dir, "31_variant_subkeys"),
        finalize=False,
        bypass_env_check=True,
    )[0][0]
    found_replacements = False
    from conda_build.build import get_all_replacements

    for variant in m.config.variants:
        found_replacements = get_all_replacements(variant)
    assert len(found_replacements), "Did not find replacements"
    m.final = False
    outputs = m.get_output_metadata_set(permit_unsatisfiable_variants=False)
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
