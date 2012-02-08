import base64
import json
import re

from constants import base

from django.core.management import setup_environ

from utils import format_date, log_configure, log_exception, mypool

from services.utils import settings
setup_environ(settings)

# Configure the log.
log_configure()

from django_statsd.clients import statsd


# TODO: Update these to their correct locations.
PERSONA_HOST = PERSONA_CDN_HOST = 'http://getpersonas.com'


class PersonaUpdate(object):

    def __init__(self, locale, id):
        self.conn, self.cursor = None, None
        self.data = dict(locale=locale, id=id)
        self.data.update(atype=base.ADDON_PERSONA)
        self.data['row'] = {}

        if not self.cursor:
            self.conn = mypool.connect()
            self.cursor = self.conn.cursor()

    def get_update(self):

        sql = """
        SELECT
          personas.persona_id, addons.id,
          t_name.localized_string AS name,
          t_desc.localized_string AS description,
          personas.author, personas.display_username, personas.header,
          personas.footer, personas.accentcolor, personas.textcolor,
          UNIX_TIMESTAMP(personas.approve) AS modified
        FROM addons
        LEFT JOIN personas ON personas.addon_id=addons.id
        LEFT JOIN translations AS t_name
          ON t_name.id=personas.name AND t_name.locale=%(locale)s
        LEFT JOIN translations AS t_desc
          ON t_desc.id=personas.description AND t_desc.locale=%(locale)s
        WHERE personas.persona_id=%(id)s AND addons.addontype_id=%(atype)s
        """

        self.cursor.execute(sql, self.data)
        result = self.cursor.fetchone()

        if result:
            row = dict(zip([
                'id', 'addon_id', 'name', 'description', 'author', 'username',
                'header', 'footer', 'accentcolor', 'textcolor', 'modified'],
                list(result)))
            self.data['row'] = row
            return True

        return False

    def get_json(self):
        if self.get_update():
            return self.compose_good_json()
        else:  # Persona not found.
            return None

    def url_prefix(self, id):
        """Uses last 2 digits to add extra directories.

        For example:
            url_prefix(1234) => '4/3/1234'
        """
        return '%s/%s/%s' % (id % 10, (id // 10) % 10, id)

    def compose_good_json(self):

        id = self.data['id']
        accent = self.data.get('accentcolor')
        text = self.data.get('textcolor')
        base_url = '%s/static/%s/' % (PERSONA_CDN_HOST,
                                      self.url_prefix(id))
        row = self.data.get('row')

        data = {
            'id': id,
            'name': row.get('name'),
            'description': row.get('description'),
            'author': row.get('author'),
            'username': row.get('username'),
            'headerURL': '%s/%s?%s' % (base_url, row['header'],
                                       row['modified']),
            'footerURL': '%s/%s?%s' % (base_url, row['footer'],
                                       row['modified']),
            'detailURL': '%s/persona/%s' % (PERSONA_HOST, id),
            'previewURL': '%s/preview.jpg?%s' % (base_url,
                                                 row['modified']),
            'iconURL': '%s/preview_small.jpg?%s' % (base_url,
                                                    row['modified']),
            # TODO: dataurl requires a call to the filesystem to base64.
            # 'dataurl': self.base64_icon(id),
            'dataurl': '',
            'accentcolor': '#%s' % accent if accent else None,
            'textcolor': '#%s' % text if text else None,
            'updateUrl': '%s/%s/update_check/%s' % (PERSONA_HOST,
                                                    self.data['locale'], id),
            'version': row.get('modified'),
        }

        return json.dumps(data)

    def base64_icon(self, persona_id):
        path = '%s/%s/preview_icon.jpg' % (settings.PERSONAS_PATH,
                                           self.url_prefix(id))
        with open(path, 'r') as f:
            return base64.b64encode(f.read())

    def get_headers(self, length):
        return [('Content-Type', 'application/json'),
                ('Cache-Control', 'public, max-age=3600'),
                ('Last-Modified', format_date(0)),
                ('Expires', format_date(3600)),
                ('Content-Length', str(length))]


url_re = re.compile('/(?P<locale>[^/]+)/personas/update_check/(?P<id>\d+)$')


def application(environ, start_response):
    status = '200 OK'
    with statsd.timer('services.persona_update'):

        data = environ['wsgi.input'].read()
        try:
            locale, id = url_re.match(environ['PATH_INFO']).groups()
            id = int(id)
        except AttributeError:  # URL path incorrect.
            start_response('404 Not Found', [])
            return ['']

        try:
            update = PersonaUpdate(locale, id)
            output = update.get_json()
            if not output:
                start_response('404 Not Found', [])
                return ['']
            start_response(status, update.get_headers(len(output)))
        except:
            log_exception(data)
            raise

    return [output]
