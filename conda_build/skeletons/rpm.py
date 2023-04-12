# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause
import argparse
from copy import copy

from conda_build.license_family import guess_license_family
from conda_build.source import download_to_cache

try:
    import cPickle as pickle
except:
    import pickle as pickle

import gzip
import hashlib
import re
from os import chmod, makedirs
from os.path import basename, dirname, exists, join, splitext
from textwrap import wrap
from xml.etree import ElementTree as ET

from .cran import yaml_quote_string

try:
    from urllib.request import urlopen
except ImportError:
    from urllib2 import urlopen


# This is used in two places
default_architecture = "x86_64"
default_distro = "centos6"

RPM_META = """\
package:
  name: {packagename}
  version: {version}

source:
  - url: {rpmurl}
    {checksum_name}: {checksum}
    no_hoist: true
    folder: binary
  - url: {srcrpmurl}
    folder: source

build:
  number: 2
  noarch: generic
  missing_dso_whitelist:
    - '*'

{depends}

about:
  home: {home}
  license: {license}
  license_family: {license_family}
  summary: {summary}
  description: {description}
"""


BUILDSH = """\
#!/bin/bash

set -o errexit -o pipefail

mkdir -p "${PREFIX}"/{hostmachine}/sysroot
if [[ -d usr/lib ]]; then
  if [[ ! -d lib ]]; then
    ln -s usr/lib lib
  fi
fi
if [[ -d usr/lib64 ]]; then
  if [[ ! -d lib64 ]]; then
    ln -s usr/lib64 lib64
  fi
fi
pushd "${PREFIX}"/{hostmachine}/sysroot > /dev/null 2>&1
cp -Rf "${SRC_DIR}"/binary/* .
"""


