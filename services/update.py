import json
import sys

from django.utils.encoding import force_bytes
from email.Utils import formatdate
from time import time
from urlparse import parse_qsl

from services.utils import mypool, settings

# This has to be imported after the settings so statsd knows where to log to.
from django_statsd.clients import statsd

try:
    from compare import version_int
except ImportError:
    from olympia.versions.compare import version_int

from olympia.constants import applications, base
import olympia.core.logger

from .utils import get_cdn_url, log_configure, PLATFORM_NAMES_TO_CONSTANTS


# Go configure the log.
log_configure()

good_rdf = """<?xml version="1.0"?>
<RDF:RDF xmlns:RDF="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:em="http://www.mozilla.org/2004/em-rdf#">
    <RDF:Description about="urn:mozilla:%(type)s:%(guid)s">
        <em:updates>
            <RDF:Seq>
                <RDF:li resource="urn:mozilla:%(type)s:%(guid)s:%(version)s"/>
            </RDF:Seq>
        </em:updates>
    </RDF:Description>

    <RDF:Description about="urn:mozilla:%(type)s:%(guid)s:%(version)s">
        <em:version>%(version)s</em:version>
        <em:targetApplication>
            <RDF:Description>
                <em:id>%(appguid)s</em:id>
                <em:minVersion>%(min)s</em:minVersion>
                <em:maxVersion>%(max)s</em:maxVersion>
                <em:updateLink>%(url)s</em:updateLink>
                %(if_update)s
                %(if_hash)s
            </RDF:Description>
        </em:targetApplication>
    </RDF:Description>
</RDF:RDF>"""


bad_rdf = """<?xml version="1.0"?>
<RDF:RDF xmlns:RDF="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:em="http://www.mozilla.org/2004/em-rdf#">
</RDF:RDF>"""


no_updates_rdf = """<?xml version="1.0"?>
<RDF:RDF xmlns:RDF="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns:em="http://www.mozilla.org/2004/em-rdf#">
    <RDF:Description about="urn:mozilla:%(type)s:%(guid)s">
        <em:updates>
            <RDF:Seq>
            </RDF:Seq>
        </em:updates>
    </RDF:Description>
</RDF:RDF>"""


error_log = olympia.core.logger.getLogger('z.services')


