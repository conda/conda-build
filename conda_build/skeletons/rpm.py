import argparse
from conda_build.conda_interface import iteritems
from conda_build.source import download_to_cache
from conda_build.license_family import guess_license_family
from copy import copy
try:
    import cPickle as pickle
except:
    import pickle as pickle
import gzip
import hashlib
from os import (chmod, makedirs)
from os.path import (basename, dirname, exists, join, splitext)
import re
from six import string_types
from six.moves import zip_longest
from textwrap import wrap
from xml.etree import cElementTree as ET
from .cran import yaml_quote_string


try:
    from urllib.request import urlopen
except ImportError:
    from urllib2 import urlopen


RPM_META = """\
package:
  name: {packagename}
  version: {version}

source:
  - url: {rpmurl}
    {checksum_name}: {checksum}
    folder: binary
  - url: {srcrpmurl}
    folder: source

outputs:
  - name: {packagename}
    target: noarch
    about:
      home: {home}
      license: {license}
      license_family: {license_family}
      summary: {summary}
      description: {description}

{depends}
"""


RPM2CPIO = """\
#!/bin/sh

# Based on:
# https://www.redhat.com/archives/rpm-list/2003-June/msg00367.html
# Modified to also support xz compression.

pkg=$1
if [ "$pkg" = "" -o ! -e "$pkg" ]; then
    echo "no package supplied" 1>&2
   exit 1
fi

leadsize=96
o=`expr $leadsize + 8`
set `od -j $o -N 8 -t u1 $pkg`
il=`expr 256 \* \( 256 \* \( 256 \* $2 + $3 \) + $4 \) + $5`
dl=`expr 256 \* \( 256 \* \( 256 \* $6 + $7 \) + $8 \) + $9`

sigsize=`expr 8 + 16 \* $il + $dl`
o=`expr $o + $sigsize + \( 8 - \( $sigsize \% 8 \) \) \% 8 + 8`
set `od -j $o -N 8 -t u1 $pkg`
il=`expr 256 \* \( 256 \* \( 256 \* $2 + $3 \) + $4 \) + $5`
dl=`expr 256 \* \( 256 \* \( 256 \* $6 + $7 \) + $8 \) + $9`

hdrsize=`expr 8 + 16 \* $il + $dl`
o=`expr $o + $hdrsize`

hdr=`dd if=$pkg ibs=$o skip=1 count=1 2>/dev/null | od -N 2 -t x1 -An`
# macOS dd and Linux od give different results
hdr="${hdr#"${hdr%%[![:space:]]*}"}"
# remove trailing whitespace characters
hdr="${hdr%"${hdr##*[![:space:]]}"}"
if [[ "$hdr" == "1f 8b" ]] || [[ "$hdr" == "1f  8b" ]]; then
  dd if=$pkg ibs=$o skip=1 2>/dev/null | gunzip
else
  dd if=$pkg ibs=$o skip=1 2>/dev/null | xz -d
fi
"""

BUILDSH = """\
#!/bin/bash

RPM=$(find ${PWD}/binary -name "*.rpm")
mkdir -p ${PREFIX}/{hostmachine}/sysroot
pushd ${PREFIX}/{hostmachine}/sysroot > /dev/null 2>&1
  "${RECIPE_DIR}"/rpm2cpio "${RPM}" | cpio -idmv
popd > /dev/null 2>&1
"""


