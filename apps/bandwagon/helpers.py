import math
import random

import jinja2
from jingo import register, env
from tower import ugettext as _

from amo.helpers import login_link
from cake.urlresolvers import remora_url


@register.function
def user_collection_list(collections=[], heading=''):
    """list of collections, as used on the user profile page"""
    c = {'collections': collections, 'heading': heading}
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

    user_vote = 0  #  Non-zero if logged in and voted.

    if request.user.is_authenticated():
        # TODO: Use reverse when bandwagon is on Zamboni.
        base_action = remora_url(u'collections/vote/%s' % collection.url_slug)
        up_action = base_action + '/up'
        down_action = base_action + '/down'
        cancel = base_action + '/cancel'
        up_title = _('Add a positive vote for this collection')
        down_title = _('Add a negative vote for this collection')
        cancel_title = _('Remove my vote for this collection')

        votes = request.amo_user.votes.filter(collection=collection)
        if votes:
            user_vote = votes[0]

    else:
        up_action = down_action = cancel_action = login_link(c)
        login_title = _('Log in to vote for this collection')
        up_title = down_title = cancel_title = login_title


    up_class = 'upvotes'
    down_class = 'downvotes'

    total_votes = collection.upvotes + collection.downvotes

    if total_votes:
        up_ratio = int(math.ceil(round(100 * collection.upvotes
                                       / total_votes, 2)))
        down_ratio = 100 - up_ratio

        up_width = max(up_ratio - 1, 0)
        down_width = max(down_ratio - 1, 0)

    if user_vote:
        up_class += ' voted'
        down_class += ' voted'
    up_class
    c.update(locals())
    c.update({ 'c': collection, })
    return c
