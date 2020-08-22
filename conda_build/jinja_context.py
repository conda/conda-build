from __future__ import absolute_import, division, print_function

from functools import partial
import json
import os
import re
import time
import datetime

import jinja2

from .conda_interface import PY3
from .environ import get_dict as get_environ
from .utils import (get_installed_packages, apply_pin_expressions, get_logger, HashableDict,
                    string_types)
from .render import get_env_dependencies
from .utils import copy_into, check_call_env, rm_rf, ensure_valid_spec
from .variants import DEFAULT_COMPILERS
from .exceptions import CondaBuildException
from . import _load_setup_py_data


class UndefinedNeverFail(jinja2.Undefined):
    """
    A class for Undefined jinja variables.
    This is even less strict than the default jinja2.Undefined class,
    because it permits things like {{ MY_UNDEFINED_VAR[:2] }} and
    {{ MY_UNDEFINED_VAR|int }}. This can mask lots of errors in jinja templates, so it
    should only be used for a first-pass parse, when you plan on running a 'strict'
    second pass later.

    Note:
        When using this class, any usage of an undefined variable in a jinja template is recorded
        in the (global) all_undefined_names class member.  Therefore, after jinja rendering,
        you can detect which undefined names were used by inspecting that list.
        Be sure to clear the all_undefined_names list before calling template.render().
    """
    all_undefined_names = []

    def __init__(self, hint=None, obj=jinja2.runtime.missing, name=None,
                 exc=jinja2.exceptions.UndefinedError):
        jinja2.Undefined.__init__(self, hint, obj, name, exc)

    # Using any of these methods on an Undefined variable
    # results in another Undefined variable.
    __add__ = __radd__ = __mul__ = __rmul__ = __div__ = __rdiv__ = \
    __truediv__ = __rtruediv__ = __floordiv__ = __rfloordiv__ = \
    __mod__ = __rmod__ = __pos__ = __neg__ = __call__ = \
    __getitem__ = __lt__ = __le__ = __gt__ = __ge__ = \
    __complex__ = __pow__ = __rpow__ = \
        lambda self, *args, **kwargs: self._return_undefined(self._undefined_name)

    # Accessing an attribute of an Undefined variable
    # results in another Undefined variable.
    def __getattr__(self, k):
        try:
            return object.__getattr__(self, k)
        except AttributeError:
            self._return_undefined(self._undefined_name + '.' + k)

    # Unlike the methods above, Python requires that these
    # few methods must always return the correct type
    __str__ = __repr__ = lambda self: self._return_value(str())
    __unicode__ = lambda self: self._return_value(u'')
    __int__ = lambda self: self._return_value(0)
    __float__ = lambda self: self._return_value(0.0)
    __nonzero__ = lambda self: self._return_value(False)

    def _return_undefined(self, result_name):
        # Record that this undefined variable was actually used.
        UndefinedNeverFail.all_undefined_names.append(self._undefined_name)
        return UndefinedNeverFail(hint=self._undefined_hint,
                                  obj=self._undefined_obj,
                                  name=result_name,
                                  exc=self._undefined_exception)

    def _return_value(self, value=None):
        # Record that this undefined variable was actually used.
        UndefinedNeverFail.all_undefined_names.append(self._undefined_name)
        return value


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
        # we have circular imports here.  Do a local import
        from .metadata import select_lines, ns_cfg
        contents, filename, uptodate = self._unfiltered_loader.get_source(environment,
                                                                          template)
        return (select_lines(contents, ns_cfg(self.config),
                             variants_in_place=bool(self.config.variant)), filename, uptodate)