CDTs = dict({'centos5': {'dirname': 'centos5',
                         'short_name': 'cos5',
                         'base_url': 'http://vault.centos.org/5.11/os/{base_architecture}/CentOS/',
                         'sbase_url': 'http://vault.centos.org/5.11/os/Source/',
                         'repomd_url': 'http://vault.centos.org/5.11/os/{base_architecture}/repodata/repomd.xml',  # noqa
                         'host_machine': '{architecture}-conda_cos5-linux-gnu',
                         'host_subdir': 'linux-{bits}',
                         'rpm_filename_platform': 'el5.{architecture}',
                         'checksummer': hashlib.sha1,
                         'checksummer_name': "sha1",
                         'macros': {}},
            'centos6': {'dirname': 'centos6',
                         'short_name': 'cos6',
                         'base_url': 'http://mirror.centos.org/centos/6.9/os/{base_architecture}/CentOS/',  # noqa
                         'sbase_url': 'http://vault.centos.org/6.9/os/Source/SPackages/',
                         'repomd_url': 'http://mirror.centos.org/centos/6.9/os/{base_architecture}/repodata/repomd.xml',  # noqa
                         'host_machine': '{architecture}-conda_cos6-linux-gnu',
                         'host_subdir': 'linux-{bits}',
                         'rpm_filename_platform': 'el6.{architecture}',
                         'checksummer': hashlib.sha256,
                         'checksummer_name': "sha256",
                         # Some macros are defined in /etc/rpm/macros.* but I cannot find where
                         # these ones are defined. Also, rpm --eval "%{gdk_pixbuf_base_version}"
                         # gives nothing nor does rpm --showrc | grep gdk
                         'macros': {'pyver': '2.6.6',
                                    'gdk_pixbuf_base_version': '2.24.1'}},
            'suse_leap_rpi3': {'dirname': 'suse_leap_rpi3',
                                'cdt_short_name': 'slrpi3',
                                'base_url': 'http://download.opensuse.org/ports/{arch}/distribution/leap/42.3-Current/repo/oss/suse/{arch}/',  # noqa
                                'base_url_to_repomd': 'repodata/repomd.xml',
                                'repomd_url': 'http://vault.centos.org/5.11/os/{base_architecture}/repodata/repomd.xml',  # noqa
                                'host_machine': 'aarch64-conda_rpi3-linux-gnueabi',
                                'host_subdir': 'linux-aarch64',
                                'rpm_filename_platform': 'el5.{arch}',
                                'checksummer': hashlib.sha256,
                                'checksummer_name': "sha256",
                                'macros': {}},
             'raspbian_rpi2': {'dirname': 'raspbian_rpi2',
                               'cdt_short_name': 'rrpi2',
                               'host_machine': 'armv7a-conda_rpi2-linux-gnueabi',
                               'host_subdir': 'armv7a-32',
                               'checksummer': hashlib.sha256,
                               'checksummer_name': "sha256",
                               'macros': {}},
             })


def package_exists(package_name):
    """This is a simple function returning True/False for if a requested package string exists
    in the add-on repository."""
    return True


def cache_file(src_cache, url, fn=None, checksummer=hashlib.sha256):
    if fn:
        source = dict({'url': url, 'fn': fn})
    else:
        source = dict({'url': url})
    cached_path = download_to_cache(src_cache, '', source)
    csum = checksummer()
    csum.update(open(cached_path, 'rb').read())
    csumstr = csum.hexdigest()
    return cached_path, csumstr


def rpm_filename_split(rpmfilename):
    base, _ = splitext(rpmfilename)
    release_platform = base.split('-')[-1]
    parts = release_platform.split('.')
    if len(parts) == 2:
        release, platform = parts[0], parts[1]
    elif len(parts) > 2:
        release, platform = '.'.join(parts[0:len(parts) - 1]), '.'.join(parts[-1:])
    else:
        print("ERROR: Cannot figure out the release and platform for {}".format(base))
    name_version = base.split('-')[0:-1]
    version = name_version[-1]
    rpm_name = '-'.join(name_version[0:len(name_version) - 1])
    return rpm_name, version, release, platform


