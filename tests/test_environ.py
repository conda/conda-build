import os

import pytest

from conda_build import environ, api
from conda_build.conda_interface import PaddingError, LinkError, CondaError, subdir
from conda_build.utils import on_win
from conda_build.render import reparse

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
    metadata.meta['package']['name'] = 'test_env_creation_with_short_prefix'
    fn = api.get_output_file_path(metadata)[0]
    if os.path.isfile(fn):
        os.remove(fn)
    try:
        output = api.build(metadata)[0]
        assert not api.inspect_prefix_length(output, 255)
        config.prefix_length = 255
        environ.create_env(config.build_prefix, specs=["python", metadata.name()], config=config,
                           subdir=subdir)
    except:
        raise
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
    metadata.meta['package']['name'] = 'test_env_creation_with_short_prefix'
    fn = api.get_output_file_path(metadata)[0]
    if os.path.isfile(fn):
        os.remove(fn)

    with pytest.raises((SystemExit, PaddingError, LinkError, CondaError)):
        output = api.build(metadata)[0]
        assert not api.inspect_prefix_length(output, 255)
        config.prefix_length = 255
        environ.create_env(config.build_prefix, specs=["python", metadata.name()], config=config,
                           subdir=subdir)


@pytest.mark.serial
@pytest.mark.skipif(on_win, reason=("Windows binary prefix replacement (for pip exes)"
                                    " not length dependent"))
def test_catch_openssl_legacy_short_prefix_error(testing_metadata, caplog):
    testing_metadata.config = api.get_or_merge_config(testing_metadata.config, python='2.6')
    testing_metadata = reparse(testing_metadata, testing_metadata.config.index)
    cmd = """
import os

prefix = os.environ['PREFIX']
fn = os.path.join(prefix, 'binary-has-prefix')

with open(fn, 'wb') as f:
    f.write(prefix.encode('utf-8') + b'\x00\x00')
 """
    testing_metadata.meta['build']['script'] = 'python -c "{0}"'.format(cmd)

    api.build(testing_metadata)
    assert "Falling back to legacy prefix" in caplog.text


def test_ensure_valid_spec():
    assert environ._ensure_valid_spec('python') == 'python'
    assert environ._ensure_valid_spec('python 2.7') == 'python 2.7.*'
    assert environ._ensure_valid_spec('python 2.7.2') == 'python 2.7.2.*'
    assert environ._ensure_valid_spec('python 2.7.12 0') == 'python 2.7.12 0'
    assert environ._ensure_valid_spec('python >=2.7,<2.8') == 'python >=2.7,<2.8'
    assert environ._ensure_valid_spec('numpy x.x') == 'numpy x.x'
