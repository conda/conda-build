import os

import pytest

from conda_build import environ, api
from conda_build.conda_interface import PaddingError, LinkError, CondaError, subdir
from conda_build.utils import on_win

from .utils import metadata_dir


def test_environment_creation_preserves_PATH(testing_workdir, testing_config):
    ref_path = os.environ['PATH']
    environ.create_env(testing_workdir, ['python'], testing_config,
                       subdir=testing_config.build_subdir)
    assert os.environ['PATH'] == ref_path


@pytest.mark.serial
@pytest.mark.skipif(on_win, reason=("Windows binary prefix replacement (for pip exes)"
                                    " not length dependent"))
def test_env_creation_with_short_prefix_does_not_deadlock(testing_workdir, caplog):
    config = api.Config(croot=testing_workdir, anaconda_upload=False, verbose=True,
                        set_build_id=False, _prefix_length=80)
    recipe_path = os.path.join(metadata_dir, "has_prefix_files")
    metadata = api.render(recipe_path, config=config)[0][0]
    output = api.build(metadata)[0]
    assert not api.inspect_prefix_length(output, 255)
    config.prefix_length = 255
    environ.create_env(config.build_prefix, specs_or_actions=["python", metadata.name()],
                        config=config, subdir=subdir)
    assert 'One or more of your package dependencies needs to be rebuilt' in caplog.text


@pytest.mark.serial
@pytest.mark.skipif(on_win, reason=("Windows binary prefix replacement (for pip exes)"
                                    " not length dependent"))
def test_env_creation_with_prefix_fallback_disabled():
    test_base = os.path.expanduser("~/cbtmp")
    config = api.Config(croot=test_base, anaconda_upload=False, verbose=True,
                        prefix_length_fallback=False, _prefix_length=80)
    recipe_path = os.path.join(metadata_dir, "has_prefix_files")
    metadata = api.render(recipe_path, config=config)[0][0]
    fn = api.get_output_file_path(metadata)[0]
    if os.path.isfile(fn):
        os.remove(fn)

    with pytest.raises((SystemExit, PaddingError, LinkError, CondaError)):
        output = api.build(metadata)[0]
        assert not api.inspect_prefix_length(output, 255)
        config.prefix_length = 255
        environ.create_env(config.build_prefix, specs_or_actions=["python", metadata.name()],
                           config=config, subdir=subdir)


def test_ensure_valid_spec():
    assert environ._ensure_valid_spec('python') == 'python'
    assert environ._ensure_valid_spec('python 2.7') == 'python 2.7.*'
    assert environ._ensure_valid_spec('python 2.7.2') == 'python 2.7.2.*'
    assert environ._ensure_valid_spec('python 2.7.12 0') == 'python 2.7.12 0'
    assert environ._ensure_valid_spec('python >=2.7,<2.8') == 'python >=2.7,<2.8'
    assert environ._ensure_valid_spec('numpy x.x') == 'numpy x.x'
