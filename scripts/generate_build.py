#!/usr/bin/env python
import uuid

# Generate build id for Dockerfile.deploy
print('BUILD_ID = "%s"' % uuid.uuid4())
