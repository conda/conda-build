import os
import subprocess
import tempfile

from conda_build import variants
from conda_build import render
from .utils import testing_workdir, test_config

import yaml

global_specs = {"python": ["2.7.*", "3.5.*"],
                "numpy": ["1.10.*", "1.11.*"]}

single_version = {"python": "2.7.*",
                  "numpy": "1.11.*"}

no_numpy_version = {"python": ["2.7.*", "3.5.*"]}

thisdir = os.path.dirname(__file__)


def test_later_spec_priority():
    # override a single key
    combined_spec = variants.combine_specs([global_specs, single_version])
    assert len(combined_spec) == 2
    assert combined_spec["python"] == "2.7.*"

    # keep keys that are not overwritten
    combined_spec = variants.combine_specs([single_version, no_numpy_version])
    assert len(combined_spec) == 2
    assert len(combined_spec["python"]) == 2


def test_get_package_variants(test_config):
    with tempfile.NamedTemporaryFile() as f:
        fname = f.name
        if hasattr(fname, 'encode'):
            fname = fname.encode()
        test_config.variant_config_files = [fname]
        test_config.ignore_system_config = True
        with open(fname, 'w') as inner_f:
            yaml.dump(global_specs, inner_f)
        metadata = render.render_recipe(os.path.join(thisdir, "variant_recipe"),
                                        no_download_source=False, config=test_config)
    # one for each Python version
    assert len(metadata) == 2
    assert any('python 2.7' in req for req in metadata[0][0].meta['requirements']['run'])
    assert any('python 3.5' in req for req in metadata[1][0].meta['requirements']['run'])
