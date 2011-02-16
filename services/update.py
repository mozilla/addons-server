from email.Utils import formatdate
from urlparse import parse_qsl
from time import time

import MySQLdb as mysql
import sqlalchemy.pool as pool

import settings_local as settings

try:
    from compare import version_int
except ImportError:
    from apps.versions.compare import version_int

from utils import (get_mirror,
                   APP_GUIDS, PLATFORMS, VERSION_BETA,
                   STATUS_PUBLIC, STATUSES_PUBLIC, STATUS_BETA, STATUS_NULL,
                   STATUS_LITE, STATUS_LITE_AND_NOMINATED, ADDON_SLUGS_UPDATE)


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


def getconn():
    db = settings.DATABASE_SETTINGS
    return mysql.connect(host=db['host'], user=db['user'],
                         passwd=db['passwd'], db=db['db'])


mypool = pool.QueuePool(getconn, max_overflow=10, pool_size=5)


class Update(object):

    def __init__(self, data):
        self.conn, self.cursor = None, None
        self.data = data.copy()
        self.data['row'] = {}
        self.flags = {'use_version': False, 'multiple_status': False}
        self.is_beta_version = False
        self.version_int = 0

    def is_valid(self):
        # If you accessing this from unit tests, then before calling
        # is valid, you can assign your own cursor.
        if not self.cursor:
            self.conn = mypool.connect()
            self.cursor = self.conn.cursor()

        data = self.data

        for field in ['reqVersion', 'id', 'version', 'appID', 'appVersion']:
            if field not in data:
                return False

        data['app_id'] = APP_GUIDS.get(data['appID'])
        if not data['app_id']:
            return False

        sql = """SELECT id, status FROM addons
                 WHERE guid = %(guid)s AND inactive = 0 LIMIT 1;"""
        self.cursor.execute(sql, {'guid': self.data['id']})
        result = self.cursor.fetchone()
        if result is None:
            return False

        data['id'], data['addon_status'] = result
        data['version_int'] = version_int(data['appVersion'])

        if 'appOS' in data:
            for k, v in PLATFORMS.items():
                if k in data['appOS']:
                    data['appOS'] = v
                    break
            else:
                data['appOS'] = None

        self.is_beta_version = VERSION_BETA.search(data.get('version', ''))
        return True

    def get_beta(self):
        data = self.data
        data['status'] = STATUS_PUBLIC

        if data['addon_status'] == STATUS_PUBLIC:
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
                    if status in (STATUS_BETA, STATUS_PUBLIC):
                        data['status'] = status
                    else:
                        data.update(STATUSES_PUBLIC)
                        self.flags['multiple_status'] = True

        elif data['addon_status'] in (STATUS_LITE, STATUS_LITE_AND_NOMINATED):
            data['status'] = STATUS_LITE
        else:
            # Otherwise then we'll keep the update within the current version.
            data['status'] = STATUS_NULL
            self.flags['use_version'] = True

    def get_update(self):
        self.get_beta()
        data = self.data

        sql = """
            SELECT
                addons.guid as guid, addons.addontype_id as type,
                addons.inactive as disabled_by_user,
                applications.guid as appguid, appmin.version as min,
                appmax.version as max, files.id as file_id,
                files.status as file_status, files.hash,
                files.filename, versions.id as version_id,
                files.datestatuschanged as datestatuschanged,
                versions.releasenotes, versions.version as version
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
            """
        if data.get('appOS'):
            sql += ' OR files.platform_id = %(appOS)s'

        if self.flags['use_version']:
            sql += (') WHERE files.status > %(status)s AND '
                    'versions.version = %(version)s ')
        else:
            if self.flags['multiple_status']:
                # Note that getting this properly escaped is a pain.
                # Suggestions for improvement welcome.
                sql += (') WHERE files.status in (%(STATUS_PUBLIC)s,'
                        '%(STATUS_LITE)s,%(STATUS_LITE_AND_NOMINATED)s)')
            else:
                sql += ') WHERE files.status = %(status)s '

        sql += """
            AND (appmin.version_int <= %(version_int)s
            AND appmax.version_int >= %(version_int)s)
            ORDER BY versions.id DESC LIMIT 1;
            """

        self.cursor.execute(sql, data)
        result = self.cursor.fetchone()
        if result:
            row = dict(zip([
                'guid', 'type', 'disabled_by_user', 'appguid', 'min', 'max',
                'file_id', 'file_status', 'hash', 'filename', 'version_id',
                'datestatuschanged', 'releasenotes', 'version'],
                list(result)))
            row['type'] = ADDON_SLUGS_UPDATE[row['type']]
            row['url'] = get_mirror(self.data['addon_status'],
                                    self.data['id'], row)
            data['row'] = row
            return True

        return False

    def get_bad_rdf(self):
        return bad_rdf

    def get_rdf(self):
        if self.is_valid() and self.get_update():
            rdf = self.get_good_rdf()
        else:
            rdf = self.get_bad_rdf()
        self.cursor.close()
        if self.conn:
            self.conn.close()
        return rdf

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


def application(environ, start_response):
    status = '200 OK'
    data = dict(parse_qsl(environ['QUERY_STRING']))
    update = Update(data)
    output = update.get_rdf()
    start_response(status, update.get_headers(len(output)))
    return output
