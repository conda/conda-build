printf '#!/bin/bash\necho 'hello world'\n' > $PREFIX/bin/exepath1
printf '#!/bin/bash\necho 'hello again world'\n' > $PREFIX/bin/exepath2

chmod +x $PREFIX/bin/exepath1
chmod +x $PREFIX/bin/exepath2

