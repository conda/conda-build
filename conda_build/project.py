import os
import subprocess
from git import Repo
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
        self.tests_path = os.path.join(self.project_path, 'tests')
        self.conda_recipe_path = os.path.join(self.project_path, 'conda-recipe')
        self.templates = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates/project')))
        self.author = conf.get('author') or get_user_info('name')
        self.email = conf.get('email') or get_user_info('email')
        self.repo = None

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
        (self.templates.get_template('build.sh').stream()
         .dump(os.path.join(self.conda_recipe_path, 'build.sh')))
        (self.templates.get_template('bld.bat').stream()
         .dump(os.path.join(self.conda_recipe_path, 'bld.bat')))
        (self.templates.get_template('setup.cfg')
         .stream(name=self.name)
         .dump(os.path.join(self.project_path, 'setup.cfg')))
        (self.templates.get_template('coveragerc')
         .stream(name=self.name)
         .dump(os.path.join(self.project_path, '.coveragerc')))
        (self.templates.get_template('gitignore')
         .stream(name=self.name)
         .dump(os.path.join(self.project_path, '.gitignore')))
        (self.templates.get_template('travis.yml')
         .stream(name=self.name, email=self.email)
         .dump(os.path.join(self.project_path, '.travis.yml')))
        (self.templates.get_template('README.md')
         .stream(name=self.name)
         .dump(os.path.join(self.project_path, 'README.md')))

    def init_git(self):
        self.repo = Repo.init(self.project_path)

    def initial_commit(self):
        if not self.repo:
            self.init_git()
        self.repo.git.add(A=True)
        self.repo.index.commit("Initial commit by conda project!")

def create_project_skeleton(project):
    os.mkdir(project.project_path)
    os.mkdir(project.module_path)
    os.mkdir(project.tests_path)
    os.mkdir(project.conda_recipe_path)
    project.create_base_files()
