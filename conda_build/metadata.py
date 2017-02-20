from __future__ import absolute_import, division, print_function

import os
from os.path import isfile, join
import re
import sys

from .conda_interface import iteritems, PY3, text_type
from .conda_interface import memoized, md5_file
from .conda_interface import non_x86_linux_machines, platform, arch_name
from .conda_interface import MatchSpec
from .conda_interface import specs_from_url

from conda_build import exceptions
from conda_build.features import feature_list
from conda_build.config import Config
from conda_build.utils import ensure_list, find_recipe, expand_globs
from conda_build.license_family import ensure_valid_license_family

try:
    import yaml

    # try to import C loader
    try:
        from yaml import CBaseLoader as BaseLoader
    except ImportError:
        from yaml import BaseLoader
except ImportError:
    sys.exit('Error: could not import yaml (required to read meta.yaml '
             'files of conda recipes)')

on_win = (sys.platform == 'win32')


def ns_cfg(config):
    # Remember to update the docs of any of this changes
    plat = config.subdir
    py = config.CONDA_PY
    np = config.CONDA_NPY
    pl = config.CONDA_PERL
    lua = config.CONDA_LUA
    assert isinstance(py, int), py
    d = dict(
        linux=plat.startswith('linux-'),
        linux32=bool(plat == 'linux-32'),
        linux64=bool(plat == 'linux-64'),
        arm=plat.startswith('linux-arm'),
        osx=plat.startswith('osx-'),
        unix=plat.startswith(('linux-', 'osx-')),
        win=plat.startswith('win-'),
        win32=bool(plat == 'win-32'),
        win64=bool(plat == 'win-64'),
        x86=plat.endswith(('-32', '-64')),
        x86_64=plat.endswith('-64'),
        pl=pl,
        py=py,
        lua=lua,
        luajit=bool(lua[0] == "2"),
        py3k=bool(30 <= py < 40),
        py2k=bool(20 <= py < 30),
        py26=bool(py == 26),
        py27=bool(py == 27),
        py33=bool(py == 33),
        py34=bool(py == 34),
        py35=bool(py == 35),
        py36=bool(py == 36),
        np=np,
        os=os,
        environ=os.environ,
        nomkl=bool(int(os.environ.get('FEATURE_NOMKL', False)))
    )
    for machine in non_x86_linux_machines:
        d[machine] = bool(plat == 'linux-%s' % machine)

    for feature, value in feature_list:
        d[feature] = value
    d.update(os.environ)
    return d


# Selectors must be either:
# - at end of the line
# - embedded (anywhere) within a comment
#
# Notes:
# - [([^\[\]]+)\] means "find a pair of brackets containing any
#                 NON-bracket chars, and capture the contents"
# - (?(2).*)$ means "allow trailing characters iff group 2 (#.*) was found."
sel_pat = re.compile(r'(.+?)\s*(#.*)?\[([^\[\]]+)\](?(2).*)$')


# this function extracts the variable name from a NameError exception, it has the form of:
# "NameError: name 'var' is not defined", where var is the variable that is not defined. This gets
#    returned
def parseNameNotFound(error):
    m = re.search('\'(.+?)\'', str(error))
    if len(m.groups()) == 1:
        return m.group(1)
    else:
        return ""


# We evaluate the selector and return True (keep this line) or False (drop this line)
# If we encounter a NameError (unknown variable in selector), then we replace it by False and
#     re-run the evaluation
def eval_selector(selector_string, namespace):
    try:
        # TODO: is there a way to do this without eval?  Eval allows arbitrary
        #    code execution.
        return eval(selector_string, namespace, {})
    except NameError as e:
        missing_var = parseNameNotFound(e)
        print("Warning: Treating unknown selector \'" + missing_var + "\' as if it was False.")
        next_string = selector_string.replace(missing_var, "False")
        return eval_selector(next_string, namespace)


