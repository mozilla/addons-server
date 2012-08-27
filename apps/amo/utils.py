import codecs
import collections
import contextlib
import datetime
import functools
import hashlib
import itertools
import operator
import os
import random
import re
import shutil
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
from django.core.files.storage import (FileSystemStorage,
                                       default_storage as storage)
from django.core.serializers import json
from django.core.validators import ValidationError, validate_slug
from django.core.mail import EmailMessage
from django.forms.fields import Field
from django.http import HttpRequest
from django.template import Context, loader
from django.utils import translation
from django.utils.functional import Promise
from django.utils.encoding import smart_str, smart_unicode

from babel import Locale
import bleach
from cef import log_cef as _log_cef
from easy_thumbnails import processors
import elasticutils.contrib.django as elasticutils
import html5lib
from html5lib.serializer.htmlserializer import HTMLSerializer
from jingo import env
import jinja2
import pyes.exceptions as pyes
import pytz
from PIL import Image, ImageFile, PngImagePlugin

import amo.search
from amo import ADDON_ICON_SIZES
from amo.urlresolvers import get_outgoing_url, reverse
from translations.models import Translation
from users.models import UserNotification
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
              manage_url=None, headers=None, cc=None, real_email=False):
    """
    A wrapper around django.core.mail.EmailMessage.

    Adds blacklist checking and error logging.
    """
    from amo.helpers import absolutify
    import users.notifications as notifications
    if not recipient_list:
        return True

    connection = get_email_backend(real_email)

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
            if perm_setting:
                template = loader.get_template('amo/emails/unsubscribe.ltxt')
                if not manage_url:
                    manage_url = urlparams(absolutify(
                        reverse('users.edit', add_prefix=False)),
                        'acct-notify')
                for recipient in white_list:
                    # Add unsubscribe link to footer.
                    token, hash = UnsubscribeCode.create(recipient)
                    unsubscribe_url = absolutify(reverse('users.unsubscribe',
                            args=[token, hash, perm_setting.short],
                            add_prefix=False))

                    context = {'message': message,
                               'manage_url': manage_url,
                               'unsubscribe_url': unsubscribe_url,
                               'perm_setting': perm_setting.label,
                               'SITE_URL': settings.SITE_URL,
                               'mandatory': perm_setting.mandatory}
                    # Render this template in the default locale until
                    # bug 635840 is fixed.
                    with no_translation():
                        send_message = template.render(
                            Context(context, autoescape=False))

                        result = EmailMessage(subject, send_message,
                                              from_email, [recipient],
                                              cc=cc and [cc] or None,
                                              connection=connection,
                                              headers=headers or {},
                                              ).send(fail_silently=False)
            else:
                result = EmailMessage(subject, message, from_email,
                                      white_list, cc=cc and [cc] or None,
                                      connection=connection,
                                      headers=headers or {},
                                      ).send(fail_silently=False)
        else:
            result = True
    except Exception as e:
        result = False
        log.error('send_mail failed with error: %s' % e)
        if not fail_silently:
            raise

    return result


def send_mail_jinja(subject, template, context, *args, **kwargs):
    """Sends mail using a Jinja template with autoescaping turned off.

    Jinja is especially useful for sending email since it has whitespace
    control.
    """
    # Get a jinja environment so we can override autoescaping for text emails.
    autoescape_orig = env.autoescape
    env.autoescape = False
    template = env.get_template(template)
    send_mail(subject, template.render(**context), *args, **kwargs)
    env.autoescape = autoescape_orig


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


def slugify(s, ok=SLUG_OK, lower=True, spaces=False, delimiter='-'):
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
        new = re.sub('[-\s]+', delimiter, new)
    return new.lower() if lower else new


def slug_validator(s, ok=SLUG_OK, lower=True, spaces=False, delimiter='-',
                   message=validate_slug.message, code=validate_slug.code):
    """
    Raise an error if the string has any punctuation characters.

    Regexes don't work here because they won't check alnums in the right
    locale.
    """
    if not (s and slugify(s, ok, lower, spaces, delimiter) == s):
        raise ValidationError(message, code=code)


def raise_required():
    raise ValidationError(Field.default_error_messages['required'])


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


def resize_image(src, dst, size=None, remove_src=True,
                 locally=False):
    """Resizes and image from src, to dst. Returns width and height.

    When locally is True, src and dst are assumed to reside
    on the local disk (not in the default storage). When dealing
    with local files it's up to you to ensure that all directories
    exist leading up to the dst filename.
    """
    if src == dst:
        raise Exception("src and dst can't be the same: %s" % src)

    open_ = open if locally else storage.open
    delete = os.unlink if locally else storage.delete

    with open_(src, 'rb') as fp:
        im = Image.open(fp)
        im = im.convert('RGBA')
        if size:
            im = processors.scale_and_crop(im, size)
    with open_(dst, 'wb') as fp:
        im.save(fp, 'png')

    if remove_src:
        delete(src)

    return im.size