def load_setup_py_data(m, setup_file='setup.py', from_recipe_dir=False, recipe_dir=None,
                       permit_undefined_jinja=True):
    _setuptools_data = None
    # we must copy the script into the work folder to avoid incompatible pyc files
    origin_setup_script = os.path.join(os.path.dirname(__file__), '_load_setup_py_data.py')
    dest_setup_script = os.path.join(m.config.work_dir, '_load_setup_py_data.py')
    copy_into(origin_setup_script, dest_setup_script)
    env = get_environ(m)
    env["CONDA_BUILD_STATE"] = "RENDER"
    if os.path.isfile(m.config.build_python):
        args = [m.config.build_python, dest_setup_script, m.config.work_dir, setup_file]
        if from_recipe_dir:
            assert recipe_dir, 'recipe_dir must be set if from_recipe_dir is True'
            args.append('--from-recipe-dir')
            args.extend(['--recipe-dir', recipe_dir])
        if permit_undefined_jinja:
            args.append('--permit-undefined-jinja')
        check_call_env(args, env=env)
        # this is a file that the subprocess will have written
        with open(os.path.join(m.config.work_dir, 'conda_build_loaded_setup_py.json')) as f:
            _setuptools_data = json.load(f)
    else:
        try:
            _setuptools_data = _load_setup_py_data.load_setup_py_data(setup_file,
                                                    from_recipe_dir=from_recipe_dir,
                                                    recipe_dir=recipe_dir,
                                                    work_dir=m.config.work_dir,
                                                    permit_undefined_jinja=permit_undefined_jinja)
        except (TypeError, OSError):
            # setup.py file doesn't yet exist.  Will get picked up in future parsings
            pass
        except ImportError as e:
            if permit_undefined_jinja:
                log = get_logger(__name__)
                log.debug("Reading setup.py failed due to missing modules.  This is probably OK, "
                          "since it may succeed in later passes.  Watch for incomplete recipe "
                          "info, though.")
            else:
                raise CondaBuildException("Could not render recipe - need modules "
                                        "installed in root env.  Import error was \"{}\"".format(e))
    # cleanup: we must leave the source tree empty unless the source code is already present
    rm_rf(os.path.join(m.config.work_dir, '_load_setup_py_data.py'))
    return _setuptools_data if _setuptools_data else {}


def load_setuptools(m, setup_file='setup.py', from_recipe_dir=False, recipe_dir=None,
                    permit_undefined_jinja=True):
    log = get_logger(__name__)
    log.warn("Deprecation notice: the load_setuptools function has been renamed to "
             "load_setup_py_data.  load_setuptools will be removed in a future release.")
    return load_setup_py_data(m, setup_file=setup_file, from_recipe_dir=from_recipe_dir,
                              recipe_dir=recipe_dir, permit_undefined_jinja=permit_undefined_jinja)


def load_npm():
    # json module expects bytes in Python 2 and str in Python 3.
    mode_dict = {'mode': 'r', 'encoding': 'utf-8'} if PY3 else {'mode': 'rb'}
    with open('package.json', **mode_dict) as pkg:
        return json.load(pkg)


def load_file_regex(config, load_file, regex_pattern, from_recipe_dir=False,
                    recipe_dir=None, permit_undefined_jinja=True):
    match = False
    log = get_logger(__name__)

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
        with open(load_file, 'r') as lfile:
            match = re.search(regex_pattern, lfile.read())
    else:
        if not permit_undefined_jinja:
            raise TypeError('{} is not a file that can be read'.format(load_file))

    # Reset the working directory
    if cd_to_work:
        os.chdir(cwd)

    return match if match else None


cached_env_dependencies = {}


def pin_compatible(m, package_name, lower_bound=None, upper_bound=None, min_pin='x.x.x.x.x.x',
                   max_pin='x', permit_undefined_jinja=False, exact=False, bypass_env_check=False):
    """dynamically pin based on currently installed version.

    only mandatory input is package_name.
    upper_bound is the authoritative upper bound, if provided.  The lower bound is the the
        currently installed version.
    pin expressions are of the form 'x.x' - the number of pins is the number of x's separated
        by ``.``.
    """
    global cached_env_dependencies
    compatibility = ""

    # optimization: this is slow (requires solver), so better to bypass it
    # until the finalization stage.
    if not bypass_env_check and not permit_undefined_jinja:
        # this is the version split up into its component bits.
        # There are two cases considered here (so far):
        # 1. Good packages that follow semver style (if not philosophy).  For example, 1.2.3
        # 2. Evil packages that cram everything alongside a single major version.  For example, 9b
        key = (m.name(), HashableDict(m.config.variant))
        if key in cached_env_dependencies:
            pins = cached_env_dependencies[key]
        else:
            if m.is_cross and not m.build_is_host:
                pins, _, _ = get_env_dependencies(m, 'host', m.config.variant)
            else:
                pins, _, _ = get_env_dependencies(m, 'build', m.config.variant)
                if m.build_is_host:
                    host_pins, _, _ = get_env_dependencies(m, 'host', m.config.variant)
                    pins.extend(host_pins)
            cached_env_dependencies[key] = pins
        versions = {p.split(' ')[0]: p.split(' ')[1:] for p in pins}
        if versions:
            if exact and versions.get(package_name):
                compatibility = ' '.join(versions[package_name])
            else:
                version = lower_bound or versions.get(package_name)
                if version:
                    if hasattr(version, '__iter__') and not isinstance(version, string_types):
                        version = version[0]
                    else:
                        version = str(version)
                    if upper_bound:
                        if min_pin or lower_bound:
                            compatibility = ">=" + str(version) + ","
                        compatibility += '<{upper_bound}'.format(upper_bound=upper_bound)
                    else:
                        compatibility = apply_pin_expressions(version, min_pin, max_pin)

    if (not compatibility and not permit_undefined_jinja and not bypass_env_check):
        check = re.compile(r'pin_compatible\s*\(\s*[''"]{}[''"]'.format(package_name))
        if check.search(m.extract_requirements_text()):
            raise RuntimeError("Could not get compatibility information for {} package.  "
                               "Is it one of your host dependencies?".format(package_name))
    return " ".join((package_name, compatibility)) if compatibility is not None else package_name


