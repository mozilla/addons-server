from functools import partial

from django.contrib import messages as django_messages

import jinja2
from jingo import env

"""
This file was created because AMO wants to have multi-line messages including a
title and some content.  Django's messages framework only takes a single string.
Importing this file should behave exactly like Django's messages framework
except it will take a 3rd argument as message content (the second is the message
title).
"""

def _make_message(title=None, message=None, title_safe=False,
                                            message_safe=False):
    c = {'title': title, 'message': message,
         'title_safe': title_safe, 'message_safe': message_safe}
    t = env.get_template('message_content.html').render(**c)
    return jinja2.Markup(t)


def _is_dupe(msg, request):
    """Returns whether a particular message is already cued for display."""
    storage = django_messages.get_messages(request)

    # If there are no messages stored, Django doesn't give us a proper storage
    # object, so just bail early.
    if not storage:
        return False

    smsg = str(msg)
    is_dupe = False
    for message in storage:
        if str(message) == smsg:
            # We can't return from here because we need to tell Django not to
            # consume the messages.
            is_dupe = True
            break

    storage.used = False
    return is_dupe


def _file_message(type_, request, title, message=None, extra_tags='',
                  fail_silently=False, title_safe=False, message_safe=False):
    msg = _make_message(title, message, title_safe, message_safe)
    # Don't save duplicates.
    if _is_dupe(msg, request):
        return
    getattr(django_messages, type_)(request, msg, extra_tags, fail_silently)


debug = partial(_file_message, 'debug')
info = partial(_file_message, 'info')
success = partial(_file_message, 'success')
warning = partial(_file_message, 'warning')
error = partial(_file_message, 'error')
