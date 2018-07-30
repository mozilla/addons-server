from django.template import loader
from django.utils.translation import ugettext

import jinja2

from django_jinja import library

from olympia.addons.templatetags.jinja_helpers import new_context
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import chunked


@library.global_function
@library.render_with('bandwagon/collection_listing_items.html')
@jinja2.contextfunction
def collection_listing_items(context, collections, field=None):
    c = dict(context.items())
    c.update(collections=collections, field=field)
    return c


@library.global_function
@library.render_with('bandwagon/impala/collection_listing_items.html')
@jinja2.contextfunction
def impala_collection_listing_items(context, collections, field=None):
    c = dict(context.items())
    c.update(collections=collections, field=field)
    return c


@library.global_function
def user_collection_list(collections=None, heading='', id='', link=None):
    """list of collections, as used on the user profile page"""
    if collections is None:
        collections = []
    c = {'collections': collections, 'heading': heading, 'link': link,
         'id': id}
    template = loader.get_template('bandwagon/users/collection_list.html')
    return jinja2.Markup(template.render(c))


@library.global_function
@library.render_with('addons/includes/collection_add_widget.html')
def collection_add_widget(addon, condensed=False):
    """Displays 'Add to Collection' widget"""
    return {'addon': addon, 'condensed': condensed}


@library.filter
@jinja2.contextfilter
@library.render_with('bandwagon/collection_grid.html')
def collection_grid(context, collections, src=None, pagesize=4, cols=2):
    pages = chunked(collections, pagesize)
    columns = 'cols-%d' % cols
    return new_context(**locals())


@library.global_function
@jinja2.contextfunction
def favorites_widget(context, addon, condensed=False):
    """Displays 'Add to Favorites' widget."""
    c = dict(context.items())
    request = c['request']
    if request.user.is_authenticated():
        is_favorite = addon.id in request.user.favorite_addons
        faved_class = 'faved' if is_favorite else ''

        unfaved_text = '' if condensed else ugettext('Add to favorites')
        faved_text = (
            ugettext('Favorite') if condensed else
            ugettext('Remove from favorites'))

        add_url = reverse('collections.alter',
                          args=[request.user.username, 'favorites', 'add'])
        remove_url = reverse('collections.alter',
                             args=[request.user.username,
                                   'favorites', 'remove'])

        c.update(locals())
        t = loader.get_template('bandwagon/favorites_widget.html').render(c)
        return jinja2.Markup(t)


@library.global_function
@jinja2.contextfunction
def collection_widgets(context, collection, condensed=False):
    """Displays collection widgets"""
    c = dict(context.items())
    if collection:
        c.update({'condensed': condensed,
                  'c': collection})
        template = loader.get_template('bandwagon/collection_widgets.html')
        return jinja2.Markup(template.render(c))
