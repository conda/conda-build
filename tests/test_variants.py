import os
import subprocess
import tempfile

from conda_build import variants
from conda_build import render

import yaml

global_specs = {"python_pin": ["2.7", "3.5"],
                "numpy_pin": ["1.10", "1.11"]}

single_version = {"python_pin": "2.7",
                  "numpy_pin": "1.10"}

no_numpy_version = {"python_pin": ["2.7", "3.5"]}

thisdir = os.path.dirname(__file__)


def test_later_spec_priority():
    # override a single key
    combined_spec = variants.combine_specs([global_specs, single_version])
    assert len(combined_spec) == 2
    assert combined_spec["python_pin"] == "2.7"

    # keep keys that are not overwritten
    combined_spec = variants.combine_specs([single_version, no_numpy_version])
    assert len(combined_spec) == 2
    assert len(combined_spec["python_pin"]) == 2


def test_get_package_variants():
    with tempfile.NamedTemporaryFile() as f:
        yaml.dump(global_specs, f)
        metadata, _ = render.render_recipe(os.path.join(thisdir, "variant_recipe"),
                                        no_download_source=False, verbose=False,
                                        permit_undefined_jinja=True)
        vars = variants.get_package_variants(metadata, config_file=f.name,
                                             ignore_system_config=True)
    assert "python_pin" in vars


def test_build_config_file():
    metadata, _ = render.render_recipe(os.path.join(thisdir, "variant_recipe"),
                                    no_download_source=False, verbose=False,
                                    permit_undefined_jinja=True)
    assert not any("git" in pkg for pkg in metadata.meta["requirements"]["build"]), metadata.meta["requirements"]["build"]
    metadata = render.add_build_config(metadata, os.path.join(thisdir, "variant_recipe", "build_config.yaml"))
    assert any("git" in pkg for pkg in metadata.meta["requirements"]["build"]), metadata.meta["requirements"]["build"]


def test_build_bootstrap_env_by_name():
    metadata, _ = render.render_recipe(os.path.join(thisdir, "variant_recipe"),
                                       no_download_source=False, verbose=False,
                                       permit_undefined_jinja=True)
    assert not any("git" in pkg for pkg in metadata.meta["requirements"]["build"]), metadata.meta["requirements"]["build"]
    try:
        cmd = "conda create -y -n conda_build_bootstrap_test git"
        subprocess.check_call(cmd.split())
        metadata = render.add_build_config(metadata, "conda_build_bootstrap_test")
        assert any("git" in pkg for pkg in metadata.meta["requirements"]["build"]), metadata.meta["requirements"]["build"]
    finally:
        cmd = "conda remove -y -n conda_build_bootstrap_test --all"
        subprocess.check_call(cmd.split())


def test_build_bootstrap_env_by_path():
    metadata, _ = render.render_recipe(os.path.join(thisdir, "variant_recipe"),
                                       no_download_source=False, verbose=False,
                                       permit_undefined_jinja=True)
    assert not any("git" in pkg for pkg in metadata.meta["requirements"]["build"]), metadata.meta["requirements"]["build"]
    path = os.path.join(thisdir, "conda_build_bootstrap_test")
    try:
        cmd = "conda create -y -p {} git".format(path)
        subprocess.check_call(cmd.split())
        metadata = render.add_build_config(metadata, path)
        assert any("git" in pkg for pkg in metadata.meta["requirements"]["build"]), metadata.meta["requirements"]["build"]
    finally:
        cmd = "conda remove -y -p {} --all".format(path)
        subprocess.check_call(cmd.split())
