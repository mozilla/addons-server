#!/usr/bin/env python
import uuid


# Generate build id for docker image.
print('BUILD_ID = "%s"' % uuid.uuid4())