def rpm_url_split(rpm_url, src_cache):
    """
    Exists mainly to check the results of rpm_filename_split with pyrpm.
    These need to match because we use the same (well, reverse) logic to
    form the URLs for the dependencies.

    .. or rather it used to do that, but I do not want to depend on pyrpm
    anymore so it does nothing now.
    """
    cached_path, sha256str = cache_file(src_cache, rpm_url)
    rpm_name, version, release, platform = rpm_filename_split(basename(rpm_url))

    """
    try:
        from pyrpm.rpm import RPM
    except ImportError:
        RPM = None
        print("ERROR: Please install pyrpm via:\nconda install pyrpm")
        sys.exit(1)

    with open(cached_path, 'rb') as rpmfile:
        rpm = RPM(rpmfile)
        check_rpm_name = rpm.header.name
        check_version = rpm.header.version
        check_release = rpm.header.release
        check_platform = rpm.header.platform
        check_sha256str = rpm.checksum
        # print((rpm.header.entries))

        assert check_rpm_name == rpm_name, 'rpm_name {} != {}'.format(check_rpm_name, rpm_name)
        assert check_version == version, 'version {} != {}'.format(check_version, version)
        assert check_release == release, 'release {} != {}'.format(check_release, release)
        # assert check_platform == platform, 'platform {} != {}'.format(check_platform, platform)
        if check_sha256str != sha256str:
            # Make sure to remove the file if the checksums do not match
            print("ERROR: RPM checksum: {} does not match\n"\
                  "        cached file: {} for file {}".format(check_sha256str,
                                                               sha256str,
                                                               cached_path))
            unlink(cached_path)
        assert check_sha256str == sha256str
    """

    return rpm_name, version, release, platform, cached_path, sha256str


def rpm_filename_generate(rpm_name, version, release, platform):
    return '{}-{}-{}.{}.rpm'.format(rpm_name, version, release, platform)


def rpm_url_generate(url_dirname, rpm_name, version, release, platform, src_cache):
    """
    Forms the URL and also attempts to cache it to verify it exists.
    """
    result = rpm_filename_generate(rpm_name, version, release, platform)
    url = join(url_dirname, result)
    path = download_to_cache(src_cache, '', dict({'url': url}))
    assert path, "Failed to cache generated RPM url {}".format(result)
    return url


def find_repo_entry_and_arch(repo_primary, architectures, depend):
    dep_name = depend['name']
    found_package_name = ''
    try:
        # Try direct lookup first.
        found_package = repo_primary[dep_name]
        found_package_name = dep_name
    except:
        # Look through the provides of all packages.
        for name, package in iteritems(repo_primary):
            for arch in architectures:
                if arch in package:
                    if 'provides' in package[arch]:
                        for provide in package[arch]['provides']:
                            if provide['name'] == dep_name:
                                print("Found it in {}".format(name))
                                found_package = package
                                found_package_name = name
                                break

    if found_package_name == '':
        print("WARNING: Did not find package called (or another one providing) {}".format(dep_name))  # noqa
        return None, None, None

    chosen_arch = None
    for arch in architectures:
        if arch in found_package:
            chosen_arch = arch
            break
    if not chosen_arch:
        return None, None, None
    entry = found_package[chosen_arch]
    return entry, found_package_name, chosen_arch


str_flags_to_conda_version_spec = dict({'LT': '<',
                                        'LE': '<=',
                                        'EQ': '==',
                                        'GE': '>=',
                                        'GT': '>',
                                        })


def RPMprco_to_depends(RPMprco):
    epoch = RPMprco.version[0]
    if epoch is None:
        epoch = 0
    if epoch != 0:
        print("WARNING: {} has an (unhandled) epoch of {}".format(RPMprco.name, epoch))
    if RPMprco.str_flags is not None:
        str_flags = str_flags_to_conda_version_spec[RPMprco.str_flags]
    else:
        str_flags = None
    return dict({'name': RPMprco.name,
                 'flags': str_flags,
                 'epoch': epoch,
                 'ver': RPMprco.version[1],
                 'rel': RPMprco.version[2]})


def dictify(r, root=True):
    if root:
        return {r.tag: dictify(r, False)}
    d = copy(r.attrib)
    if r.text:
        d["_text"] = r.text
    for x in r.findall("./*"):
        if x.tag not in d:
            d[x.tag] = []
        d[x.tag].append(dictify(x, False))
    return d


def dictify_pickled(xml_file, dict_massager=None, cdt=None):
    pickled = xml_file + '.p'
    if exists(pickled):
        return pickle.load(open(pickled, 'rb'))
    with open(xml_file, 'rt') as xf:
        xmlstring = xf.read()
        # Remove the global namespace.
        xmlstring = re.sub(r'\sxmlns="[^"]+"', r'', xmlstring, count=1)
        # Replace sub-namespaces with their names.
        xmlstring = re.sub(r'\sxmlns:([a-zA-Z]*)="[^"]+"', r' xmlns:\1="\1"', xmlstring)
        root = ET.fromstring(xmlstring)
        result = dictify(root)
        if dict_massager:
            result = dict_massager(result, cdt)
        pickle.dump(result, open(pickled, 'wb'))
        return result


