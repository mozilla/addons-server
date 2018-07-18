from django.conf import settings

import jinja2

from django_jinja import library

from olympia.addons.templatetags.jinja_helpers import persona_preview
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import urlparams


@library.global_function
@jinja2.contextfunction
def disco_persona_preview(
    context,
    persona,
    size='large',
    linked=True,
    extra=None,
    details=False,
    title=False,
    caption=False,
    src=None,
):
    url = None
    if linked:
        url = reverse('discovery.addons.detail', args=[persona.addon.slug])
        url = settings.SERVICES_URL + url
        if src in ('discovery-video', 'discovery-promo', 'discovery-featured'):
            url = urlparams(url, src=src)
    return persona_preview(
        context,
        persona,
        size=size,
        linked=linked,
        extra=extra,
        details=details,
        title=title,
        caption=caption,
        url=url,
    )
