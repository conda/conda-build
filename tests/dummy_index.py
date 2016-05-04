import collections
import os

from conda_build.index import write_repodata
import conda.config


_DummyPackage = collections.namedtuple('_DummyPackage',
                                       ['pkg_name', 'build_deps', 'run_deps'])


class DummyPackage(_DummyPackage):
    def __new__(cls, name, build_deps=None, run_deps=None):
        return super(DummyPackage, cls).__new__(cls, name, build_deps or (),
                                                run_deps or ())

    def name(self):
        return self.pkg_name

    def dist(self):
        return '{}-{}-{}'.format(self.name(), '0.0', '0')

    def get_value(self, item, default):
        if item == 'requirements/run':
            return self.run_deps
        elif item == 'requirements/build':
            return self.build_deps
        else:
            raise AttributeError(item)

    def __repr__(self):
        # For testing purposes, this is particularly convenient.
        return self.name()


class DummyIndex(dict):
    def add_pkg(self, name, version, build_string='',
                depends=(), build_number='0',
                **extra_items):
        if build_string:
            build_string = '{}_{}'.format(build_string, build_number)
        else:
            build_string = build_number
        pkg_info = dict(name=name, version=version, build_number=build_number,
                        build=build_string, subdir=conda.config.subdir,
                        depends=tuple(depends), **extra_items)
        self['{}-{}-{}.tar.bz2'.format(name, version, build_string)] = pkg_info

    def add_pkg_meta(self, meta):
        # Add a package given its MetaData instance. This may include a DummyPackage
        # instance in the future.
        if isinstance(meta, DummyPackage):
            raise NotImplementedError('')
        self['{}.tar.bz2'.format(meta.dist())] = meta.info_index()

    def write_to_channel(self, dest):
        # Write the index to a channel. Useful to get conda to read it back in again
        # using conda.api.get_index().
        channel_subdir = os.path.join(dest, conda.config.subdir)
        if not os.path.exists(channel_subdir):
            os.mkdir(channel_subdir)
        write_repodata({'packages': self, 'info': {}}, channel_subdir)

        return channel_subdir

