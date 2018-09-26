import os

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
STYLES = os.listdir(os.path.join(TEMPLATES_DIR, "styles"))


TEMPLATES = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(['yaml']),
    trim_blocks=True,
    lstrip_blocks=True
)
