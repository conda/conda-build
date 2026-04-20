# Copyright (C) 2014 Anaconda, Inc
# SPDX-License-Identifier: BSD-3-Clause

from rattler_build.package import Package
from rattler_build.render import RenderConfig
from rattler_build.stage0 import Stage0Recipe
from rattler_build.tool_config import PlatformConfig
from rattler_build.variant_config import VariantConfig


def test_variants():
    """
    Test variants with multiple values for one key.
    """

    recipe_yaml = """
package:
  name: test-multi-variant
  version: 1.0.0

build:
  string: np${{ numpy | replace(".", "") }}py${{ python | replace(".", "") }}h${{ hash }}_${{ build_number }}
  number: 0

requirements:
  host:
    - python ${{ python }}.*
    - numpy ${{ numpy }}.*
  run:
    - python ${{ python }}.*
    - numpy ${{ numpy }}.*

about:
  summary: Test recipe for multiple variant values
  """

    variant_yaml = """
python:
  - 3.11
  - 3.12

numpy:
  - 2.0
  """

    # load and render the recipe
    recipe = Stage0Recipe.from_yaml(recipe_yaml)
    variant_config = VariantConfig.from_yaml(variant_yaml)
    rendered = recipe.render(variant_config, RenderConfig())

    # we should have 2 variants
    assert len(rendered) == 2

    # check first output
    assert "python 3.11.*" in rendered[0].recipe.requirements.host
    assert "numpy 2.0.*" in rendered[0].recipe.requirements.host
    assert rendered[0].recipe.used_variant["python"] == "3.11"
    assert rendered[0].recipe.used_variant["numpy"] == "2.0"
    assert "np20py311" in rendered[0].recipe.build.string

    # check second output
    assert "python 3.12.*" in rendered[1].recipe.requirements.host
    assert "numpy 2.0.*" in rendered[1].recipe.requirements.host
    assert rendered[1].recipe.used_variant["python"] == "3.12"
    assert rendered[1].recipe.used_variant["numpy"] == "2.0"
    assert "np20py312" in rendered[1].recipe.build.string


def test_noarch_python():
    recipe_yaml = """
context:
  name: toml
  version: 0.10.2

package:
  name: "${{ name|lower }}"
  version: "${{ version }}"

source:
  url: https://pypi.io/packages/source/${{ name[0] }}/${{ name }}/${{ name }}-${{ version }}.tar.gz
  sha256: b3bda1d108d5dd99f4a20d24d9c348e91c4db7ab1b749200bded2f839ccbe68f

build:
  noarch: python
  script: python -m pip install . -vv

requirements:
  host:
    - python 3.12.1.*
    - pip 23.3.2.*
    - setuptools 68.*
  run:
    - python >=3.11

about:
  homepage: https://github.com/uiri/toml
  license: MIT
  license_file: LICENSE
  summary: Python lib for TOML.

extra:
  recipe-maintainers:
    - conda-forge/toml-feedstock
  foobar: 123
  tags:
    - toml
    - config
    - parser
    """

    # load, render and build the recipe
    recipe = Stage0Recipe.from_yaml(recipe_yaml)
    rendered = recipe.render(VariantConfig(), RenderConfig())
    build_result = rendered[0].run_build()

    package = Package.from_file(build_result.packages[0])

    assert "site-packages/toml-0.10.2.dist-info/INSTALLER" in package.files
    assert "site-packages/toml-0.10.2.dist-info/LICENSE" in package.files

    assert "python" in package.depends
    assert "python >=3.11" in package.depends


def test_noarch_variant():
    recipe_yaml = """
context:
  name: rattler-build-demo
  version: 1
  build_variant: ${{ 'unix' if unix else 'win' }}
  build_number: 0

outputs:
  - package:
      name: ${{ name }}
      version: ${{ version }}
    build:
      noarch: generic
      number: ${{ build_number }}
      string: ${{ build_variant }}_${{ hash }}_${{ build_number }}
    requirements:
      run:
        - ${{ "__unix" if unix }}
        - ${{ "__win >=11.0.123 foobar" if win }}

  - package:
      name: ${{ name }}-subpackage
      version: ${{ version }}
    build:
      noarch: generic
      number: ${{ build_number }}
      string: ${{ build_variant }}_${{ hash }}_${{ build_number }}
    requirements:
      run:
        - ${{ pin_subpackage('rattler-build-demo', exact=True) }}
    """

    recipe = Stage0Recipe.from_yaml(recipe_yaml)

    platform_config = PlatformConfig(target_platform="linux-64")

    render_config = RenderConfig(platform=platform_config)
    rendered = recipe.render(VariantConfig(), render_config)

    assert len(rendered) == 2

    output1 = rendered[0].recipe.to_dict()
    assert output1["requirements"]["run"] == ["__unix"]
    assert output1["build"]["string"] == "unix_5600cae_0"

    output2 = rendered[1].recipe.to_dict()
    pin = {"pin_subpackage": {"name": "rattler-build-demo", "exact": True}}
    assert output2["build"]["string"] == "unix_63d9094_0"
    assert output2["build"]["noarch"] == "generic"
    assert output2["requirements"]["run"] == [pin]

    platform_config = PlatformConfig(target_platform="win-64")

    render_config = RenderConfig(platform=platform_config)
    rendered = recipe.render(VariantConfig(), render_config)

    assert len(rendered) == 2
    output1_win = rendered[0].recipe.to_dict()
    assert output1_win["requirements"]["run"] == ["__win >=11.0.123 foobar"]
    assert output1_win["build"]["string"] == "win_19aa286_0"
    assert output1_win["build"]["noarch"] == "generic"

    pin = {"pin_subpackage": {"name": "rattler-build-demo", "exact": True}}

    output2_win = rendered[1].recipe.to_dict()
    assert output2_win["build"]["string"] == "win_95d38b2_0"
    assert output2_win["build"]["noarch"] == "generic"
    assert output2_win["requirements"]["run"] == [pin]
