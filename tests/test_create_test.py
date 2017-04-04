import os

from conda_build import create_test as ct


def test_create_py_files_with_py_imports(testing_workdir, testing_metadata):
    testing_metadata.meta['test']['imports'] = ['time', 'datetime']
    ct.create_py_files(testing_metadata)
    test_file = os.path.join(testing_metadata.config.test_dir, 'run_test.py')
    assert os.path.isfile(test_file)
    with open(test_file) as f:
        data = f.readlines()
    assert 'import time\n' in data
    assert 'import datetime\n' in data


def test_create_py_files_in_other_language(testing_workdir, testing_metadata):
    testing_metadata.meta['test']['imports'] = [{'lang': 'python', 'imports': ['time', 'datetime']}]
    testing_metadata.meta['package']['name'] = 'perl-conda-test'
    ct.create_py_files(testing_metadata)
    test_file = os.path.join(testing_metadata.config.test_dir, 'run_test.py')
    assert os.path.isfile(test_file)
    with open(test_file) as f:
        data = f.readlines()
    assert 'import time\n' in data
    assert 'import datetime\n' in data


def test_create_r_files(testing_workdir, testing_metadata):
    testing_metadata.meta['test']['imports'] = ['r-base', 'r-matrix']
    testing_metadata.meta['package']['name'] = 'r-conda-test'
    ct.create_r_files(testing_metadata)
    test_file = os.path.join(testing_metadata.config.test_dir, 'run_test.r')
    assert os.path.isfile(test_file)
    with open(test_file) as f:
        data = f.readlines()
    assert 'library(r-base)\n' in data
    assert 'library(r-matrix)\n' in data


def test_create_r_files_lang_spec(testing_workdir, testing_metadata):
    testing_metadata.meta['test']['imports'] = [{'lang': 'r', 'imports': ['r-base', 'r-matrix']}]
    testing_metadata.meta['package']['name'] = 'conda-test-r'
    ct.create_r_files(testing_metadata)
    test_file = os.path.join(testing_metadata.config.test_dir, 'run_test.r')
    assert os.path.isfile(test_file)
    with open(test_file) as f:
        data = f.readlines()
    assert 'library(r-base)\n' in data
    assert 'library(r-matrix)\n' in data


def test_create_pl_files(testing_workdir, testing_metadata):
    testing_metadata.meta['test']['imports'] = ['perl-base', 'perl-matrix']
    testing_metadata.meta['package']['name'] = 'perl-conda-test'
    ct.create_pl_files(testing_metadata)
    test_file = os.path.join(testing_metadata.config.test_dir, 'run_test.pl')
    assert os.path.isfile(test_file)
    with open(test_file) as f:
        data = f.readlines()
    assert 'use perl-base;\n' in data
    assert 'use perl-matrix;\n' in data


def test_create_pl_files_lang_spec(testing_workdir, testing_metadata):
    testing_metadata.meta['test']['imports'] = [{'lang': 'perl', 'imports': ['perl-base',
                                                                          'perl-matrix']}]
    testing_metadata.meta['package']['name'] = 'conda-test-perl'
    ct.create_pl_files(testing_metadata)
    test_file = os.path.join(testing_metadata.config.test_dir, 'run_test.pl')
    assert os.path.isfile(test_file)
    with open(test_file) as f:
        data = f.readlines()
    assert 'use perl-base;\n' in data
    assert 'use perl-matrix;\n' in data


def test_create_lua_files(testing_workdir, testing_metadata):
    testing_metadata.meta['test']['imports'] = ['lua-base', 'lua-matrix']
    testing_metadata.meta['package']['name'] = 'lua-conda-test'
    ct.create_lua_files(testing_metadata)
    test_file = os.path.join(testing_metadata.config.test_dir, 'run_test.lua')
    assert os.path.isfile(test_file)
    with open(test_file) as f:
        data = f.readlines()
    assert 'require "lua-base"\n' in data
    assert 'require "lua-matrix"\n' in data


def test_create_lua_files_lang_spec(testing_workdir, testing_metadata):
    testing_metadata.meta['test']['imports'] = [{'lang': 'lua', 'imports': ['lua-base',
                                                                          'lua-matrix']}]
    testing_metadata.meta['package']['name'] = 'conda-test-lua'
    ct.create_lua_files(testing_metadata)
    test_file = os.path.join(testing_metadata.config.test_dir, 'run_test.lua')
    assert os.path.isfile(test_file)
    with open(test_file) as f:
        data = f.readlines()
    assert 'require "lua-base"\n' in data
    assert 'require "lua-matrix"\n' in data
