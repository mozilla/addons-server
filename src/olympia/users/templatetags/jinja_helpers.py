from django.utils.encoding import force_str
from django.utils.translation import pgettext

import markupsafe

from django_jinja import library


@library.filter
def user_link(user):
    if not user:
        return ''
    return markupsafe.Markup(_user_link(user))


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

    return markupsafe.Markup(', '.join(user_list + tail))


def _user_link(user, max_text_length=None):
    if isinstance(user, str):
        return user

    if max_text_length and len(user.name) > max_text_length:
        name = user.name[:max_text_length].strip() + '...'
    else:
        name = user.name

    return '<a href="{}" title="{}">{}</a>'.format(
        user.get_absolute_url(),
        markupsafe.escape(user.name),
        markupsafe.escape(force_str(name)),
    )
