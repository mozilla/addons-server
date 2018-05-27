import base64
import json
import os
import posixpath
import re
from time import time
from wsgiref.handlers import format_date_time

from olympia.constants import base

from services.utils import log_configure, log_exception, mypool
from services.utils import settings, user_media_path, user_media_url

# This has to be imported after the settings (utils).
from django_statsd.clients import statsd


# Configure the log.
log_configure()


class ThemeUpdate(object):

    def __init__(self, locale, id_, qs=None):
        self.conn, self.cursor = None, None
        self.from_gp = qs == 'src=gp'
        self.data = {
            'locale': locale,
            'id': id_,
            # If we came from getpersonas.com, then look up by `persona_id`.
            # Otherwise, look up `addon_id`.
            'primary_key': 'persona_id' if self.from_gp else 'addon_id',
            'atype': base.ADDON_PERSONA,
            'row': {}
        }
        if not self.cursor:
            self.conn = mypool.connect()
            self.cursor = self.conn.cursor()

    def base64_icon(self, addon_id):
        path = self.image_path('icon.jpg')
        if not os.path.isfile(path):
            return ''

        try:
            with open(path, 'r') as f:
                return base64.b64encode(f.read())
        except IOError as e:
            if len(e.args) == 1:
                log_exception('I/O error: {0}'.format(e[0]))
            else:
                log_exception('I/O error({0}): {1}'.format(e[0], e[1]))
            return ''

    def get_headers(self, length):
        return [('Cache-Control', 'public, max-age=3600'),
                ('Content-Length', str(length)),
                ('Content-Type', 'application/json'),
                ('Expires', format_date_time(time() + 3600)),
                ('Last-Modified', format_date_time(time()))]

    def get_update(self):
        """
        TODO:

        * When themes have versions let's not use
          `personas.approve` as a `modified` timestamp. Either set this
          during theme approval, or let's keep a hash of the header and
          footer.

        * Do a join on `addons_users` to get the actual correct user.
          We're cheating and setting `personas.display_username` during
          submission/management heh. But `personas.author` and
          `personas.display_username` are not what we want.

        """

        sql = """
        SELECT p.persona_id, a.id, a.slug, v.version,
            t_name.localized_string AS name,
            t_desc.localized_string AS description,
            p.display_username, p.header,
            p.footer, p.accentcolor, p.textcolor,
            UNIX_TIMESTAMP(a.modified) AS modified,
            p.checksum
        FROM addons AS a
        LEFT JOIN personas AS p ON p.addon_id=a.id
        LEFT JOIN versions AS v ON a.current_version=v.id
        LEFT JOIN translations AS t_name
            ON t_name.id=a.name AND t_name.locale=%(locale)s
        LEFT JOIN translations AS t_desc
            ON t_desc.id=a.summary AND t_desc.locale=%(locale)s
        WHERE p.{primary_key}=%(id)s AND
            a.addontype_id=%(atype)s AND a.status=4 AND a.inactive=0
        """.format(primary_key=self.data['primary_key'])

        self.cursor.execute(sql, self.data)
        row = self.cursor.fetchone()

        def row_to_dict(row):
            return dict(zip((
                'persona_id', 'addon_id', 'slug', 'current_version', 'name',
                'description', 'username', 'header', 'footer', 'accentcolor',
                'textcolor', 'modified', 'checksum'),
                list(row)))

        if row:
            self.data['row'] = row_to_dict(row)

            # Fall back to `en-US` if the name was null for our locale.
            # TODO: Write smarter SQL and don't rerun the whole query.
            if not self.data['row']['name']:
                self.data['locale'] = 'en-US'
                self.cursor.execute(sql, self.data)
                row = self.cursor.fetchone()
                if row:
                    self.data['row'] = row_to_dict(row)

            return True

        return False

    # TODO: Cache on row['modified']
    def get_json(self):
        if not self.get_update():
            # Persona not found.
            return

        row = self.data['row']
        accent = row.get('accentcolor')
        text = row.get('textcolor')

        id_ = str(row[self.data['primary_key']])

        data = {
            'id': id_,
            'name': row.get('name'),
            'description': row.get('description'),
            # TODO: Change this to be `addons_users.user.username`.
            'author': row.get('username'),
            # TODO: Change this to be `addons_users.user.display_name`.
            'username': row.get('username'),
            'headerURL': self.image_url(row['header']),
            'footerURL': (
                # Footer can be blank, return '' if that's the case.
                self.image_url(row['footer']) if row['footer'] else ''),
            'detailURL': self.locale_url(settings.SITE_URL,
                                         '/addon/%s/' % row['slug']),
            'previewURL': self.image_url('preview.png'),
            'iconURL': self.image_url('icon.png'),
            'dataurl': self.base64_icon(row['addon_id']),
            'accentcolor': '#%s' % accent if accent else None,
            'textcolor': '#%s' % text if text else None,
            'updateURL': self.locale_url(settings.VAMO_URL,
                                         '/themes/update-check/' + id_),
            # 04-25-2013: Bumped for GP migration so we get new `updateURL`s.
            'version': row.get('current_version', 0)
        }

        # If this theme was originally installed from getpersonas.com,
        # we have to use the `<persona_id>?src=gp` version of the `updateURL`.
        if self.from_gp:
            data['updateURL'] += '?src=gp'

        return json.dumps(data)

    def image_path(self, filename):
        row = self.data['row']

        # Special cased for non-AMO-uploaded themes imported from getpersonas.
        if row['persona_id'] != 0:
            if filename == 'preview.png':
                filename = 'preview.jpg'
            elif filename == 'icon.png':
                filename = 'preview_small.jpg'

        return os.path.join(user_media_path('addons'), str(row['addon_id']),
                            filename)

    def image_url(self, filename):
        row = self.data['row']

        # Special cased for non-AMO-uploaded themes imported from getpersonas.
        if row['persona_id'] != 0:
            if filename == 'preview.png':
                filename = 'preview.jpg'
            elif filename == 'icon.png':
                filename = 'preview_small.jpg'

        image_url = posixpath.join(user_media_url('addons'),
                                   str(row['addon_id']), filename or '')
        if row['checksum']:
            modified = row['checksum'][:8]
        elif row['modified']:
            modified = int(row['modified'])
        else:
            modified = 0
        return '%s?modified=%s' % (image_url, modified)

    def locale_url(self, domain, url):
        return '%s/%s%s' % (domain, self.data.get('locale', 'en-US'), url)


url_re = re.compile('(?P<locale>.+)?/themes/update-check/(?P<id>\d+)$')


def application(environ, start_response):
    """
    Developing locally?

        gunicorn -b 0.0.0.0:7000 -w 12 -k sync -t 90 --max-requests 5000 \
            -n gunicorn-theme_update services.wsgi.theme_update:application

    """

    status = '200 OK'
    with statsd.timer('services.theme_update'):
        try:
            locale, id_ = url_re.match(environ['PATH_INFO']).groups()
            locale = (locale or 'en-US').lstrip('/')
            id_ = int(id_)
        except AttributeError:  # URL path incorrect.
            start_response('404 Not Found', [])
            return ['']

        try:
            update = ThemeUpdate(locale, id_, environ.get('QUERY_STRING'))
            output = update.get_json()
            if not output:
                start_response('404 Not Found', [])
                return ['']
            start_response(status, update.get_headers(len(output)))
        except Exception:
            log_exception(environ['PATH_INFO'])
            raise

    return [output]
