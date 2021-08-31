import json

from django.utils.encoding import force_bytes
from email.utils import formatdate
from urllib.parse import parse_qsl
from time import time

from services.utils import (
    get_cdn_url,
    log_configure,
    mypool,
    settings,
)

# This has to be imported after the settings so statsd knows where to log to.
from django_statsd.clients import statsd

try:
    from compare import version_int
except ImportError:
    from olympia.versions.compare import version_int

from olympia.constants import applications, base
import olympia.core.logger


# Go configure the log.
log_configure()

log = olympia.core.logger.getLogger('z.services')


class Update:
    def __init__(self, data, compat_mode='strict'):
        self.conn, self.cursor = None, None
        self.data = data.copy()
        self.data['row'] = {}
        self.version_int = 0
        self.compat_mode = compat_mode

    def is_valid(self):
        # If you accessing this from unit tests, then before calling
        # is valid, you can assign your own cursor.
        if not self.cursor:
            self.conn = mypool.connect()
            self.cursor = self.conn.cursor()

        data = self.data
        # Version can be blank.
        data['version'] = data.get('version', '')
        for field in ['reqVersion', 'id', 'appID', 'appVersion']:
            if field not in data:
                return False

        app = applications.APP_GUIDS.get(data['appID'])
        if not app:
            return False

        data['app_id'] = app.id

        sql = """SELECT `id`, `status`, `addontype_id`, `guid` FROM `addons`
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

        data['id'], data['addon_status'], data['type'], data['guid'] = result
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
                `addons`.`addontype_id` AS `type`,
                `addons`.`inactive` AS `disabled_by_user`,
                `appmin`.`version` AS `min`,
                `appmax`.`version` AS `max`,
                `files`.`id` AS `file_id`,
                `files`.`status` AS `file_status`,
                `files`.`hash`,
                `files`.`filename`,
                `versions`.`id` AS `version_id`,
                `files`.`datestatuschanged` AS `datestatuschanged`,
                `files`.`strict_compatibility` AS strict_compat,
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
            -- Find a reference to the user's current version, if it exists.
            -- These should never be inner joins. We need results even if we
            -- can't find the current version.
            LEFT JOIN `versions` `curver`
                ON `curver`.`addon_id` = `addons`.`id`
                AND `curver`.`version` = %(version)s
            LEFT JOIN `files` `curfile`
                ON `curfile`.`version_id` = `curver`.`id`
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
            # Filter out versions that don't have the minimum maxVersion
            # requirement to qualify for default-to-compatible.
            d2c_min = applications.D2C_MIN_VERSIONS.get(data['app_id'])
            if d2c_min:
                data['d2c_min_version'] = version_int(d2c_min)
                sql.append('AND `appmax`.`version_int` >= %(d2c_min_version)s ')

        else:  # Not defined or 'strict'.
            sql.append('AND `appmax`.`version_int` >= %(version_int)s ')

        sql.append('ORDER BY `versions`.`id` DESC LIMIT 1;')
        self.cursor.execute(''.join(sql), data)
        result = self.cursor.fetchone()

        if result:
            row = dict(
                zip(
                    [
                        'guid',
                        'type',
                        'disabled_by_user',
                        'min',
                        'max',
                        'file_id',
                        'file_status',
                        'hash',
                        'filename',
                        'version_id',
                        'datestatuschanged',
                        'strict_compat',
                        'releasenotes',
                        'version',
                    ],
                    list(result),
                )
            )
            row['type'] = base.ADDON_SLUGS_UPDATE[row['type']]
            row['url'] = get_cdn_url(data['id'], row)
            row['appguid'] = applications.APPS_ALL[data['app_id']].guid
            data['row'] = row
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
        if self.conn:
            self.conn.close()
        return json.dumps(contents)

    def get_error_output(self):
        return {}

    def get_no_updates_output(self):
        return {'addons': {self.data['guid']: {'updates': []}}}

    def get_success_output(self):
        data = self.data['row']
        update = {
            'version': data['version'],
            'update_link': data['url'],
            'applications': {'gecko': {'strict_min_version': data['min']}},
        }
        if data['strict_compat']:
            update['applications']['gecko']['strict_max_version'] = data['max']
        if data['hash']:
            update['update_hash'] = data['hash']
        if data['releasenotes']:
            update['update_info_url'] = '{}{}{}/%APP_LOCALE%/'.format(
                settings.SITE_URL,
                '/versions/updateInfo/',
                data['version_id'],
            )
        return {'addons': {self.data['guid']: {'updates': [update]}}}

    def format_date(self, secs):
        return '%s GMT' % formatdate(time() + secs)[:25]

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