def pin_subpackage_against_outputs(metadata, matching_package_keys, outputs, min_pin, max_pin,
                                   exact, permit_undefined_jinja, skip_build_id=False):
    pin = None
    if matching_package_keys:
        # two ways to match:
        #    1. only one other output named the same as the subpackage_name from the key
        #    2. whole key matches (both subpackage name and variant (used keys only))
        if len(matching_package_keys) == 1:
            key = matching_package_keys[0]
        elif len(matching_package_keys) > 1:
            key = None
            for pkg_name, variant in matching_package_keys:
                # This matches other outputs with any keys that are common to both
                # metadata objects. For debugging, the keys are always the (package
                # name, used vars+values). It used to be (package name, variant) -
                # but that was really big and hard to look at.
                shared_vars = set(variant.keys()) & set(metadata.config.variant.keys())
                if not shared_vars or all(variant[sv] == metadata.config.variant[sv]
                                            for sv in shared_vars):
                    key = (pkg_name, variant)
                    break

        if key in outputs:
            sp_m = outputs[key][1]
            if permit_undefined_jinja and not sp_m.version():
                pin = None
            else:
                if exact:
                    pin = " ".join([sp_m.name(), sp_m.version(),
                                    sp_m.build_id() if not skip_build_id else str(sp_m.build_number())])
                else:
                    pin = "{0} {1}".format(sp_m.name(),
                                        apply_pin_expressions(sp_m.version(), min_pin,
                                                                max_pin))
        else:
            pin = matching_package_keys[0][0]
    return pin


def pin_subpackage(metadata, subpackage_name, min_pin='x.x.x.x.x.x', max_pin='x',
                   exact=False, permit_undefined_jinja=False, allow_no_other_outputs=False,
                   skip_build_id=False):
    """allow people to specify pinnings based on subpackages that are defined in the recipe.

    For example, given a compiler package, allow it to specify either a compatible or exact
    pinning on the runtime package that is also created by the compiler package recipe
    """
    pin = None

    if not hasattr(metadata, 'other_outputs'):
        if allow_no_other_outputs:
            pin = subpackage_name
        else:
            raise ValueError("Bug in conda-build: we need to have info about other outputs in "
                             "order to allow pinning to them.  It's not here.")
    else:
        # two ways to match:
        #    1. only one other output named the same as the subpackage_name from the key
        #    2. whole key matches (both subpackage name and variant)
        keys = list(metadata.other_outputs.keys())
        matching_package_keys = [k for k in keys if k[0] == subpackage_name]
        pin = pin_subpackage_against_outputs(metadata, matching_package_keys,
                                             metadata.other_outputs, min_pin, max_pin,
                                             exact, permit_undefined_jinja,
                                             skip_build_id=skip_build_id)
    if not pin:
        pin = subpackage_name
        if not permit_undefined_jinja and not allow_no_other_outputs:
            raise ValueError("Didn't find subpackage version info for '{}', which is used in a"
                             " pin_subpackage expression.  Is it actually a subpackage?  If not, "
                             "you want pin_compatible instead.".format(subpackage_name))
    return pin


def native_compiler(language, config):
    compiler = language

    for platform in [config.platform, config.platform.split('-')[0]]:
        try:
            compiler = DEFAULT_COMPILERS[platform][language]
            break
        except KeyError:
            continue
    if hasattr(compiler, 'keys'):
        compiler = compiler.get(config.variant.get('python', 'nope'), 'vs2017')
    return compiler