CDTs = dict(
    {
        "centos5": {
            "dirname": "centos5",
            "short_name": "cos5",
            "base_url": "http://vault.centos.org/5.11/os/{base_architecture}/CentOS/",
            "sbase_url": "http://vault.centos.org/5.11/os/Source/",
            "repomd_url": "http://vault.centos.org/5.11/os/{base_architecture}/repodata/repomd.xml",  # noqa
            "host_machine": "{architecture}-conda_cos5-linux-gnu",
            "host_subdir": "linux-{bits}",
            "fname_architecture": "{architecture}",
            "rpm_filename_platform": "el5.{architecture}",
            "checksummer": hashlib.sha1,
            "checksummer_name": "sha1",
            "macros": {},
        },
        "centos6": {
            "dirname": "centos6",
            "short_name": "cos6",
            "base_url": "http://vault.centos.org/centos/6.10/os/{base_architecture}/CentOS/",  # noqa
            "sbase_url": "http://vault.centos.org/6.10/os/Source/SPackages/",
            "repomd_url": "http://vault.centos.org/centos/6.10/os/{base_architecture}/repodata/repomd.xml",  # noqa
            "host_machine": "{architecture}-conda_cos6-linux-gnu",
            "host_subdir": "linux-{bits}",
            "fname_architecture": "{architecture}",
            "rpm_filename_platform": "el6.{architecture}",
            "checksummer": hashlib.sha256,
            "checksummer_name": "sha256",
            # Some macros are defined in /etc/rpm/macros.* but I cannot find where
            # these ones are defined. Also, rpm --eval "%{gdk_pixbuf_base_version}"
            # gives nothing nor does rpm --showrc | grep gdk
            "macros": {"pyver": "2.6.6", "gdk_pixbuf_base_version": "2.24.1"},
        },
        "centos7": {
            "dirname": "centos7",
            "short_name": "cos7",
            "base_url": "http://vault.centos.org/altarch/7/os/{base_architecture}/CentOS/",  # noqa
            "sbase_url": "http://vault.centos.org/7.7.1908/os/Source/SPackages/",
            "repomd_url": "http://vault.centos.org/altarch/7/os/{base_architecture}/repodata/repomd.xml",  # noqa
            "host_machine": "{gnu_architecture}-conda_cos7-linux-gnu",
            "host_subdir": "linux-ppc64le",
            "fname_architecture": "{architecture}",
            "rpm_filename_platform": "el7.{architecture}",
            "checksummer": hashlib.sha256,
            "checksummer_name": "sha256",
            # Some macros are defined in /etc/rpm/macros.* but I cannot find where
            # these ones are defined. Also, rpm --eval "%{gdk_pixbuf_base_version}"
            # gives nothing nor does rpm --showrc | grep gdk
            "macros": {"pyver": "2.6.6", "gdk_pixbuf_base_version": "2.24.1"},
        },
        "clefos": {
            "dirname": "clefos",
            "short_name": "cos7",
            "base_url": "http://download.sinenomine.net/clefos/7/os/{base_architecture}/",  # noqa
            "sbase_url": "http://download.sinenomine.net/clefos/7/source/srpms/",  # noqa
            "repomd_url": "http://download.sinenomine.net/clefos/7/os/repodata/repomd.xml",  # noqa
            "host_machine": "{gnu_architecture}-conda-cos7-linux-gnu",
            "host_subdir": "linux-s390x",
            "fname_architecture": "{architecture}",
            "rpm_filename_platform": "el7.{architecture}",
            "checksummer": hashlib.sha256,
            "checksummer_name": "sha256",
            "macros": {"pyver": "2.7.5", "gdk_pixbuf_base_version": "2.36.2"},
        },
        "suse_leap_rpi3": {
            "dirname": "suse_leap_rpi3",
            "short_name": "slrpi3",
            # I cannot locate the src.rpms for OpenSUSE leap. The existence
            # of this key tells this code to ignore missing src rpms but we
            # should *never* release binaries we do not have the sources for.
            "allow_missing_sources": True,
            "repomd_url": "http://download.opensuse.org/ports/aarch64/distribution/leap/42.3-Current/repo/oss/suse/repodata/repomd.xml",  # noqa
            "base_url": "http://download.opensuse.org/ports/{architecture}/distribution/leap/42.3-Current/repo/oss/suse/{architecture}/",  # noqa
            "sbase_url": "http://download.opensuse.org/ports/{architecture}/source/factory/repo/oss/suse/src/",  # noqa
            # I even tried an older release but it was just as bad:
            # 'repomd_url': 'http://download.opensuse.org/ports/aarch64/distribution/leap/42.2/repo/oss/suse/repodata/repomd.xml', # noqa
            # 'base_url': 'http://download.opensuse.org/ports/{architecture}/distribution/leap/42.2/repo/oss/suse/{architecture}/',  # noqa
            # 'sbase_url': 'http://download.opensuse.org/source/distribution/leap/42.2/repo/oss/suse/src/',  # noqa
            "host_machine": "aarch64-conda_rpi3-linux-gnueabi",
            "host_subdir": "linux-aarch64",
            "fname_architecture": "{architecture}",
            "rpm_filename_platform": "{architecture}",
            "checksummer": hashlib.sha256,
            "checksummer_name": "sha256",
            "macros": {},
        },
        "raspbian_rpi2": {
            "dirname": "raspbian_rpi2",
            "cdt_short_name": "rrpi2",
            "host_machine": "armv7a-conda_rpi2-linux-gnueabi",
            "host_subdir": "armv7a-32",
            "fname_architecture": "{architecture}",
            "checksummer": hashlib.sha256,
            "checksummer_name": "sha256",
            "macros": {},
        },
    }
)


def package_exists(package_name):
    """This is a simple function returning True/False for if a requested package string exists
    in the add-on repository."""
    return True


def cache_file(src_cache, url, fn=None, checksummer=hashlib.sha256):
    if fn:
        source = dict({"url": url, "fn": fn})
    else:
        source = dict({"url": url})
    cached_path, _ = download_to_cache(src_cache, "", source)
    csum = checksummer()
    csum.update(open(cached_path, "rb").read())
    csumstr = csum.hexdigest()
    return cached_path, csumstr


def rpm_filename_split(rpmfilename):
    base, _ = splitext(rpmfilename)
    release_platform = base.split("-")[-1]
    parts = release_platform.split(".")
    if len(parts) == 2:
        release, platform = parts[0], parts[1]
    elif len(parts) > 2:
        release, platform = ".".join(parts[0 : len(parts) - 1]), ".".join(parts[-1:])
    else:
        print(f"ERROR: Cannot figure out the release and platform for {base}")
    name_version = base.split("-")[0:-1]
    version = name_version[-1]
    rpm_name = "-".join(name_version[0 : len(name_version) - 1])
    return rpm_name, version, release, platform


def rpm_split_url_and_cache(rpm_url, src_cache):
    cached_path, sha256str = cache_file(src_cache, rpm_url)
    rpm_name, version, release, platform = rpm_filename_split(basename(rpm_url))
    return rpm_name, version, release, platform, cached_path, sha256str


