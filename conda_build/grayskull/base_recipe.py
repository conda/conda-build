from abc import abstractmethod, ABC
from dataclasses import asdict

import yaml

from conda_build.grayskull import (
    About,
    App,
    Build,
    Outputs,
    Package,
    Requirements,
    Source,
    Test,
)


class Grayskull(ABC):
    ALL_SECTIONS = (
        "package",
        "source",
        "build",
        "outputs",
        "requirements",
        "app",
        "test",
        "about",
    )

    def __init__(self, name=None, version=None):
        self._package = Package(name=name, version=version)
        self._source = Source()
        self._build = Build()
        self._outputs = Outputs()
        self._requirements = Requirements()
        self._app = App()
        self._test = Test()
        self._about = About()
        self.refresh_all_recipe()
        super(Grayskull, self).__init__()

    def refresh_all_recipe(self):
        for section in self.ALL_SECTIONS:
            self.refresh_section(section)

    @abstractmethod
    def refresh_section(self, section=""):
        pass

    @property
    def package(self):
        return self._package

    @package.setter
    def package(self, value):
        self._package = Package(**value)

    @property
    def source(self):
        return self._source

    @source.setter
    def source(self, value):
        self._source = Source(**value)

    @property
    def build(self):
        return self._build

    @build.setter
    def build(self, value):
        self._build = Build(**value)

    @property
    def outputs(self):
        return self._outputs

    @outputs.setter
    def outputs(self, value):
        self._outputs = Outputs(**value)

    @property
    def requirements(self):
        return self._requirements

    @requirements.setter
    def requirements(self, value):
        self._requirements = Requirements(**value)

    @property
    def app(self):
        return self._app

    @app.setter
    def app(self, value):
        self._app = App(**value)

    @property
    def test(self):
        return self._test

    @test.setter
    def test(self, value):
        self._test = Test(**value)

    @property
    def about(self):
        return self._about

    @about.setter
    def about(self, value):
        self._about = About(**value)

    def __getitem__(self, item):
        if item in self.ALL_SECTIONS:
            return getattr(self, item.lower())
        raise ValueError(f"Section {item} not found.")

    def __len__(self):
        return len(self.ALL_SECTIONS)

    def __iter__(self):
        for section in self.ALL_SECTIONS:
            yield section, self[section]

    def as_dict(self, exclude_empty_values=True):
        """Convert the recipe attributes to a dict to be able to dump it in a
        yaml file.

        :param exclude_empty_values: If True it will exclude the empty values
            in the recipe. Otherwise it will return everything
        :return dict:
        """
        if exclude_empty_values:
            return self.clean_section(
                {section: self.clean_section(value) for section, value in self}
            )
        return dict(self)

    @staticmethod
    def clean_section(section):
        """Create a new dictionary without None values.

        :param section: Receives a dict or a namedtuple
        :return dict: return a new dict without the None values
        """
        if not isinstance(section, dict):
            section = asdict(section)
        return {key: value for key, value in section.items() if value}

    def generate_yaml(self):
        return yaml.dump(self.as_dict())