def remove_icons(destination):
    for size in ADDON_ICON_SIZES:
        filename = '%s-%s.png' % (destination, size)
        if storage.exists(filename):
            storage.delete(filename)


class ImageCheck(object):

    def __init__(self, image):
        self._img = image

    def is_image(self):
        try:
            self._img.seek(0)
            self.img = Image.open(self._img)
            # PIL doesn't tell us what errors it will raise at this point,
            # just "suitable ones", so let's catch them all.
            self.img.verify()
            return True
        except:
            log.error('Error decoding image', exc_info=True)
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
        return to_language(translation.trans_real.to_language(locale))
    # Django returns en-us but we want to see en-US.
    elif '-' in locale:
        lang, region = locale.split('-')
        return '%s-%s' % (lang, region.upper())
    else:
        return translation.trans_real.to_language(locale)


def get_locale_from_lang(lang):
    """Pass in a language (u'en-US') get back a Locale object courtesy of
    Babel.  Use this to figure out currencies, bidi, names, etc."""
    # Special fake language can just act like English for formatting and such
    if lang == 'dbg':
        lang = 'en'
    return Locale(translation.to_locale(lang))


class HttpResponseSendFile(http.HttpResponse):

    def __init__(self, request, path, content=None, status=None,
                 content_type='application/octet-stream'):
        self.request = request
        self.path = path
        super(HttpResponseSendFile, self).__init__('', status=status,
                                                   content_type=content_type)
        if settings.XSENDFILE:
            self[settings.XSENDFILE_HEADER] = path

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


def memoize_key(prefix, *args, **kwargs):
    """Returns the memoize key."""
    key = hashlib.md5()
    for arg in itertools.chain(args, sorted(kwargs.items())):
        key.update(str(arg))
    return '%s:memoize:%s:%s' % (settings.CACHE_PREFIX,
                                 prefix, key.hexdigest())


def memoize_get(prefix, *args, **kwargs):
    """Returns the content of the cache given the key."""
    return cache.get(memoize_key(prefix, *args, **kwargs))


