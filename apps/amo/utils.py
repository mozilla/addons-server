import functools
import hashlib
import itertools
import operator
import os
import random
import re
import time
import unicodedata
import urllib
import urlparse
import uuid

import django.core.mail
from django import http
from django.conf import settings
from django.contrib import messages
from django.core import paginator
from django.core.cache import cache
from django.core.serializers import json
from django.core.validators import ValidationError, validate_slug
from django.core.mail import send_mail as django_send_mail
from django.template import Context, loader
from django.utils.translation import trans_real
from django.utils.functional import Promise
from django.utils.encoding import smart_str, smart_unicode

from easy_thumbnails import processors
import html5lib
from html5lib.serializer.htmlserializer import HTMLSerializer
import pytz
from PIL import Image, ImageFile, PngImagePlugin

import amo.search
from amo import ADDON_ICON_SIZES
from amo.urlresolvers import reverse
from translations.models import Translation
from users.models import UserNotification
import users.notifications as notifications
from users.utils import UnsubscribeCode

from . import logger_log as log


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
    if not hasattr(key, '__call__'):
        key = operator.attrgetter(key)
    return itertools.groupby(sorted(seq, key=key), key=key)


def paginate(request, queryset, per_page=20, count=None):
    """
    Get a Paginator, abstracting some common paging actions.

    If you pass ``count``, that value will be used instead of calling
    ``.count()`` on the queryset.  This can be good if the queryset would
    produce an expensive count query.
    """
    p = (ESPaginator if isinstance(queryset, amo.search.ES)
         else paginator.Paginator)(queryset, per_page)

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

    paginated.url = u'%s?%s' % (request.path, request.GET.urlencode())
    return paginated


def send_mail(subject, message, from_email=None, recipient_list=None,
              fail_silently=False, use_blacklist=True, perm_setting=None,
              connection=None):
    """
    A wrapper around django.core.mail.send_mail.

    Adds blacklist checking and error logging.
    """
    if not recipient_list:
        return True

    if not from_email:
        from_email = settings.DEFAULT_FROM_EMAIL

    # Check against user notification settings
    if perm_setting:
        if isinstance(perm_setting, str):
            perm_setting = notifications.NOTIFICATIONS_BY_SHORT[perm_setting]
        perms = dict(UserNotification.objects
                                     .filter(user__email__in=recipient_list,
                                             notification_id=perm_setting.id)
                                     .values_list('user__email', 'enabled'))

        d = perm_setting.default_checked
        recipient_list = [e for e in recipient_list
                          if e and perms.setdefault(e, d)]

    # Prune blacklisted emails.
    if use_blacklist:
        white_list = []
        for email in recipient_list:
            if email and email.lower() in settings.EMAIL_BLACKLIST:
                log.debug('Blacklisted email removed from list: %s' % email)
            else:
                white_list.append(email)
    else:
        white_list = recipient_list

    try:
        if white_list:
            if settings.IMPALA_EDIT and perm_setting:
                template = loader.get_template('amo/emails/unsubscribe.ltxt')
                for recipient in white_list:
                    # Add unsubscribe link to footer
                    token, hash = UnsubscribeCode.create(recipient)
                    from amo.helpers import absolutify
                    url = absolutify(reverse('users.unsubscribe',
                            args=[token, hash, perm_setting.short]))
                    context = {'message': message, 'unsubscribe': url,
                               'perm_setting': perm_setting.label,
                               'SITE_URL': settings.SITE_URL}
                    send_message = template.render(Context(context,
                                                           autoescape=False))

                    result = django_send_mail(subject, send_message, from_email,
                                              [recipient], fail_silently=False,
                                              connection=connection)
            else:
                result = django_send_mail(subject, message, from_email,
                                          white_list, fail_silently=False,
                                          connection=connection)
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
        from versions.models import ApplicationsVersions

        unicodable = (Translation, Promise)

        if isinstance(obj, unicodable):
            return unicode(obj)
        if isinstance(obj, ApplicationsVersions):
            return {unicode(obj.application): {'min': unicode(obj.min),
                                               'max': unicode(obj.max)}}

        return super(JSONEncoder, self).default(obj)


def chunked(seq, n):
    """
    Yield successive n-sized chunks from seq.

    >>> for group in chunked(range(8), 3):
    ...     print group
    [0, 1, 2]
    [3, 4, 5]
    [6, 7]
    """
    seq = iter(seq)
    while 1:
        rv = list(itertools.islice(seq, 0, n))
        if not rv:
            break
        yield rv


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
SLUG_OK = '-_~'


