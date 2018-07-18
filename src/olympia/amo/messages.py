from functools import partial

from django.contrib import messages as django_messages
from django.template import loader
from django.utils import safestring

import jinja2

from rest_framework.request import Request


"""
This file was created because AMO wants to have multi-line messages including a
title and some content.  Django's messages framework only takes a single
string.
Importing this file should behave exactly like Django's messages framework
except it will take a 3rd argument as message content (the second is the
message title).
"""


class DoubleSafe(safestring.SafeData, jinja2.Markup):
    """Double safe all the way: marks safe for django and jinja2.

    Even though we're using jinja2 for most of the template rendering, we may
    have places where it's Django deciding whether the data is safe or not. An
    example is the messaging framework. If we add a new message that is marked
    safe for jinja2 (using a Markup object), it's not persisted that way by
    Django, and we thus loose the "safeness" of the message.

    This serves to give us the best of both worlds.

    """


def _make_message(
    title=None, message=None, title_safe=False, message_safe=False
):
    c = {
        'title': title,
        'message': message,
        'title_safe': title_safe,
        'message_safe': message_safe,
    }
    t = loader.get_template('message_content.html').render(c)
    return DoubleSafe(t)


def _is_dupe(msg, request):
    """Returns whether a particular message is already cued for display."""
    storage = django_messages.get_messages(request)

    # If there are no messages stored, Django doesn't give us a proper storage
    # object, so just bail early.
    if not storage:
        return False

    try:
        smsg = unicode(msg)
        is_dupe = False
        for message in storage:
            if unicode(message) == smsg:
                # We can't return from here because we need to tell Django not
                # to consume the messages.
                is_dupe = True
                break
    except (UnicodeDecodeError, UnicodeEncodeError):
        return False

    storage.used = False
    return is_dupe


def _file_message(
    type_,
    request,
    title,
    message=None,
    extra_tags='',
    fail_silently=False,
    title_safe=False,
    message_safe=False,
):
    msg = _make_message(title, message, title_safe, message_safe)
    # Don't save duplicates.
    if _is_dupe(msg, request):
        return

    if isinstance(request, Request):
        # Support for passing of django-rest-framework wrapped request objects
        request = request._request

    getattr(django_messages, type_)(request, msg, extra_tags, fail_silently)


debug = partial(_file_message, 'debug')
info = partial(_file_message, 'info')
success = partial(_file_message, 'success')
warning = partial(_file_message, 'warning')
error = partial(_file_message, 'error')
