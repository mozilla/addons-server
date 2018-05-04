import calendar
import collections
import contextlib
import datetime
import errno
import functools
import itertools
import json
import operator
import os
import random
import re
import shutil
import time
import unicodedata
import urllib
import urlparse
import string
import subprocess
import scandir

import django.core.mail

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import (
    FileSystemStorage, default_storage as storage)
from django.core.paginator import (
    EmptyPage, InvalidPage, Paginator as DjangoPaginator)
from django.core.validators import ValidationError, validate_slug
from django.forms.fields import Field
from django.http import HttpResponse
from django.template import engines, loader
from django.utils import translation
from django.utils.encoding import force_bytes, force_text
from django.utils.http import _urlparse as django_urlparse

import bleach
import html5lib
import jinja2
import pytz
import basket

from babel import Locale
from django_statsd.clients import statsd
from easy_thumbnails import processors
from html5lib.serializer.htmlserializer import HTMLSerializer
from PIL import Image
from rest_framework.utils.encoders import JSONEncoder
from validator import unicodehelper

from olympia.amo import ADDON_ICON_SIZES, search
from olympia.amo.pagination import ESPaginator
from olympia.amo.urlresolvers import linkify_with_outgoing, reverse
from olympia.translations.models import Translation
from olympia.users.models import UserNotification
from olympia.users.utils import UnsubscribeCode

from . import logger_log as log


def render(request, template, ctx=None, status=None, content_type=None):
    rendered = loader.render_to_string(template, ctx, request=request)
    return HttpResponse(rendered, status=status, content_type=content_type)


def from_string(string):
    return engines['jinja2'].from_string(string)


def days_ago(n):
    return datetime.datetime.now() - datetime.timedelta(days=n)


def urlparams(url_, hash=None, **query):
    """
    Add a fragment and/or query parameters to a URL.

    New query params will be appended to existing parameters, except duplicate
    names, which will be replaced.
    """
    url = django_urlparse(force_text(url_))

    fragment = hash if hash is not None else url.fragment

    # Use dict(parse_qsl) so we don't get lists of values.
    q = url.query
    query_dict = dict(urlparse.parse_qsl(force_bytes(q))) if q else {}
    query_dict.update(
        (k, force_bytes(v) if v is not None else v) for k, v in query.items())
    query_string = urlencode(
        [(k, urllib.unquote(v)) for k, v in query_dict.items()
         if v is not None])
    new = urlparse.ParseResult(url.scheme, url.netloc, url.path, url.params,
                               query_string, fragment)
    return new.geturl()


def partial(func, *args, **kw):
    """A thin wrapper around functools.partial which updates the wrapper
    as would a decorator."""
    return functools.update_wrapper(functools.partial(func, *args, **kw), func)


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
    if isinstance(queryset, search.ES):
        paginator = ESPaginator(
            queryset, per_page, use_elasticsearch_dsl=False)
    else:
        paginator = DjangoPaginator(queryset, per_page)

    if count is not None:
        paginator._count = count

    # Get the page from the request, make sure it's an int.
    try:
        page = int(request.GET.get('page', 1))
    except ValueError:
        page = 1

    # Get a page of results, or the first page if there's a problem.
    try:
        paginated = paginator.page(page)
    except (EmptyPage, InvalidPage):
        paginated = paginator.page(1)

    paginated.url = u'%s?%s' % (request.path, request.GET.urlencode())
    return paginated


def decode_json(json_string):
    """Helper that transparently handles BOM encoding."""
    return json.loads(unicodehelper.decode(json_string))


