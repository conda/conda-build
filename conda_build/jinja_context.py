from __future__ import absolute_import, division, print_function

from functools import partial
import json
import logging
import os
import re

import jinja2

from .conda_interface import PY3
from .environ import get_dict as get_environ
from .metadata import select_lines, ns_cfg
from .utils import copy_into, check_call_env
from . import _load_setup_py_data


class UndefinedNeverFail(jinja2.Undefined):
    """
    A class for Undefined jinja variables.
    This is even less strict than the default jinja2.Undefined class,
    because it permits things like {{ MY_UNDEFINED_VAR[:2] }} and
    {{ MY_UNDEFINED_VAR|int }}. This can mask lots of errors in jinja templates, so it
    should only be used for a first-pass parse, when you plan on running a 'strict'
    second pass later.
    """
    all_undefined_names = []

    def __init__(self, hint=None, obj=jinja2.runtime.missing, name=None,
                 exc=jinja2.exceptions.UndefinedError):
        UndefinedNeverFail.all_undefined_names.append(name)
        jinja2.Undefined.__init__(self, hint, obj, name, exc)

    __add__ = __radd__ = __mul__ = __rmul__ = __div__ = __rdiv__ = \
    __truediv__ = __rtruediv__ = __floordiv__ = __rfloordiv__ = \
    __mod__ = __rmod__ = __pos__ = __neg__ = __call__ = \
    __getitem__ = __lt__ = __le__ = __gt__ = __ge__ = \
    __complex__ = __pow__ = __rpow__ = \
        lambda self, *args, **kwargs: UndefinedNeverFail(hint=self._undefined_hint,
                                                         obj=self._undefined_obj,
                                                         name=self._undefined_name,
                                                         exc=self._undefined_exception)

    __str__ = __repr__ = \
        lambda *args, **kwargs: u''

    __int__ = lambda _: 0
    __float__ = lambda _: 0.0

    def __getattr__(self, k):
        try:
            return object.__getattr__(self, k)
        except AttributeError:
            return UndefinedNeverFail(hint=self._undefined_hint,
                                      obj=self._undefined_obj,
                                      name=self._undefined_name + '.' + k,
                                      exc=self._undefined_exception)


class FilteredLoader(jinja2.BaseLoader):
    """
    A pass-through for the given loader, except that the loaded source is
    filtered according to any metadata selectors in the source text.
    """

    def __init__(self, unfiltered_loader, config):
        self._unfiltered_loader = unfiltered_loader
        self.list_templates = unfiltered_loader.list_templates
        self.config = config

    def get_source(self, environment, template):
        contents, filename, uptodate = self._unfiltered_loader.get_source(environment,
                                                                          template)
        return select_lines(contents, ns_cfg(self.config)), filename, uptodate


def load_setup_py_data(config, setup_file='setup.py', from_recipe_dir=False, recipe_dir=None,
                       permit_undefined_jinja=True):
    # we must copy the script into the work folder to avoid incompatible pyc files
    origin_setup_script = os.path.join(os.path.dirname(__file__), '_load_setup_py_data.py')
    dest_setup_script = os.path.join(config.work_dir, '_load_setup_py_data.py')
    copy_into(origin_setup_script, dest_setup_script)
    if os.path.isfile(config.build_python):
        args = [config.build_python, dest_setup_script, config.work_dir, setup_file]
        if from_recipe_dir:
            assert recipe_dir, 'recipe_dir must be set if from_recipe_dir is True'
            args.append('--from-recipe-dir')
            args.extend(['--recipe-dir', recipe_dir])
        if permit_undefined_jinja:
            args.append('--permit_undefined_jinja')
        check_call_env(args, env=get_environ(config))
        # this is a file that the subprocess will have written
        with open(os.path.join(config.work_dir, 'conda_build_loaded_setup_py.json')) as f:
            _setuptools_data = json.load(f)
    else:
        _setuptools_data = _load_setup_py_data.load_setup_py_data(setup_file,
                                                    from_recipe_dir=from_recipe_dir,
                                                    recipe_dir=recipe_dir,
                                                    work_dir=config.work_dir,
                                                    permit_undefined_jinja=permit_undefined_jinja)
    return _setuptools_data if _setuptools_data else None


def load_setuptools(config, setup_file='setup.py', from_recipe_dir=False, recipe_dir=None,
                    permit_undefined_jinja=True):
    log = logging.getLogger(__name__)
    log.warn("Deprecation notice: the load_setuptools function has been renamed to "
             "load_setup_py_data.  load_setuptools will be removed in a future release.")
    return load_setup_py_data(config=config, setup_file=setup_file, from_recipe_dir=from_recipe_dir,
                              recipe_dir=recipe_dir, permit_undefined_jinja=permit_undefined_jinja)


def load_npm():
    # json module expects bytes in Python 2 and str in Python 3.
    mode_dict = {'mode': 'r', 'encoding': 'utf-8'} if PY3 else {'mode': 'rb'}
    with open('package.json', **mode_dict) as pkg:
        return json.load(pkg)


def load_file_regex(config, load_file, regex_pattern, from_recipe_dir=False,
                    recipe_dir=None, permit_undefined_jinja=True):
    match = False
    log = logging.getLogger(__name__)

    cd_to_work = False

    if from_recipe_dir and recipe_dir:
        load_file = os.path.abspath(os.path.join(recipe_dir, load_file))
    elif os.path.exists(config.work_dir):
        cd_to_work = True
        cwd = os.getcwd()
        os.chdir(config.work_dir)
        if not os.path.isabs(load_file):
            load_file = os.path.join(config.work_dir, load_file)
    else:
        message = ("Did not find {} file in manually specified location, and source "
                  "not downloaded yet.".format(load_file))
        if permit_undefined_jinja:
            log.debug(message)
            return {}
        else:
            raise RuntimeError(message)

    if os.path.isfile(load_file):
        match = re.search(regex_pattern, open(load_file, 'r').read())
    else:
        if not permit_undefined_jinja:
            raise TypeError('{} is not a file that can be read'.format(load_file))

    # Reset the working directory
    if cd_to_work:
        os.chdir(cwd)

    return match if match else None


def context_processor(initial_metadata, recipe_dir, config, permit_undefined_jinja):
    """
    Return a dictionary to use as context for jinja templates.

    initial_metadata: Augment the context with values from this MetaData object.
                      Used to bootstrap metadata contents via multiple parsing passes.
    """
    ctx = get_environ(config=config, m=initial_metadata)
    environ = dict(os.environ)
    environ.update(get_environ(config=config, m=initial_metadata))

    ctx.update(
        load_setup_py_data=partial(load_setup_py_data, config=config, recipe_dir=recipe_dir,
                                   permit_undefined_jinja=permit_undefined_jinja),
        # maintain old alias for backwards compatibility:
        load_setuptools=partial(load_setuptools, config=config, recipe_dir=recipe_dir,
                                permit_undefined_jinja=permit_undefined_jinja),
        load_npm=load_npm,
        load_file_regex=partial(load_file_regex, config=config, recipe_dir=recipe_dir,
                                permit_undefined_jinja=permit_undefined_jinja),
        environ=environ)
    return ctx
