import random

import jinja2

from jingo import register, env


@register.function
def user_collection_list(collections=[], heading=''):
    """list of collections, as used on the user profile page"""
    c = {'collections': collections, 'heading': heading}
    t = env.get_template('bandwagon/users/collection_list.html').render(**c)
    return jinja2.Markup(t)