def select_lines(data, namespace):
    lines = []

    for i, line in enumerate(data.splitlines()):
        line = line.rstrip()

        trailing_quote = ""
        if line and line[-1] in ("'", '"'):
            trailing_quote = line[-1]

        if line.lstrip().startswith('#'):
            # Don't bother with comment only lines
            continue
        m = sel_pat.match(line)
        if m:
            cond = m.group(3)
            try:
                if eval_selector(cond, namespace):
                    lines.append(m.group(1) + trailing_quote)
            except:
                sys.exit('''\
Error: Invalid selector in meta.yaml line %d:
%s
''' % (i + 1, line))
                sys.exit(1)
            continue
        lines.append(line)
    return '\n'.join(lines) + '\n'


@memoized
def yamlize(data):
    try:
        return yaml.load(data, Loader=BaseLoader)
    except yaml.error.YAMLError as e:
        if '{{' in data:
            try:
                import jinja2
                jinja2  # Avoid pyflakes failure: 'jinja2' imported but unused
            except ImportError:
                raise exceptions.UnableToParseMissingJinja2(original=e)
        raise exceptions.UnableToParse(original=e)


def ensure_valid_fields(meta):
    try:
        pin_depends = meta['build']['pin_depends']
    except KeyError:
        pin_depends = ''
    if pin_depends not in ('', 'record', 'strict'):
        raise RuntimeError("build/pin_depends cannot be '%s'" % pin_depends)


def ensure_valid_noarch_value(meta):
    try:
        build_noarch = meta['build']['noarch']
    except KeyError:
        return
    if build_noarch.lower() == 'none':
        raise exceptions.CondaBuildException("Invalid value for noarch: %s" % build_noarch)


def parse(data, config, path=None):
    data = select_lines(data, ns_cfg(config))
    res = yamlize(data)
    # ensure the result is a dict
    if res is None:
        res = {}
    for field in FIELDS:
        if field not in res:
            continue
        # ensure that empty fields are dicts (otherwise selectors can cause invalid fields)
        if not res[field]:
            res[field] = {}
        if not isinstance(res[field], dict):
            raise RuntimeError("The %s field should be a dict, not %s in file %s." %
                               (field, res[field].__class__.__name__, path))

    ensure_valid_fields(res)
    ensure_valid_license_family(res)
    ensure_valid_noarch_value(res)
    return sanitize(res)


trues = {'y', 'on', 'true', 'yes'}
falses = {'n', 'no', 'false', 'off'}

default_structs = {
    'source/patches': list,
    'build/entry_points': list,
    'build/script': list,
    'build/script_env': list,
    'build/features': list,
    'build/track_features': list,
    'requirements/build': list,
    'requirements/run': list,
    'requirements/conflicts': list,
    'test/requires': list,
    'test/files': list,
    'test/source_files': list,
    'test/commands': list,
    'test/imports': list,
    'package/version': text_type,
    'build/string': text_type,
    'build/pin_depends': text_type,
    'source/svn_rev': text_type,
    'source/git_tag': text_type,
    'source/git_branch': text_type,
    'source/md5': text_type,
    'source/git_rev': text_type,
    'source/path': text_type,
    'source/git_url': text_type,
    'build/osx_is_app': bool,
    'build/preserve_egg_dir': bool,
    'build/binary_relocation': bool,
    'build/noarch': text_type,
    'build/noarch_python': bool,
    'build/detect_binary_files_with_prefix': bool,
    'build/skip': bool,
    'build/skip_compile_pyc': list,
    'build/preferred_env': text_type,
    'build/preferred_env_executable_paths': list,
    'app/own_environment': bool
}


def sanitize(meta):
    """
    Sanitize the meta-data to remove aliases/handle deprecation

    """
    # make a copy to avoid side-effects
    meta = meta.copy()
    sanitize_funs = [('source', _git_clean), ]
    for section, func in sanitize_funs:
        if section in meta:
            meta[section] = func(meta[section])
    return meta


