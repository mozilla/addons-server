from email.Utils import formatdate
from email.mime.text import MIMEText
import smtplib
import sys
from time import time
import traceback
from urlparse import parse_qsl

import MySQLdb as mysql
import sqlalchemy.pool as pool

import commonware.log
from django.core.management import setup_environ
from django.utils.http import urlencode

import settings_local as settings
setup_environ(settings)
# This has to be imported after the settings so statsd knows where to log to.
from django_statsd.clients import statsd

try:
    from compare import version_int
except ImportError:
    from apps.versions.compare import version_int

from constants import applications, base
from utils import (get_mirror, log_configure, APP_GUIDS, PLATFORMS,
                   STATUSES_PUBLIC)

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


timing_log = commonware.log.getLogger('z.timer')
error_log = commonware.log.getLogger('z.services')


def getconn():
    db = settings.SERVICES_DATABASE
    return mysql.connect(host=db['HOST'], user=db['USER'],
                         passwd=db['PASSWORD'], db=db['NAME'])


mypool = pool.QueuePool(getconn, max_overflow=10, pool_size=5, recycle=300)


class Update(object):

    def __init__(self, data, compat_mode='strict'):
        self.conn, self.cursor = None, None
        self.data = data.copy()
        self.data['row'] = {}
        self.flags = {'use_version': False, 'multiple_status': False}
        self.is_beta_version = False
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

        data['app_id'] = APP_GUIDS.get(data['appID'])
        if not data['app_id']:
            return False

        sql = """SELECT id, status, addontype_id, guid FROM addons
                 WHERE guid = %(guid)s AND
                       inactive = 0 AND
                       status != %(STATUS_DELETED)s
                 LIMIT 1;"""
        self.cursor.execute(sql, {'guid': self.data['id'],
                                  'STATUS_DELETED': base.STATUS_DELETED})
        result = self.cursor.fetchone()
        if result is None:
            return False

        data['id'], data['addon_status'], data['type'], data['guid'] = result
        data['version_int'] = version_int(data['appVersion'])

        if 'appOS' in data:
            for k, v in PLATFORMS.items():
                if k in data['appOS']:
                    data['appOS'] = v
                    break
            else:
                data['appOS'] = None

        self.is_beta_version = base.VERSION_BETA.search(data['version'])
        return True

    def get_beta(self):
        data = self.data
        data['status'] = base.STATUS_PUBLIC

        if data['addon_status'] == base.STATUS_PUBLIC:
            # Beta channel looks at the addon name to see if it's beta.
            if self.is_beta_version:
                # For beta look at the status of the existing files.
                sql = """
                    SELECT versions.id, status
                    FROM files INNER JOIN versions
                    ON files.version_id = versions.id
                    WHERE versions.addon_id = %(id)s
                          AND versions.version = %(version)s LIMIT 1;"""
                self.cursor.execute(sql, data)
                result = self.cursor.fetchone()
                # Only change the status if there are files.
                if result is not None:
                    status = result[1]
                    # If it's in Beta or Public, then we should be looking
                    # for similar. If not, find something public.
                    if status in (base.STATUS_BETA, base.STATUS_PUBLIC):
                        data['status'] = status
                    else:
                        data.update(STATUSES_PUBLIC)
                        self.flags['multiple_status'] = True

        elif data['addon_status'] in (base.STATUS_LITE,
                                      base.STATUS_LITE_AND_NOMINATED):
            data['status'] = base.STATUS_LITE
        else:
            # Otherwise then we'll keep the update within the current version.
            data['status'] = base.STATUS_NULL
            self.flags['use_version'] = True

    def get_update(self):
        self.get_beta()
        data = self.data

        sql = ["""
            SELECT
                addons.guid as guid, addons.addontype_id as type,
                addons.inactive as disabled_by_user,
                applications.guid as appguid, appmin.version as min,
                appmax.version as max, files.id as file_id,
                files.status as file_status, files.hash,
                files.filename, versions.id as version_id,
                files.datestatuschanged as datestatuschanged,
                files.strict_compatibility as strict_compat,
                versions.releasenotes, versions.version as version,
                addons.premium_type
            FROM versions
            INNER JOIN addons
                ON addons.id = versions.addon_id AND addons.id = %(id)s
            INNER JOIN applications_versions
                ON applications_versions.version_id = versions.id
            INNER JOIN applications
                ON applications_versions.application_id = applications.id
                AND applications.id = %(app_id)s
            INNER JOIN appversions appmin
                ON appmin.id = applications_versions.min
            INNER JOIN appversions appmax
                ON appmax.id = applications_versions.max
            INNER JOIN files
                ON files.version_id = versions.id AND (files.platform_id = 1
            """]
        if data.get('appOS'):
            sql.append(' OR files.platform_id = %(appOS)s')

        if self.flags['use_version']:
            sql.append(') WHERE files.status > %(status)s AND '
                    'versions.version = %(version)s ')
        else:
            if self.flags['multiple_status']:
                # Note that getting this properly escaped is a pain.
                # Suggestions for improvement welcome.
                sql.append(') WHERE files.status in (%(STATUS_PUBLIC)s,'
                        '%(STATUS_LITE)s,%(STATUS_LITE_AND_NOMINATED)s) ')
            else:
                sql.append(') WHERE files.status = %(status)s ')

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
            d2c_max = applications.D2C_MAX_VERSIONS.get(data['app_id'])
            if d2c_max:
                data['d2c_max_version'] = version_int(d2c_max)
                sql.append("AND appmax.version_int >= %(d2c_max_version)s ")

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

        sql.append('ORDER BY versions.id DESC LIMIT 1;')

        self.cursor.execute(''.join(sql), data)
        result = self.cursor.fetchone()

        if result:
            row = dict(zip([
                'guid', 'type', 'disabled_by_user', 'appguid', 'min', 'max',
                'file_id', 'file_status', 'hash', 'filename', 'version_id',
                'datestatuschanged', 'strict_compat', 'releasenotes',
                'version', 'premium_type'],
                list(result)))
            row['type'] = base.ADDON_SLUGS_UPDATE[row['type']]
            if row['premium_type'] in base.ADDON_PREMIUMS:
                qs = urlencode(dict((k, data.get(k, ''))
                               for k in base.WATERMARK_KEYS))
                row['url'] = (u'%s/downloads/watermarked/%s?%s' %
                              (settings.SITE_URL, row['file_id'], qs))
            else:
                row['url'] = get_mirror(self.data['addon_status'],
                                        self.data['id'], row)
            data['row'] = row
            return True

        return False

    def get_bad_rdf(self):
        return bad_rdf

    def get_rdf(self):
        if self.is_valid():
            if self.get_update():
                rdf = self.get_good_rdf()
            else:
                rdf = self.get_no_updates_rdf()
        else:
            rdf = self.get_bad_rdf()
        self.cursor.close()
        if self.conn:
            self.conn.close()
        return rdf

    def get_no_updates_rdf(self):
        name = base.ADDON_SLUGS_UPDATE[self.data['type']]
        return no_updates_rdf % ({'guid': self.data['guid'], 'type': name})

    def get_good_rdf(self):
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
        return [('Content-Type', 'text/xml'),
                ('Cache-Control', 'public, max-age=3600'),
                ('Last-Modified', self.format_date(0)),
                ('Expires', self.format_date(3600)),
                ('Content-Length', str(length))]


def mail_exception(data):
    if settings.EMAIL_BACKEND != 'django.core.mail.backends.smtp.EmailBackend':
        return

    msg = MIMEText('%s\n\n%s' % (
        '\n'.join(traceback.format_exception(*sys.exc_info())), data))
    msg['Subject'] = '[Update] ERROR at /services/update'
    msg['To'] = ','.join([a[1] for a in settings.ADMINS])
    msg['From'] = settings.DEFAULT_FROM_EMAIL

    conn = smtplib.SMTP(getattr(settings, 'EMAIL_HOST', 'localhost'),
                        getattr(settings, 'EMAIL_PORT', '25'))
    conn.sendmail(settings.DEFAULT_FROM_EMAIL, msg['To'], msg.as_string())
    conn.close()


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
            output = update.get_rdf()
            start_response(status, update.get_headers(len(output)))
        except:
            #mail_exception(data)
            log_exception(data)
            raise
    return [output]
