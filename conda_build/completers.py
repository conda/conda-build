import os
from .conda_interface import Completer
from .utils import find_recipe


class RecipeCompleter(Completer):
    def _get_items(self):
        completions = []
        for path in os.listdir('.'):
            if os.path.isdir(path):
                try:
                    find_recipe(path)
                    completions.append(path)
                except IOError:
                    pass
        if os.path.isfile('meta.yaml'):
            completions.append('.')
        return completions