def rpm_filename_generate(rpm_name, version, release, platform):
    return f"{rpm_name}-{version}-{release}.{platform}.rpm"


def rpm_url_generate(url_dirname, rpm_name, version, release, platform, src_cache):
    """
    Forms the URL and also attempts to cache it to verify it exists.
    """
    result = rpm_filename_generate(rpm_name, version, release, platform)
    url = join(url_dirname, result)
    path, _ = download_to_cache(src_cache, "", dict({"url": url}))
    assert path, f"Failed to cache generated RPM url {result}"
    return url


def find_repo_entry_and_arch(repo_primary, architectures, depend):
    dep_name = depend["name"]
    found_package_name = ""
    try:
        # Try direct lookup first.
        found_package = repo_primary[dep_name]
        found_package_name = dep_name
    except:
        # Look through the provides of all packages.
        for name, package in repo_primary.items():
            for arch in architectures:
                if arch in package:
                    if "provides" in package[arch]:
                        for provide in package[arch]["provides"]:
                            if provide["name"] == dep_name:
                                print(f"Found it in {name}")
                                found_package = package
                                found_package_name = name
                                break

    if found_package_name == "":
        print(
            f"WARNING: Did not find package called (or another one providing) {dep_name}"
        )  # noqa
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


str_flags_to_conda_version_spec = dict(
    {
        "LT": "<",
        "LE": "<=",
        "EQ": "==",
        "GE": ">=",
        "GT": ">",
    }
)


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


def dictify_pickled(xml_file, src_cache, dict_massager=None, cdt=None):
    pickled = xml_file + ".p"
    if exists(pickled):
        return pickle.load(open(pickled, "rb"))
    with open(xml_file, encoding="utf-8") as xf:
        xmlstring = xf.read()
        # Remove the global namespace.
        xmlstring = re.sub(r'\sxmlns="[^"]+"', r"", xmlstring, count=1)
        # Replace sub-namespaces with their names.
        xmlstring = re.sub(r'\sxmlns:([a-zA-Z]*)="[^"]+"', r' xmlns:\1="\1"', xmlstring)
        root = ET.fromstring(xmlstring.encode("utf-8"))
        result = dictify(root)
        if dict_massager:
            result = dict_massager(result, src_cache, cdt)
        pickle.dump(result, open(pickled, "wb"))
        return result


def get_repo_dict(repomd_url, data_type, dict_massager, cdt, src_cache):
    xmlstring = urlopen(repomd_url).read()
    # Remove the default namespace definition (xmlns="http://some/namespace")
    xmlstring = re.sub(rb'\sxmlns="[^"]+"', b"", xmlstring, count=1)
    repomd = ET.fromstring(xmlstring)
    for child in repomd.findall(f"*[@type='{data_type}']"):
        open_csum = child.findall("open-checksum")[0].text
        xml_file = join(src_cache, open_csum)
        try:
            xml_file, xml_csum = cache_file(
                src_cache, xml_file, None, cdt["checksummer"]
            )
        except:
            csum = child.findall("checksum")[0].text
            location = child.findall("location")[0].attrib["href"]
            xmlgz_file = dirname(dirname(repomd_url)) + "/" + location
            cached_path, cached_csum = cache_file(
                src_cache, xmlgz_file, None, cdt["checksummer"]
            )
            assert (
                csum == cached_csum
            ), "Checksum for {} does not match value in {}".format(
                xmlgz_file, repomd_url
            )
            with gzip.open(cached_path, "rb") as gz:
                xml_content = gz.read()
                xml_csum = cdt["checksummer"]()
                xml_csum.update(xml_content)
                xml_csum = xml_csum.hexdigest()
                if xml_csum == open_csum:
                    with open(xml_file, "wb") as xml:
                        xml.write(xml_content)
                else:
                    print(
                        f"ERROR: Checksum of uncompressed file {xmlgz_file} does not match"
                    )  # noqa
        return dictify_pickled(xml_file, src_cache, dict_massager, cdt)
    return dict({})


