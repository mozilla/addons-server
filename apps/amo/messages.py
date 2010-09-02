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

def _make_message(title=None, message=None):
    c = {'title': title, 'message': message}
    t = env.get_template('message_content.html').render(**c)
    return jinja2.Markup(t)

def debug(request, title, msg=None, extra_tags='', fail_silently=False):
    django_messages.debug(request, _make_message(title, msg),
                          extra_tags, fail_silently)

def info(request, title, msg=None, extra_tags='', fail_silently=False):
    django_messages.info(request, _make_message(title, msg),
                          extra_tags, fail_silently)

def success(request, title, msg=None, extra_tags='', fail_silently=False):
    django_messages.success(request, _make_message(title, msg),
                          extra_tags, fail_silently)

def warning(request, title, msg=None, extra_tags='', fail_silently=False):
    django_messages.warning(request, _make_message(title, msg),
                          extra_tags, fail_silently)

def error(request, title, msg=None, extra_tags='', fail_silently=False):
    django_messages.error(request, _make_message(title, msg),
                          extra_tags, fail_silently)
