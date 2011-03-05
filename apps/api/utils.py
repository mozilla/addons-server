from django.conf import settings

import amo
from amo.urlresolvers import reverse
from amo.utils import urlparams, epoch


def addon_to_dict(addon, disco=False):
    """
    Renders an addon in JSON for the API.
    """
    v = addon.current_version
    url = lambda u, **kwargs: settings.SITE_URL + urlparams(u, **kwargs)
    src = 'api'

    if disco:
        learnmore = settings.SERVICES_URL + reverse('discovery.addons.detail',
                                                    args=[addon.slug])
        learnmore = urlparams(learnmore, src='discovery-personalrec')
    else:
        learnmore = url(addon.get_url_path(), src=src)

    d = {
         'id': addon.id,
         'name': addon.name,
         'guid': addon.guid,
         'status': addon.status,
         'type': amo.ADDON_SLUGS_UPDATE[addon.type],
         'author': (addon.listed_authors[0].name if
                    addon.listed_authors else ''),
         'summary': addon.summary,
         'description': addon.description,
         'icon': addon.icon_url,
         'learnmore': learnmore,
         'reviews': url(addon.reviews_url),
         'total_dls': addon.total_downloads,
         'weekly_dls': addon.weekly_downloads,
         'adu': addon.average_daily_users,
         'created': epoch(addon.created),
         'last_updated': epoch(addon.last_updated),
         'homepage': addon.homepage,
         'support': addon.support_url,
    }

    if v:
        d['version'] = v.version
        d['platforms'] = [a.name for a in v.supported_platforms]
        d['compatible_apps'] = v.compatible_apps.values()

    if addon.eula:
        d['eula'] = addon.eula

    if addon.developer_comments:
        d['dev_comments'] = addon.developer_comments

    if addon.wants_contributions:
        contribution = {
                'link': url(addon.contribution_url, src=src),
                'meet_developers': url(addon.meet_the_dev_url(), src=src),
                'suggested_amount': addon.suggested_amount,
                }
        d['contribution'] = contribution

    if addon.type == amo.ADDON_PERSONA:
        d['previews'] = [addon.persona.preview_url]
    else:
        d['previews'] = [p.as_dict(src=src) for p in addon.all_previews]

    return d