def send_mail(subject, message, from_email=None, recipient_list=None,
              use_deny_list=True, perm_setting=None, manage_url=None,
              headers=None, cc=None, real_email=False, html_message=None,
              attachments=None, max_retries=3, reply_to=None):
    """
    A wrapper around django.core.mail.EmailMessage.

    Adds deny checking and error logging.
    """
    from olympia.amo.templatetags.jinja_helpers import absolutify
    from olympia.amo.tasks import send_email
    from olympia.users import notifications

    if not recipient_list:
        return True

    if isinstance(recipient_list, basestring):
        raise ValueError('recipient_list should be a list, not a string.')

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

    # Prune denied emails.
    if use_deny_list:
        white_list = []
        for email in recipient_list:
            if email and email.lower() in settings.EMAIL_DENY_LIST:
                log.debug('Blacklisted email removed from list: %s' % email)
            else:
                white_list.append(email)
    else:
        white_list = recipient_list

    if not from_email:
        from_email = settings.DEFAULT_FROM_EMAIL

    if cc:
        # If not basestring, assume it is already a list.
        if isinstance(cc, basestring):
            cc = [cc]

    if not headers:
        headers = {}

    # Avoid auto-replies per rfc 3834 and the Microsoft variant
    headers['X-Auto-Response-Suppress'] = 'RN, NRN, OOF, AutoReply'
    headers['Auto-Submitted'] = 'auto-generated'

    def send(recipient, message, **options):
        kwargs = {
            'attachments': attachments,
            'cc': cc,
            'from_email': from_email,
            'headers': headers,
            'html_message': html_message,
            'max_retries': max_retries,
            'real_email': real_email,
            'reply_to': reply_to,
        }
        kwargs.update(options)
        # Email subject *must not* contain newlines
        args = (recipient, ' '.join(subject.splitlines()), message)
        return send_email.delay(*args, **kwargs)

    if white_list:
        if perm_setting:
            html_template = loader.get_template('amo/emails/unsubscribe.html')
            text_template = loader.get_template('amo/emails/unsubscribe.ltxt')
            if not manage_url:
                manage_url = urlparams(absolutify(
                    reverse('users.edit', add_prefix=False)),
                    'acct-notify')
            for recipient in white_list:
                # Add unsubscribe link to footer.
                token, hash = UnsubscribeCode.create(recipient)
                unsubscribe_url = absolutify(
                    reverse('users.unsubscribe',
                            args=[token, hash, perm_setting.short],
                            add_prefix=False))

                context = {
                    'message': message,
                    'manage_url': manage_url,
                    'unsubscribe_url': unsubscribe_url,
                    'perm_setting': perm_setting.label,
                    'SITE_URL': settings.SITE_URL,
                    'mandatory': perm_setting.mandatory,
                }
                # Render this template in the default locale until
                # bug 635840 is fixed.
                with translation.override(settings.LANGUAGE_CODE):
                    message_with_unsubscribe = text_template.render(context)

                if html_message:
                    context['message'] = html_message
                    with translation.override(settings.LANGUAGE_CODE):
                        html_with_unsubscribe = html_template.render(context)
                        result = send([recipient], message_with_unsubscribe,
                                      html_message=html_with_unsubscribe,
                                      attachments=attachments)
                else:
                    result = send([recipient], message_with_unsubscribe,
                                  attachments=attachments)
        else:
            result = send(recipient_list, message=message,
                          html_message=html_message, attachments=attachments)
    else:
        result = True

    return result


@contextlib.contextmanager
def no_jinja_autoescape():
    """Disable Jinja2 autoescape."""
    autoescape_orig = engines['jinja2'].env.autoescape
    engines['jinja2'].env.autoescape = False
    yield
    engines['jinja2'].env.autoescape = autoescape_orig


def send_mail_jinja(subject, template, context, *args, **kwargs):
    """Sends mail using a Jinja template with autoescaping turned off.

    Jinja is especially useful for sending email since it has whitespace
    control.
    """
    with no_jinja_autoescape():
        template = loader.get_template(template)
    msg = send_mail(subject, template.render(context), *args, **kwargs)
    return msg


def send_html_mail_jinja(subject, html_template, text_template, context,
                         *args, **kwargs):
    """Sends HTML mail using a Jinja template with autoescaping turned off."""
    # Get a jinja environment so we can override autoescaping for text emails.
    with no_jinja_autoescape():
        html_template = loader.get_template(html_template)
        text_template = loader.get_template(text_template)
    msg = send_mail(subject, text_template.render(context),
                    html_message=html_template.render(context), *args,
                    **kwargs)
    return msg


def fetch_subscribed_newsletters(user_profile):
    try:
        data = basket.lookup_user(user_profile.email)
    except (basket.BasketNetworkException, basket.BasketException):
        log.exception('basket exception')
        return ()
    return data['newsletters']


def subscribe_newsletter(user_profile, basket_id):
    try:
        # Make a syncronize request to basket to
        # a) ensure the user is really subscribed now and
        # b) retrieve the basket token
        response = basket.subscribe(
            user_profile.email, basket_id, sync='Y')
        user_profile.update(basket_token=response['token'])
        return response['status'] == 'ok'
    except (basket.BasketNetworkException, basket.BasketException):
        log.exception('basket exception')
    return False


