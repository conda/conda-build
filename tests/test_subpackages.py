import os
import pytest

from conda_build import api, utils

from .utils import is_valid_dir, subpackage_dir


@pytest.fixture(params=[dirname for dirname in os.listdir(subpackage_dir)
                        if is_valid_dir(subpackage_dir, dirname)])
def recipe(request):
    return os.path.join(subpackage_dir, request.param)


def test_subpackage_recipes(recipe, test_config):
    api.build(recipe, config=test_config)


def test_autodetect_raises_on_invalid_extension(test_config):
    with pytest.raises(NotImplementedError):
        api.build(os.path.join(subpackage_dir, '_invalid_script_extension'), config=test_config)


# regression test for https://github.com/conda/conda-build/issues/1661
def test_rm_rf_does_not_remove_relative_source_package_files(test_config, monkeypatch):
    recipe_dir = os.path.join(subpackage_dir, '_rm_rf_stays_within_prefix')
    monkeypatch.chdir(recipe_dir)
    bin_file_that_disappears = os.path.join('bin', 'lsfm')
    if not os.path.isfile(bin_file_that_disappears):
        with open(bin_file_that_disappears, 'w') as f:
            f.write('weee')
    assert os.path.isfile(bin_file_that_disappears)
    api.build('conda', config=test_config)
    assert os.path.isfile(bin_file_that_disappears)


def test_toplevel_entry_points_do_not_apply_to_subpackages(test_config):
    recipe_dir = os.path.join(subpackage_dir, '_entry_points')
    outputs = api.build(recipe_dir, config=test_config)
    if utils.on_win:
        script_dir = 'Scripts'
        ext = '.exe'
    else:
        script_dir = 'bin'
        ext = ''
    for out in outputs:
        fn = os.path.basename(out)
        if fn.startswith('split_package_entry_points1'):
            assert utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'pkg1', ext))
            assert not utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'pkg2', ext))
            assert not utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'top1', ext))
            assert not utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'top2', ext))
        elif fn.startswith('split_package_entry_points2'):
            assert utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'pkg2', ext))
            assert not utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'pkg1', ext))
            assert not utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'top1', ext))
            assert not utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'top2', ext))
        elif fn.startswith('test_split_package_entry_points'):
            # python commands will make sure that these are available.
            # assert utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'top1', ext))
            # assert utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'top2', ext))
            assert not utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'pkg1', ext))
            assert not utils.package_has_file(out, '{}/{}{}'.format(script_dir, 'pkg2', ext))
        else:
            raise ValueError("Didn't see any of the 3 expected filenames.  Filename was {}".format(fn))
