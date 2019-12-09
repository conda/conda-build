from dataclasses import field, make_dataclass

from conda_build.metadata import FIELDS


def get_valid_fields(fields):
    return [(name.replace("-", "_"), 'typing.Any', field(default=None)) for name in fields]


Package = make_dataclass("Package", get_valid_fields(FIELDS["package"]))
Source = make_dataclass("Source", get_valid_fields(FIELDS["source"]))
Build = make_dataclass("Build", get_valid_fields(FIELDS["build"]))
Outputs = make_dataclass("Outputs", get_valid_fields(FIELDS["outputs"]))
Requirements = make_dataclass(
    "Requirements", get_valid_fields(FIELDS["requirements"])
)
App = make_dataclass("App", get_valid_fields(FIELDS["app"]))
Test = make_dataclass("Test", get_valid_fields(FIELDS["test"]))
About = make_dataclass("About", get_valid_fields(FIELDS["about"]))
