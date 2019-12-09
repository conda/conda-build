import re

import requests
from requests import HTTPError

from conda_build import utils
from conda_build.grayskull import Package, About, Test, Requirements
from conda_build.grayskull.base_recipe import Grayskull

log = utils.get_logger(__name__)


class PyPi(Grayskull):
    URL_PYPI_METADATA = "https://pypi.org/pypi/{pkg_name}/json"

    def __init__(self, name=None, version=None, force_setup=False):
        self._force_setup = force_setup
        self._pypi_metadata = None
        self._setup_metadata = None
        self._is_using_selectors = False
        self._is_no_arch = True
        super(PyPi, self).__init__(name=name, version=version)

    def refresh_section(self, section=""):
        if self._force_setup:
            all_fields = self._get_fields_by_distutils()
            self._set_all_fields(all_fields)
            return

        self[section] = self._get_pypi_metadata()[section]
        if len(self.build.requirements.run) == 1:
            self._force_setup = True
            self.refresh_section(section)

    def _get_pypi_metadata(self):
        if not self.package.version:
            log.info(
                f"Version for {self.package.name} not specified.\n"
                f"Getting the latest one."
            )
            url_pypi = self.URL_PYPI_METADATA.format(pkg_name=self.package.name)
        else:
            url_pypi = self.URL_PYPI_METADATA.format(
                pkg_name=self.package.name + f"/{self.package.version}"
            )
        if self._pypi_metadata \
                and self._pypi_metadata["package"] == self.package:
            return self._pypi_metadata

        metadata = requests.get(url=url_pypi)
        if metadata.status_code != 200:
            raise HTTPError(
                "It was not possible to recover PyPi metadata for"
                f" {self.package.name}."
            )
        metadata = metadata.json()
        info = metadata["info"]
        project_urls = info.get("project_urls", {})

        self._pypi_metadata = {
            "package": Package(
                name=self.package.name, version=info["version"]
            ),
            "requirements": self._extract_pypi_requirements(metadata),
            "test": Test(imports=[self.package.name.lower()]),
            "about": About(
                home=info.get("project_url"),
                summary=info.get("summary"),
                doc_url=info.get("docs_url"),
                dev_url=project_urls.get("Source"),
                license=info.get("license"),
            ),
        }
        log.info(
            f"Extracting metadata for {self.package.name}"
            f" {self.package.version}."
        )
        return self._pypi_metadata

    def _extract_pypi_requirements(self, metadata):
        info = metadata["info"]
        requires_dist = info.get("requires_dist")
        limit_python = " " + info.get("requires_python") if info.get("requires_python") else None
        run_req = []

        if not requires_dist:
            return Requirements(host={"python", "pip"}, run={"python"})

        re_pkg = re.compile(r"^\s*(\w+)\s*(\(.*\))?\s*", re.DOTALL)
        re_extra = re.compile(r"^\s*(\w+)\s+(\W*)\s+(.*)", re.DOTALL)
        for req in requires_dist:
            split_req = req.split(";")
            pkg = re_pkg.match(split_req[0])
            pkg_name = pkg.group(1).strip()
            version = ""
            selector = ""
            if len(pkg.groups()) > 1 and pkg.group(2):
                version = " " + pkg.group(2).strip()
                version = version.replace("(", "")
                version = version.replace(")", "")

            if len(split_req) > 1:
                self._is_using_selectors = True
                option, operation, value = re_extra.match(split_req[1]).groups()
                value = re.sub(r"['\"]", "", value)
                if value == "testing":
                    continue
                selector = self._get_selector(option, operation, value)
            run_req.append(f"{pkg_name}{version}{selector}")

        host_req = [f"python{limit_python}", "pip"]
        run_req.insert(0, f"python{limit_python}")
        return Requirements(host=host_req, run=run_req)

    @staticmethod
    def _get_selector(option, operation, value):
        if option == "extra":
            return ""
        if option == "python_version":
            value = value.split(".")
            value = "".join(value[:2])
            return f"  # [py{operation}{value}]"
        if option == "sys_platform":
            value = re.sub(r"[^a-zA-Z]+", "", value)
            return f"  # [{value.lower()}]"


