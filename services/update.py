import MySQLdb as mysql
from urlparse import parse_qs

import settings_services as settings
from utils import (version_int, get_mirror,
                   APP_GUIDS, PLATFORMS, VERSION_BETA,
                   STATUS_PUBLIC, STATUS_BETA, STATUS_NULL,
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


class Update(object):

    def __init__(self, data):
        # Todo: split this into something cleaner.
        if hasattr(settings, 'DATABASE_SETTINGS'):
            db = settings.DATABASE_SETTINGS
            self.conn = mysql.connect(host=db['host'], user=db['user'],
                                      passwd=db['passwd'], db=db['db'])
            self.cursor = self.conn.cursor()
        else:
            self.conn, self.cursor = None, None

        self.cleaned_data = self.data = data.copy()
        self.data['row'] = {}
        self.flags = {'has_os': False,
                      'use_version': False,
                      'multiple_status': False}
        self.is_beta_version = False
        self.version_int = 0
        self._valid = False

    def is_valid(self):
        if self._valid:
            return True

        required = ['reqVersion', 'id', 'version', 'appID', 'appVersion']

        for field in required:
            if field not in self.data:
                return False

        if self.data['appID'] not in APP_GUIDS:
            return False

        sql = 'SELECT id, status FROM addons WHERE guid = %(guid)s LIMIT 1;'
        self.cursor.execute(sql, {'guid': self.data['id']})
        result = self.cursor.fetchone()
        if result is None:
            return False

        self.data['id'], self.data['status'] = result
        self.data['version_int'] = version_int(self.data['appVersion'])

        if 'appOS' in self.data:
            for k, v in PLATFORMS.items():
                if k in self.data['appOS']:
                    self.data['appOS'] = v
                    break
            else:
                self.data['appOS'] = None

        self.is_beta_version = VERSION_BETA.search(self.data.get('version',
                                                                 ''))
        self._valid = True
        return True

    def get_beta(self):
        if self.data['status'] == STATUS_PUBLIC:
            if self.is_beta_version:
                sql = """
                    SELECT versions.id, status
                    FROM files INNER JOIN versions
                    ON files.version_id = versions.id
                    WHERE versions.addon_id = %(id)s
                          AND versions.version = %(version)s LIMIT 1"""
                self.cursor.execute(sql, self.data)
                result = self.cursor.fetchone()
                if result is not None:
                    status = result[1]
                    if status in (STATUS_BETA, STATUS_PUBLIC):
                        self.data['status'] = status
                    else:
                        self.data['status_lite'] = STATUS_LITE
                        self.data['status_nom'] = STATUS_LITE_AND_NOMINATED
                        self.data['status_public'] = STATUS_PUBLIC
                        self.flags['multiple_status'] = True
                else:
                    self.data['status'] = STATUS_BETA
            else:
                self.data['status'] = STATUS_PUBLIC
        elif self.data['status'] in (STATUS_LITE, STATUS_LITE_AND_NOMINATED):
            self.data['status'] = STATUS_LITE
        else:
            self.data['status'] = STATUS_NULL

    def get_update(self):
        self.get_beta()
        data = self.data

        sql = """
SELECT
    addons.guid as guid, addons.addontype_id as type,
    addons.inactive as disabled_by_user,
    applications.guid as appguid, appmin.version as min,
    appmax.version as max, files.id as file_id, files.hash,
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
    AND applications.guid = %(appID)s
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
                sql += (') WHERE files.status in (%(status_lite)s,'
                        '%(status_nom)s,%(status_public)s)')
            else:
                sql += ') WHERE files.status = %(status)s '

        sql += """
AND (appmin.version_int <= %(version_int)s
AND appmax.version_int >= %(version_int)s)
ORDER BY versions.id DESC
"""

        self.cursor.execute(sql, data)
        result = self.cursor.fetchone()
        if result:
            row = dict(zip([
                'guid', 'type', 'disabled_by_user', 'appguid', 'min', 'max',
                'file_id', 'hash', 'filename', 'version_id',
                'datestatuschanged', 'releasenotes', 'version'],
                list(result)))
            row['type'] = ADDON_SLUGS_UPDATE[row['type']]
            row['url'] = get_mirror(self.data['status'], self.data['id'], row)
            self.data['row'] = row
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


def application(environ, start_response):
    status = '200 OK'
    response_headers = [('Content-type', 'text/xml')]
    start_response(status, response_headers)

    data = parse_qs(environ['QUERY_STRING'])
    for k, v in data.items():
        data[k] = v[0]
    update = Update(data)
    return update.get_rdf()


def load(count):
    for x in range(0, count):
        data = {
                'id': '{2fa4ed95-0317-4c6a-a74c-5f3e3912c1f9}',
                'version': '2.0.58',
                'reqVersion': 1,
                'appID': '{ec8030f7-c20a-464f-9b0e-13a3a9e97384}',
                'appVersion': '3.7a1pre',
            }
        update = Update(data)
        update.get_rdf()


if __name__ == '__main__':
    import cProfile
    import pstats
    cProfile.run('load(100)', 'load')
    p = pstats.Stats('load')
    p.sort_stats('time').print_stats(25)
