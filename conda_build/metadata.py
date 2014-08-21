from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import os
import re
import sys
from io import open
from os.path import isdir, isfile, join

from conda.compat import iteritems, PY3
from conda.utils import memoized, md5_file
import conda.config as cc
from conda.resolve import MatchSpec

try:
    import yaml
    from yaml import Loader, SafeLoader
except ImportError:
    sys.exit('Error: could not import yaml (required to read meta.yaml '
             'files of conda recipes)')

# Override the default string handling function to always return unicode
# objects (taken from StackOverflow)
def construct_yaml_str(self, node):
    return self.construct_scalar(node)
Loader.add_constructor(u'tag:yaml.org,2002:str', construct_yaml_str)
SafeLoader.add_constructor(u'tag:yaml.org,2002:str', construct_yaml_str)

from conda_build.config import config

# Python 2.x backward compatibility
if sys.version_info < (3, 0):
    str = unicode


def ns_cfg():
    # Remember to update the docs of any of this changes
    plat = cc.subdir
    py = config.CONDA_PY
    np = config.CONDA_NPY
    pl = config.CONDA_PERL
    for x in py, np:
        assert isinstance(x, int), x
    return dict(
        linux = plat.startswith('linux-'),
        linux32 = bool(plat == 'linux-32'),
        linux64 = bool(plat == 'linux-64'),
        armv6 = bool(plat == 'linux-armv6l'),
        osx = plat.startswith('osx-'),
        unix = plat.startswith(('linux-', 'osx-')),
        win = plat.startswith('win-'),
        win32 = bool(plat == 'win-32'),
        win64 = bool(plat == 'win-64'),
        pl = pl,
        py = py,
        py3k = bool(30 <= py < 40),
        py2k = bool(20 <= py < 30),
        py26 = bool(py == 26),
        py27 = bool(py == 27),
        py33 = bool(py == 33),
        py34 = bool(py == 34),
        np = np,
    )


sel_pat = re.compile(r'(.+?)\s*\[(.+)\]$')
def select_lines(data, namespace):
    lines = []
    for i, line in enumerate(data.splitlines()):
        line = line.rstrip()
        m = sel_pat.match(line)
        if m:
            cond = m.group(2)
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
    return yaml.load(data)


def parse(data):
    data = select_lines(data, ns_cfg())
    res = yamlize(data)
    # ensure the result is a dict
    if res is None:
        res = {}
    for field in FIELDS:
        if field in res and not isinstance(res[field], dict):
            raise RuntimeError("The %s field should be a dict, not %s" % (field, res[field].__class__.__name__))
    # ensure those are lists
    for field in ('source/patches',
                  'build/entry_points',
                  'build/features', 'build/track_features',
                  'requirements/build', 'requirements/run',
                  'requirements/conflicts', 'test/requires',
                  'test/files', 'test/commands', 'test/imports'):
        section, key = field.split('/')
        if res.get(section) is None:
            res[section] = {}
        if res[section].get(key, None) is None:
            res[section][key] = []
    # ensure those are strings
    for field in ('package/version', 'build/string', 'source/svn_rev',
                  'source/git_tag', 'source/git_branch', 'source/md5'):
        section, key = field.split('/')
        if res.get(section) is None:
            res[section] = {}
        val = res[section].get(key, '')
        if val is None:
            val = ''
        res[section][key] = str(val)
    return res

# If you update this please update the example in
# conda-docs/docs/source/build.rst
FIELDS = {
    'package': ['name', 'version'],
    'source': ['fn', 'url', 'md5', 'sha1', 'sha256',
               'git_url', 'git_tag', 'git_branch',
               'hg_url', 'hg_tag',
               'svn_url', 'svn_rev', 'svn_ignore_externals',
               'patches'],
    'build': ['number', 'string', 'entry_points', 'osx_is_app',
              'features', 'track_features', 'preserve_egg_dir',
              'no_link', 'binary_relocation', 'script', 'noarch',
              'has_prefix_files', 'binary_has_prefix_files'],
    'requirements': ['build', 'run', 'conflicts'],
    'app': ['entry', 'icon', 'summary', 'type', 'cli_opts',
            'own_environment'],
    'test': ['requires', 'commands', 'files', 'imports'],
    'about': ['home', 'license', 'summary'],
}

def check_bad_chrs(s, field):
    bad_chrs = '=!@#$%^&*:;"\'\\|<>?/ '
    if field in ('package/version', 'build/string'):
        bad_chrs += '-'
    for c in bad_chrs:
        if c in s:
            sys.exit("Error: bad character '%s' in %s: %s" % (c, field, s))

def get_contents(meta_path):
    '''
    Get the contents of the [meta.yaml|conda.yaml] file.
    If jinja is installed, then the template.render function is called
    before standard conda macro processors
    '''
    try:
        import jinja2
    except ImportError:
        print("There was an error importing jinja2.", file=sys.stderr)
        print("Please run `conda install jinja2` to enable jinja template support", file=sys.stderr)
        with open(meta_path, encoding='utf-8') as fd:
            return fd.read()

    from conda_build.jinja_context import context_processor

    path, filename = os.path.split(meta_path)
    loaders = [jinja2.PackageLoader('conda_build'),
               jinja2.FileSystemLoader(path)
               ]
    env = jinja2.Environment(loader=jinja2.ChoiceLoader(loaders))
    env.globals.update(context_processor())
    env.globals.update(ns_cfg())

    template = env.get_or_select_template(filename)

    contents = template.render(environment=env)
    return contents