class Update(object):

    def __init__(self, data, compat_mode='strict'):
        self.conn, self.cursor = None, None
        self.data = data.copy()
        self.data['row'] = {}
        self.version_int = 0
        self.compat_mode = compat_mode
        self.use_json = self.should_use_json()

    def should_use_json(self):
        # We serve JSON manifests to Firefox and Firefox for Android only,
        # because we've seen issues with Seamonkey and Thunderbird.
        # https://github.com/mozilla/addons-server/issues/7223
        app = applications.APP_GUIDS.get(self.data.get('appID'))
        return app and app.id in (applications.FIREFOX.id,
                                  applications.ANDROID.id)

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

        sql = """SELECT id, status, addontype_id, guid FROM addons
                 WHERE guid = %(guid)s AND
                       inactive = 0 AND
                       status NOT IN (%(STATUS_DELETED)s, %(STATUS_DISABLED)s)
                 LIMIT 1;"""
        self.cursor.execute(sql, {
            'guid': self.data['id'],
            'STATUS_DELETED': base.STATUS_DELETED,
            'STATUS_DISABLED': base.STATUS_DISABLED,
        })
        result = self.cursor.fetchone()
        if result is None:
            return False

        data['id'], data['addon_status'], data['type'], data['guid'] = result
        data['version_int'] = version_int(data['appVersion'])

        if 'appOS' in data:
            for k, v in PLATFORM_NAMES_TO_CONSTANTS.items():
                if k in data['appOS']:
                    data['appOS'] = v
                    break
            else:
                data['appOS'] = None

        return True

    def get_update(self):
        data = self.data

        data['STATUS_PUBLIC'] = base.STATUS_PUBLIC
        data['RELEASE_CHANNEL_LISTED'] = base.RELEASE_CHANNEL_LISTED

        sql = ["""
            SELECT
                addons.guid as guid, addons.addontype_id as type,
                addons.inactive as disabled_by_user, appmin.version as min,
                appmax.version as max, files.id as file_id,
                files.status as file_status, files.hash,
                files.filename, versions.id as version_id,
                files.datestatuschanged as datestatuschanged,
                files.strict_compatibility as strict_compat,
                versions.releasenotes, versions.version as version
            FROM versions
            INNER JOIN addons
                ON addons.id = versions.addon_id AND addons.id = %(id)s
            INNER JOIN applications_versions
                ON applications_versions.version_id = versions.id
            INNER JOIN appversions appmin
                ON appmin.id = applications_versions.min
                AND appmin.application_id = %(app_id)s
            INNER JOIN appversions appmax
                ON appmax.id = applications_versions.max
                AND appmax.application_id = %(app_id)s
            INNER JOIN files
                ON files.version_id = versions.id AND (files.platform_id = 1
            """]
        if data.get('appOS'):
            sql.append(' OR files.platform_id = %(appOS)s')

        sql.append("""
            )
            -- Find a reference to the user's current version, if it exists.
            -- These should never be inner joins. We need results even if we
            -- can't find the current version.
            LEFT JOIN versions curver
                ON curver.addon_id = addons.id AND curver.version = %(version)s
            LEFT JOIN files curfile
                ON curfile.version_id = curver.id
            WHERE
                versions.deleted = 0 AND
                versions.channel = %(RELEASE_CHANNEL_LISTED)s AND
                files.status = %(STATUS_PUBLIC)s
        """)

        sql.append('AND appmin.version_int <= %(version_int)s ')

        if self.compat_mode == 'ignore':
            pass  # no further SQL modification required.

        elif self.compat_mode == 'normal':
            # When file has strict_compatibility enabled, or file has binary
            # components, default to compatible is disabled.
            sql.append("""AND
                CASE WHEN files.strict_compatibility = 1 OR
                          files.binary_components = 1
                THEN appmax.version_int >= %(version_int)s ELSE 1 END
            """)
            # Filter out versions that don't have the minimum maxVersion
            # requirement to qualify for default-to-compatible.
            d2c_min = applications.D2C_MIN_VERSIONS.get(data['app_id'])
            if d2c_min:
                data['d2c_min_version'] = version_int(d2c_min)
                sql.append("AND appmax.version_int >= %(d2c_min_version)s ")

            # Filter out versions found in compat overrides
            sql.append("""AND
                NOT versions.id IN (
                SELECT version_id FROM incompatible_versions
                WHERE app_id=%(app_id)s AND
                  (min_app_version='0' AND
                       max_app_version_int >= %(version_int)s) OR
                  (min_app_version_int <= %(version_int)s AND
                       max_app_version='*') OR
                  (min_app_version_int <= %(version_int)s AND
                       max_app_version_int >= %(version_int)s)) """)

        else:  # Not defined or 'strict'.
            sql.append('AND appmax.version_int >= %(version_int)s ')

        # Special case for bug 1031516.
        if data['guid'] == 'firefox-hotfix@mozilla.org':
            app_version = data['version_int']
            hotfix_version = data['version']
            if version_int('10') <= app_version <= version_int('16.0.1'):
                if hotfix_version < '20121019.01':
                    sql.append("AND versions.version = '20121019.01' ")
                elif hotfix_version < '20130826.01':
                    sql.append("AND versions.version = '20130826.01' ")
            elif version_int('16.0.2') <= app_version <= version_int('24.*'):
                if hotfix_version < '20130826.01':
                    sql.append("AND versions.version = '20130826.01' ")

        sql.append('ORDER BY versions.id DESC LIMIT 1;')

        self.cursor.execute(''.join(sql), data)
        result = self.cursor.fetchone()

        if result:
            row = dict(zip([
                'guid', 'type', 'disabled_by_user', 'min', 'max',
                'file_id', 'file_status', 'hash', 'filename', 'version_id',
                'datestatuschanged', 'strict_compat', 'releasenotes',
                'version'],
                list(result)))
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
        return json.dumps(contents) if self.use_json else contents

    def get_error_output(self):
        return {} if self.use_json else bad_rdf

    def get_no_updates_output(self):
        if self.use_json:
            return {
                'addons': {
                    self.data['guid']: {
                        'updates': []
                    }
                }
            }
        else:
            name = base.ADDON_SLUGS_UPDATE[self.data['type']]
            return no_updates_rdf % ({'guid': self.data['guid'], 'type': name})

    def get_success_output(self):
        if self.use_json:
            return self.get_success_output_json()
        else:
            return self.get_success_output_rdf()

    def get_success_output_json(self):
        data = self.data['row']
        update = {
            'version': data['version'],
            'update_link': data['url'],
            'applications': {
                'gecko': {
                    'strict_min_version': data['min']
                }
            }
        }
        if data['strict_compat']:
            update['applications']['gecko']['strict_max_version'] = data['max']
        if data['hash']:
            update['update_hash'] = data['hash']
        if data['releasenotes']:
            update['update_info_url'] = '%s%s%s/%%APP_LOCALE%%/' % (
                settings.SITE_URL, '/versions/updateInfo/', data['version_id'])
        return {
            'addons': {
                self.data['guid']: {
                    'updates': [update]
                }
            }
        }

    def get_success_output_rdf(self):
        data = self.data['row']
        data['if_hash'] = ''
        if data['hash']:
            data['if_hash'] = ('<em:updateHash>%s</em:updateHash>' %
                               data['hash'])

        data['if_update'] = ''
        if data['releasenotes']:
            data['if_update'] = ('<em:updateInfoURL>%s%s%s/%%APP_LOCALE%%/'
                                 '</em:updateInfoURL>' %
                                 (settings.SITE_URL, '/versions/updateInfo/',
                                  data['version_id']))

        return good_rdf % data

    def format_date(self, secs):
        return '%s GMT' % formatdate(time() + secs)[:25]

    def get_headers(self, length):
        content_type = 'application/json' if self.use_json else 'text/xml'
        return [('Content-Type', content_type),
                ('Cache-Control', 'public, max-age=3600'),
                ('Last-Modified', self.format_date(0)),
                ('Expires', self.format_date(3600)),
                ('Content-Length', str(length))]


def log_exception(data):
    (typ, value, traceback) = sys.exc_info()
    error_log.error(u'Type: %s, %s. Query: %s' % (typ, value, data))


def application(environ, start_response):
    status = '200 OK'
    with statsd.timer('services.update'):
        data = dict(parse_qsl(environ['QUERY_STRING']))
        compat_mode = data.pop('compatMode', 'strict')
        try:
            update = Update(data, compat_mode)
            output = force_bytes(update.get_output())
            start_response(status, update.get_headers(len(output)))
        except Exception:
            log_exception(data)
            raise
    return [output]
