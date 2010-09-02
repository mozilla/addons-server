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

def debug(request, title, message=None, extra_tags='', fail_silently=False,
          title_safe=False, message_safe=False):
    msg = _make_message(title, message, title_safe, message_safe)
    django_messages.debug(request, msg, extra_tags, fail_silently)

def info(request, title, message=None, extra_tags='', fail_silently=False,
         title_safe=False, message_safe=False):
    msg = _make_message(title, message, title_safe, message_safe)
    django_messages.info(request, msg, extra_tags, fail_silently)

def success(request, title, message=None, extra_tags='', fail_silently=False,
            title_safe=False, message_safe=False):
    msg = _make_message(title, message, title_safe, message_safe)
    django_messages.success(request, msg, extra_tags, fail_silently)

def warning(request, title, message=None, extra_tags='', fail_silently=False,
            title_safe=False, message_safe=False):
    msg = _make_message(title, message, title_safe, message_safe)
    django_messages.warning(request, msg, extra_tags, fail_silently)

def error(request, title, message=None, extra_tags='', fail_silently=False,
          title_safe=False, message_safe=False):
    msg = _make_message(title, message, title_safe, message_safe)
    django_messages.error(request, msg, extra_tags, fail_silently)