def unsubscribe_newsletter(user_profile, basket_id):
    if not user_profile.basket_token:
        basket_data = basket.lookup_user(user_profile.email)
        user_profile.update(basket_token=basket_data['token'])

    try:
        response = basket.unsubscribe(
            user_profile.basket_token, user_profile.email, basket_id)
        return response['status'] == 'ok'
    except (basket.BasketNetworkException, basket.BasketException):
        log.exception('basket exception')
    return False


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
        return urllib.urlencode([(k, force_bytes(v)) for k, v in items])


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

    for c in force_text(s):
        cat = unicodedata.category(c)[0]
        if cat in 'LN' or c in ok:
            rv.append(c)
        if cat == 'Z':  # space
            rv.append(' ')
    new = ''.join(rv).strip()
    if not spaces:
        new = re.sub('[-\s]+', delimiter, new)
    return new.lower() if lower else new


def normalize_string(value, strip_puncutation=False):
    """Normalizes a unicode string.

     * decomposes unicode characters
     * strips whitespaces, newlines and tabs
     * optionally removes puncutation
    """
    value = unicodedata.normalize('NFD', force_text(value))
    value = value.encode('utf-8', 'ignore')

    if strip_puncutation:
        value = value.translate(None, string.punctuation)
    return force_text(' '.join(value.split()))


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


def clean_nl(string):
    """
    This will clean up newlines so that nl2br can properly be called on the
    cleaned text.
    """

    html_blocks = ['{http://www.w3.org/1999/xhtml}blockquote',
                   '{http://www.w3.org/1999/xhtml}ol',
                   '{http://www.w3.org/1999/xhtml}li',
                   '{http://www.w3.org/1999/xhtml}ul']

    if not string:
        return string

    def parse_html(tree):
        # In etree, a tag may have:
        # - some text content (piece of text before its first child)
        # - a tail (piece of text just after the tag, and before a sibling)
        # - children
        # Eg: "<div>text <b>children's text</b> children's tail</div> tail".

        # Strip new lines directly inside block level elements: first new lines
        # from the text, and:
        # - last new lines from the tail of the last child if there's children
        #   (done in the children loop below).
        # - or last new lines from the text itself.
        if tree.tag in html_blocks:
            if tree.text:
                tree.text = tree.text.lstrip('\n')
                if not len(tree):  # No children.
                    tree.text = tree.text.rstrip('\n')

            # Remove the first new line after a block level element.
            if tree.tail and tree.tail.startswith('\n'):
                tree.tail = tree.tail[1:]

        for child in tree:  # Recurse down the tree.
            if tree.tag in html_blocks:
                # Strip new lines directly inside block level elements: remove
                # the last new lines from the children's tails.
                if child.tail:
                    child.tail = child.tail.rstrip('\n')
            parse_html(child)
        return tree

    parse = parse_html(html5lib.parseFragment(string))

    # Serialize the parsed tree back to html.
    walker = html5lib.treewalkers.getTreeWalker('etree')
    stream = walker(parse)
    serializer = HTMLSerializer(quote_attr_values=True,
                                omit_optional_tags=False)
    return serializer.render(stream)


def image_size(filename):
    """
    Return an image size tuple, as returned by PIL.
    """
    with Image.open(filename) as img:
        size = img.size
    return size


def pngcrush_image(src, **kw):
    """
    Optimizes a PNG image by running it through Pngcrush.
    """
    log.info('Optimizing image: %s' % src)
    try:
        # When -ow is used, the output file name (second argument after
        # options) is used as a temporary filename (that must reside on the
        # same filesystem as the original) to save the optimized file before
        # overwriting the original. By default it's "pngout.png" but we want
        # that to be unique in order to avoid clashes with multiple tasks
        # processing different images in parallel.
        tmp_path = '%s.crush.png' % os.path.splitext(src)[0]
        # -brute is not recommended, and in general does not improve things a
        # lot. -reduce is on by default for pngcrush above 1.8.0, but we're
        # still on an older version (1.7.85 at the time of writing this
        # comment, because that's what comes with Debian stretch that is used
        # for our docker container).
        cmd = [settings.PNGCRUSH_BIN, '-q', '-reduce', '-ow', src, tmp_path]
        process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()

        if process.returncode != 0:
            log.error('Error optimizing image: %s; %s' % (src, stderr.strip()))
            return False

        log.info('Image optimization completed for: %s' % src)
        return True

    except Exception, e:
        log.error('Error optimizing image: %s; %s' % (src, e))
    return False


