import os
from os.path import isdir, isfile, join
from conda.cli.common import Completer


all_versions = {
    'python': [26, 27, 33, 34, 35],
    'numpy': [16, 17, 18, 19, 110],
    'perl': None,
    'R': None,
    'lua': ["2.0", "5.1", "5.2", "5.3"]
}

conda_version = {
    'python': 'CONDA_PY',
    'numpy': 'CONDA_NPY',
    'perl': 'CONDA_PERL',
    'R': 'CONDA_R',
    'lua': 'CONDA_LUA',
}


class RecipeCompleter(Completer):
    def _get_items(self):
        completions = []
        for path in os.listdir('.'):
            if isdir(path) and isfile(join(path, 'meta.yaml')):
                completions.append(path)
        if isfile('meta.yaml'):
            completions.append('.')
        return completions

# These don't represent all supported versions. It's just for tab completion.


class PythonVersionCompleter(Completer):
    def _get_items(self):
        return ['all'] + [str(i/10) for i in all_versions['python']]


class NumPyVersionCompleter(Completer):
    def _get_items(self):
        versions = [str(i) for i in all_versions['numpy']]
        return ['all'] + ['%s.%s' % (ver[0], ver[1:]) for ver in versions]


class RVersionsCompleter(Completer):
    def _get_items(self):
        return ['3.1.2', '3.1.3', '3.2.0', '3.2.1', '3.2.2']


class LuaVersionsCompleter(Completer):
    def _get_items(self):
        return ['all'] + [i for i in all_versions['lua']]

