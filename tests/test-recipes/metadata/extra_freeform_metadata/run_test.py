from glob import glob
import os
import json
import yaml


def main():
    prefix = os.environ['PREFIX']
    info_file = glob(os.path.join(prefix, 'conda-meta', 'conda-build-test-extra-metadata-1.0*.json'))[0]
    with open(info_file) as fh:
        info = json.load(fh)

    source_file = os.path.join(info['link']['source'],
                               'info', 'recipe', 'meta.yaml')
    with open(source_file) as fh:
        source = yaml.safe_load(fh)

    assert 'custom' in source['extra']
    assert 'however' in source['extra']
    assert source['extra']['custom'] == 'metadata'
    assert source['extra']['however'] == {'we': 'want'}


if __name__ == '__main__':
    main()
