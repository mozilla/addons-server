import json
import logging.config
import os

from django.utils.encoding import force_bytes
from email.utils import formatdate
import MySQLdb as mysql
from urllib.parse import parse_qsl
import sqlalchemy.pool as pool
from time import time

from services.settings import settings

# This has to be imported after the settings so statsd knows where to log to.
from django_statsd.clients import statsd

from olympia.constants import applications, base
from olympia.versions.compare import version_int
import olympia.core.logger


def get_connection():
    db = settings.SERVICES_DATABASE
    return mysql.connect(
        host=db['HOST'],
        user=db['USER'],
        passwd=db['PASSWORD'],
        db=db['NAME'],
        charset=db['OPTIONS']['charset'],
    )


pool = pool.QueuePool(get_connection, max_overflow=10, pool_size=5, recycle=300)


class Update:
    def __init__(self, data, compat_mode='strict'):
        self.connection, self.cursor = None, None
        self.data = data.copy()
        self.data['row'] = {}
        self.version_int = 0
        self.compat_mode = compat_mode
        self.app = applications.APP_GUIDS.get(data.get('appID'))

    def is_valid(self):
        # If you accessing this from unit tests, then before calling
        # is valid, you can assign your own cursor.
        if not self.cursor:
            self.connection = pool.connect()
            self.cursor = self.connection.cursor()

        data = self.data
        # Version can be blank.
        data['version'] = data.get('version', '')
        for field in ['reqVersion', 'id', 'appID', 'appVersion']:
            if field not in data:
                return False

        if not self.app:
            return False

        data['app_id'] = self.app.id

        sql = """SELECT `id`, `status`, `guid` FROM `addons`
                 WHERE `guid` = %(guid)s AND
                       `inactive` = 0 AND
                       `status` NOT IN (%(STATUS_DELETED)s, %(STATUS_DISABLED)s)
                 LIMIT 1;"""
        self.cursor.execute(
            sql,
            {
                'guid': self.data['id'],
                'STATUS_DELETED': base.STATUS_DELETED,
                'STATUS_DISABLED': base.STATUS_DISABLED,
            },
        )
        result = self.cursor.fetchone()
        if result is None:
            return False

        data['id'], data['addon_status'], data['guid'] = result
        data['version_int'] = version_int(data['appVersion'])
        return True

    def get_update(self):
        data = self.data

        data['STATUS_APPROVED'] = base.STATUS_APPROVED
        data['RELEASE_CHANNEL_LISTED'] = base.RELEASE_CHANNEL_LISTED

        sql = [
            """
            SELECT
                `addons`.`guid` AS `guid`,
                `addons`.`slug` AS `slug`,
                `appmin`.`version` AS `min`,
                `appmax`.`version` AS `max`,
                `files`.`hash`,
                `files`.`filename`,
                `files`.`id` AS `file_id`,
                `files`.`strict_compatibility` AS `strict_compat`,
                `versions`.`releasenotes`,
                `versions`.`version` AS `version`
            FROM `versions`
            INNER JOIN `addons`
                ON `addons`.`id` = `versions`.`addon_id`
                AND `addons`.`id` = %(id)s
            INNER JOIN `applications_versions`
                ON `applications_versions`.`version_id` = `versions`.`id`
            INNER JOIN `appversions` `appmin`
                ON `appmin`.`id` = `applications_versions`.`min`
                AND `appmin`.`application_id` = %(app_id)s
            INNER JOIN `appversions` `appmax`
                ON `appmax`.`id` = `applications_versions`.`max`
                AND `appmax`.`application_id` = %(app_id)s
            INNER JOIN `files`
                ON `files`.`version_id` = `versions`.`id`
            WHERE
                `versions`.`deleted` = 0
                AND `versions`.`channel` = %(RELEASE_CHANNEL_LISTED)s
                AND `files`.`status` = %(STATUS_APPROVED)s
                AND `appmin`.`version_int` <= %(version_int)s
        """
        ]

        if self.compat_mode == 'ignore':
            pass  # no further SQL modification required.

        elif self.compat_mode == 'normal':
            # When file has strict_compatibility enabled, default to compatible
            # is disabled.
            sql.append(
                """AND
                CASE WHEN `files`.`strict_compatibility` = 1
                THEN `appmax`.`version_int` >= %(version_int)s ELSE 1 END
            """
            )
        else:  # Not defined or 'strict'.
            sql.append('AND `appmax`.`version_int` >= %(version_int)s ')

        sql.append('ORDER BY `versions`.`id` DESC LIMIT 1;')
        self.cursor.execute(''.join(sql), data)
        result = self.cursor.fetchone()

        if result:
            data['row'] = dict(
                zip(
                    [
                        'guid',
                        'slug',
                        'min',
                        'max',
                        'hash',
                        'filename',
                        'file_id',
                        'strict_compat',
                        'releasenotes',
                        'version',
                    ],
                    list(result),
                )
            )
            return True

        return False

    def get_output(self):
        if self.is_valid():
            if self.get_update():
                contents = self.get_success_output()
            else:
                contents = self.get_no_updates_output()
        else:
            contents = self.get_error_output()
        self.cursor.close()
        if self.connection:
            self.connection.close()
        return json.dumps(contents)

    def get_error_output(self):
        return {}

    def get_no_updates_output(self):
        return {'addons': {self.data['guid']: {'updates': []}}}

    def get_success_output(self):
        data = self.data['row']
        slug = data['slug']
        version = data['version']
        file_id = data['file_id']
        filename = os.path.basename(data['filename'])
        update = {
            'version': data['version'],
            # This is essentially re-implementing File.get_absolute_url()
            # without needing django.
            'update_link': (
                f'{settings.SITE_URL}/{self.app.short}/'
                f'downloads/file/{file_id}/{filename}'
            ),
            'applications': {'gecko': {'strict_min_version': data['min']}},
        }
        if data['strict_compat']:
            update['applications']['gecko']['strict_max_version'] = data['max']
        if data['hash']:
            update['update_hash'] = data['hash']
        if data['releasenotes']:
            update['update_info_url'] = (
                f'{settings.SITE_URL}/%APP_LOCALE%/'
                f'{self.app.short}/addon/{slug}/versions/{version}/updateinfo/'
            )
        return {'addons': {self.data['guid']: {'updates': [update]}}}

    def format_date(self, secs):
        return formatdate(time() + secs, usegmt=True)

    def get_headers(self, length):
        content_type = 'application/json'
        return [
            ('Content-Type', content_type),
            ('Cache-Control', 'public, max-age=3600'),
            ('Last-Modified', self.format_date(0)),
            ('Expires', self.format_date(3600)),
            ('Content-Length', str(length)),
        ]


def application(environ, start_response):
    # Logging has to be configured before it can be used. In the django app
    # this is done through settings.LOGGING but the update service is its own
    # separate wsgi app.
    logging.config.dictConfig(settings.LOGGING)

    # Now we can get our logger instance.
    log = olympia.core.logger.getLogger('z.services')

    status = '200 OK'
    with statsd.timer('services.update'):
        data = dict(parse_qsl(environ['QUERY_STRING']))
        compat_mode = data.pop('compatMode', 'strict')
        try:
            update = Update(data, compat_mode)
            output = force_bytes(update.get_output())
            start_response(status, update.get_headers(len(output)))
        except Exception as e:
            log.exception(e)
            raise
    return [output]