def slugify(s, ok=SLUG_OK, lower=True, spaces=False):
    # L and N signify letter/number.
    # http://www.unicode.org/reports/tr44/tr44-4.html#GC_Values_Table
    rv = []
    for c in smart_unicode(s):
        cat = unicodedata.category(c)[0]
        if cat in 'LN' or c in ok:
            rv.append(c)
        if cat == 'Z':  # space
            rv.append(' ')
    new = ''.join(rv).strip()
    if not spaces:
        new = re.sub('[-\s]+', '-', new)
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
    Docs: http://bit.ly/dEhegk
    """
    for message in messages.get_messages(request):
        pass


def clean_nl(string):
    """
    This will clean up newlines so that nl2br can properly be called on the
    cleaned text.
    """

    html_blocks = ['blockquote', 'ol', 'li', 'ul']

    if not string:
        return string

    def parse_html(tree):
        prev_tag = ''
        for i, node in enumerate(tree.childNodes):
            if node.type == 4:  # Text node
                value = node.value

                # Strip new lines directly inside block level elements.
                if node.parent.name in html_blocks:
                    value = value.strip('\n')

                # Remove the first new line after a block level element.
                if (prev_tag in html_blocks and value.startswith('\n')):
                    value = value[1:]

                tree.childNodes[i].value = value
            else:
                tree.insertBefore(parse_html(node), node)
                tree.removeChild(node)

            prev_tag = node.name
        return tree

    parse = parse_html(html5lib.parseFragment(string))

    walker = html5lib.treewalkers.getTreeWalker('simpletree')
    stream = walker(parse)
    serializer = HTMLSerializer(quote_attr_values=True,
                                omit_optional_tags=False)
    return serializer.render(stream)


# From: http://bit.ly/eTqloE
# Without this, you'll notice a slight grey line on the edges of
# the adblock plus icon.
def patched_chunk_tRNS(self, pos, len):
    i16 = PngImagePlugin.i16
    s = ImageFile._safe_read(self.fp, len)
    if self.im_mode == "P":
        self.im_info["transparency"] = map(ord, s)
    elif self.im_mode == "L":
        self.im_info["transparency"] = i16(s)
    elif self.im_mode == "RGB":
        self.im_info["transparency"] = i16(s), i16(s[2:]), i16(s[4:])
    return s
PngImagePlugin.PngStream.chunk_tRNS = patched_chunk_tRNS


def patched_load(self):
    if self.im and self.palette and self.palette.dirty:
        apply(self.im.putpalette, self.palette.getdata())
        self.palette.dirty = 0
        self.palette.rawmode = None
        try:
            trans = self.info["transparency"]
        except KeyError:
            self.palette.mode = "RGB"
        else:
            try:
                for i, a in enumerate(trans):
                    self.im.putpalettealpha(i, a)
            except TypeError:
                self.im.putpalettealpha(trans, 0)
            self.palette.mode = "RGBA"
    if self.im:
        return self.im.pixel_access(self.readonly)
Image.Image.load = patched_load


def resize_image(src, dst, size, remove_src=True):
    """Resizes and image from src, to dst. Returns width and height."""
    if src == dst:
        raise Exception("src and dst can't be the same: %s" % src)

    dirname = os.path.dirname(dst)
    if not os.path.exists(dirname):
        os.makedirs(dirname)

    im = Image.open(src)
    im = im.convert('RGBA')
    im = processors.scale_and_crop(im, size)
    im.save(dst, 'png')

    if remove_src:
        os.remove(src)

    return im.size


def remove_icons(destination):
    for size in ADDON_ICON_SIZES:
        filename = '%s-%s.png' % (destination, size)
        if os.path.exists(filename):
            os.remove(filename)


class ImageCheck(object):

    def __init__(self, image):
        self._img = image

    def is_image(self):
        try:
            self._img.seek(0)
            self.img = Image.open(self._img)
            return True
        except IOError:
            return False

    def is_animated(self, size=100000):
        if not self.is_image():
            return False

        img = self.img
        if img.format == 'PNG':
            self._img.seek(0)
            data = ''
            while True:
                chunk = self._img.read(size)
                if not chunk:
                    break
                data += chunk
                acTL, IDAT = data.find('acTL'), data.find('IDAT')
                if acTL > -1 and acTL < IDAT:
                    return True
            return False
        elif img.format == 'GIF':
            # See the PIL docs for how this works:
            # http://www.pythonware.com/library/pil/handbook/introduction.htm
            try:
                img.seek(1)
            except EOFError:
                return False
            return True


class MenuItem():
    """Refinement item with nestable children for use in menus."""
    url, text, selected, children = ('', '', False, [])


def to_language(locale):
    """Like django's to_language, but en_US comes out as en-US."""
    # A locale looks like en_US or fr.
    if '_' in locale:
        return to_language(trans_real.to_language(locale))
    # Django returns en-us but we want to see en-US.
    elif '-' in locale:
        lang, region = locale.split('-')
        return '%s-%s' % (lang, region.upper())
    else:
        return trans_real.to_language(locale)