def memoize(prefix, time=60):
    """
    A simple memoize that caches into memcache, using a simple
    key based on stringing args and kwargs. Keep args simple.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            key = memoize_key(prefix, *args, **kwargs)
            data = cache.get(key)
            if data is not None:
                return data
            data = func(*args, **kwargs)
            cache.set(key, data, time)
            return data
        return wrapper
    return decorator


def cache_ns_key(namespace, increment=False):
    """
    Returns a key with namespace value appended. If increment is True, the
    namespace will be incremented effectively invalidating the cache.

    Memcache doesn't have namespaces, but we can simulate them by storing a
    "%(key)s_namespace" value. Invalidating the namespace simply requires
    editing that key. Your application will no longer request the old keys,
    and they will eventually fall off the end of the LRU and be reclaimed.
    """
    ns_key = 'ns:%s' % namespace
    if increment:
        try:
            ns_val = cache.incr(ns_key)
        except ValueError:
            log.info('Cache increment failed for key: %s. Resetting.' % ns_key)
            ns_val = epoch(datetime.datetime.now())
            cache.set(ns_key, ns_val, 0)
    else:
        ns_val = cache.get(ns_key)
        if ns_val == None:
            ns_val = epoch(datetime.datetime.now())
            cache.set(ns_key, ns_val, 0)
    return '%s:%s' % (ns_val, ns_key)


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


@contextlib.contextmanager
def guard(name):
    """
    A memcache based guard around a function such as extracting something on
    to the file system, that you'd like to prevent from having race conditions.
    Saves us doing lock files or similar.
    """
    msg = Message(name)
    if msg.get():
        # This is currently in progress.
        yield True
    else:
        # This is not in progress, save a flag and delete on exit.
        msg.save(True)
        try:
            yield False
        finally:
            msg.delete()


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


def get_email_backend(real_email=False):
    """Get a connection to an email backend.

    If settings.SEND_REAL_EMAIL is False, a debugging backend is returned.
    """
    if real_email or settings.SEND_REAL_EMAIL:
        backend = None
    else:
        backend = 'amo.mail.FakeEmailBackend'
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


def smart_path(string):
    """Returns a string you can pass to path.path safely."""
    if os.path.supports_unicode_filenames:
        return smart_unicode(string)
    return smart_str(string)


def log_cef(name, severity, env, *args, **kwargs):
    """Simply wraps the cef_log function so we don't need to pass in the config
    dictionary every time.  See bug 707060.  env can be either a request
    object or just the request.META dictionary"""

    c = {'cef.product': getattr(settings, 'CEF_PRODUCT', 'AMO'),
         'cef.vendor': getattr(settings, 'CEF_VENDOR', 'Mozilla'),
         'cef.version': getattr(settings, 'CEF_VERSION', '0'),
         'cef.device_version': getattr(settings, 'CEF_DEVICE_VERSION', '0'),
         'cef.file': getattr(settings, 'CEF_FILE', 'syslog'), }

    # The CEF library looks for some things in the env object like
    # REQUEST_METHOD and any REMOTE_ADDR stuff.  Django not only doesn't send
    # half the stuff you'd expect, but it specifically doesn't implement
    # readline on its FakePayload object so these things fail.  I have no idea
    # if that's outdated code in Django or not, but andym made this
    # <strike>awesome</strike> less crappy so the tests will actually pass.
    # In theory, the last part of this if() will never be hit except in the
    # test runner.  Good luck with that.
    if isinstance(env, HttpRequest):
        r = env.META.copy()
    elif isinstance(env, dict):
        r = env
    else:
        r = {}

    return _log_cef(name, severity, r, *args, config=c, **kwargs)


@contextlib.contextmanager
def no_translation():
    lang = translation.trans_real.get_language()
    translation.trans_real.deactivate()
    yield
    translation.trans_real.activate(lang)


def escape_all(v):
    """Escape html in JSON value, including nested items."""
    if isinstance(v, basestring):
        v = jinja2.escape(smart_unicode(v))
        v = bleach.linkify(v, nofollow=True, filter_url=get_outgoing_url)
        return v
    elif isinstance(v, list):
        for i, lv in enumerate(v):
            v[i] = escape_all(lv)
    elif isinstance(v, dict):
        for k, lv in v.iteritems():
            v[k] = escape_all(lv)
    elif isinstance(v, Translation):
        v = jinja2.escape(smart_unicode(v.localized_string))
    return v


class LocalFileStorage(FileSystemStorage):
    """Local storage to an unregulated absolute file path.

    Unregulated means that, unlike the default file storage, you can write to
    any path on the system if you have access.

    Unlike Django's default FileSystemStorage, this class behaves more like a
    "cloud" storage system. Specifically, you never have to write defensive
    code that prepares for leading directory paths to exist.
    """

    def __init__(self, base_url=None):
        super(LocalFileStorage, self).__init__(location='/', base_url=base_url)

    def delete(self, name):
        """Delete a file or empty directory path.

        Unlike the default file system storage this will also delete an empty
        directory path. This behavior is more in line with other storage
        systems like S3.
        """
        full_path = self.path(name)
        if os.path.isdir(full_path):
            os.rmdir(full_path)
        else:
            return super(LocalFileStorage, self).delete(name)

    def _open(self, name, mode='rb'):
        if mode.startswith('w'):
            parent = os.path.dirname(self.path(name))
            if not os.path.exists(parent):
                os.makedirs(parent)
        return super(LocalFileStorage, self)._open(name, mode=mode)

    def path(self, name):
        """Actual file system path to name without any safety checks."""
        return os.path.normpath(os.path.join(self.location,
                                             self._smart_path(name)))

    def _smart_path(self, string):
        if os.path.supports_unicode_filenames:
            return smart_unicode(string)
        return smart_str(string)


def strip_bom(data):
    """
    Strip the BOM (byte order mark) from byte string `data`.

    Returns a new byte string.
    """
    for bom in (codecs.BOM_UTF32_BE,
                codecs.BOM_UTF32_LE,
                codecs.BOM_UTF16_BE,
                codecs.BOM_UTF16_LE,
                codecs.BOM_UTF8):
        if data.startswith(bom):
            data = data[len(bom):]
            break
    return data


def attach_trans_dict(model, addons):
    """Put all translations into a translations dict."""
    fields = model._meta.translated_fields
    ids = {}
    for addon in addons:
        addon.translations = collections.defaultdict(list)
        ids.update((getattr(addon, field.attname, None), addon)
                   for field in fields)
    ids.pop(None, None)
    qs = (Translation.objects
          .filter(id__in=ids, localized_string__isnull=False)
          .values_list('id', 'locale', 'localized_string'))
    for id, translations in sorted_groupby(qs, lambda x: x[0]):
        ids[id].translations[id] = [(locale, string)
                                    for id, locale, string in translations]


def rm_local_tmp_dir(path):
    """Remove a local temp directory.

    This is just a wrapper around shutil.rmtree(). Use it to indicate you are
    certain that your executing code is operating on a local temp dir, not a
    directory managed by the Django Storage API.
    """
    return shutil.rmtree(path)


def rm_local_tmp_file(path):
    """Remove a local temp file.

    This is just a wrapper around os.unlink(). Use it to indicate you are
    certain that your executing code is operating on a local temp file, not a
    path managed by the Django Storage API.
    """
    return os.unlink(path)


def create_es_index_if_missing(index, config=None):
    es = elasticutils.get_es()
    if settings.IN_TEST_SUITE:
        if not config:
            config = {}
        # Be nice to ES running on ci.mozilla.org
        config.update({'number_of_shards': 3,
                       'number_of_replicas': 0})
    try:
        es.create_index_if_missing(index, settings=config)
    except pyes.ElasticSearchException, exc:
        log.info('ES error creating index: %s' % exc)
