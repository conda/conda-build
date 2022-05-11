# normally run with "conda index" or bin/conda-index
import logging

logging.basicConfig(
    format="%(asctime)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    level=logging.INFO,
)
logging.getLogger("conda_build.index").setLevel(logging.DEBUG)
import conda_build.cli.main_index   # must import *after* logging config
conda_build.cli.main_index.main()