class HttpResponseSendFile(http.HttpResponse):

    def __init__(self, request, path, content=None, status=None,
                 content_type='application/octet-stream'):
        self.request = request
        self.path = path
        super(HttpResponseSendFile, self).__init__('', status=status,
                                                   content_type=content_type)
        if settings.XSENDFILE:
            self['X-SENDFILE'] = path

    def __iter__(self):
        if settings.XSENDFILE:
            return iter([])

        chunk = 4096
        fp = open(self.path, 'rb')
        if 'wsgi.file_wrapper' in self.request.META:
            return self.request.META['wsgi.file_wrapper'](fp, chunk)
        else:
            self['Content-Length'] = os.path.getsize(self.path)

            def wrapper():
                while 1:
                    data = fp.read(chunk)
                    if not data:
                        break
                    yield data
            return wrapper()


def memoize(prefix, time=60):
    """
    A simple memoize that caches into memcache, using a simple
    key based on stringing args and kwargs. Keep args simple.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = hashlib.md5()
            for arg in itertools.chain(args, sorted(kwargs.items())):
                key.update(str(arg))
            key = '%s:memoize:%s:%s' % (settings.CACHE_PREFIX,
                                        prefix, key.hexdigest())
            data = cache.get(key)
            if data is not None:
                return data
            data = func(*args, **kwargs)
            cache.set(key, data, time)
            return data
        return wrapper
    return decorator


class Message:
    """
    A simple message class for when you don't have a session, but wish
    to pass a message through memcache. For example, memcache up to the
    user.
    """
    def __init__(self, key):
        self.key = '%s:message:%s' % (settings.CACHE_PREFIX, key)

    def delete(self):
        cache.delete(self.key)

    def save(self, message, time=60 * 5):
        cache.set(self.key, message, time)

    def get(self, delete=False):
        res = cache.get(self.key)
        if delete:
            cache.delete(self.key)
        return res


class Token:
    """
    A simple token, useful for security. It can have an expiry
    or be grabbed and deleted. It will check that the key is valid and
    and well formed before checking. If you don't have a key, it will
    generate a randomish one for you.
    """
    _well_formed = re.compile('^[a-z0-9-]+$')

    def __init__(self, token=None, data=True):
        if token is None:
            token = str(uuid.uuid4())
        self.token = token
        self.data = data

    def cache_key(self):
        assert self.token, 'No token value set.'
        return '%s:token:%s' % (settings.CACHE_PREFIX, self.token)

    def save(self, time=60):
        cache.set(self.cache_key(), self.data, time)

    def well_formed(self):
        return self._well_formed.match(self.token)

    @classmethod
    def valid(cls, key, data=True):
        """Checks that the token is valid."""
        token = cls(key)
        if not token.well_formed():
            return False
        result = cache.get(token.cache_key())
        if result is not None:
            return result == data
        return False

    @classmethod
    def pop(cls, key, data=True):
        """Checks that the token is valid and deletes it."""
        token = cls(key)
        if not token.well_formed():
            return False
        result = cache.get(token.cache_key())
        if result is not None:
            if result == data:
                cache.delete(token.cache_key())
                return True
        return False


def get_email_backend():
    """Get a connection to an email backend.

    If settings.SEND_REAL_EMAIL is False, a debugging backend is returned.
    """
    backend = None if settings.SEND_REAL_EMAIL else 'amo.mail.FakeEmailBackend'
    return django.core.mail.get_connection(backend)


class ESPaginator(paginator.Paginator):
    """A better paginator for search results."""
    # The normal Paginator does a .count() query and then a slice. Since ES
    # results contain the total number of results, we can take an optimistic
    # slice and then adjust the count.
    def page(self, number):
        # Fake num_pages so it looks like we can have results.
        self._num_pages = float('inf')
        number = self.validate_number(number)
        self._num_pages = None

        bottom = (number - 1) * self.per_page
        top = bottom + self.per_page
        page = paginator.Page(self.object_list[bottom:top], number, self)

        # Force the search to evaluate and then attach the count.
        list(page.object_list)
        self._count = page.object_list.count()
        return page