def _git_clean(source_meta):
    """
    Reduce the redundancy in git specification by removing git_tag and
    git_branch.

    If one is specified, copy to git_rev.

    If more than one field is used to specified, exit
    and complain.
    """

    git_rev_tags_old = ('git_branch', 'git_tag')
    git_rev = 'git_rev'

    git_rev_tags = (git_rev,) + git_rev_tags_old

    has_rev_tags = tuple(bool(source_meta.get(tag, text_type())) for
                          tag in git_rev_tags)
    if sum(has_rev_tags) > 1:
        msg = "Error: multiple git_revs:"
        msg += ', '.join("{}".format(key) for key, has in
                         zip(git_rev_tags, has_rev_tags) if has)
        sys.exit(msg)

    # make a copy of the input so we have no side-effects
    ret_meta = source_meta.copy()
    # loop over the old versions
    for key, has in zip(git_rev_tags[1:], has_rev_tags[1:]):
        # update if needed
        if has:
            ret_meta[git_rev_tags[0]] = ret_meta[key]
        # and remove
        ret_meta.pop(key, None)

    return ret_meta


# If you update this please update the example in
# conda-docs/docs/source/build.rst
FIELDS = {
    'package': ['name', 'version'],
    'source': ['fn', 'url', 'md5', 'sha1', 'sha256', 'path',
               'git_url', 'git_tag', 'git_branch', 'git_rev', 'git_depth',
               'hg_url', 'hg_tag',
               'svn_url', 'svn_rev', 'svn_ignore_externals',
               'patches'
               ],
    'build': ['number', 'string', 'entry_points', 'osx_is_app',
              'features', 'track_features', 'preserve_egg_dir',
              'no_link', 'binary_relocation', 'script', 'noarch', 'noarch_python',
              'has_prefix_files', 'binary_has_prefix_files', 'ignore_prefix_files',
              'detect_binary_files_with_prefix', 'skip_compile_pyc', 'rpaths',
              'script_env', 'always_include_files', 'skip', 'msvc_compiler',
              'pin_depends', 'include_recipe',  # pin_depends is experimental still
              'preferred_env', 'preferred_env_executable_paths',
              ],
    'requirements': ['build', 'run', 'conflicts'],
    'app': ['entry', 'icon', 'summary', 'type', 'cli_opts',
            'own_environment'],
    'test': ['requires', 'commands', 'files', 'imports', 'source_files'],
    'about': ['home', 'dev_url', 'doc_url', 'license_url',  # these are URLs
              'license', 'summary', 'description', 'license_family',  # text
              'license_file', 'readme',  # paths in source tree
              ],
}


def check_bad_chrs(s, field):
    bad_chrs = '=@#$%^&*:;"\'\\|<>?/ '
    if field in ('package/version', 'build/string'):
        bad_chrs += '-'
    if field != 'package/version':
        bad_chrs += '!'
    for c in bad_chrs:
        if c in s:
            sys.exit("Error: bad character '%s' in %s: %s" % (c, field, s))


def handle_config_version(ms, ver, dep_type='run'):
    """
    'ms' is an instance of MatchSpec, and 'ver' is the version from the
    configuration, e.g. for ms.name == 'python', ver = 26 or None,
    return a (sometimes new) MatchSpec object
    """
    if ms.strictness == 3:
        return ms

    if ms.strictness == 2:
        if ms.spec.split()[1] == 'x.x':
            if ver is None:
                raise RuntimeError("'%s' requires external setting" % ms.spec)
            # (no return here - proceeds below)
        else:  # regular version
            return ms

    # If we don't have a configured version, or we are dealing with a simple
    # numpy runtime dependency; just use "numpy"/the name of the package as
    # the specification. In practice this means that a recipe which just
    # defines numpy as a runtime dependency will match any version of numpy
    # at install time.
    if ver is None or (dep_type == 'run' and ms.strictness == 1 and
                       ms.name == 'numpy'):
        return MatchSpec(ms.name)

    ver = text_type(ver)
    if '.' not in ver:
        if ms.name == 'numpy':
            ver = '%s.%s' % (ver[0], ver[1:])
        else:
            ver = '.'.join(ver)
    return MatchSpec('%s %s*' % (ms.name, ver))


