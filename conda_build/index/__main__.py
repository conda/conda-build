# normally run with "conda index" or bin/conda-index
import conda_build.cli.main_index
import logging
logging.getLogger("conda_build.index").setLevel(logging.DEBUG)
conda_build.cli.main_index.main()
