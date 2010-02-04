import sys
import os

# This only works if you're running schematic from the zamboni root.
sys.path.insert(0, os.path.realpath('.'))

# Set up zamboni.
import manage
from django.conf import settings

config = settings.DATABASES['default']
config['HOST'] = config.get('HOST') or 'localhost'
config['PORT'] = config.get('PORT') or '3306'

s = 'mysql {NAME} -h{HOST} -P{PORT} -u{USER} -p{PASSWORD}'
db = s.format(**config)
table = 'schema_version'
