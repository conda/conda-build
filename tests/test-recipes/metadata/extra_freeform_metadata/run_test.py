from glob import glob
import os
import json
import yaml


def main():
    prefix = os.environ['PREFIX']
    info_file = glob(os.path.join(prefix, 'conda-meta', 'conda-build-test-extra-metadata-1.0*.json'))[0]
    with open(info_file, 'r') as fh:
        info = json.load(fh)

    source_file = os.path.join(info['link']['source'],
                               'info', 'recipe', 'meta.yaml')
    with open(source_file, 'r') as fh:
        source = yaml.load(fh)

    assert source['extra'] == {"custom": "metadata",
                               "however": {"we": "want"}}


if __name__ == '__main__':
    main()
