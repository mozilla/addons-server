from django.conf import settings
from django.core.cache import cache
from django.utils.html import strip_tags

import olympia.core.logger

from olympia import amo
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import cache_ns_key, epoch, urlparams
from olympia.versions.compare import version_int
from olympia.versions.models import Version


log = olympia.core.logger.getLogger('z.api')


def addon_to_dict(addon, disco=False, src='api'):
    """
    Renders an addon into a dict for the legacy API.
    """
    def url(u, **kwargs):
        return settings.SITE_URL + urlparams(u, **kwargs)

    v = addon.current_version

    if disco:
        learnmore = settings.SERVICES_URL + reverse('discovery.addons.detail',
                                                    args=[addon.slug])
        learnmore = urlparams(learnmore, src='discovery-personalrec')
    else:
        learnmore = url(addon.get_url_path(), src=src)

    d = {
        'id': addon.id,
        'name': unicode(addon.name) if addon.name else None,
        'guid': addon.guid,
        'status': amo.STATUS_CHOICES_API[addon.status],
        'type': amo.ADDON_SLUGS_UPDATE[addon.type],
        'authors': [{'id': a.id, 'name': unicode(a.name),
                     'link': absolutify(a.get_url_path(src=src))}
                    for a in addon.listed_authors],
        'summary': (
            strip_tags(unicode(addon.summary)) if addon.summary else None),
        'description': strip_tags(unicode(addon.description)),
        'icon': addon.icon_url,
        'learnmore': learnmore,
        'reviews': url(addon.ratings_url),
        'total_dls': addon.total_downloads,
        'weekly_dls': addon.weekly_downloads,
        'adu': addon.average_daily_users,
        'created': epoch(addon.created),
        'last_updated': epoch(addon.last_updated),
        'homepage': unicode(addon.homepage) if addon.homepage else None,
        'support': unicode(addon.support_url) if addon.support_url else None,
    }
    if addon.is_persona():
        d['theme'] = addon.persona.theme_data

    if v:
        d['version'] = v.version
        d['platforms'] = [unicode(a.name) for a in v.supported_platforms]
        d['compatible_apps'] = [{
            unicode(amo.APP_IDS[appver.application].pretty): {
                'min': unicode(appver.min) if appver else (
                    amo.D2C_MIN_VERSIONS.get(app.id, '1.0')),
                'max': unicode(appver.max) if appver else amo.FAKE_MAX_VERSION,
            }} for app, appver in v.compatible_apps.items() if appver]
    if addon.eula:
        d['eula'] = unicode(addon.eula)

    if addon.developer_comments:
        d['dev_comments'] = unicode(addon.developer_comments)

    if addon.contributions:
        d['contribution'] = {
            'meet_developers': addon.contributions,
        }

    if addon.type == amo.ADDON_PERSONA:
        d['previews'] = [addon.persona.preview_url]
    else:
        def preview_as_dict(preview, src):
            d = {'full': urlparams(preview.image_url, src=src),
                 'thumbnail': urlparams(preview.thumbnail_url, src=src),
                 'caption': unicode(preview.caption)}
            return d

        d['previews'] = [preview_as_dict(p, src) for p in addon.all_previews]

    return d


def find_compatible_version(addon, app_id, app_version=None, platform=None,
                            compat_mode='strict'):
    """Returns the newest compatible version (ordered by version id desc)
    for the given addon."""
    if not app_id:
        return None

    if platform:
        # We include platform_id=1 always in the SQL so we skip it here.
        platform = platform.lower()
        if platform != 'all' and platform in amo.PLATFORM_DICT:
            platform = amo.PLATFORM_DICT[platform].id
        else:
            platform = None

    log.debug(u'Checking compatibility for add-on ID:%s, APP:%s, V:%s, '
              u'OS:%s, Mode:%s' % (addon.id, app_id, app_version, platform,
                                   compat_mode))
    valid_file_statuses = ','.join(map(str, addon.valid_file_statuses))
    data = {
        'id': addon.id,
        'app_id': app_id,
        'platform': platform,
        'valid_file_statuses': valid_file_statuses,
        'channel': amo.RELEASE_CHANNEL_LISTED,
    }
    if app_version:
        data.update(version_int=version_int(app_version))
    else:
        # We can't perform the search queries for strict or normal without
        # an app version.
        compat_mode = 'ignore'

    ns_key = cache_ns_key('d2c-versions:%s' % addon.id)
    cache_key = '%s:%s:%s:%s:%s' % (ns_key, app_id, app_version, platform,
                                    compat_mode)
    version_id = cache.get(cache_key)
    if version_id is not None:
        log.debug(u'Found compatible version in cache: %s => %s' % (
                  cache_key, version_id))
        if version_id == 0:
            return None
        else:
            try:
                return Version.objects.get(pk=version_id)
            except Version.DoesNotExist:
                pass

    raw_sql = ["""
        SELECT versions.*
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
            ON files.version_id = versions.id AND
               (files.platform_id = 1"""]

    if platform:
        raw_sql.append(' OR files.platform_id = %(platform)s')

    raw_sql.append(') WHERE files.status IN (%(valid_file_statuses)s) ')

    raw_sql.append(' AND versions.channel = %(channel)s ')

    if app_version:
        raw_sql.append('AND appmin.version_int <= %(version_int)s ')

    if compat_mode == 'ignore':
        pass  # No further SQL modification required.

    elif compat_mode == 'normal':
        raw_sql.append("""AND
            CASE WHEN files.strict_compatibility = 1 OR
                      files.binary_components = 1
            THEN appmax.version_int >= %(version_int)s ELSE 1 END
        """)
        # Filter out versions that don't have the minimum maxVersion
        # requirement to qualify for default-to-compatible.
        d2c_max = amo.D2C_MIN_VERSIONS.get(app_id)
        if d2c_max:
            data['d2c_max_version'] = version_int(d2c_max)
            raw_sql.append(
                "AND appmax.version_int >= %(d2c_max_version)s ")

        # Filter out versions found in compat overrides
        raw_sql.append("""AND
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
        raw_sql.append('AND appmax.version_int >= %(version_int)s ')

    raw_sql.append('ORDER BY versions.id DESC LIMIT 1;')

    # Use no_cache to make the result not depend on cache-machine
    # caches. The whole function is heavily cached anyway.
    version = list(Version.objects.no_cache().raw(''.join(raw_sql) % data))
    if version:
        version = version[0]
        version_id = version.id
    else:
        version = None
        version_id = 0

    log.debug(u'Caching compat version %s => %s' % (cache_key, version_id))
    cache.set(cache_key, version_id, None)

    return version