def get_repo_dict(repomd_url, data_type, dict_massager, cdt, src_cache):
    xmlstring = urlopen(repomd_url).read()
    # Remove the default namespace definition (xmlns="http://some/namespace")
    xmlstring = re.sub(b'\sxmlns="[^"]+"', b'', xmlstring, count=1)
    repomd = ET.fromstring(xmlstring)
    for child in repomd.findall("*[@type='{}']".format(data_type)):
        open_csum = child.findall("open-checksum")[0].text
        xml_file = join(src_cache, open_csum)
        try:
            xml_file, xml_csum = cache_file(src_cache, xml_file, cdt['checksummer'])
        except:
            csum = child.findall("checksum")[0].text
            location = child.findall("location")[0].attrib['href']
            xmlgz_file = dirname(dirname(repomd_url)) + '/' + location
            cached_path, cached_csum = cache_file(src_cache, xmlgz_file,
                                                  csum, cdt['checksummer'])
            assert csum == cached_csum, "Checksum for {} does not match value in {}".format(
                xmlgz_file, repomd_url)
            with gzip.open(cached_path, 'rb') as gz:
                xml_content = gz.read()
                xml_csum = cdt['checksummer']()
                xml_csum.update(xml_content)
                xml_csum = xml_csum.hexdigest()
                if xml_csum == open_csum:
                    with open(xml_file, 'wb') as xml:
                        xml.write(xml_content)
                else:
                    print("ERROR: Checksum of uncompressed file {} does not match".format(xmlgz_file))  # noqa
        return dictify_pickled(xml_file, dict_massager, cdt)
    return dict({})


def massage_primary_requires(requires, cdt):
    for require in requires:
        require['name'] = require['name']
        if 'flags' in require:
            require['flags'] = str_flags_to_conda_version_spec[require['flags']]
        else:
            require['flags'] = None
        if 'ver' in require:
            if '%' in require['ver']:
                require['ver'] = require['ver'].replace('%', '')
                if not require['ver'].startswith('{'):
                    require['ver'] = '{' + require['ver']
                if not require['ver'].endswith('}'):
                    require['ver'] = require['ver'] + '}'
                require['ver'] = require['ver'].format(**cdt['macros'])
    return requires


def massage_primary(repo_primary, cdt):
    """
    Massages the result of dictify() into a less cumbersome form.
    In particular:
    1. There are many lists that can only be of length one that
       don't need to be lists at all.
    2. The '_text' entries need to go away.
    3. The real information starts at ['metadata']['package']
    4. We want the top-level key to be the package name and under
       that, an entry for each arch for which the package exists.
    """

    new_dict = dict({})
    for package in repo_primary['metadata']['package']:
        name = package['name'][0]['_text']
        arch = package['arch'][0]['_text']
        if arch == 'src':
            continue
        checksum = package['checksum'][0]['_text']
        source = package['format'][0]['{rpm}sourcerpm'][0]['_text']
        location = package['location'][0]['href']
        version = package['version'][0]
        summary = package['summary'][0]['_text']
        description = package['description'][0]['_text']
        if '_text' in package['url'][0]:
            url = package['url'][0]['_text']
        else:
            url = ''
        license = package['format'][0]['{rpm}license'][0]['_text']
        try:
            provides = package['format'][0]['{rpm}provides'][0]['{rpm}entry']
            provides = massage_primary_requires(provides, cdt)
        except:
            provides = []
        try:
            requires = package['format'][0]['{rpm}requires'][0]['{rpm}entry']
            requires = massage_primary_requires(requires, cdt)
        except:
            requires = []
        new_package = dict({'checksum': checksum,
                            'location': location,
                            'home': url,
                            'source': source,
                            'version': version,
                            'summary': yaml_quote_string(summary),
                            'description': description,
                            'license': license,
                            'provides': provides,
                            'requires': requires})
        if name in new_dict:
            if arch in new_dict[name]:
                print("WARNING: Duplicate packages exist for {} for arch {}".format(name, arch))
            new_dict[name][arch] = new_package
        else:
            new_dict[name] = dict({arch: new_package})
    return new_dict


