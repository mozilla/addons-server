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

    return (
        f'<a href="{user.get_absolute_url()}" title="{markupsafe.escape(user.name)}">'
        f'{markupsafe.escape(force_str(name))}</a>'
    )