def compiler(language, config, permit_undefined_jinja=False):
    """Support configuration of compilers.  This is somewhat platform specific.

    Native compilers never list their host - it is always implied.  Generally, they are
    metapackages, pointing at a package that does specify the host.  These in turn may be
    metapackages, pointing at a package where the host is the same as the target (both being the
    native architecture).
    """

    compiler = native_compiler(language, config)
    version = None
    if config.variant:
        target_platform = config.variant.get('target_platform', config.subdir)
        language_compiler_key = '{}_compiler'.format(language)
        # fall back to native if language-compiler is not explicitly set in variant
        compiler = config.variant.get(language_compiler_key, compiler)
        version = config.variant.get(language_compiler_key + '_version')
    else:
        target_platform = config.subdir

    # support cross compilers.  A cross-compiler package will have a name such as
    #    gcc_target
    #    gcc_linux-cos6-64
    compiler = '_'.join([compiler, target_platform])
    if version:
        compiler = ' '.join((compiler, version))
        compiler = ensure_valid_spec(compiler, warn=False)
    return compiler


def ccache(method, config, permit_undefined_jinja=False):
    config.ccache_method = method
    return 'ccache'


def cdt(package_name, config, permit_undefined_jinja=False):
    """Support configuration of Core Dependency Trees.
    We should define CDTs in a single location. The current
    idea is to emit parts of the following to index.json (the
    bits that the solver could make use of) and parts to
    about.json (the other bits).
    "system": {
      "os": {
        "type": "windows", "linux", "bsd", "darwin",
        "os_distribution": "CentOS", "FreeBSD", "Windows", "osx",
        "os_version": "6.9", "10.12.3",
        "os_kernel_version" : "2.6.32",
        "os_libc_family": "glibc",
        "os_libc_version": "2.12",
      }
      "cpu": {
        # Whichever cpu_architecture/cpu_isa we build-out for:
        # .. armv6 is compatible with and uses all CPU features of a Raspberry PI 1
        # .. armv7a is compatible with and uses all CPU features of a Raspberry PI 2
        # .. aarch64 is compatible with and uses all CPU features of a Raspberry PI 3
        "cpu_architecture": "x86", "x86_64",
                            "armv6", "armv7a", "aarch32", "aarch64",
                            "powerpc", "powerpc64",
                            "s390", "s390x",
        "cpu_isa": "nocona", "armv8.1-a", "armv8.3-a",
        # "?" because the vfpu is specified by cpu_architecture + cpu_isa + rules.
        "vfpu": "?",
        "cpu_endianness": "BE", "LE",
      }
      "gpu ?": {
      }
      "compilerflags": {
        # When put into a CDT these should be the base defaults.
        # Package builds can and will change these frequently.
        "CPPFLAGS": "-D_FORTIFY_SOURCE=2",
        "CFLAGS": "-march=nocona -mtune=haswell -ftree-vectorize -fPIC -fstack-protector-strong -O2 -pipe",
        "CXXFLAGS": "-fvisibility-inlines-hidden -std=c++17 -fmessage-length=0 -march=nocona -mtune=haswell -ftree-vectorize -fPIC -fstack-protector-strong -O2 -pipe",
        "LDFLAGS": "-Wl,-O1,--sort-common,--as-needed,-z,relro",
        "FFLAGS": "-fopenmp",
        # These are appended to the non-DEBUG values:
        "DEBUG_CFLAGS": "-Og -g -Wall -Wextra -fcheck=all -fbacktrace -fimplicit-none -fvar-tracking-assignments",
        "DEBUG_CXXFLAGS": "-Og -g -Wall -Wextra -fcheck=all -fbacktrace -fimplicit-none -fvar-tracking-assignments",
        "DEBUG_FFLAGS": "-Og -g -Wall -Wextra -fcheck=all -fbacktrace -fimplicit-none -fvar-tracking-assignments",
      }
    }
    """  # NOQA

    cdt_name = 'cos6'
    arch = config.host_arch or config.arch
    if arch == 'ppc64le' or arch == 'aarch64' or arch == 'ppc64' or arch == 's390x':
        cdt_name = 'cos7'
        cdt_arch = arch
    else:
        cdt_arch = 'x86_64' if arch == '64' else 'i686'
    if config.variant:
        cdt_name = config.variant.get('cdt_name', cdt_name)
        cdt_arch = config.variant.get('cdt_arch', cdt_arch)
    if ' ' in package_name:
        name = package_name.split(' ')[0]
        ver_build = package_name.split(' ')[1:]
        result = (name + '-' + cdt_name + '-' + cdt_arch + ' ' + ' '.join(ver_build))
    else:
        result = (package_name + '-' + cdt_name + '-' + cdt_arch)
    return result