def build_string_from_metadata(metadata):
    if metadata.meta.get('build', {}).get('string'):
        return metadata.get_value('build/string')
    res = []
    version_pat = re.compile(r'(?:==)?(\d+)\.(\d+)')
    for name, s in (('numpy', 'np'), ('python', 'py'),
                    ('perl', 'pl'), ('lua', 'lua'),
                    ('r', 'r'), ('r-base', 'r')):
        for ms in metadata.ms_depends():
            if ms.name == name:
                try:
                    v = ms.spec.split()[1]
                except IndexError:
                    if name not in ['numpy']:
                        res.append(s)
                    break
                if any(i in v for i in ',|>!<'):
                    break
                if name not in ['perl', 'lua', 'r', 'r-base']:
                    match = version_pat.match(v)
                    if match:
                        res.append(s + match.group(1) + match.group(2))
                else:
                    res.append(s + v.strip('*'))
                break

    features = ensure_list(metadata.get_value('build/features', []))
    if res:
        res.append('_')
    if features:
        res.extend(('_'.join(features), '_'))
    res.append('{0}'.format(metadata.build_number() if metadata.build_number() else 0))
    return "".join(res)


class MetaData(object):
    def __init__(self, path, config=None):

        self.undefined_jinja_vars = []

        if not config:
            config = Config()

        self.config = config

        if isfile(path):
            self.meta_path = path
            self.path = os.path.dirname(path)
        else:
            self.meta_path = find_recipe(path)
            self.path = os.path.dirname(self.meta_path)
        self.requirements_path = join(self.path, 'requirements.txt')

        # Start with bare-minimum contents so we can call environ.get_dict() with impunity
        # We'll immediately replace these contents in parse_again()
        self.meta = parse("package:\n"
                          "  name: uninitialized",
                          path=self.meta_path,
                          config=self.config)

        # This is the 'first pass' parse of meta.yaml, so not all variables are defined yet
        # (e.g. GIT_FULL_HASH, etc. are undefined)
        # Therefore, undefined jinja variables are permitted here
        # In the second pass, we'll be more strict. See build.build()
        self.parse_again(config=config, permit_undefined_jinja=True)
        self.config.disable_pip = self.disable_pip

    @property
    def disable_pip(self):
        return 'build' in self.meta and 'disable_pip' in self.meta['build']

    def parse_again(self, config=None, permit_undefined_jinja=False):
        """Redo parsing for key-value pairs that are not initialized in the
        first pass.

        config: a conda-build Config object.  If None, the config object passed at creation
                time is used.

        permit_undefined_jinja: If True, *any* use of undefined jinja variables will
                                evaluate to an emtpy string, without emitting an error.
        """
        if self.meta_path:
            if not config:
                config = self.config
            try:
                os.environ["CONDA_BUILD_STATE"] = "RENDER"
                self.meta = parse(self._get_contents(permit_undefined_jinja, config=config),
                                config=config, path=self.meta_path)
            except:
                raise
            finally:
                del os.environ["CONDA_BUILD_STATE"]

            if (isfile(self.requirements_path) and
                    not self.meta['requirements']['run']):
                self.meta.setdefault('requirements', {})
                run_requirements = specs_from_url(self.requirements_path)
                self.meta['requirements']['run'] = run_requirements

        self.validate_features()
        self.append_requirements()

    def append_requirements(self):
        """For dynamic determination of build or run reqs, based on configuration"""
        reqs = self.meta.get('requirements', {})
        run_reqs = reqs.get('run', [])
        # build_reqs = reqs.get('build', [])
        if bool(self.get_value('build/osx_is_app', False)) and self.config.platform == 'osx':
            run_reqs.append('python.app')
        self.meta['requirements'] = reqs

    def parse_until_resolved(self, config):
        # undefined_jinja_vars is refreshed by self.parse again
        undefined_jinja_vars = ()
        # always parse again at least once.
        self.parse_again(config, permit_undefined_jinja=True)

        while set(undefined_jinja_vars) != set(self.undefined_jinja_vars):
            undefined_jinja_vars = self.undefined_jinja_vars
            self.parse_again(config, permit_undefined_jinja=True)
        if undefined_jinja_vars:
            sys.exit("Undefined Jinja2 variables remain ({}).  Please enable "
                     "source downloading and try again.".format(self.undefined_jinja_vars))

        # always parse again at the end, too.
        self.parse_again(config, permit_undefined_jinja=True)

    @classmethod
    def fromstring(cls, metadata, config=None):
        m = super(MetaData, cls).__new__(cls)
        if not config:
            config = Config()
        m.meta = parse(metadata, path='', config=config)
        m.config = config
        m.parse_again(config=config, permit_undefined_jinja=True)
        return m

    @classmethod
    def fromdict(cls, metadata, config=None):
        """
        Create a MetaData object from metadata dict directly.
        """
        m = super(MetaData, cls).__new__(cls)
        m.path = ''
        m.meta_path = ''
        m.meta = sanitize(metadata)

        if not config:
            config = Config()

        m.config = config
        m.undefined_jinja_vars = []

        return m

    def get_section(self, section):
        return self.meta.get(section, {})

    def get_value(self, field, default=None, autotype=True):
        """
        Get a value from a meta.yaml.
        :param field: Field to return
        :param default: Default object to return if field doesn't exist
        :param autotype: If True, return the default type of field if one exists.
        False will return the default object.
        :return:
        """
        section, key = field.split('/')

        # get correct default
        if autotype and default is None and field in default_structs:
            default = default_structs[field]()

        value = self.get_section(section).get(key, default)

        # handle yaml 1.1 boolean values
        if isinstance(value, text_type):
            if value.lower() in trues:
                value = True
            elif value.lower() in falses:
                value = False

        return value

    def check_fields(self):
        for section, submeta in iteritems(self.meta):
            # anything goes in the extra section
            if section == 'extra':
                continue
            if section not in FIELDS:
                raise ValueError("unknown section: %s" % section)
            for key in submeta:
                if key not in FIELDS[section]:
                    raise ValueError("in section %r: unknown key %r" %
                             (section, key))
        return True

    def name(self):
        res = self.get_value('package/name')
        if not res:
            sys.exit('Error: package/name missing in: %r' % self.meta_path)
        res = text_type(res)
        if res != res.lower():
            sys.exit('Error: package/name must be lowercase, got: %r' % res)
        check_bad_chrs(res, 'package/name')
        return res

    def version(self):
        res = str(self.get_value('package/version'))
        if res is None:
            sys.exit("Error: package/version missing in: %r" % self.meta_path)
        check_bad_chrs(res, 'package/version')
        assert self.undefined_jinja_vars or not res.startswith('.'), "Fully-rendered version can't\
        start with leading period -  got %s" % res
        return res

    def build_number(self):
        number = self.get_value('build/number')
        # build number can come back as None if no setting (or jinja intermediate)
        try:
            build_int = int(number)
        except (ValueError, TypeError):
            build_int = ""
        return build_int

    def ms_depends(self, typ='run'):
        res = []
        name_ver_list = [
            ('python', self.config.CONDA_PY),
            ('numpy', self.config.CONDA_NPY),
            ('perl', self.config.CONDA_PERL),
            ('lua', self.config.CONDA_LUA),
            # r is kept for legacy installations, r-base deprecates it.
            ('r', self.config.CONDA_R),
            ('r-base', self.config.CONDA_R),
        ]
        for spec in self.get_value('requirements/' + typ, []):
            try:
                ms = MatchSpec(spec)
            except AssertionError:
                raise RuntimeError("Invalid package specification: %r" % spec)
            except AttributeError:
                raise RuntimeError("Received dictionary as spec.  Note that pip requirements are "
                                   "not supported in conda-build meta.yaml.")
            if ms.name == self.name():
                raise RuntimeError("%s cannot depend on itself" % self.name())
            for name, ver in name_ver_list:
                if ms.name == name:
                    if self.get_value('build/noarch_python') or self.get_value('build/noarch'):
                        continue
                    ms = handle_config_version(ms, ver, typ)

            for c in '=!@#$%^&*:;"\'\\|<>?/':
                if c in ms.name:
                    sys.exit("Error: bad character '%s' in package name "
                             "dependency '%s'" % (c, ms.name))
                parts = spec.split()
                if len(parts) >= 2:
                    if parts[1] in {'>', '>=', '=', '==', '!=', '<', '<='}:
                        msg = ("Error: bad character '%s' in package version "
                               "dependency '%s'" % (parts[1], ms.name))
                        if len(parts) >= 3:
                            msg += "\nPerhaps you meant '%s %s%s'" % (ms.name,
                                parts[1], parts[2])
                        sys.exit(msg)
            res.append(ms)
        return res

    def build_id(self):
        ret = self.get_value('build/string')
        if ret:
            check_bad_chrs(ret, 'build/string')
        else:
            ret = build_string_from_metadata(self)
        return ret

    def dist(self):
        return '%s-%s-%s' % (self.name(), self.version(), self.build_id())

    def pkg_fn(self):
        return "%s.tar.bz2" % self.dist()

    def is_app(self):
        return bool(self.get_value('app/entry'))

    def app_meta(self):
        d = {'type': 'app'}
        if self.get_value('app/icon'):
            d['icon'] = '%s.png' % md5_file(join(
                self.path, self.get_value('app/icon')))

        for field, key in [('app/entry', 'app_entry'),
                           ('app/type', 'app_type'),
                           ('app/cli_opts', 'app_cli_opts'),
                           ('app/summary', 'summary'),
                           ('app/own_environment', 'app_own_environment')]:
            value = self.get_value(field)
            if value:
                d[key] = value
        return d

    def info_index(self):
        d = dict(
            name=self.name(),
            version=self.version(),
            build=self.build_id(),
            build_number=self.build_number() if self.build_number() else 0,
            platform=platform,
            arch=arch_name,
            subdir=self.config.subdir,
            depends=sorted(' '.join(ms.spec.split())
                             for ms in self.ms_depends()),
        )
        for key in ('license', 'license_family'):
            value = self.get_value('about/' + key)
            if value:
                d[key] = value

        build_noarch = self.get_value('build/noarch')
        if self.get_value('build/features'):
            d['features'] = ' '.join(self.get_value('build/features'))
        if self.get_value('build/track_features'):
            d['track_features'] = ' '.join(self.get_value('build/track_features'))
        if self.get_value('build/noarch_python') or build_noarch:
            d['platform'] = d['arch'] = None
            d['subdir'] = 'noarch'
            if build_noarch:
                d['noarch'] = build_noarch
        if self.is_app():
            d.update(self.app_meta())
        return d

    def has_prefix_files(self):
        ret = ensure_list(self.get_value('build/has_prefix_files', []))
        if not isinstance(ret, list):
            raise RuntimeError('build/has_prefix_files should be a list of paths')
        if sys.platform == 'win32':
            if any('\\' in i for i in ret):
                raise RuntimeError("build/has_prefix_files paths must use / "
                                   "as the path delimiter on Windows")
        return expand_globs(ret, self.config.build_prefix)

    def ignore_prefix_files(self):
        ret = self.get_value('build/ignore_prefix_files', False)
        if type(ret) not in (list, bool):
            raise RuntimeError('build/ignore_prefix_files should be boolean or a list of paths '
                               '(optionally globs)')
        if sys.platform == 'win32':
            if type(ret) is list and any('\\' in i for i in ret):
                raise RuntimeError("build/ignore_prefix_files paths must use / "
                                   "as the path delimiter on Windows")
        return expand_globs(ret, self.config.build_prefix) if type(ret) is list else ret

    def always_include_files(self):
        files = ensure_list(self.get_value('build/always_include_files', []))
        if any('\\' in i for i in files):
            raise RuntimeError("build/always_include_files paths must use / "
                                "as the path delimiter on Windows")
        if on_win:
            files = [f.replace("/", "\\") for f in files]

        return expand_globs(files, self.config.build_prefix)

    def binary_relocation(self):
        ret = self.get_value('build/binary_relocation', True)
        if type(ret) not in (list, bool):
            raise RuntimeError('build/ignore_prefix_files should be boolean or a list of paths '
                               '(optionally globs)')
        if sys.platform == 'win32':
            if type(ret) is list and any('\\' in i for i in ret):
                raise RuntimeError("build/ignore_prefix_files paths must use / "
                                   "as the path delimiter on Windows")
        return expand_globs(ret, self.config.build_prefix) if type(ret) is list else ret

    def include_recipe(self):
        return self.get_value('build/include_recipe', True)

    def binary_has_prefix_files(self):
        ret = ensure_list(self.get_value('build/binary_has_prefix_files', []))
        if not isinstance(ret, list):
            raise RuntimeError('build/binary_has_prefix_files should be a list of paths')
        if sys.platform == 'win32':
            if any('\\' in i for i in ret):
                raise RuntimeError("build/binary_has_prefix_files paths must use / "
                                   "as the path delimiter on Windows")
        return expand_globs(ret, self.config.build_prefix)

    def skip(self):
        return self.get_value('build/skip', False)

    def _get_contents(self, permit_undefined_jinja, config):
        '''
        Get the contents of our [meta.yaml|conda.yaml] file.
        If jinja is installed, then the template.render function is called
        before standard conda macro processors.

        permit_undefined_jinja: If True, *any* use of undefined jinja variables will
                                evaluate to an emtpy string, without emitting an error.
        '''
        try:
            import jinja2
        except ImportError:
            print("There was an error importing jinja2.", file=sys.stderr)
            print("Please run `conda install jinja2` to enable jinja template support", file=sys.stderr)  # noqa
            with open(self.meta_path) as fd:
                return fd.read()

        from conda_build.jinja_context import context_processor, UndefinedNeverFail, FilteredLoader

        path, filename = os.path.split(self.meta_path)
        loaders = [  # search relative to '<conda_root>/Lib/site-packages/conda_build/templates'
                   jinja2.PackageLoader('conda_build'),
                   # search relative to RECIPE_DIR
                   jinja2.FileSystemLoader(path)
                   ]

        # search relative to current conda environment directory
        conda_env_path = os.environ.get('CONDA_DEFAULT_ENV')  # path to current conda environment
        if conda_env_path and os.path.isdir(conda_env_path):
            conda_env_path = os.path.abspath(conda_env_path)
            conda_env_path = conda_env_path.replace('\\', '/')  # need unix-style path
            env_loader = jinja2.FileSystemLoader(conda_env_path)
            loaders.append(jinja2.PrefixLoader({'$CONDA_DEFAULT_ENV': env_loader}))

        undefined_type = jinja2.StrictUndefined
        if permit_undefined_jinja:
            # The UndefinedNeverFail class keeps a global list of all undefined names
            # Clear any leftover names from the last parse.
            UndefinedNeverFail.all_undefined_names = []
            undefined_type = UndefinedNeverFail

        loader = FilteredLoader(jinja2.ChoiceLoader(loaders), config=config)
        env = jinja2.Environment(loader=loader, undefined=undefined_type)

        env.globals.update(ns_cfg(config))
        env.globals.update(context_processor(self, path, config=config,
                                             permit_undefined_jinja=permit_undefined_jinja))

        try:
            template = env.get_or_select_template(filename)
            rendered = template.render(environment=env)

            if permit_undefined_jinja:
                self.undefined_jinja_vars = UndefinedNeverFail.all_undefined_names
            else:
                self.undefined_jinja_vars = []
            return rendered

        except jinja2.TemplateError as ex:
            if "'None' has not attribute" in str(ex):
                ex = "Failed to run jinja context function"
            sys.exit("Error: Failed to render jinja template in {}:\n{}"
                     .format(self.meta_path, str(ex)))

    def __unicode__(self):
        '''
        String representation of the MetaData.
        '''
        return text_type(self.__dict__)

    def __str__(self):
        if PY3:
            return self.__unicode__()
        else:
            return self.__unicode__().encode('utf-8')

    def __repr__(self):
        '''
        String representation of the MetaData.
        '''
        return self.__str__()

    @property
    def uses_setup_py_in_meta(self):
        with open(self.meta_path) as f:
            meta_text = f.read()
        return "load_setup_py_data" in meta_text or "load_setuptools" in meta_text

    @property
    def uses_regex_in_meta(self):
        with open(self.meta_path) as f:
            meta_text = f.read()
        return "load_file_regex" in meta_text

    @property
    def needs_source_for_render(self):
        return self.uses_vcs_in_meta or self.uses_setup_py_in_meta or self.uses_regex_in_meta

    @property
    def uses_jinja(self):
        if not self.meta_path:
            return False
        with open(self.meta_path) as f:
            metayaml = f.read()
            matches = re.findall(r"{{.*}}", metayaml)
        return len(matches) > 0

    @property
    def uses_vcs_in_meta(self):
        """returns name of vcs used if recipe contains metadata associated with version control systems.
        If this metadata is present, a download/copy will be forced in parse_or_try_download.
        """
        vcs_types = ["git", "svn", "hg"]
        # We would get here if we use Jinja2 templating, but specify source with path.
        with open(self.meta_path) as f:
            metayaml = f.read()
            for vcs in vcs_types:
                matches = re.findall(r"{}_[^\.\s\'\"]+".format(vcs.upper()), metayaml)
                if len(matches) > 0 and vcs != self.meta['package']['name']:
                    if vcs == "hg":
                        vcs = "mercurial"
                    return vcs
        return None

    @property
    def uses_vcs_in_build(self):
        build_script = "bld.bat" if on_win else "build.sh"
        build_script = os.path.join(os.path.dirname(self.meta_path), build_script)
        for recipe_file in (build_script, self.meta_path):
            if os.path.isfile(recipe_file):
                vcs_types = ["git", "svn", "hg"]
                with open(recipe_file) as f:
                    build_script = f.read()
                    for vcs in vcs_types:
                        # commands are assumed to have 3 parts:
                        #   1. the vcs command, optionally with an exe extension
                        #   2. a subcommand - for example, "clone"
                        #   3. a target url or other argument
                        matches = re.findall(r"{}(?:\.exe)?(?:\s+\w+\s+[\w\/\.:@]+)".format(vcs),
                                            build_script, flags=re.IGNORECASE)
                        if len(matches) > 0 and vcs != self.meta['package']['name']:
                            if vcs == "hg":
                                vcs = "mercurial"
                            return vcs
        return None

    def validate_features(self):
        if any('-' in feature for feature in ensure_list(self.get_value('build/features'))):
            raise ValueError("- is a disallowed character in features.  Please change this "
                             "character in your recipe.")
