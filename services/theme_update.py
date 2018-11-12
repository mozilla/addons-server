import json
import posixpath
import re
from time import time
from wsgiref.handlers import format_date_time

from six import text_type

from olympia.constants import base

from services.utils import (
    get_cdn_url, log_configure, log_exception, mypool, settings,
    user_media_url)

# This has to be imported after the settings (utils).
from django_statsd.clients import statsd

import olympia.core.logger

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
                "converted_theme": {
                    "url": get_cdn_url(self.data['stheme_id'], self.data),
                    "hash": self.data['hash']
                }
            }
            return json.dumps(response)


class LWThemeUpdate(ThemeUpdate):

    def __init__(self, locale, id_, qs=None):
        super(LWThemeUpdate, self).__init__(locale, id_, qs)
        self.data = {
            'locale': locale,
            'id': id_,
            # If we came from getpersonas.com, then look up by `persona_id`.
            # Otherwise, look up `addon_id`.
            'primary_key': 'persona_id' if self.from_gp else 'addon_id',
            'atype': base.ADDON_PERSONA,
            'row': {}
        }

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


url_re = re.compile(r'(?P<locale>.+)?/themes/update-check/(?P<id>\d+)$')


def is_android_ua(user_agent):
    return 'android' in text_type(user_agent).lower()


update_log = olympia.core.logger.getLogger('z.addons')


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
            query_string = environ.get('QUERY_STRING')
            update = MigratedUpdate(locale, id_, query_string)
            is_migrated = update.is_migrated
            user_agent_string = environ.get('HTTP_USER_AGENT')
            update_log.info(
                "HTTP_USER_AGENT %s; is_migrated: %s, is_android_ua: %s",
                user_agent_string, is_migrated,
                is_android_ua(user_agent_string))
            if not is_migrated:
                update = LWThemeUpdate(locale, id_, query_string)
            elif is_android_ua(user_agent_string):
                update = None
            output = update.get_json() if update else None
            if not output:
                start_response('404 Not Found', [])
                return ['']
            start_response(status, update.get_headers(len(output)))
        except Exception:
            log_exception(environ['PATH_INFO'])
            raise

    return [output]
