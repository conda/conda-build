from collections import namedtuple

from conda_build.metadata import FIELDS

Package = namedtuple(
    "Package", FIELDS["package"], defaults=(None,) * len(FIELDS["package"])
)
Source = namedtuple(
    "Source", FIELDS["source"], defaults=(None,) * len(FIELDS["source"])
)
Build = namedtuple(
    "Build", FIELDS["build"], defaults=(None,) * len(FIELDS["build"])
)
Outputs = namedtuple(
    "Outputs", FIELDS["outputs"], defaults=(None,) * len(FIELDS["outputs"])
)
Requirements = namedtuple(
    "Requirements",
    FIELDS["requirements"],
    defaults=(None,) * len(FIELDS["requirements"]),
)
App = namedtuple("App", FIELDS["app"], defaults=(None,) * len(FIELDS["app"]))
Test = namedtuple(
    "Test", FIELDS["test"], defaults=(None,) * len(FIELDS["test"])
)
About = namedtuple(
    "About", FIELDS["about"], defaults=(None,) * len(FIELDS["about"])
)