def massage_primary_requires(requires, cdt):
    for require in requires:
        require["name"] = require["name"]
        if "flags" in require:
            require["flags"] = str_flags_to_conda_version_spec[require["flags"]]
        else:
            require["flags"] = None
        if "ver" in require:
            if "%" in require["ver"]:
                require["ver"] = require["ver"].replace("%", "")
                if not require["ver"].startswith("{"):
                    require["ver"] = "{" + require["ver"]
                if not require["ver"].endswith("}"):
                    require["ver"] = require["ver"] + "}"
                require["ver"] = require["ver"].format(**cdt["macros"])
    return requires


def massage_primary(repo_primary, src_cache, cdt):
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
    for package in repo_primary["metadata"]["package"]:
        name = package["name"][0]["_text"]
        arch = package["arch"][0]["_text"]
        if arch == "src":
            continue
        checksum = package["checksum"][0]["_text"]
        source = package["format"][0]["{rpm}sourcerpm"][0]["_text"]
        # If you need to check if the sources exist (perhaps you've got the source URL wrong
        # or the distro has forgotten to copy them?):
        # import requests
        # sbase_url = cdt['sbase_url']
        # surl = sbase_url + source
        # print("{} {}".format(requests.head(surl).status_code, surl))
        location = package["location"][0]["href"]
        version = package["version"][0]
        summary = package["summary"][0]["_text"]
        try:
            description = package["description"][0]["_text"]
        except:
            description = "NA"
        if "_text" in package["url"][0]:
            url = package["url"][0]["_text"]
        else:
            url = ""
        license = package["format"][0]["{rpm}license"][0]["_text"]
        try:
            provides = package["format"][0]["{rpm}provides"][0]["{rpm}entry"]
            provides = massage_primary_requires(provides, cdt)
        except:
            provides = []
        try:
            requires = package["format"][0]["{rpm}requires"][0]["{rpm}entry"]
            requires = massage_primary_requires(requires, cdt)
        except:
            requires = []
        new_package = dict(
            {
                "checksum": checksum,
                "location": location,
                "home": url,
                "source": source,
                "version": version,
                "summary": yaml_quote_string(summary),
                "description": description,
                "license": license,
                "provides": provides,
                "requires": requires,
            }
        )
        if name in new_dict:
            if arch in new_dict[name]:
                print(f"WARNING: Duplicate packages exist for {name} for arch {arch}")
            new_dict[name][arch] = new_package
        else:
            new_dict[name] = dict({arch: new_package})
    return new_dict


def valid_depends(depends):
    name = depends["name"]
    str_flags = depends["flags"]
    if (
        not name.startswith("rpmlib(")
        and not name.startswith("config(")
        and not name.startswith("pkgconfig(")
        and not name.startswith("/")
        and name != "rtld(GNU_HASH)"
        and ".so" not in name
        and "(" not in name
        and str_flags
    ):
        return True
    return False


def remap_license(rpm_license):
    mapping = {
        "lgplv2+": "LGPL (>= 2)",
        "gplv2+": "GPL (>= 2)",
        "public domain (uncopyrighted)": "Public-Domain",
        "public domain": "Public-Domain",
        "mit/x11": "MIT",
        "the open group license": "The Open Group License",
    }
    l_rpm_license = rpm_license.lower()
    if l_rpm_license in mapping:
        license, family = mapping[l_rpm_license], guess_license_family(
            mapping[l_rpm_license]
        )
    else:
        license, family = rpm_license, guess_license_family(rpm_license)
    # Yuck:
    if family == "APACHE":
        family = "Apache"
    elif family == "PUBLIC-DOMAIN":
        family = "Public-Domain"
    elif family == "PROPRIETARY":
        family = "Proprietary"
    elif family == "OTHER":
        family = "Other"
    return license, family


def tidy_text(text, wrap_at=0):
    stripped = text.strip("'\"\n ")
    if wrap_at > 0:
        stripped = wrap(stripped, wrap_at)
    return stripped


