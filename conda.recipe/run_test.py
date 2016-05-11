import os

import pytest
import conda_build

print('conda_build.__version__: %s' % conda_build.__version__)
pytest.main([os.path.join(os.getenv("SOURCE_DIR"), 'tests')])
