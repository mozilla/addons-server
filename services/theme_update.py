import json
import re
from time import time
from wsgiref.handlers import format_date_time

from services.utils import (
    get_cdn_url, log_configure, log_exception, mypool, settings)

# This has to be imported after the settings (utils).
from django_statsd.clients import statsd

# Configure the log.
log_configure()


class ThemeUpdate(object):

    def __init__(self, locale, id_, qs=None):
        self.from_gp = qs == 'src=gp'
        self.addon_id = id_
        self.cursor = mypool.connect().cursor()

    def get_headers(self, length):
        return [('Cache-Control', 'public, max-age=86400'),
                ('Content-Length', str(length)),
                ('Content-Type', 'application/json'),
                ('Expires', format_date_time(time() + 86400)),
                ('Last-Modified', format_date_time(time()))]


class MigratedUpdate(ThemeUpdate):

    def get_data(self):
        if hasattr(self, 'data'):
            return self.data

        primary_key = (
            'getpersonas_id' if self.from_gp else 'lightweight_theme_id')

        """sql from:
            MigratedLWT.objects.filter(lightweight_theme_id=xxx).values_list(
                'static_theme_id',
                'static_theme___current_version__files__filename',
                'static_theme___current_version__files__hash').query"""

        sql = """
        SELECT `migrated_personas`.`static_theme_id`,
               `files`.`filename`,
               `files`.`hash`
        FROM `migrated_personas`
        INNER JOIN `addons` T3 ON (
            `migrated_personas`.`static_theme_id` = T3.`id` )
        LEFT OUTER JOIN `versions` ON (
            T3.`current_version` = `versions`.`id` )
        LEFT OUTER JOIN `files` ON (
            `versions`.`id` = `files`.`version_id` )
        WHERE `migrated_personas`.{primary_key}=%(id)s
        """.format(primary_key=primary_key)
        self.cursor.execute(sql, {'id': self.addon_id})
        row = self.cursor.fetchone()
        self.data = (
            dict(zip(('stheme_id', 'filename', 'hash'), row)) if row else {})
        return self.data

    @property
    def is_migrated(self):
        return bool(self.get_data())

    def get_json(self):
        if self.get_data():
            response = {
                'converted_theme': {
                    'url': get_cdn_url(self.data['stheme_id'], self.data),
                    'hash': self.data['hash']
                }
            }
            return json.dumps(response)


url_re = re.compile(r'(?P<locale>.+)?/themes/update-check/(?P<id>\d+)$')


def application(environ, start_response):
    """
    Developing locally?

        gunicorn -b 0.0.0.0:7000 -w 12 -k sync -t 90 --max-requests 5000 \
            -n gunicorn-theme_update services.wsgi.theme_update:application

    """

    with statsd.timer('services.theme_update'):
        try:
            locale, id_ = url_re.match(environ['PATH_INFO']).groups()
            locale = (locale or 'en-US').lstrip('/')
            id_ = int(id_)
        except AttributeError:  # URL path incorrect.
            start_response('404 Not Found', [])
            return ['']

        try:
            query_string = environ.get('QUERY_STRING')
            update = MigratedUpdate(locale, id_, query_string)
            is_migrated = update.is_migrated
            if is_migrated:
                output = (
                    update.get_json() if settings.MIGRATED_LWT_UPDATES_ENABLED
                    else None)
            else:
                output = None

            if not output:
                start_response('404 Not Found', [])
                return ['']
            start_response('200 OK', update.get_headers(len(output)))
        except Exception:
            log_exception(environ['PATH_INFO'])
            raise

    return [output.encode('utf-8')]
