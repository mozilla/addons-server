from django.conf import settings

from addons.decorators import addon_view_factory
from addons.models import Addon
from addons.views import _category_personas as _category_themes

import jingo

addon_all_view = addon_view_factory(qs=Addon.objects.all)


@addon_all_view
def detail(request, addon):
    """Theme details page."""
    theme = addon.persona

    categories = addon.all_categories
    if categories:
        qs = Addon.objects.public().filter(categories=categories[0])
        category_themes = _category_themes(qs, limit=6)
    else:
        category_themes = None

    data = {
        'product': addon,
        'categories': categories,
        'category_themes': category_themes,
        'author_themes': theme.authors_other_addons(request.APP)[:3],
        'theme': theme,
    }
    if not theme.is_new():
        # Remora uses persona.author despite there being a display_username.
        data['author_gallery'] = settings.PERSONAS_USER_ROOT % theme.author

    return jingo.render(request, 'themes/detail.html', data)