def write_conda_recipes(
    recursive,
    repo_primary,
    package,
    architectures,
    cdt,
    output_dir,
    override_arch,
    src_cache,
):
    entry, entry_name, arch = find_repo_entry_and_arch(
        repo_primary, architectures, dict({"name": package})
    )
    if not entry:
        return
    if override_arch:
        arch = architectures[0]
    else:
        arch = cdt["fname_architecture"]
    package = entry_name
    rpm_url = dirname(dirname(cdt["base_url"])) + "/" + entry["location"]
    srpm_url = cdt["sbase_url"] + entry["source"]
    _, _, _, _, _, sha256str = rpm_split_url_and_cache(rpm_url, src_cache)
    try:
        # We ignore the hash of source RPMs since they
        # are not given in the source repository data.
        _, _, _, _, _, _ = rpm_split_url_and_cache(srpm_url, src_cache)
    except:
        # Just pretend the binaries are sources.
        if "allow_missing_sources" in cdt:
            srpm_url = rpm_url
        else:
            raise
    depends = [required for required in entry["requires"] if valid_depends(required)]

    if package in cdt["dependency_add"]:
        for missing_dep in cdt["dependency_add"][package]:
            e_missing, e_name_missing, _ = find_repo_entry_and_arch(
                repo_primary, architectures, dict({"name": missing_dep})
            )
            if e_missing:
                for provides in e_missing["provides"]:
                    if provides["name"] == e_name_missing:
                        copy_provides = copy(provides)
                        if "rel" in copy_provides:
                            del copy_provides["rel"]
                        depends.append(copy_provides)
            else:
                print(
                    "WARNING: Additional dependency of {}, {} not found".format(
                        package, missing_dep
                    )
                )
    for depend in depends:
        dep_entry, dep_name, dep_arch = find_repo_entry_and_arch(
            repo_primary, architectures, depend
        )
        if override_arch:
            dep_arch = architectures[0]
        depend["arch"] = dep_arch
        # Because something else may provide a substitute for the wanted package
        # we need to also overwrite the versions with those of the provider, e.g.
        # libjpeg 6b is provided by libjpeg-turbo 1.2.1
        if depend["name"] != dep_name and "version" in dep_entry:
            if "ver" in dep_entry["version"]:
                depend["ver"] = dep_entry["version"]["ver"]
            if "epoch" in dep_entry["version"]:
                depend["epoch"] = dep_entry["version"]["epoch"]
        if recursive:
            depend["name"] = write_conda_recipes(
                recursive,
                repo_primary,
                depend["name"],
                architectures,
                cdt,
                output_dir,
                override_arch,
                src_cache,
            )

    sn = cdt["short_name"] + "-" + arch
    dependsstr = ""
    if len(depends):
        depends_specs = [
            "{}-{}-{} {}{}".format(
                depend["name"].lower().replace("+", "x"),
                cdt["short_name"],
                depend["arch"],
                depend["flags"],
                depend["ver"],
            )
            for depend in depends
        ]
        dependsstr_part = "\n".join(
            [f"    - {depends_spec}" for depends_spec in depends_specs]
        )
        dependsstr_build = "  build:\n" + dependsstr_part + "\n"
        dependsstr_host = "  host:\n" + dependsstr_part + "\n"
        dependsstr_run = "  run:\n" + dependsstr_part
        dependsstr = (
            "requirements:\n" + dependsstr_build + dependsstr_host + dependsstr_run
        )

    package_l = package.lower().replace("+", "x")
    package_cdt_name = package_l + "-" + sn
    license, license_family = remap_license(entry["license"])
    d = dict(
        {
            "version": entry["version"]["ver"],
            "packagename": package_cdt_name,
            "hostmachine": cdt["host_machine"],
            "hostsubdir": cdt["host_subdir"],
            "depends": dependsstr,
            "rpmurl": rpm_url,
            "srcrpmurl": srpm_url,
            "home": entry["home"],
            "license": license,
            "license_family": license_family,
            "checksum_name": cdt["checksummer_name"],
            "checksum": entry["checksum"],
            "summary": '"(CDT) ' + tidy_text(entry["summary"]) + '"',
            "description": "|\n        "
            + "\n        ".join(tidy_text(entry["description"], 78)),  # noqa
            # Cheeky workaround.  I use ${PREFIX},
            # ${PWD}, ${RPM} and ${RECIPE_DIR} in
            # BUILDSH and they get interpreted as
            # format string tokens so bounce them
            # back.
            "PREFIX": "{PREFIX}",
            "RPM": "{RPM}",
            "PWD": "{PWD}",
            "RECIPE_DIR": "{RECIPE_DIR}",
            "SRC_DIR": "{SRC_DIR}",
        }
    )
    odir = join(output_dir, package_cdt_name)
    try:
        makedirs(odir)
    except:
        pass
    with open(join(odir, "meta.yaml"), "wb") as f:
        f.write(RPM_META.format(**d).encode("utf-8"))
    buildsh = join(odir, "build.sh")
    with open(buildsh, "wb") as f:
        chmod(buildsh, 0o755)
        f.write(BUILDSH.format(**d).encode("utf-8"))
    return package


