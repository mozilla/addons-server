import math

import jinja2
from jingo import register, env
from tower import ugettext as _

from amo.helpers import login_link
from cake.urlresolvers import remora_url
from amo.urlresolvers import reverse


@register.inclusion_tag('bandwagon/collection_listing_items.html')
@jinja2.contextfunction
def collection_listing_items(context, collections, show_weekly=False,
                            show_date=None):
    c = dict(context.items())
    c.update(collections=collections, show_weekly=show_weekly,
             show_date=show_date)
    return c


@register.function
def user_collection_list(collections=[], heading='', link=None):
    """list of collections, as used on the user profile page"""
    c = {'collections': collections, 'heading': heading, 'link': link}
    t = env.get_template('bandwagon/users/collection_list.html').render(**c)
    return jinja2.Markup(t)


@register.inclusion_tag('bandwagon/collection_favorite.html')
@jinja2.contextfunction
def collection_favorite(context, collection):
    c = dict(context.items())
    user = c['request'].amo_user
    is_subscribed = collection.is_subscribed(user)

    button_class = 'add-to-fav'

    if is_subscribed:
        button_class += ' fav'
        text = _('Remove from Favorites')
        action = remora_url('collections/unsubscribe')

    else:
        text = _('Add to Favorites')
        action = remora_url('collections/subscribe')

    c.update(locals())
    c.update({'c': collection})
    return c


@register.inclusion_tag('bandwagon/barometer.html')
@jinja2.contextfunction
def barometer(context, collection):
    """Shows a barometer for a collection."""
    c = dict(context.items())
    request = c['request']

    user_vote = None  # Non-zero if logged in and voted.

    if request.user.is_authenticated():
        # TODO: Use reverse when bandwagon is on Zamboni.
        up_action = collection.upvote_url()
        down_action = collection.downvote_url()
        up_title = _('Add a positive vote for this collection')
        down_title = _('Add a negative vote for this collection')
        cancel_title = _('Remove my vote for this collection')

        if 'collection_votes' in context:
            user_vote = context['collection_votes'].get(collection.id)
        else:
            votes = request.amo_user.votes.filter(collection=collection)
            if votes:
                user_vote = votes[0]

    else:
        up_action = down_action = login_link(c)
        login_title = _('Log in to vote for this collection')
        up_title = down_title = cancel_title = login_title

    up_class = 'upvotes'
    down_class = 'downvotes'
    cancel_class = 'cancel_vote'

    total_votes = collection.upvotes + collection.downvotes

    if total_votes:
        up_ratio = int(math.ceil(round(100 * collection.upvotes
                                       / total_votes, 2)))
        down_ratio = 100 - up_ratio

        up_width = max(up_ratio - 1, 0)
        down_width = max(down_ratio - 1, 0)

    if user_vote:
        if user_vote.vote > 0:
            up_class += ' voted'
        else:
            down_class += ' voted'
    else:
        cancel_class += ' hidden'

    c.update(locals())
    c.update({'c': collection})
    return c


@register.inclusion_tag('addons/includes/collection_add_widget.html')
@register.function
@jinja2.contextfunction
def collection_add_widget(context, addon, condensed=False):
    """Displays 'Add to Collection' widget"""
    c = dict(context.items())
    c.update(locals())
    return c


@register.function
@jinja2.contextfunction
def favorites_widget(context, addon, condensed=False):
    """Displays 'Add to Favorites' widget."""
    c = dict(context.items())
    request = c['request']
    if request.user.is_authenticated():
        is_favorite = addon.id in request.amo_user.favorite_addons
        faved_class = 'faved' if is_favorite else ''

        unfaved_text = '' if condensed else _('Add to favorites')
        faved_text = 'Favorite' if condensed else _('Remove from favorites')

        add_url = reverse('collections.alter',
                          args=[request.amo_user.username, 'favorites', 'add'])
        remove_url = reverse('collections.alter',
                             args=[request.amo_user.username,
                                   'favorites', 'remove'])

        c.update(locals())
        t = env.get_template('bandwagon/favorites_widget.html').render(**c)
        return jinja2.Markup(t)


@register.function
@jinja2.contextfunction
def collection_widgets(context, collection, condensed=False):
    """Displays collection widgets"""
    c = dict(context.items())
    request = c['request']
    if collection:
        c.update({'condensed': condensed,
                  'c': collection,
                 })
        t = env.get_template('bandwagon/collection_widgets.html').render(**c)
        return jinja2.Markup(t)
