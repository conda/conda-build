from abc import abstractmethod, ABC

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
    def __init__(self):
        self.package = Package()
        self.source = Source()
        self.build = Build()
        self.outputs = Outputs()
        self.requirements = Requirements()
        self.app = App()
        self.test = Test()
        self.about = About()
        self.populate_recipe()
        super(Grayskull, self).__init__()

    @abstractmethod
    def populate_recipe(self):
        pass

    def as_dict(self):
        """Convert the recipe attributes to a dict to be able to dump it in a
        yaml file.

        :return dict:
        """
        return self.clean_section({
            "package": self.clean_section(self.package),
            "source": self.clean_section(self.source),
            "build": self.clean_section(self.build),
            "outputs": self.clean_section(self.outputs),
            "requirements": self.clean_section(self.requirements),
            "app": self.clean_section(self.app),
            "test": self.clean_section(self.test),
            "about": self.clean_section(self.about),
        })

    def clean_section(self, section):
        """Create a new dictionary without None values.

        :param section: Receives a dict or a namedtuple
        :return dict: return a new dict without the None values
        """
        if not isinstance(section, dict):
            section = section._asdict()
        return {
            key: value for key, value in section.items() if value is not None
        }
