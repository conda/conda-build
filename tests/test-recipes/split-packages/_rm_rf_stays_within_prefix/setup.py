from setuptools import setup
from os.path import join

setup(name='lsfm',
      version="1.0",
      modules=['lsfm'],
      scripts=[join('bin', 'lsfm')],
      )
