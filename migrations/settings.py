"""
This settings.py gets imported instead of zamboni's settings.py.  But then we
need to access config in that settings.py.  What are we going to do?  Put the
zamboni root at the beginning of sys.path, and delete this settings.py from
sys.modules.  Python forgets that it ever imported us and starts finding
zamboni's settings instead.
"""
import sys
import os

# This only works if you're running schematic from the zamboni root.
sys.path.insert(0, os.path.realpath('.'))
del sys.modules['settings']

# Set up zamboni.
import manage
from django.conf import settings

config = settings.DATABASES['default']
config['HOST'] = config.get('HOST') or 'localhost'
config['PORT'] = config.get('PORT') or '3306'

s = 'mysql {NAME} -h{HOST} -P{PORT} -u{USER} -p{PASSWORD}'
db = s.format(**config)
table = 'schema_version'