class MetaData(object):

    def __init__(self, path):
        assert isdir(path)
        self.path = path
        self.meta_path = join(path, 'meta.yaml')
        if not isfile(self.meta_path):
            self.meta_path = join(path, 'conda.yaml')
            if not isfile(self.meta_path):
                sys.exit("Error: meta.yaml or conda.yaml not found in %s" % path)

        self.meta = parse(get_contents(self.meta_path))

    def parse_again(self):
        """Redo parsing for key-value pairs that are not initialized in the
        first pass.
        """
        if not self.meta_path:
            return
        self.meta = parse(get_contents(self.meta_path))

    @classmethod
    def fromdict(cls, metadata):
        """
        Create a MetaData object from metadata dict directly.
        """
        m = super(MetaData, cls).__new__(cls)
        m.path = ''
        m.meta_path = ''
        m.meta = metadata
        return m

    def get_section(self, section):
        return self.meta.get(section, {})

    def get_value(self, field, default=None):
        section, key = field.split('/')
        return self.get_section(section).get(key, default)

    def check_fields(self):
        for section, submeta in iteritems(self.meta):
            if section not in FIELDS:
                sys.exit("Error: unknown section: %s" % section)
            for key in submeta:
                if key not in FIELDS[section]:
                    sys.exit("Error: in section %r: unknown key %r" %
                             (section, key))

    def name(self):
        res = self.get_value('package/name')
        if not res:
            sys.exit('Error: package/name missing in: %r' % self.meta_path)
        res = str(res)
        if res != res.lower():
            sys.exit('Error: package/name must be lowercase, got: %r' % res)
        check_bad_chrs(res, 'package/name')
        return res

    def version(self):
        res = self.get_value('package/version')
        if not res:
            sys.exit("Error: package/version missing in: %r" % self.meta_path)
        check_bad_chrs(res, 'package/version')
        return res

    def build_number(self):
        return int(self.get_value('build/number', 0))

    def ms_depends(self, typ='run'):
        res = []
        name_ver_list = [('python', config.CONDA_PY), ('numpy', config.CONDA_NPY),
                         ('perl', config.CONDA_PERL)]
        for spec in self.get_value('requirements/' + typ, []):
            try:
                ms = MatchSpec(spec)
            except AssertionError:
                raise RuntimeError("Invalid package specification: %r" % spec)
            for name, ver in name_ver_list:
                if ms.name == name:
                    if ms.strictness != 1:
                        continue
                    str_ver = str(ver)
                    if '.' not in str_ver:
                        str_ver = '.'.join(str_ver)
                    ms = MatchSpec('%s %s*' % (name, str_ver))
            for c in '=!@#$%^&*:;"\'\\|<>?/':
                if c in ms.name:
                    sys.exit("Error: bad character '%s' in package name "
                             "dependency '%s'" % (c, ms.name))
            res.append(ms)
        return res

    def build_id(self):
        ret = self.get_value('build/string')
        if ret:
            check_bad_chrs(ret, 'build/string')
            return ret
        res = []
        version_re = re.compile(r'(?:==)?(\d)\.(\d)')
        for name, s in (('numpy', 'np'), ('python', 'py'), ('perl', 'pl')):
            for ms in self.ms_depends():
                if ms.name == name:
                    v = ms.spec.split()[1]
                    if ',' in v or '|' in v:
                        break
                    if name != 'perl':
                        match = version_re.match(v)
                        if match:
                            res.append(s + match.group(1) + match.group(2))
                    else:
                        res.append(s + v.strip('*>=!<'))
                    break
        if res:
            res.append('_')
        res.append('%d' % self.build_number())
        return ''.join(res)

    def dist(self):
        return '%s-%s-%s' % (self.name(), self.version(), self.build_id())

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
            license = self.get_value('about/license'),
            platform = cc.platform,
            arch = cc.arch_name,
            depends = sorted(ms.spec for ms in self.ms_depends())
        )
        if self.get_value('build/features'):
            d['features'] = ' '.join(self.get_value('build/features'))
        if self.get_value('build/track_features'):
            d['track_features'] = ' '.join(self.get_value('build/track_features'))
        if self.get_value('build/noarch'):
            d['platform'] = d['arch'] = None
        if self.is_app():
            d.update(self.app_meta())
        return d

    def has_prefix_files(self):
        ret = self.get_value('build/has_prefix_files', [])
        if not isinstance(ret, list):
            raise RuntimeError('build/has_prefix_files should be a list of paths')
        return ret

    def binary_has_prefix_files(self):
        ret = self.get_value('build/binary_has_prefix_files', [])
        if not isinstance(ret, list):
            raise RuntimeError('build/binary_has_prefix_files should be a list of paths')
        return ret

    def __unicode__(self):
        '''
        String representation of the MetaData.
        '''
        return str(self.__dict__)

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