def resolved_packages(m, env, permit_undefined_jinja=False,
                      bypass_env_check=False):
    """Returns the final list of packages that are listed in host or build.
    This include all packages (including the indirect dependencies) that will
    be installed in the host or build environment. An example usage of this
    jinja function can be::

        requirements:
          host:
            - curl 7.55.1
          run_constrained:
          {% for package in resolved_packages('host') %}
            - {{ package }}
          {% endfor %}

    which will render to::

        requirements:
            host:
                - ca-certificates 2017.08.26 h1d4fec5_0
                - curl 7.55.1 h78862de_4
                - libgcc-ng 7.2.0 h7cc24e2_2
                - libssh2 1.8.0 h9cfc8f7_4
                - openssl 1.0.2n hb7f436b_0
                - zlib 1.2.11 ha838bed_2
            run_constrained:
                - ca-certificates 2017.08.26 h1d4fec5_0
                - curl 7.55.1 h78862de_4
                - libgcc-ng 7.2.0 h7cc24e2_2
                - libssh2 1.8.0 h9cfc8f7_4
                - openssl 1.0.2n hb7f436b_0
                - zlib 1.2.11 ha838bed_2
    """
    if env not in ('host', 'build'):
        raise ValueError('Only host and build dependencies are supported.')

    package_names = []

    # optimization: this is slow (requires solver), so better to bypass it
    # until the finalization stage as done similarly in pin_compatible.
    if not bypass_env_check and not permit_undefined_jinja:
        package_names, _, _ = get_env_dependencies(m, env, m.config.variant)

    return package_names


def context_processor(initial_metadata, recipe_dir, config, permit_undefined_jinja,
                      allow_no_other_outputs=False, bypass_env_check=False, skip_build_id=False,
                      variant=None):
    """
    Return a dictionary to use as context for jinja templates.

    initial_metadata: Augment the context with values from this MetaData object.
                      Used to bootstrap metadata contents via multiple parsing passes.
    """
    ctx = get_environ(m=initial_metadata, for_env=False, skip_build_id=skip_build_id,
                      escape_backslash=True, variant=variant)
    environ = dict(os.environ)
    environ.update(get_environ(m=initial_metadata, skip_build_id=skip_build_id))

    ctx.update(
        load_setup_py_data=partial(load_setup_py_data, m=initial_metadata, recipe_dir=recipe_dir,
                                   permit_undefined_jinja=permit_undefined_jinja),
        # maintain old alias for backwards compatibility:
        load_setuptools=partial(load_setuptools, m=initial_metadata, recipe_dir=recipe_dir,
                                permit_undefined_jinja=permit_undefined_jinja),
        load_npm=load_npm,
        load_file_regex=partial(load_file_regex, config=config, recipe_dir=recipe_dir,
                                permit_undefined_jinja=permit_undefined_jinja),
        installed=get_installed_packages(os.path.join(config.host_prefix, 'conda-meta')),
        pin_compatible=partial(pin_compatible, initial_metadata,
                               permit_undefined_jinja=permit_undefined_jinja,
                               bypass_env_check=bypass_env_check),
        pin_subpackage=partial(pin_subpackage, initial_metadata,
                               permit_undefined_jinja=permit_undefined_jinja,
                               allow_no_other_outputs=allow_no_other_outputs,
                               skip_build_id=skip_build_id),
        compiler=partial(compiler, config=config, permit_undefined_jinja=permit_undefined_jinja),
        cdt=partial(cdt, config=config, permit_undefined_jinja=permit_undefined_jinja),
        ccache=partial(ccache, config=config, permit_undefined_jinja=permit_undefined_jinja),
        resolved_packages=partial(resolved_packages, initial_metadata,
                             permit_undefined_jinja=permit_undefined_jinja,
                             bypass_env_check=bypass_env_check),
        time=time,
        datetime=datetime,

        environ=environ)
    return ctx
