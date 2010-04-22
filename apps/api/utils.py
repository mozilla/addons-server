from django.conf import settings

from amo.utils import urlparams, epoch

def addon_to_dict(addon):
    """
    Renders an addon in JSON for the API.
    """
    v = addon.current_version
    previews = addon.previews.all()
    url = lambda u, **kwargs: settings.SITE_URL + urlparams(u, **kwargs)
    src = 'api'

    d = {
         'id': addon.id,
         'name': unicode(addon.name),
         'guid': addon.guid,
         'status': addon.status,
         'author': (addon.listed_authors[0].display_name if
                    addon.listed_authors else ''),
         'summary': unicode(addon.summary),
         'description': unicode(addon.description),
         'icon': addon.icon_url,
         'previews': [p.as_dict(src=src) for p in previews],
         'learnmore': url(addon.get_url_path(), src=src),
         'reviews': url(addon.reviews_url),
         'total_dls': addon.total_downloads,
         'weekly_dls': addon.weekly_downloads,
         'adu': addon.average_daily_users,
         'created': epoch(addon.created),
         'last_updated': epoch(addon.last_updated),
         'homepage': unicode(addon.homepage),
         'support': unicode(addon.support_url),
    }

    if v:
        d['version'] = v.version
        d['platforms'] = [unicode(a.name) for a in v.supported_platforms]
        apps = v.compatible_apps.values()
        compatible_apps = dict((unicode(a.application),
                {'min': unicode(a.min), 'max': unicode(a.max)}) for a in apps)

        d['compatible_apps'] = compatible_apps

    if addon.eula:
        d['eula'] = unicode(addon.eula)

    if addon.developer_comments:
        d['dev_comments'] = unicode(addon.developer_comments)

    if addon.wants_contributions:
        contribution = {
                'link': url(addon.contribution_url, src=src),
                'meet_developers': url(addon.meet_the_dev_url(), src=src),
                'suggested_amount': unicode(addon.suggested_amount),
                }
        d['contribution'] = contribution

    return d