def resize_image(source, destination, size=None):
    """Resizes and image from src, to dst.
    Returns a tuple of new width and height, original width and height.

    When dealing with local files it's up to you to ensure that all directories
    exist leading up to the dst filename.
    """
    if source == destination:
        raise Exception(
            "source and destination can't be the same: %s" % source)

    with storage.open(source, 'rb') as fp:
        im = Image.open(fp)
        im = im.convert('RGBA')
        original_size = im.size
        if size:
            im = processors.scale_and_crop(im, size)
    with storage.open(destination, 'wb') as fp:
        # Save the image to PNG in destination file path. Don't keep the ICC
        # profile as it can mess up pngcrush badly (mozilla/addons/issues/697).
        im.save(fp, 'png', icc_profile=None)
    pngcrush_image(destination)
    return (im.size, original_size)


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
        except Exception:
            log.error('Error decoding image', exc_info=True)
            return False

    def is_animated(self, size=100000):
        if not self.is_image():
            return False

        if self.img.format == 'PNG':
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
        elif self.img.format == 'GIF':
            # The image has been verified, and thus the file closed, we need to
            # reopen. Check the "verify" method of the Image object:
            # http://pillow.readthedocs.io/en/latest/reference/Image.html
            self._img.seek(0)
            img = Image.open(self._img)
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
        idx = locale.find('-')
        return locale[:idx].lower() + '-' + locale[idx + 1:].upper()
    else:
        return translation.trans_real.to_language(locale)


def get_locale_from_lang(lang):
    """Pass in a language (u'en-US') get back a Locale object courtesy of
    Babel.  Use this to figure out currencies, bidi, names, etc."""
    # Special fake language can just act like English for formatting and such.
    # Do the same for 'cak' because it's not in http://cldr.unicode.org/ and
    # therefore not supported by Babel - trying to fake the class leads to a
    # rabbit hole of more errors because we need valid locale data on disk, to
    # get decimal formatting, plural rules etc.
    if not lang or lang in ('cak', 'dbg', 'dbr', 'dbl'):
        lang = 'en'
    return Locale.parse(translation.to_locale(lang))


class HttpResponseSendFile(HttpResponse):

    def __init__(self, request, path, content=None, status=None,
                 content_type='application/octet-stream', etag=None):
        self.request = request
        self.path = path
        super(HttpResponseSendFile, self).__init__('', status=status,
                                                   content_type=content_type)
        header_path = self.path
        if isinstance(header_path, unicode):
            header_path = header_path.encode('utf8')
        if settings.XSENDFILE:
            self[settings.XSENDFILE_HEADER] = header_path
        if etag:
            self['ETag'] = '"%s"' % etag

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
            cache.set(ns_key, ns_val, None)
    else:
        ns_val = cache.get(ns_key)
        if ns_val is None:
            ns_val = epoch(datetime.datetime.now())
            cache.set(ns_key, ns_val, None)
    return '%s:%s' % (ns_val, ns_key)


def get_email_backend(real_email=False):
    """Get a connection to an email backend.

    If settings.SEND_REAL_EMAIL is False, a debugging backend is returned.
    """
    if real_email or settings.SEND_REAL_EMAIL:
        backend = None
    else:
        backend = 'olympia.amo.mail.DevEmailBackend'
    return django.core.mail.get_connection(backend)


def escape_all(v, linkify_only_full=False):
    """Escape html in JSON value, including nested items.

    Only linkify full urls, including a scheme, if "linkify_only_full" is True.

    """
    if isinstance(v, basestring):
        v = jinja2.escape(force_text(v))
        v = linkify_with_outgoing(v, only_full=linkify_only_full)
        return v
    elif isinstance(v, list):
        for i, lv in enumerate(v):
            v[i] = escape_all(lv, linkify_only_full=linkify_only_full)
    elif isinstance(v, dict):
        for k, lv in v.iteritems():
            v[k] = escape_all(lv, linkify_only_full=linkify_only_full)
    elif isinstance(v, Translation):
        v = jinja2.escape(force_text(v))
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
        super(LocalFileStorage, self).__init__(base_url=base_url)

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
            try:
                # Try/except to prevent race condition raising "File exists".
                os.makedirs(parent)
            except OSError as e:
                if e.errno == errno.EEXIST and os.path.isdir(parent):
                    pass
                else:
                    raise
        return super(LocalFileStorage, self)._open(name, mode=mode)

    def path(self, name):
        """Actual file system path to name without any safety checks."""
        return os.path.normpath(os.path.join(self.location, force_bytes(name)))


