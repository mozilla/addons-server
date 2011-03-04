from django.conf import settings

import jinja2

from jingo import register

import amo
from amo.utils import urlparams
from amo.urlresolvers import reverse
from addons.helpers import persona_preview


@register.function
@jinja2.contextfunction
def disco_persona_preview(context, persona, size='large', linked=True,
                          extra=None, details=False, title=False, caption=False,
                          src=None):
    url = None
    if linked:
        url = reverse('discovery.addons.detail', args=[persona.addon.slug])
        url = settings.SERVICES_URL + url
        if src in ('discovery-promo', 'discovery-featured'):
            url = urlparams(url, src=src)
    return persona_preview(context, persona, size=size, linked=linked,
                           extra=extra, details=details, title=title,
                           caption=caption, url=url)
