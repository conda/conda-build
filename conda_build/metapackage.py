from collections import defaultdict
from conda_build.config import Config
from conda_build.metadata import MetaData


def create_metapackage(name, version, entry_points=(), build_string=None, build_number=0,
                       dependencies=(), home=None, license=None, summary=None, config=None):
    # local import to avoid circular import, we provid create_metapackage in api
    from conda_build.build import build_tree

    if not config:
        config = Config()

    d = defaultdict(dict)
    d['package']['name'] = name
    d['package']['version'] = version
    d['build']['number'] = build_number
    d['build']['entry_points'] = entry_points
    # MetaData does the auto stuff if the build string is None
    d['build']['string'] = build_string
    d['requirements']['run'] = dependencies
    d['about']['home'] = home
    d['about']['license'] = license
    d['about']['summary'] = summary
    d = dict(d)
    m = MetaData.fromdict(d, config=config)
    config.compute_build_id(m.name())

    return build_tree([(m, False, False)], config=config)