def translations_for_field(field):
    """Return all the translations for a given field.

    This returns a dict of locale:localized_string, not Translation objects.

    """
    if field is None:
        return {}

    translation_id = getattr(field, 'id')
    qs = Translation.objects.filter(id=translation_id,
                                    localized_string__isnull=False)
    translations = dict(qs.values_list('locale', 'localized_string'))
    return translations


def attach_trans_dict(model, objs):
    """Put all translations into a translations dict."""
    # Get the ids of all the translations we need to fetch.
    fields = model._meta.translated_fields
    ids = [getattr(obj, f.attname) for f in fields
           for obj in objs if getattr(obj, f.attname, None) is not None]

    # Get translations in a dict, ids will be the keys. It's important to
    # consume the result of sorted_groupby, which is an iterator.
    qs = Translation.objects.filter(id__in=ids, localized_string__isnull=False)
    all_translations = dict((k, list(v)) for k, v in
                            sorted_groupby(qs, lambda trans: trans.id))

    def get_locale_and_string(translation, new_class):
        """Convert the translation to new_class (making PurifiedTranslations
           and LinkifiedTranslations work) and return locale / string tuple."""
        converted_translation = new_class()
        converted_translation.__dict__ = translation.__dict__
        return (converted_translation.locale.lower(),
                unicode(converted_translation))

    # Build and attach translations for each field on each object.
    for obj in objs:
        obj.translations = collections.defaultdict(list)
        for field in fields:
            t_id = getattr(obj, field.attname, None)
            field_translations = all_translations.get(t_id, None)
            if not t_id or field_translations is None:
                continue

            obj.translations[t_id] = [get_locale_and_string(t, field.rel.to)
                                      for t in field_translations]


def rm_local_tmp_dir(path):
    """Remove a local temp directory.

    This is just a wrapper around shutil.rmtree(). Use it to indicate you are
    certain that your executing code is operating on a local temp dir, not a
    directory managed by the Django Storage API.
    """
    assert path.startswith(settings.TMP_PATH)

    return shutil.rmtree(path)


def timer(*func, **kwargs):
    """
    Outputs statsd timings for the decorated method, ignored if not
    in test suite. It will give us a name that's based on the module name.

    It will work without params. Or with the params:
    key: a key to override the calculated one
    test_only: only time while in test suite (default is True)
    """
    key = kwargs.get('key', None)
    test_only = kwargs.get('test_only', True)

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            if test_only and not settings.IN_TEST_SUITE:
                return func(*args, **kw)
            else:
                name = (key if key else
                        '%s.%s' % (func.__module__, func.__name__))
                with statsd.timer('timer.%s' % name):
                    return func(*args, **kw)
        return wrapper

    if func:
        return decorator(func[0])
    return decorator


def find_language(locale):
    """
    Return a locale we support, or None.
    """
    if not locale:
        return None

    if locale in settings.AMO_LANGUAGES:
        return locale

    # Check if locale has a short equivalent.
    loc = settings.SHORTER_LANGUAGES.get(locale)
    if loc:
        return loc

    # Check if locale is something like en_US that needs to be converted.
    locale = to_language(locale)
    if locale in settings.AMO_LANGUAGES:
        return locale

    return None


def has_links(html):
    """Return True if links (text or markup) are found in the given html."""
    # Call bleach.linkify to transform text links to real links, and add some
    # content to the ``href`` attribute. If the result is different from the
    # initial string, links were found.
    class LinkFound(Exception):
        pass

    def raise_on_link(attrs, new):
        raise LinkFound

    try:
        bleach.linkify(html, callbacks=[raise_on_link])
    except LinkFound:
        return True
    return False


def walkfiles(folder, suffix=''):
    """Iterator over files in folder, recursively."""
    return (os.path.join(basename, filename)
            for basename, dirnames, filenames in scandir.walk(folder)
            for filename in filenames
            if filename.endswith(suffix))


def utc_millesecs_from_epoch(for_datetime=None):
    """
    Returns millesconds from the Unix epoch in UTC.

    If `for_datetime` is None, the current datetime will be used.
    """
    if not for_datetime:
        for_datetime = datetime.datetime.now()
    return calendar.timegm(for_datetime.utctimetuple()) * 1000


class AMOJSONEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Translation):
            return force_text(obj)
        return super(AMOJSONEncoder, self).default(obj)