# How do we map conda names to RPM names? The issue would be if two distros
# name their RPMs differently we probably want to hide that away from users
# Do I want to pass just the package name, the CDT and the arch and rely on
# expansion to form the URL? I have been going backwards and forwards here.
def write_conda_recipe(
    packages,
    distro,
    output_dir,
    architecture,
    recursive,
    override_arch,
    dependency_add,
    config,
):
    cdt_name = distro
    bits = "32" if architecture in ("armv6", "armv7a", "i686", "i386") else "64"
    base_architectures = dict({"i686": "i386"})
    # gnu_architectures are those recognized by the canonical config.sub / config.guess
    # and crosstool-ng. They are returned from ${CC} -dumpmachine and are a part of the
    # sysroot.
    gnu_architectures = dict({"ppc64le": "powerpc64le"})
    try:
        base_architecture = base_architectures[architecture]
    except:
        base_architecture = architecture
    try:
        gnu_architecture = gnu_architectures[architecture]
    except:
        gnu_architecture = architecture
    architecture_bits = dict(
        {
            "architecture": architecture,
            "base_architecture": base_architecture,
            "gnu_architecture": gnu_architecture,
            "bits": bits,
        }
    )
    cdt = dict()
    for k, v in CDTs[cdt_name].items():
        if isinstance(v, str):
            cdt[k] = v.format(**architecture_bits)
        else:
            cdt[k] = v

    # Add undeclared dependencies. These can be baked into the global
    # CDTs dict, passed in on the commandline or a mixture of both.
    if "dependency_add" not in cdt:
        cdt["dependency_add"] = dict()
    if dependency_add:
        for package_and_missed_deps in dependency_add:
            as_list = package_and_missed_deps[0].split(",")
            if as_list[0] in cdt["dependency_add"]:
                cdt["dependency_add"][as_list[0]].extend(as_list[1:])
            else:
                cdt["dependency_add"][as_list[0]] = as_list[1:]

    repomd_url = cdt["repomd_url"]
    repo_primary = get_repo_dict(
        repomd_url, "primary", massage_primary, cdt, config.src_cache
    )
    for package in packages:
        write_conda_recipes(
            recursive,
            repo_primary,
            package,
            [architecture, "noarch"],
            cdt,
            output_dir,
            override_arch,
            config.src_cache,
        )


def skeletonize(
    packages,
    output_dir=".",
    version=None,
    recursive=False,
    architecture=default_architecture,
    override_arch=True,
    dependency_add=[],
    config=None,
    distro=default_distro,
):
    write_conda_recipe(
        packages,
        distro,
        output_dir,
        architecture,
        recursive,
        override_arch,
        dependency_add,
        config,
    )


def add_parser(repos):
    rpm = repos.add_parser(
        "rpm",
        help="""
    Create recipe skeleton for RPM files
        """,
    )

    rpm.add_argument("packages", nargs="+", help="RPM package name(s)")

    rpm.add_argument(
        "--output-dir",
        help="Directory to write recipes to (default: %(default)s).",
        default=".",
    )

    rpm.add_argument(
        "--recursive",
        action="store_true",
        dest="recursive",
        help="Create recipes for dependencies if they do not already exist",
    )

    rpm.add_argument(
        "--dependency-add",
        nargs="+",
        action="append",
        help="Add undeclared dependencies (format: package,missing_dep1,missing_dep2)",
    )

    rpm.add_argument(
        "--architecture",
        help="Conda arch to make these packages for, used in URL expansions (default: %(default)s).",  # noqa
        default=default_architecture,
    )

    rpm.add_argument(
        "--version",
        help="Version to use. Applies to all packages.",
    )

    def valid_distros():
        return ", ".join([name for name, _ in CDTs.items()])

    def distro(distro_name):
        if distro_name not in CDTs:
            raise argparse.ArgumentTypeError(
                f"valid --distro values are {valid_distros()}"
            )
        return distro_name

    rpm.add_argument(
        "--distro",
        type=distro,
        default=default_distro,
        help="Distro to use. Applies to all packages, valid values are: {}".format(
            valid_distros()
        ),
    )

    rpm.add_argument(
        "--no-override-arch",
        help="Do not override noarch in package names",
        dest="override_arch",
        default=True,
        action="store_false",
    )
