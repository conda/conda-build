# This file makes sure that our API has not changed.  Doing so can not be accidental.  Whenever it
#    happens, we should bump our major build number, because we may have broken someone.

from inspect import getargspec
import sys

from conda_build import api


def test_api_config():
    assert hasattr(api, 'Config')
    assert hasattr(api, 'get_or_merge_config')


def test_api_get_or_merge_config():
    argspec = getargspec(api.get_or_merge_config)
    assert argspec.args == ['config']
    assert argspec.defaults is None


def test_api_render():
    argspec = getargspec(api.render)
    assert argspec.args == ['recipe_path', 'config']
    assert argspec.defaults == (None,)


def test_api_output_yaml():
    argspec = getargspec(api.output_yaml)
    assert argspec.args == ['metadata', 'file_path']
    assert argspec.defaults == (None,)


def test_api_get_output_file_path():
    argspec = getargspec(api.get_output_file_path)
    assert argspec.args == ['recipe_path_or_metadata', 'no_download_source', 'config']
    assert argspec.defaults == (False, None)


def test_api_check():
    argspec = getargspec(api.check)
    assert argspec.args == ['recipe_path', 'no_download_source', 'config']
    assert argspec.defaults == (False, None)


def test_api_build():
    argspec = getargspec(api.build)
    assert argspec.args == ['recipe_paths_or_metadata', 'post', 'need_source_download',
                            'build_only', 'notest', 'config']
    assert argspec.defaults == (None, True, False, False, None)


def test_api_test():
    argspec = getargspec(api.test)
    assert argspec.args == ['recipedir_or_package_or_metadata', 'move_broken', 'config']
    assert argspec.defaults == (True, None)


def test_api_keygen():
    argspec = getargspec(api.keygen)
    assert argspec.args == ['name', 'size']
    assert argspec.defaults == ('conda_build_signing', 2048)


def test_api_import_sign_key():
    argspec = getargspec(api.import_sign_key)
    assert argspec.args == ['private_key_path', 'new_name']
    assert argspec.defaults == (None,)


def test_api_sign():
    argspec = getargspec(api.sign)
    assert argspec.args == ['file_path', 'key_name_or_path']
    assert argspec.defaults == (None,)


def test_api_verify():
    argspec = getargspec(api.verify)
    assert argspec.args == ['file_path']
    assert argspec.defaults is None


def test_api_list_skeletons():
    argspec = getargspec(api.list_skeletons)
    assert argspec.args == []
    assert argspec.defaults is None


def test_api_skeletonize():
    argspec = getargspec(api.skeletonize)
    assert argspec.args == ['config']
    assert argspec.defaults == ()


def test_api_develop():
    argspec = getargspec(api.develop)
    assert argspec.args == ['recipe_dir', 'prefix', 'no_pth_file', 'build_ext',
                            'clean', 'uninstall']
    assert argspec.defaults == (sys.prefix, False, False, False, False)


def test_api_convert():
    argspec = getargspec(api.convert)
    assert argspec.args == ['package_file', 'output_dir', 'show_imports', 'platforms', 'force',
                            'dependencies', 'verbose', 'quiet', 'dry_run']
    assert argspec.defaults == ('.', False, None, False, None, False, True, False)


def test_api_installable():
    argspec = getargspec(api.test_installable)
    assert argspec.args == ['channel']
    assert argspec.defaults == ('defaults',)


def test_api_inspect_linkages():
    argspec = getargspec(api.inspect_linkages)
    assert argspec.args == ['packages', 'prefix', 'untracked', 'all_packages',
                            'show_files', 'groupby']
    assert argspec.defaults == (sys.prefix, False, False, False, 'package')


def test_api_inspect_objects():
    argspec = getargspec(api.inspect_objects)
    assert argspec.args == ['packages', 'prefix', 'groupby']
    assert argspec.defaults == (sys.prefix, 'filename')


def test_api_inspect_prefix_length():
    argspec = getargspec(api.inspect_prefix_length)
    assert argspec.args == ['packages', 'min_prefix_length']
    # hard-coded prefix length as intentional check here
    assert argspec.defaults == (255,)


def test_api_create_metapackage():
    argspec = getargspec(api.create_metapackage)
    assert argspec.args == ['name', 'version', 'entry_points', 'build_string', 'build_number',
                            'dependencies', 'home', 'license_name', 'summary', 'config']
    assert argspec.defaults == ((), None, 0, (), None, None, None, None)


def test_api_update_index():
    argspec = getargspec(api.update_index)
    assert argspec.args == ['dir_paths', 'config', 'force', 'check_md5', 'remove']
    assert argspec.defaults == (None, False, False, False)
