import sys
import os

# This only works if you're running schematic from the zamboni root.
sys.path.insert(0, os.path.realpath('.'))

# Set up zamboni.
import manage
from django.conf import settings

config = settings.DATABASES['default']
config['HOST'] = config.get('HOST', 'localhost')
config['PORT'] = config.get('PORT', '3306')

if config['HOST'].endswith('.sock'):
    """ Oh you meant 'localhost'! """
    config['HOST'] = 'localhost'

s = 'mysql --silent {NAME} -h{HOST} -P{PORT} -u{USER}'

if config['PASSWORD']:
    s += ' -p{PASSWORD}'
else:
    del config['PASSWORD']

db = s.format(**config)
table = 'schema_version'
