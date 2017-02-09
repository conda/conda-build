import json
import os
import requests
import subprocess
import sys
from getpass import getpass
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


def run_cmd(cmd):
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=sys.stdout) 
    p.wait()
    return p.returncode == 0


def get_conda_env_path(env_name):
    envs = json.loads(subprocess.check_output(('conda', 'env', 'list', '--json')).decode('utf-8'))
    print(envs)
    envs = [e for e in envs['envs'] if e.endswith(env_name)]
    print(env_name, ":", envs)
    if len(envs) == 1:
        return envs[0]
    raise ValueError("Could not find environment path.")

class Project(object):

    def __init__(self, name, path, conf=None):
        self.name = name
        self.path = path
        self.project_path = get_project_path(name, path)
        self.module_path = os.path.join(self.project_path, name.replace('-', '_'))
        self.tests_path = os.path.join(self.project_path, 'tests')
        self.conda_recipe_path = os.path.join(self.project_path, 'conda-recipe')
        self.env_path = None
        self.templates = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), 'templates/project')))
        self.author = conf.get('author') or get_user_info('name')
        self.email = conf.get('email') or get_user_info('email')
        self.repo = None

    def create_base_files(self, dryrun=None):
        if dryrun:
            pass
        (self.templates.get_template('init.py')
         .stream().dump(os.path.join(self.module_path, '__init__.py')))
        (self.templates.get_template('version.py')
         .stream().dump(os.path.join(self.module_path, '_version.py')))
        (self.templates.get_template('versioneer.py')
         .stream().dump(os.path.join(self.project_path, 'versioneer.py')))
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
        self.repo.create_tag("0.0.1", message='Initial tag by conda project!')

    def create_conda_env(self, python_ver):
        cmd = ["conda", "create", "-y", "-n", self.name, 
               "python={}".format(python_ver), "ipython"]
        print("\n\nCreating conda environment...\n")
        if not run_cmd(cmd):
            raise Exception("See above for error")
        self.env_path = get_conda_env_path(self.name)

    def develop_install(self):
        cmd = [os.path.join(self.env_path, "bin", "pip"), "install", "-e", self.project_path]
        print("\n\nInstalling develop version of project...\n")
        if not run_cmd(cmd):
            raise Exception("See above for error")

    def push_to_github(self):
        print("\n\nCreating github repo...\n")
        git_user = input("Enter github username: ")
        git_pass = getpass("Enter github password: ")
        r = requests.post("https://api.github.com/user/repos", auth=(git_user, git_pass),
                          json={'name': self.name})
        if not r.ok:
            raise requests.exceptions.HTTPError(r.text)
        repo = r.json()
        remote_type = input("Do you have ssh setup with github?[y/n]")
        remote_url = repo['ssh_url'] if remote_type == 'y' else repo['html_url']
        cmd = ["git", "-C", self.project_path, "remote", "add", "origin", remote_url]
        if not run_cmd(cmd):
            raise Exception("See above for error")
        cmd = ['git', '-C', self.project_path, 'push', '-u', 'origin', 'master']
        if not run_cmd(cmd):
            raise Exception("See above for error")
        print("\n\nGitHub Repo: {}\n\n".format(repo['html_url']))


def create_project_skeleton(project):
    os.mkdir(project.project_path)
    os.mkdir(project.module_path)
    os.mkdir(project.tests_path)
    os.mkdir(project.conda_recipe_path)
    project.create_base_files()
