from django.utils.encoding import force_text
from django.utils.translation import pgettext

import jinja2

from django_jinja import library


@library.filter
def user_link(user):
    if not user:
        return ''
    return jinja2.Markup(_user_link(user))


@library.global_function
def users_list(users, size=None, max_text_length=None):
    if not users:
        return ''

    tail = []
    if size and size < len(users):
        users = users[:size]
        tail = [pgettext('user_list_others', 'others')]

    if max_text_length:
        user_list = [_user_link(user, max_text_length) for user in users]
    else:
        user_list = list(map(_user_link, users))

    return jinja2.Markup(', '.join(user_list + tail))


def _user_link(user, max_text_length=None):
    if isinstance(user, str):
        return user

    if max_text_length and len(user.name) > max_text_length:
        name = user.name[:max_text_length].strip() + '...'
    else:
        name = user.name

    return '<a href="%s" title="%s">%s</a>' % (
        user.get_absolute_url(),
        jinja2.escape(user.name),
        jinja2.escape(force_text(name)),
    )
