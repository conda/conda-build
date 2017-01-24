import os

import pytest

from conda_build import environ, api, utils
from conda_build.conda_interface import url_path, PaddingError, LinkError

# * import because pytest fixtures need to be all imported
from .utils import metadata_dir


def test_environment_creation_preserves_PATH(testing_workdir, testing_config):
    ref_path = os.environ['PATH']
    environ.create_env(testing_workdir, ['python'], testing_config, subdir=testing_config.build_subdir)
    assert os.environ['PATH'] == ref_path


@pytest.mark.skipif(utils.on_win, reason=("Windows binary prefix replacement (for pip exes)"
                                    " not length dependent"))
def test_env_creation_with_short_prefix_does_not_deadlock(testing_config, caplog):
    test_base = os.path.expanduser("~/cbtmp")
    config = api.Config(croot=test_base, anaconda_upload=False, verbose=True)
    recipe_path = os.path.join(metadata_dir, "has_prefix_files")
    metadata = api.render(recipe_path, config=config)[0][0]
    pkg_name = 'test_env_creation_with_short_prefix_deadlock'
    metadata.meta['package']['name'] = pkg_name
    metadata.config.prefix_length = 80
    try:
        output = api.build(metadata)[0]
        assert not api.inspect_prefix_length(output, 255)
        metadata.config.prefix_length = 255
        metadata.config.channel_urls = [url_path(os.path.dirname(output))]
        environ.create_env(config.build_prefix, specs=["python", pkg_name], config=metadata.config,
                           subdir=testing_config.build_subdir)
    except:
        raise
    finally:
        utils.rm_rf(test_base)
    assert 'One or more of your package dependencies needs to be rebuilt' in caplog.text()


@pytest.mark.skipif(utils.on_win, reason=("Windows binary prefix replacement (for pip exes)"
                                    " not length dependent"))
def test_env_creation_with_prefix_fallback_disabled(testing_config):
    test_base = os.path.expanduser("~/cbtmp")
    config = api.Config(croot=test_base, anaconda_upload=False, verbose=True,
                        prefix_length_fallback=False)
    recipe_path = os.path.join(metadata_dir, "has_prefix_files")
    metadata = api.render(recipe_path, config=config)[0][0]
    pkg_name = 'test_env_creation_with_short_prefix_fallback'
    metadata.meta['package']['name'] = pkg_name
    metadata.config.prefix_length = 80

    with pytest.raises((SystemExit, PaddingError, LinkError)):
        output = api.build(metadata)[0]
        assert not api.inspect_prefix_length(output, 255)
        config.prefix_length = 255
        config.channel_urls = [url_path(os.path.dirname(output))]
        environ.create_env(config.build_prefix, specs=["python", pkg_name], config=config,
                           subdir=testing_config.build_subdir)
