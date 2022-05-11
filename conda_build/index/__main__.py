# normally run with "conda index" or bin/conda-index
import logging

logging.basicConfig(
    format="%(asctime)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    level=logging.INFO,
)
logging.getLogger()
import conda_build.cli.main_index

conda_build.cli.main_index.main()