def valid_depends(depends):
    name = depends['name']
    str_flags = depends['flags']
    if (not name.startswith('rpmlib(') and not
         name.startswith('config(') and not
         name.startswith('pkgconfig(') and not
         name.startswith('/') and
         name != 'rtld(GNU_HASH)' and
         '.so' not in name and
         '(' not in name and
         str_flags):
        return True
    return False


def remap_license(rpm_license):
    mapping = {'lgplv2+': 'LGPL (>= 2)',
               'gplv2+': 'GPL (>= 2)',
               'public domain (uncopyrighted)': 'Public-Domain',
               'public domain': 'Public-Domain',
               'mit/x11': 'MIT',
               'the open group license': 'The Open Group License'}
    l_rpm_license = rpm_license.lower()
    if l_rpm_license in mapping:
        license, family = mapping[l_rpm_license], guess_license_family(mapping[l_rpm_license])
    else:
        license, family = rpm_license, guess_license_family(rpm_license)
    # Yuck:
    if family == 'APACHE':
        family = 'Apache'
    elif family == 'PUBLIC-DOMAIN':
        family = 'Public-Domain'
    elif family == 'PROPRIETARY':
        family = 'Proprietary'
    elif family == 'OTHER':
        family = 'Other'
    return license, family


def write_conda_recipes(recursive, repo_primary, package,
                        architectures, cdt, output_dir, override_arch, src_cache):
    entry, entry_name, arch = find_repo_entry_and_arch(repo_primary, architectures,
                                                       dict({'name': package}))
    if not entry:
        return
    if override_arch:
        arch = architectures[0]
    package = entry_name
    rpm_url = dirname(dirname(cdt['base_url'])) + '/' + entry['location']
    srpm_url = cdt['sbase_url'] + entry['source']
    _, _, _, _, _, sha256str = rpm_url_split(rpm_url, src_cache)
    _, _, _, _, _, srcsha256str = rpm_url_split(srpm_url, src_cache)
    depends = [required for required in entry['requires'] if valid_depends(required)]
    for depend in depends:
        dep_entry, dep_name, dep_arch = find_repo_entry_and_arch(repo_primary,
                                                                 architectures,
                                                                 depend)
        if override_arch:
            dep_arch = architectures[0]
        depend['arch'] = dep_arch
        if recursive:
            depend['name'] = write_conda_recipes(recursive,
                                                 repo_primary,
                                                 depend['name'],
                                                 architectures,
                                                 cdt,
                                                 output_dir,
                                                 override_arch,
                                                 src_cache)

    sn = cdt['short_name'] + '-' + arch
    if len(depends):
        depends_specs = ["{}-{}-{} {}{}".format(depend['name'].lower().replace('+', 'x'),
                                                cdt['short_name'], depend['arch'],
                                                depend['flags'], depend['ver'])
                         for depend in depends]
        dependsstr_part = '\n'.join(['    - {}'.format(depends_spec)
                                     for depends_spec in depends_specs])
        dependsstr = 'requirements:\n' \
                     '  build:\n' + dependsstr_part + '\n' + \
                     '  run:\n' + dependsstr_part
    else:
        dependsstr = ''

    package_l = package.lower().replace('+', 'x')
    package_cdt_name = package_l + '-' + sn
    license, license_family = remap_license(entry['license'])
    d = dict({'version': entry['version']['ver'],
              'packagename': package_cdt_name,
              'hostmachine': cdt['host_machine'],
              'hostsubdir': cdt['host_subdir'],
              'depends': dependsstr,
              'rpmurl': rpm_url,
              'srcrpmurl': srpm_url,
              'home': entry['home'],
              'license': license,
              'license_family': license_family,
              'checksum_name': cdt['checksummer_name'],
              'checksum': entry['checksum'],
              'summary': '(CDT) ' + entry['summary'],
              'description': '|\n        ' + '\n        '.join(wrap(entry['description'], 78)),
              # Cheeky workaround.  I use ${PREFIX},
              # ${PWD}, ${RPM} and ${RECIPE_DIR} in
              # BUILDSH and they get interpreted as
              # format string tokens so bounce them
              # back.
              'PREFIX': '{PREFIX}',
              'RPM': '{RPM}',
              'PWD': '{PWD}',
              'RECIPE_DIR': '{RECIPE_DIR}'})
    odir = join(output_dir, cdt['dirname'] + '-' + architectures[0], package_cdt_name)
    try:
        makedirs(odir)
    except:
        pass
    with open(join(odir, 'meta.yaml'), 'w') as f:
        f.write(RPM_META.format(**d))
    rpm2cpio = join(odir, 'rpm2cpio')
    with open(rpm2cpio, 'w') as f:
        chmod(rpm2cpio, 0o755)
        f.write(RPM2CPIO)
    buildsh = join(odir, 'build.sh')
    with open(buildsh, 'w') as f:
        chmod(buildsh, 0o755)
        f.write(BUILDSH.format(**d))
    return package


