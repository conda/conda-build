import os

import pytest

from conda_build import environ, api, utils
from conda_build.conda_interface import url_path, PaddingError, LinkError

from .utils import testing_workdir, test_config, metadata_dir


def test_environment_creation_preserves_PATH(testing_workdir, test_config):
    ref_path = os.environ['PATH']
    environ.create_env(testing_workdir, ['python'], test_config)
    assert os.environ['PATH'] == ref_path


@pytest.mark.skipif(utils.on_win, reason=("Windows binary prefix replacement (for pip exes)"
                                    " not length dependent"))
def test_env_creation_with_short_prefix_does_not_deadlock(caplog):
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
        environ.create_env(config.build_prefix, specs=["python", pkg_name], config=metadata.config)
    except:
        raise
    finally:
        utils.rm_rf(test_base)
    assert 'One or more of your package dependencies needs to be rebuilt' in caplog.text()


@pytest.mark.skipif(utils.on_win, reason=("Windows binary prefix replacement (for pip exes)"
                                    " not length dependent"))
def test_env_creation_with_prefix_fallback_disabled():
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
        environ.create_env(config.build_prefix, specs=["python", pkg_name], config=config)


def test_warn_on_old_conda_build(test_config, capfd):
    installed_version = "1.21.14"

    # test with a conda-generated index first.  This is a list of Package objects,
    #    from which we just take the versions.
    environ.update_index(test_config.croot, test_config)
    environ.update_index(os.path.join(test_config.croot, test_config.host_subdir), test_config)
    environ.update_index(os.path.join(test_config.croot, 'noarch'), test_config)
    index = utils.get_build_index(test_config)
    # exercise the index code path, but this test is not at all deterministic.
    environ.warn_on_old_conda_build(index=index)
    output, error = capfd.readouterr()

    # should see output here
    environ.warn_on_old_conda_build(installed_version=installed_version,
                                  available_packages=['1.21.10', '2.0.0'])
    output, error = capfd.readouterr()
    assert "conda-build appears to be out of date. You have version " in error

    # should not see output here, because newer version has a beta tag
    environ.warn_on_old_conda_build(installed_version=installed_version,
                                  available_packages=['1.21.10', '2.0.0beta2'])
    output, error = capfd.readouterr()
    assert "conda-build appears to be out of date. You have version " not in error

    # should not see output here, because newer version has a beta tag
    environ.warn_on_old_conda_build(installed_version=installed_version,
                                  available_packages=['1.21.10', '2.0.0beta2'])
    output, error = capfd.readouterr()
    assert "conda-build appears to be out of date. You have version " not in error

    # should not barf on empty lists of packages; just not show anything
    #     entries with beta will be filtered out, leaving an empty list
    environ.warn_on_old_conda_build(installed_version=installed_version,
                                  available_packages=['1.0.0beta'])
    output, error = capfd.readouterr()
    assert "conda-build appears to be out of date. You have version " not in error
