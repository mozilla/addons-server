import cgi
import functools
import urllib
import urlparse
import logging
import itertools
import time

from django.conf import settings
from django.core import paginator
from django.core.mail import send_mail as django_send_mail

import pytz

from . import log


def urlparams(url_, hash=None, **query):
    """
    Add a fragment and/or query paramaters to a URL.

    New query params will be appended to exising parameters, except duplicate
    names, which will be replaced.
    """
    url = urlparse.urlparse(url_)
    fragment = hash if hash is not None else url.fragment

    query_dict = dict(cgi.parse_qsl(str(url.query))) if url.query else {}
    query_dict.update((k, v) for k, v in query.items())

    query_string = urllib.urlencode(dict((k, v) for k, v
            in query_dict.items() if v is not None))
    new = urlparse.ParseResult(url.scheme, url.netloc, url.path, url.params,
                               query_string, fragment)
    return new.geturl()


def isotime(t):
    """Date/Time format according to ISO 8601"""
    if not hasattr(t, 'tzinfo'):
        return
    return _append_tz(t).astimezone(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def epoch(t):
    """Date/Time converted to seconds since epoch"""
    if not hasattr(t, 'tzinfo'):
        return
    return int(time.mktime(_append_tz(t).timetuple()))


def _append_tz(t):
    tz = pytz.timezone(settings.TIME_ZONE)
    return tz.localize(t)


def sorted_groupby(seq, field):
    """Given a sequence, we sort it and group it by a key"""
    key = lambda x: getattr(x, field)
    return itertools.groupby(sorted(seq, key=key), key=key)


def paginate(request, queryset, per_page=20):
    """Get a Paginator, abstracting some common paging actions."""
    p = paginator.Paginator(queryset, per_page)

    # Get the page from the request, make sure it's an int.
    try:
        page = int(request.GET.get('page', 1))
    except ValueError:
        page = 1

    # Get a page of results, or the first page if there's a problem.
    try:
        paginated = p.page(page)
    except (paginator.EmptyPage, paginator.InvalidPage):
        paginated = p.page(1)

    base = request.build_absolute_uri(request.path)

    try:
        qsa = urllib.urlencode(request.GET.items())
    except UnicodeEncodeError:
        qsa = urllib.urlencode([(k, v.encode('utf8')) for k, v
                                in request.GET.items()])
    paginated.url = u'%s?%s' % (base, qsa)
    return paginated


def send_mail(subject, message, from_email=None, recipient_list=None,
              fail_silently=False):
    """
    A wrapper around django.core.mail.send_mail.

    Adds blacklist checking and error logging.
    """
    if not recipient_list:
        return True

    if not from_email:
        from_email = settings.DEFAULT_FROM_EMAIL

    # Prune blacklisted emails.
    white_list = []
    for email in recipient_list:
        if email.lower() in settings.EMAIL_BLACKLIST:
            log.debug('Blacklisted email removed from list: %s' % email)
        else:
            white_list.append(email)
    try:
        if white_list:
            result = django_send_mail(subject, message, from_email, white_list,
                                      fail_silently=False)
        else:
            result = True
    except Exception as e:
        result = False
        log.error('send_mail failed with error: %s' % e)
        if not fail_silently:
            raise

    return result
