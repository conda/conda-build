import pytest

from conda_build.grayskull import Package
from conda_build.grayskull.base_recipe import Grayskull


class EmptyGray(Grayskull):
    def refresh_section(self, section):
        if section == "package":
            self.package.name = "PkgName"
            self.package.version = "1.0.0"
        elif section == "source":
            self.source.sha256 = "sha256-foo"
            self.source.url = "URL"
        elif section == "build":
            self.build.number = 1


def test_base_recipe():
    assert EmptyGray().as_dict() == {
        "package": {"name": "PkgName", "version": "1.0.0"},
        "source": {"sha256": "sha256-foo", "url": "URL"},
        "build": {"number": 1},
    }


def test_clean_section():
    pkg = Package(name="pkg_name", version="1.1.1")
    assert EmptyGray.clean_section(pkg) == {
        "name": "pkg_name",
        "version": "1.1.1",
    }
    pkg = Package(name="new_pkg")
    assert EmptyGray.clean_section(pkg) == {"name": "new_pkg"}


def test_magic_methods():
    recipe = EmptyGray()
    assert recipe["package"] == Package(name="PkgName", version="1.0.0")
    assert len(recipe) == 8

    with pytest.raises(ValueError) as exec_info:
        foo = recipe["KEY_FOO"]
    assert exec_info.match("Section KEY_FOO not found.")