# How do we map conda names to RPM names? The issue would be if two distros
# name their RPMs differently we probably want to hide that away from users
# Do I want to pass just the package name, the CDT and the arch and rely on
# expansion to form the URL? I have been going backwards and forwards here.
def write_conda_recipe(package_cdt, output_dir, architecture, recursive, override_arch, config):
    package, cdt_name = package_cdt
    bits = '32' if architecture in ('armv6', 'armv7a', 'i686', 'i386') else '64'
    base_architectures = dict({'i686': 'i386'})
    try:
        base_architecture = base_architectures[architecture]
    except:
        base_architecture = architecture
    architecture_bits = dict({'architecture': architecture,
                              'base_architecture': base_architecture,
                              'bits': bits})
    cdt = dict()
    for k, v in iteritems(CDTs[cdt_name]):
        if isinstance(v, string_types):
            cdt[k] = v.format(**architecture_bits)
        else:
            cdt[k] = v

    repomd_url = cdt['repomd_url']
    repo_primary = get_repo_dict(repomd_url,
                                 "primary", massage_primary,
                                 cdt,
                                 config.src_cache)
    write_conda_recipes(recursive,
                        repo_primary,
                        package,
                        [base_architecture, "noarch"],
                        cdt,
                        output_dir,
                        override_arch,
                        config.src_cache)


def skeletonize(packages, output_dir=".",
                version=None, recursive=False, architecture=None, override_arch=True, config=None):
    write_conda_recipe(packages, output_dir, architecture, recursive, override_arch, config)


def add_parser(repos):

    rpm = repos.add_parser(
        "rpm",
        help="""
    Create recipe skeleton for RPM files
        """,)

    class name_cdt(argparse._AppendAction):
        def __call__(self, parser, namespace, values, option_string=None):
            if len(values) % 2:
                raise argparse.ArgumentError(self,
                                             "%s takes groups of 2 values (rpm name, cdt), %d given"
                                             % (option_string, len(values)))
            pkgs = zip_longest(*[iter(values)] * 2, fillvalue='')
            for pkg in pkgs:
                super(name_cdt, self).__call__(parser, namespace, pkg, option_string)

    rpm.add_argument(
        "packages",
        nargs='+',
        action=name_cdt,
        help="RPM package name followed by CDT name"
    )

    rpm.add_argument(
        "--output-dir",
        help="Directory to write recipes to (default: %(default)s).",
        default=".",
    )

    rpm.add_argument(
        "--recursive",
        action='store_true',
        dest='recursive',
        help='Create recipes for dependencies if they do not already exist',
    )

    rpm.add_argument(
        "--architecture",
        help="Conda arch to make these packages for, used in URL expansions (default: %(default)s).",  # noqa
        default=None,
    )

    rpm.add_argument(
        "--version",
        help="Version to use. Applies to all packages.",
    )

    rpm.add_argument('--no-override-arch',
                     help="Do not override noarch in package names",
                     dest='override_arch',
                     default=True,
                     action='store_false')
