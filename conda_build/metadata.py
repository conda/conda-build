from __future__ import absolute_import, division, print_function

import os
import re
import sys
from os.path import isdir, isfile, join
from difflib import get_close_matches

from conda.compat import iteritems, PY3, text_type
from conda.utils import memoized, md5_file
import conda.config as cc
from conda.resolve import MatchSpec
from conda.cli.common import specs_from_url

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

from conda_build.config import config
from conda_build.utils import comma_join
from conda_build import exceptions

def ns_cfg():
    # Remember to update the docs of any of this changes
    plat = cc.subdir
    py = config.CONDA_PY
    np = config.CONDA_NPY
    pl = config.CONDA_PERL
    lua = config.CONDA_LUA
    assert isinstance(py, int), py
    d = dict(
        linux = plat.startswith('linux-'),
        linux32 = bool(plat == 'linux-32'),
        linux64 = bool(plat == 'linux-64'),
        arm = plat.startswith('linux-arm'),
        osx = plat.startswith('osx-'),
        unix = plat.startswith(('linux-', 'osx-')),
        win = plat.startswith('win-'),
        win32 = bool(plat == 'win-32'),
        win64 = bool(plat == 'win-64'),
        pl = pl,
        py = py,
        lua = lua,
        luajit = bool(lua[0] == "2"),
        py3k = bool(30 <= py < 40),
        py2k = bool(20 <= py < 30),
        py26 = bool(py == 26),
        py27 = bool(py == 27),
        py33 = bool(py == 33),
        py34 = bool(py == 34),
        py35 = bool(py == 35),
        np = np,
        os = os,
        environ = os.environ,
    )
    for machine in cc.non_x86_linux_machines:
        d[machine] = bool(plat == 'linux-%s' % machine)

    d.update(os.environ)
    return d


sel_pat = re.compile(r'(.+?)\s*(#.*)?\[(.+)\](?(2).*)$')
def select_lines(data, namespace):
    lines = []
    for i, line in enumerate(data.splitlines()):
        line = line.rstrip()
        if line.lstrip().startswith('#'):
            # Don't bother with comment only lines
            continue
        m = sel_pat.match(line)
        if m:
            cond = m.group(3)
            try:
                if eval(cond, namespace, {}):
                    lines.append(m.group(1))
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
                jinja2 # Avoid pyflakes failure: 'jinja2' imported but unused
            except ImportError:
                raise exceptions.UnableToParseMissingJinja2(original=e)
        raise exceptions.UnableToParse(original=e)


allowed_license_families = set("""
AGPL
Apache
BSD
GPL2
GPL3
LGPL
MIT
Other
PSF
Proprietary
Public-Domain
""".split())

def ensure_valid_license_family(meta):
    try:
        license_family = meta['about']['license_family']
    except KeyError:
        return
    if license_family not in allowed_license_families:
        raise RuntimeError(exceptions.indent(
            "about/license_family '%s' not allowed. Allowed families are %s." %
            (license_family, comma_join(sorted(allowed_license_families)))))

def ensure_valid_fields(meta):
    try:
        pin_depends = meta['build']['pin_depends']
    except KeyError:
        pin_depends = ''
    if pin_depends not in ('', 'record', 'strict'):
        raise RuntimeError("build/pin_depends cannot be '%s'" % pin_depends)

def parse(data, path=None):
    data = select_lines(data, ns_cfg())
    res = yamlize(data) or {}

    ensure_valid_fields(res)
    ensure_valid_license_family(res)
    return sanitize(res)


trues = {'y', 'on', 'true', 'yes'}
falses = {'n', 'no', 'false', 'off'}

