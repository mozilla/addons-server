from django.utils.encoding import force_str

import markupsafe
from django_jinja import library


@library.filter
def user_link(user):
    if not user:
        return ''
    return markupsafe.Markup(_user_link(user))


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
