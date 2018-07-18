import os
import sys

from os.path import dirname

from django.conf import settings  # noqa


sys.path.insert(
    0, dirname(dirname(dirname(dirname(os.path.abspath(__file__)))))
)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "settings")

config = settings.DATABASES['default']
config['HOST'] = config.get('HOST', 'localhost')
config['PORT'] = config.get('PORT', '3306')

if not config['HOST'] or config['HOST'].endswith('.sock'):
    """ Oh you meant 'localhost'! """
    config['HOST'] = 'localhost'

s = 'mysql --silent {NAME} -h{HOST} -u{USER}'

if config['PASSWORD']:
    os.environ['MYSQL_PWD'] = config['PASSWORD']
    del config['PASSWORD']

if config['PORT']:
    s += ' -P{PORT}'
else:
    del config['PORT']

db = s.format(**config)
table = 'schema_version'
handlers = {
    '.py': sys.executable + ' -B manage.py runscript olympia.migrations.%s'
}