default_structs = {
    'source/patches': list,
    'build/entry_points': list,
    'build/script_env': list,
    'build/features': list,
    'build/track_features': list,
    'requirements/build': list,
    'requirements/run': list,
    'requirements/conflicts': list,
    'test/requires': list,
    'test/files': list,
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
    'build/noarch_python': bool,
    'build/detect_binary_files_with_prefix': bool,
    'build/skip': bool,
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
RECOGNIZED_FIELDS = {
    'package/name', 'package/version',

    'source/fn', 'source/url', 'source/md5', 'source/sha1', 'source/patches',
    'source/sha256', 'source/path', 'source/git_url', 'source/git_tag',
    'source/git_branch', 'source/git_rev', 'source/git_depth',
    'source/hg_url', 'source/hg_tag',
    'source/snv_url', 'source/svn_rev', 'source/snv_ignore_externals',

    'build/number', 'build/string', 'build/entry_points', 'build/osx_is_app',
    'build/features', 'build/track_features', 'build/preserve_egg_dir',
    'build/no_link', 'build/binary_relocation', 'build/script',
    'build/noarch_python', 'build/has_prefix_files', 'build/binary_has_prefix_files',
    'build/script_env', 'build/detect_binary_files_with_prefix', 'build/rpaths',
    'build/always_include_files', 'build/skip', 'build/msvc_compiler',
    'build/pin_depends',  # build/pin_depends is still experimental

    'requirements/build', 'requirements/run', 'requirements/conflicts',
    'app/entry', 'app/icon', 'app/summary', 'app/type', 'app/cli_opts', 'app/own_environment',

    'test/requires', 'test/commands', 'test/files', 'test/imports',

    'about/home', 'about/dev_url', 'about/doc_url', 'about/license_url', 'about/license',
    'about/summary', 'about/description', 'about/license_family', 'about/license_file', 'about/readme'
}

def check_fields(meta, strictness=.9):
    """
    Check all fields in the meta.yaml file.  This method attempts to detect keys that might
    be typos of recognized keys.

    :param meta:
    :param strictness:
    :return:
    """
    # Check that package/name and package/version exist
    _meta = meta.meta
    try:
        _ = _meta['package']['name']
        _ = _meta['package']['version']
    except KeyError:
        sys.exit('Invalid meta.yaml: Missing package/name or package/version.')

    try:
        _ = _meta['about']['home']
        _ = _meta['about']['license_family']
    except KeyError:
        sys.exit('Missing about/home or about/license_family')

    for mk in meta.get_all_keys():
        close_matches = set(get_close_matches(mk, RECOGNIZED_FIELDS, cutoff=strictness))

        # If there was nothing even close, we allow it -- it's a user-defined key.
        # But if we found a close match, notify the user -- it's probably a typo.
        if close_matches and mk not in close_matches:
            sys.exit("In meta.yaml: {} is not a recognized key, but it's similar to a standard key.\n"
                     "Perhaps you meant {}?".format(mk, ', '.join(close_matches)))
            

bad_chars = re.compile(r'[=!@#$%^&*:;"\'\\|<>?/ -]')
def check_bad_chrs(s, field):
    m = bad_chars.search(s)
    if m:
        if m.group() == '-' and field not in {'package/version', 'build/string'}:
            return

        sys.exit("Error: Bad character '{}' in {}: {}".format(m.group(), field, s))


def handle_config_version(ms, ver):
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
        else: # regular version
            return ms

    if ver is None or (ms.strictness == 1 and ms.name == 'numpy'):
        return MatchSpec(ms.name)

    ver = text_type(ver)
    if '.' not in ver:
        if ms.name == 'numpy':
            ver = '%s.%s' % (ver[0], ver[1:])
        else:
            ver = '.'.join(ver)
    return MatchSpec('%s %s*' % (ms.name, ver))


class MetaData(object):

    def __init__(self, path):
        assert isdir(path)
        self.path = path
        self.meta_path = join(path, 'meta.yaml')
        self.requirements_path = join(path, 'requirements.txt')
        if not isfile(self.meta_path):
            self.meta_path = join(path, 'conda.yaml')
            if not isfile(self.meta_path):
                sys.exit("Error: meta.yaml or conda.yaml not found in %s" % path)

        # Start with bare-minimum contents so we can call environ.get_dict() with impunity
        # We'll immediately replace these contents in parse_again()
        self.meta = parse("package:\n"
                          "  name: uninitialized\n"
                          "  version: uninitialized\n")

        # This is the 'first pass' parse of meta.yaml, so not all variables are defined yet
        # (e.g. GIT_FULL_HASH, etc. are undefined)
        # Therefore, undefined jinja variables are permitted here
        # In the second pass, we'll be more strict. See build.build()
        self.parse_again(permit_undefined_jinja=True)

    def parse_again(self, permit_undefined_jinja=False):
        """Redo parsing for key-value pairs that are not initialized in the
        first pass.

        permit_undefined_jinja: If True, *any* use of undefined jinja variables will
                                evaluate to an emtpy string, without emitting an error.
        """
        if not self.meta_path:
            return
        self.meta = parse(self._get_contents(permit_undefined_jinja))

        if (isfile(self.requirements_path) and
                   not self.meta['requirements']['run']):
            self.meta.setdefault('requirements', {})
            run_requirements = specs_from_url(self.requirements_path)
            self.meta['requirements']['run'] = run_requirements

    @classmethod
    def fromdict(cls, metadata):
        """
        Create a MetaData object from metadata dict directly.
        """
        m = super(MetaData, cls).__new__(cls)
        m.path = ''
        m.meta_path = ''
        m.meta = sanitize(metadata)
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

    def get_all_keys(self):
        """
        Yield all keys in the meta structure.

        The returned strings are usable with get_value().
        :return:
        """

        def flatten_dict_keys(root):
            for k, v in iteritems(root):
                if isinstance(v, dict):
                    for x in flatten_dict_keys(v):
                        yield '/'.join((k, x))
                else:
                    yield k

        return iter(flatten_dict_keys(self.meta))

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
        res = self.get_value('package/version')
        if res is None:
            sys.exit("Error: package/version missing in: %r" % self.meta_path)
        check_bad_chrs(res, 'package/version')
        return res

    def build_number(self):
        return int(self.get_value('build/number', 0))

    def ms_depends(self, typ='run'):
        res = []
        name_ver_list = [
            ('python', config.CONDA_PY),
            ('numpy', config.CONDA_NPY),
            ('perl', config.CONDA_PERL),
            ('lua', config.CONDA_LUA),
            ('r', config.CONDA_R),
        ]
        for spec in self.get_value('requirements/' + typ, []):
            try:
                ms = MatchSpec(spec)
            except AssertionError:
                raise RuntimeError("Invalid package specification: %r" % spec)
            if ms.name == self.name():
                raise RuntimeError("%s cannot depend on itself" % self.name())
            for name, ver in name_ver_list:
                if ms.name == name:
                    if self.get_value('build/noarch_python'):
                        continue
                    ms = handle_config_version(ms, ver)

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
            return ret
        res = []
        version_pat = re.compile(r'(?:==)?(\d+)\.(\d+)')
        for name, s in (('numpy', 'np'), ('python', 'py'),
                        ('perl', 'pl'), ('lua', 'lua'), ('r', 'r')):
            for ms in self.ms_depends():
                if ms.name == name:
                    try:
                        v = ms.spec.split()[1]
                    except IndexError:
                        if name not in ['numpy']:
                            res.append(s)
                        break
                    if any(i in v for i in ',|>!<'):
                        break
                    if name not in ['perl', 'r', 'lua']:
                        match = version_pat.match(v)
                        if match:
                            res.append(s + match.group(1) + match.group(2))
                    else:
                        res.append(s + v.strip('*'))
                    break

        features = self.get_value('build/features', [])
        if res:
            res.append('_')
        if features:
            res.extend(('_'.join(features), '_'))
        res.append('%d' % self.build_number())
        return ''.join(res)

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
            name = self.name(),
            version = self.version(),
            build = self.build_id(),
            build_number = self.build_number(),
            platform = cc.platform,
            arch = cc.arch_name,
            subdir = cc.subdir,
            depends = sorted(' '.join(ms.spec.split())
                             for ms in self.ms_depends()),
        )
        for key in ('license', 'license_family'):
            value = self.get_value('about/' + key)
            if value:
                d[key] = value

        if self.get_value('build/features'):
            d['features'] = ' '.join(self.get_value('build/features'))
        if self.get_value('build/track_features'):
            d['track_features'] = ' '.join(self.get_value('build/track_features'))
        if self.get_value('build/noarch_python'):
            d['platform'] = d['arch'] = None
            d['subdir'] = 'noarch'
        if self.is_app():
            d.update(self.app_meta())
        return d

    def has_prefix_files(self):
        ret = self.get_value('build/has_prefix_files', [])
        if not isinstance(ret, list):
            raise RuntimeError('build/has_prefix_files should be a list of paths')
        if sys.platform == 'win32':
            if any('\\' in i for i in ret):
                raise RuntimeError("build/has_prefix_files paths must use / as the path delimiter on Windows")
        return ret

    def always_include_files(self):
        return self.get_value('build/always_include_files', [])

    def binary_has_prefix_files(self):
        ret = self.get_value('build/binary_has_prefix_files', [])
        if not isinstance(ret, list):
            raise RuntimeError('build/binary_has_prefix_files should be a list of paths')
        if sys.platform == 'win32':
            if any('\\' in i for i in ret):
                raise RuntimeError("build/binary_has_prefix_files paths must use / as the path delimiter on Windows")
        return ret

    def skip(self):
        return self.get_value('build/skip', False)

    def _get_contents(self, permit_undefined_jinja):
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
            print("Please run `conda install jinja2` to enable jinja template support", file=sys.stderr)
            with open(self.meta_path) as fd:
                return fd.read()

        from conda_build.jinja_context import context_processor

        path, filename = os.path.split(self.meta_path)
        loaders = [# search relative to '<conda_root>/Lib/site-packages/conda_build/templates'
                   jinja2.PackageLoader('conda_build'),
                   # search relative to RECIPE_DIR
                   jinja2.FileSystemLoader(path)
                   ]

        # search relative to current conda environment directory
        conda_env_path = os.environ.get('CONDA_DEFAULT_ENV')  # path to current conda environment
        if conda_env_path and os.path.isdir(conda_env_path):
            conda_env_path = os.path.abspath(conda_env_path)
            conda_env_path = conda_env_path.replace('\\', '/') # need unix-style path
            env_loader = jinja2.FileSystemLoader(conda_env_path)
            loaders.append(jinja2.PrefixLoader({'$CONDA_DEFAULT_ENV': env_loader}))

        class FilteredLoader(jinja2.BaseLoader):
            """
            A pass-through for the given loader, except that the loaded source is
            filtered according to any metadata selectors in the source text.
            """
            def __init__(self, unfiltered_loader):
                self._unfiltered_loader = unfiltered_loader
                self.list_templates = unfiltered_loader.list_templates

            def get_source(self, environment, template):
                contents, filename, uptodate = self._unfiltered_loader.get_source(environment, template)
                return select_lines(contents, ns_cfg()), filename, uptodate

        undefined_type = jinja2.StrictUndefined
        if permit_undefined_jinja:
            class UndefinedNeverFail(jinja2.Undefined):
                """
                A class for Undefined jinja variables.
                This is even less strict than the default jinja2.Undefined class,
                because it permits things like {{ MY_UNDEFINED_VAR[:2] }} and {{ MY_UNDEFINED_VAR|int }}.
                This can mask lots of errors in jinja templates, so it should only be used for a first-pass
                parse, when you plan on running a 'strict' second pass later.
                """
                __add__ = __radd__ = __mul__ = __rmul__ = __div__ = __rdiv__ = \
                __truediv__ = __rtruediv__ = __floordiv__ = __rfloordiv__ = \
                __mod__ = __rmod__ = __pos__ = __neg__ = __call__ = \
                __getitem__ = __lt__ = __le__ = __gt__ = __ge__ = \
                __complex__ = __pow__ = __rpow__ = \
                    lambda *args, **kwargs: UndefinedNeverFail()

                __str__ = __repr__ = \
                    lambda *args, **kwargs: u''

                __int__ = lambda _: 0
                __float__ = lambda _: 0.0

                def __getattr__(self, k):
                    try:
                        return object.__getattr__(self, k)
                    except AttributeError:
                        return UndefinedNeverFail()

                def __setattr__(self, k, v):
                    pass

            undefined_type = UndefinedNeverFail

        loader = FilteredLoader(jinja2.ChoiceLoader(loaders))
        env = jinja2.Environment(loader=loader, undefined=undefined_type)
        env.globals.update(ns_cfg())
        env.globals.update(context_processor(self, path))

        try:
            template = env.get_or_select_template(filename)
            return template.render(environment=env)
        except jinja2.TemplateError as ex:
            sys.exit("Error: Failed to render jinja template in {}:\n{}".format(self.meta_path, ex.message))

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


if __name__ == '__main__':
    from pprint import pprint
    from os.path import expanduser

    m = MetaData(expanduser('~/conda-recipes/pycosat'))
    pprint(m.info_index())
