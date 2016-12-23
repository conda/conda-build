import os
import subprocess
from jinja2 import Environment, FileSystemLoader


def get_project_path(name, path):
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.exists(path):
        raise ValueError("Path does not exist: {}".format(path))

    project_path = os.path.join(path, name)
    if os.path.exists(project_path):
        raise ValueError("Directory already exists: {}. Provide a directory that does not exist.".format(project_path))

    return project_path


def get_user_info(field):
    r = subprocess.Popen(['git', 'config', '--get', 'user.{}'.format(field)], stdout=subprocess.PIPE).communicate()[0]
    if r:
        return r.decode('utf-8').strip()
    else:
        r = input("Enter {}: ".format(field)) or ""
        return r.strip()


class Project(object):

    def __init__(self, name, path, conf=None):
        self.name = name
        self.path = path
        self.project_path = get_project_path(name, path)
        self.module_path = os.path.join(self.project_path, name.replace('-', '_'))
        self.conda_recipe_path = os.path.join(self.project_path, 'conda-recipe')
        self.templates = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates/project')))
        self.author = conf.get('author') or get_user_info('name')
        self.email = conf.get('email') or get_user_info('email')

    def create_base_files(self, dryrun=None):
        if dryrun:
            pass
        (self.templates.get_template('init.py')
         .stream().dump(os.path.join(self.module_path, '__init__.py')))
        (self.templates.get_template('setup.py')
         .stream(name=self.name, author=self.author, email=self.email)
         .dump(os.path.join(self.project_path, 'setup.py')))
        (self.templates.get_template('meta.yaml')
         .stream(name=self.name)
         .dump(os.path.join(self.conda_recipe_path, 'meta.yaml')))


def create_project_skeleton(project):
    os.mkdir(project.project_path)
    os.mkdir(project.module_path)
    os.mkdir(project.conda_recipe_path)
    project.create_base_files()
