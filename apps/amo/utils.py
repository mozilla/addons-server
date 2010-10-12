import itertools
import operator
import os
import random
import re
import time
import unicodedata
import urllib
import urlparse

from django.conf import settings
from django.contrib import messages
from django.core import paginator
from django.core.serializers import json
from django.core.validators import ValidationError, validate_slug
from django.core.mail import send_mail as django_send_mail
from django.utils.functional import Promise
from django.utils.encoding import smart_str, smart_unicode

from easy_thumbnails import processors
import pytz
from PIL import Image

from . import log
from translations.models import Translation
from versions.models import ApplicationsVersions


def urlparams(url_, hash=None, **query):
    """
    Add a fragment and/or query paramaters to a URL.

    New query params will be appended to exising parameters, except duplicate
    names, which will be replaced.
    """
    url = urlparse.urlparse(url_)
    fragment = hash if hash is not None else url.fragment

    # Use dict(parse_qsl) so we don't get lists of values.
    q = url.query
    query_dict = dict(urlparse.parse_qsl(smart_str(q))) if q else {}
    query_dict.update((k, v) for k, v in query.items())

    query_string = urlencode([(k, v) for k, v in query_dict.items()
                             if v is not None])
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


def sorted_groupby(seq, key):
    """
    Given a sequence, we sort it and group it by a key.

    key should be a string (used with attrgetter) or a function.
    """
    if isinstance(key, basestring):
        key = operator.attrgetter(key)
    return itertools.groupby(sorted(seq, key=key), key=key)


def paginate(request, queryset, per_page=20, count=None):
    """
    Get a Paginator, abstracting some common paging actions.

    If you pass ``count``, that value will be used instead of calling
    ``.count()`` on the queryset.  This can be good if the queryset would
    produce an expensive count query.
    """
    p = paginator.Paginator(queryset, per_page)

    if count is not None:
        p._count = count

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

    paginated.url = u'%s?%s' % (base, request.GET.urlencode())
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


class JSONEncoder(json.DjangoJSONEncoder):

    def default(self, obj):

        unicodable = (Translation, Promise)

        if isinstance(obj, unicodable):
            return unicode(obj)
        if isinstance(obj, ApplicationsVersions):
            return {unicode(obj.application): {'min': unicode(obj.min),
                                               'max': unicode(obj.max)}}

        return super(JSONEncoder, self).default(obj)


# By Ned Batchelder.
def chunked(seq, n):
    """
    Yield successive n-sized chunks from seq.

    >>> for group in chunked(range(8), 3):
    ...     print group
    [0, 1, 2]
    [3, 4, 5]
    [6, 7]
    """
    for i in xrange(0, len(seq), n):
        yield seq[i:i + n]


def urlencode(items):
    """A Unicode-safe URLencoder."""
    try:
        return urllib.urlencode(items)
    except UnicodeEncodeError:
        return urllib.urlencode([(k, smart_str(v)) for k, v in items])


def randslice(qs, limit, exclude=None):
    """
    Get a random slice of items from ``qs`` of size ``limit``.

    There will be two queries.  One to find out how many elements are in ``qs``
    and another to get a slice.  The count is so we don't go out of bounds.
    If exclude is given, we make sure that pk doesn't show up in the slice.

    This replaces qs.order_by('?')[:limit].
    """
    cnt = qs.count()
    # Get one extra in case we find the element that should be excluded.
    if exclude is not None:
        limit += 1
    rand = 0 if limit > cnt else random.randint(0, cnt - limit)
    slice_ = list(qs[rand:rand + limit])
    if exclude is not None:
        slice_ = [o for o in slice_ if o.pk != exclude][:limit - 1]
    return slice_


# Extra characters outside of alphanumerics that we'll allow.
SLUG_OK = '-_'


def slugify(s, ok=SLUG_OK, lower=True):
    # L and N signify letter/number.
    # http://www.unicode.org/reports/tr44/tr44-4.html#GC_Values_Table
    rv = []
    for c in smart_unicode(s):
        cat = unicodedata.category(c)[0]
        if cat in 'LN' or c in ok:
            rv.append(c)
        if cat == 'Z':  # space
            rv.append(' ')
    new = re.sub('[-\s]+', '-', ''.join(rv).strip())
    return new.lower() if lower else new


def slug_validator(s, ok=SLUG_OK, lower=True):
    """
    Raise an error if the string has any punctuation characters.

    Regexes don't work here because they won't check alnums in the right
    locale.
    """
    if not (s and slugify(s, ok, lower) == s):
        raise ValidationError(validate_slug.message,
                              code=validate_slug.code)


def clear_messages(request):
    """
    Clear any messages out of the messages framework for the authenticated
    user.
    Docs:
    http://docs.djangoproject.com/en/dev/ref/contrib/messages/#expiration-of-messages
    """
    for message in messages.get_messages(request):
        pass


def resize_image(src, dst, size):
    """Resizes and image from src, to dst."""
    if src == dst:
        raise Exception("src and dst can't be the same: %s" % src)
    im = Image.open(src)
    im = processors.scale_and_crop(im, size)
    im.save(dst)
    os.remove(src)
