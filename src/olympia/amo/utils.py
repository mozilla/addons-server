import collections
import contextlib
import datetime
import errno
import functools
import itertools
import json
import operator
import os
import re
import shutil
import string
import subprocess
import tempfile
import time
import unicodedata

from urllib.parse import (
    parse_qsl,
    ParseResult,
    unquote_to_bytes,
    urlencode as urllib_urlencode,
    urlparse,
)

import django.core.mail

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import FileSystemStorage, default_storage as storage
from django.core.paginator import EmptyPage, InvalidPage, Paginator as DjangoPaginator
from django.core.validators import ValidationError, validate_slug
from django.forms.fields import Field
from django.http import HttpResponse
from django.http.response import HttpResponseRedirectBase
from django.template import engines, loader
from django.urls import reverse
from django.utils import translation
from django.utils.functional import cached_property
from django.utils.encoding import force_bytes, force_str
from django.utils.http import (
    _urlparse as django_urlparse,
    quote_etag,
    url_has_allowed_host_and_scheme,
)

import bleach
import colorgram
import html5lib
import markupsafe
import pytz
import basket

from babel import Locale
from django_statsd.clients import statsd
from easy_thumbnails import processors
from html5lib.serializer import HTMLSerializer
from PIL import Image
from rest_framework.utils.encoders import JSONEncoder

from olympia.core.logger import getLogger
from olympia.amo import ADDON_ICON_SIZES, search
from olympia.amo.pagination import ESPaginator
from olympia.amo.urlresolvers import linkify_with_outgoing
from olympia.translations.models import Translation
from olympia.users.utils import UnsubscribeCode
from olympia.lib import unicodehelper


log = getLogger('z.amo')


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
    url = django_urlparse(force_str(url_))

    fragment = hash if hash is not None else url.fragment

    # Use dict(parse_qsl) so we don't get lists of values.
    query_dict = dict(parse_qsl(force_str(url.query))) if url.query else {}
    query_dict.update(
        (k, force_bytes(v) if v is not None else v) for k, v in query.items()
    )
    query_string = urlencode(
        [(k, unquote_to_bytes(v)) for k, v in query_dict.items() if v is not None]
    )
    result = ParseResult(
        url.scheme, url.netloc, url.path, url.params, query_string, fragment
    )
    return result.geturl()


def partial(func, *args, **kw):
    """A thin wrapper around functools.partial which updates the wrapper
    as would a decorator."""
    return functools.update_wrapper(functools.partial(func, *args, **kw), func)


def isotime(t):
    """Date/Time format according to ISO 8601"""
    if not hasattr(t, 'tzinfo'):
        return
    return _append_tz(t).astimezone(pytz.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _append_tz(t):
    tz = pytz.timezone(settings.TIME_ZONE)
    return tz.localize(t)


def sorted_groupby(seq, key, *, reverse=False):
    """
    Given a sequence, we sort it and group it by a key.

    key should be a string (used with attrgetter) or a function.
    """
    if not hasattr(key, '__call__'):
        key = operator.attrgetter(key)
    return itertools.groupby(sorted(seq, key=key, reverse=reverse), key=key)


def paginate(request, queryset, per_page=20, count=None):
    """
    Get a Paginator, abstracting some common paging actions.

    If you pass ``count``, that value will be used instead of calling
    ``.count()`` on the queryset.  This can be good if the queryset would
    produce an expensive count query.
    """
    if isinstance(queryset, search.ES):
        paginator = ESPaginator(queryset, per_page, use_elasticsearch_dsl=False)
    else:
        paginator = DjangoPaginator(queryset, per_page)

    if count is not None:
        paginator.count = count

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

    paginated.url = f'{request.path}?{request.GET.urlencode()}'
    return paginated


def decode_json(json_string):
    """Helper that transparently handles BOM encoding."""
    return json.loads(unicodehelper.decode(json_string))


def send_mail(
    subject,
    message,
    from_email=None,
    recipient_list=None,
    use_deny_list=True,
    perm_setting=None,
    manage_url=None,
    headers=None,
    cc=None,
    real_email=False,
    html_message=None,
    attachments=None,
    max_retries=3,
    reply_to=None,
    countdown=None,
):
    """
    A wrapper around django.core.mail.EmailMessage.

    Adds deny checking and error logging.
    """
    from olympia.amo.templatetags.jinja_helpers import absolutify
    from olympia.amo.tasks import send_email
    from olympia.users import notifications
    from olympia.users.models import UserNotification

    if not recipient_list:
        return True

    if isinstance(recipient_list, str):
        raise ValueError('recipient_list should be a list, not a string.')

    # Check against user notification settings
    if perm_setting:
        if isinstance(perm_setting, str):
            perm_setting = notifications.NOTIFICATIONS_BY_SHORT[perm_setting]
        perms = dict(
            UserNotification.objects.filter(
                user__email__in=recipient_list, notification_id=perm_setting.id
            ).values_list('user__email', 'enabled')
        )

        d = perm_setting.default_checked
        recipient_list = [e for e in recipient_list if e and perms.setdefault(e, d)]

    # Prune denied emails.
    if use_deny_list:
        white_list = []
        for email in recipient_list:
            if email and email.lower() in settings.EMAIL_DENY_LIST:
                log.info('Blacklisted email removed from list: %s' % email)
            else:
                white_list.append(email)
    else:
        white_list = recipient_list

    if not from_email:
        from_email = settings.DEFAULT_FROM_EMAIL

    if cc:
        # If not str, assume it is already a list.
        if isinstance(cc, str):
            cc = [cc]

    if not headers:
        headers = {}

    # Avoid auto-replies per rfc 3834 and the Microsoft variant
    headers['X-Auto-Response-Suppress'] = 'RN, NRN, OOF, AutoReply'
    headers['Auto-Submitted'] = 'auto-generated'

    def send(recipients, message, **options):
        kwargs = {
            'attachments': attachments,
            'cc': cc,
            'from_email': from_email,
            'headers': headers,
            'html_message': html_message,
            'max_retries': max_retries,
            'real_email': real_email,
            'reply_to': reply_to,
            'countdown': countdown,
        }
        kwargs.update(options)
        # Email subject *must not* contain newlines
        args = (list(recipients), ' '.join(subject.splitlines()), message)
        return send_email.delay(*args, **kwargs)

    if white_list:
        if perm_setting:
            html_template = loader.get_template('amo/emails/unsubscribe.html')
            text_template = loader.get_template('amo/emails/unsubscribe.ltxt')
            if not manage_url:
                manage_url = urlparams(
                    absolutify(reverse('users.edit', add_prefix=False)), 'acct-notify'
                )
            for recipient in white_list:
                # Add unsubscribe link to footer.
                token, hash = UnsubscribeCode.create(recipient)
                unsubscribe_url = absolutify(
                    reverse(
                        'users.unsubscribe',
                        args=[force_str(token), hash, perm_setting.short],
                        add_prefix=False,
                    )
                )

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
                        result = send(
                            [recipient],
                            message_with_unsubscribe,
                            html_message=html_with_unsubscribe,
                            attachments=attachments,
                        )
                else:
                    result = send(
                        [recipient], message_with_unsubscribe, attachments=attachments
                    )
        else:
            result = send(
                recipient_list,
                message=message,
                html_message=html_message,
                attachments=attachments,
            )
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


def send_html_mail_jinja(
    subject, html_template, text_template, context, *args, **kwargs
):
    """Sends HTML mail using a Jinja template with autoescaping turned off."""
    # Get a jinja environment so we can override autoescaping for text emails.
    with no_jinja_autoescape():
        html_template = loader.get_template(html_template)
        text_template = loader.get_template(text_template)
    msg = send_mail(
        subject,
        text_template.render(context),
        html_message=html_template.render(context),
        *args,
        **kwargs,
    )
    return msg


def sync_user_with_basket(user):
    """Syncronize a user with basket.

    Returns the user data in case of a successful sync.
    Returns `None` in case of an unsuccessful sync. This can happen
    if the user does not exist in basket yet.

    This raises an exception all other errors.
    """
    try:
        data = basket.lookup_user(user.email)
        user.update(basket_token=data['token'])
        return data
    except Exception as exc:
        acceptable_errors = (
            basket.errors.BASKET_INVALID_EMAIL,
            basket.errors.BASKET_UNKNOWN_EMAIL,
        )

        if getattr(exc, 'code', None) in acceptable_errors:
            return None
        else:
            raise


def fetch_subscribed_newsletters(user_profile):
    data = sync_user_with_basket(user_profile)

    if not user_profile.basket_token and data is not None:
        user_profile.update(basket_token=data['token'])
    elif data is None:
        return []
    return data['newsletters']


def subscribe_newsletter(user_profile, basket_id, request=None):
    response = basket.subscribe(
        user_profile.email,
        basket_id,
        sync='Y',
        source_url=request.build_absolute_uri() if request else None,
        optin='Y',
    )
    return response['status'] == 'ok'


def unsubscribe_newsletter(user_profile, basket_id):
    # Security check, the basket token will be set by
    # `fetch_subscribed_newsletters` but since we shouldn't simply error
    # we just fetch it in case something went wrong.
    if not user_profile.basket_token:
        sync_user_with_basket(user_profile)

    # If we still don't have a basket token we can't unsubscribe.
    # This usually means the user doesn't exist in basket yet, which
    # is more or less identical with not being subscribed to any
    # newsletters.
    if user_profile.basket_token:
        response = basket.unsubscribe(
            user_profile.basket_token, user_profile.email, basket_id
        )
        return response['status'] == 'ok'
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
    while True:
        rv = list(itertools.islice(seq, 0, n))
        if not rv:
            break
        yield rv


def urlencode(items):
    """A Unicode-safe URLencoder."""
    try:
        return urllib_urlencode(items)
    except UnicodeEncodeError:
        return urllib_urlencode([(k, force_bytes(v)) for k, v in items])


# Extra characters outside of alphanumerics that we'll allow.
SLUG_OK = '-_~'


def slugify(s, ok=SLUG_OK, lower=True, spaces=False, delimiter='-'):
    # L and N signify letter/number.
    # http://www.unicode.org/reports/tr44/tr44-4.html#GC_Values_Table
    rv = []

    for c in force_str(s):
        cat = unicodedata.category(c)[0]
        if cat in 'LN' or c in ok:
            rv.append(c)
        if cat == 'Z':  # space
            rv.append(' ')
    new = ''.join(rv).strip()
    if not spaces:
        new = re.sub(r'[-\s]+', delimiter, new)
    return new.lower() if lower else new


def normalize_string(value, strip_punctuation=False):
    """Normalizes a unicode string.

    * decomposes unicode characters
    * strips whitespaces, newlines and tabs
    * optionally removes puncutation
    """
    value = unicodedata.normalize('NFD', force_str(value))
    value = value.encode('utf-8', 'ignore')

    if strip_punctuation:
        value = value.translate(None, force_bytes(string.punctuation))
    return force_str(b' '.join(value.split()))


def slug_validator(slug, message=validate_slug.message):
    """
    Raise an error if the string has any punctuation characters.

    Regexes don't work here because they won't check alnums in the right
    locale.
    """
    if not (slug and slugify(slug, lower=False) == slug):
        raise ValidationError(message, code=validate_slug.code)


def raise_required():
    raise ValidationError(Field.default_error_messages['required'])


def clean_nl(string):
    """
    This will clean up newlines so that nl2br can properly be called on the
    cleaned text.
    """

    html_blocks = [
        '{http://www.w3.org/1999/xhtml}blockquote',
        '{http://www.w3.org/1999/xhtml}ol',
        '{http://www.w3.org/1999/xhtml}li',
        '{http://www.w3.org/1999/xhtml}ul',
    ]

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
    serializer = HTMLSerializer(quote_attr_values='always', omit_optional_tags=False)
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
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()

        if process.returncode != 0:
            log.error(f'Error optimizing image: {src}; {stderr.strip()}')
            return False

        log.info('Image optimization completed for: %s' % src)
        return True

    except Exception as e:
        log.error(f'Error optimizing image: {src}; {e}')
    return False


def convert_svg_to_png(svg_file, png_file):
    try:
        if not os.path.exists(os.path.dirname(png_file)):
            os.makedirs(os.path.dirname(png_file))
        command = [
            settings.RSVG_CONVERT_BIN,
            '--output',
            png_file,
            svg_file,
        ]
        subprocess.check_call(command)
    except OSError as io_error:
        log.info(io_error)
        return False
    except subprocess.CalledProcessError as process_error:
        log.info(process_error)
        return False
    return True


def resize_image(source, destination, size=None, *, format='png', quality=80):
    """Resizes and image from source, to destination.
    Returns a tuple of new width and height, original width and height.

    When dealing with local files it's up to you to ensure that all directories
    exist leading up to the destination filename.

    quality kwarg is only valid for jpeg format - it's ignored for png.
    """
    if source == destination:
        raise Exception("source and destination can't be the same: %s" % source)
    source_fileext = os.path.splitext(source)[1]
    if source_fileext == '.svg':
        tmp_args = {
            'dir': settings.TMP_PATH,
            'mode': 'w+b',
            'suffix': '.png',
            'delete': not settings.DEBUG,
        }
        with tempfile.NamedTemporaryFile(**tmp_args) as temporary_png:
            convert_svg_to_png(source, temporary_png.name)
            im = Image.open(temporary_png.name)
            im.load()
    else:
        with storage.open(source, 'rb') as fp:
            im = Image.open(fp)
            im.load()
    original_size = im.size
    if size:
        im = processors.scale_and_crop(im.convert('RGBA'), size)

    with storage.open(destination, 'wb') as dest_file:
        if format == 'png':
            # Save the image to PNG in destination file path.
            # Don't keep the ICC profile as it can mess up pngcrush badly
            # (mozilla/addons/issues/697).
            im = im.convert('RGBA')
            im.save(dest_file, 'png', icc_profile=None)
            pngcrush_image(destination)
        else:
            # Create a white rgba background for transparency
            final_im = Image.new('RGBA', im.size, 'WHITE')
            final_im.paste(im, (0, 0), im)
            final_im = final_im.convert('RGB')
            final_im.save(dest_file, 'JPEG', quality=quality)
            final_im.close()
    new_size = im.size
    im.close()
    return (new_size, original_size)


def remove_icons(destination):
    for size in ADDON_ICON_SIZES:
        filename = f'{destination}-{size}.png'
        if storage.exists(filename):
            storage.delete(filename)


class ImageCheck:
    def __init__(self, image):
        self._img = image

    def is_image(self):
        if not hasattr(self, '_is_image'):
            try:
                self._img.seek(0)
                self.img = Image.open(self._img)
                # PIL doesn't tell us what errors it will raise at this point,
                # just "suitable ones", so let's catch them all.
                self.img.verify()
                self._is_image = True
            except Exception:
                log.error('Error decoding image', exc_info=True)
                self._is_image = False
        return self._is_image

    @property
    def size(self):
        if not self.is_image():
            return None
        return self.img.size if hasattr(self, 'img') else None

    def is_animated(self, size=100000):
        if not self.is_image():
            return False

        if self.img.format == 'PNG':
            self._img.seek(0)
            data = b''
            while True:
                chunk = self._img.read(size)
                if not chunk:
                    break
                data += chunk
                acTL, IDAT = data.find(b'acTL'), data.find(b'IDAT')
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


class MenuItem:
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
        return locale[:idx].lower() + '-' + locale[idx + 1 :].upper()
    else:
        return translation.trans_real.to_language(locale)


def get_locale_from_lang(lang):
    """Pass in a language ('en-US') get back a Locale object courtesy of
    Babel.  Use this to figure out currencies, bidi, names, etc."""
    # Special fake language can just act like English for formatting and such.
    # Do the same for 'cak' because it's not in http://cldr.unicode.org/ and
    # therefore not supported by Babel - trying to fake the class leads to a
    # rabbit hole of more errors because we need valid locale data on disk, to
    # get decimal formatting, plural rules etc.
    if not lang or lang in ('cak',):
        lang = 'en'
    return Locale.parse(translation.to_locale(lang))


class HttpResponseXSendFile(HttpResponse):
    def __init__(
        self,
        request,
        path,
        content=None,
        status=None,
        content_type='application/octet-stream',
        etag=None,
        attachment=False,
    ):
        super().__init__('', status=status, content_type=content_type)
        # We normalize the path because if it contains dots, nginx will flag
        # the URI as unsafe.
        self[settings.XSENDFILE_HEADER] = force_bytes(os.path.normpath(path))
        if etag:
            self['ETag'] = quote_etag(etag)
        if attachment:
            self['Content-Disposition'] = 'attachment'

    def __iter__(self):
        return iter([])


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
            ns_val = utc_millesecs_from_epoch(datetime.datetime.now())
            cache.set(ns_key, ns_val, None)
    else:
        ns_val = cache.get(ns_key)
        if ns_val is None:
            ns_val = utc_millesecs_from_epoch(datetime.datetime.now())
            cache.set(ns_key, ns_val, None)
    return f'{ns_val}:{ns_key}'


def get_email_backend(real_email=False):
    """Get a connection to an email backend.

    If settings.SEND_REAL_EMAIL is False, a debugging backend is returned.
    """
    if real_email or settings.SEND_REAL_EMAIL:
        backend = None
    else:
        backend = 'olympia.amo.mail.DevEmailBackend'
    return django.core.mail.get_connection(backend)


def escape_all(value):
    """Escape html in JSON value, including nested items.

    Only linkify full urls, including a scheme, if "linkify_only_full" is True.

    """
    if isinstance(value, str):
        value = markupsafe.escape(force_str(value))
        value = linkify_with_outgoing(value)
        return value
    elif isinstance(value, list):
        for i, lv in enumerate(value):
            value[i] = escape_all(lv)
    elif isinstance(value, dict):
        for k, lv in value.items():
            value[k] = escape_all(lv)
    elif isinstance(value, Translation):
        value = markupsafe.escape(force_str(value))
    return value


class SafeStorage(FileSystemStorage):
    """Unlike Django's default FileSystemStorage, this class behaves more like a
    "cloud" storage system. Specifically, you never have to write defensive
    code that prepares for leading directory paths to exist.

    Storage is relative to settings.STORAGE_ROOT by default.
    """

    DEFAULT_CHUNK_SIZE = 64 * 2**10  # 64kB

    def __init__(self, *args, **kwargs):
        """If `user_media` arg is provided, location will be lazily resolved under the
        appropriate user_media_path. If `user_media` is falsey MEDIA_ROOT is used - see
        user_media_path for the resolution logic."""
        if 'user_media' in kwargs:
            self._user_media = kwargs.pop('user_media')
        super().__init__(*args, **kwargs)

    @cached_property
    def base_location(self):
        from olympia.amo.templatetags.jinja_helpers import user_media_path

        if hasattr(self, '_user_media'):
            return user_media_path(self._user_media or '')
        return self._value_or_setting(self._location, settings.STORAGE_ROOT)

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
        return super()._open(name, mode=mode)

    def path(self, name):
        return os.path.normpath(super().path(force_str(name)))

    def walk(self, path):
        """
        Generate the file names in a stored directory tree by walking the tree
        top-down.

        For each directory in the tree rooted at the directory top (including top
        itself), it yields a 3-tuple (dirpath, dirnames, filenames).
        """
        roots = [force_str(path)]
        while len(roots):
            new_roots = []
            for root in roots:
                root = force_str(root)
                dirs, files = self.listdir(root)
                files = [force_str(f) for f in files]
                dirs = [force_str(d) for d in dirs]
                yield root, dirs, files
                for dn in dirs:
                    dn = force_str(dn)
                    new_roots.append(f'{root}/{dn}')
            roots[:] = new_roots

    def copy_stored_file(self, src_path, dest_path, chunk_size=DEFAULT_CHUNK_SIZE):
        """
        Copy one storage path to another storage path.

        Each path will be managed by the same storage implementation.

        Note: both src_path and dest_path must be sub directories of self.location.
        """
        if src_path == dest_path:
            return
        with self.open(src_path, 'rb') as src:
            with self.open(dest_path, 'wb') as dest:
                while True:
                    chunk = src.read(chunk_size)
                    if chunk:
                        dest.write(chunk)
                    else:
                        break

    def move_stored_file(self, src_path, dest_path, chunk_size=DEFAULT_CHUNK_SIZE):
        """
        Move a storage path to another storage path.

        The source file will be copied to the new path then deleted.
        This attempts to be compatible with a wide range of storage backends
        rather than attempt to be optimized for each individual one.

        Note: both src_path and dest_path must be sub directories of self.location.
        """
        self.copy_stored_file(src_path, dest_path, chunk_size=chunk_size)
        self.delete(src_path)

    def rm_stored_dir(self, dir_path):
        """
        Removes a stored directory and all files stored beneath that path.
        """
        empty_dirs = []
        # Delete all files first then all empty directories.
        for root, dirs, files in self.walk(dir_path):
            for fn in files:
                self.delete(f'{root}/{fn}')
            empty_dirs.insert(0, root)
        empty_dirs.append(dir_path)
        for dn in empty_dirs:
            self.delete(dn)


def attach_trans_dict(model, objs):
    """Put all translations from all non-deferred translated fields from objs
    into a translations dict on each instance."""
    # Get the ids of all the translations we need to fetch.
    try:
        deferred_fields = objs[0].get_deferred_fields()
    except IndexError:
        return
    fields = [
        field
        for field in model._meta.translated_fields
        if field.attname not in deferred_fields
    ]
    ids = [
        getattr(obj, field.attname)
        for field in fields
        for obj in objs
        if getattr(obj, field.attname, None) is not None
    ]

    if ids:
        # Get translations in a dict, ids will be the keys. It's important to
        # consume the result of sorted_groupby, which is an iterator.
        qs = Translation.objects.filter(id__in=ids, localized_string__isnull=False)
    else:
        qs = []
    all_translations = {
        field_id: sorted(list(translations), key=lambda t: t.locale)
        for field_id, translations in sorted_groupby(qs, lambda t: t.id)
    }

    def get_locale_and_string(translation, new_class):
        """Convert the translation to new_class (making PurifiedTranslations
        and LinkifiedTranslations work) and return locale / string tuple."""
        converted_translation = new_class()
        converted_translation.__dict__ = translation.__dict__
        return (converted_translation.locale.lower(), str(converted_translation))

    # Build and attach translations for each field on each object.
    for obj in objs:
        if not obj:
            continue
        obj.translations = collections.defaultdict(list)
        for field in fields:
            t_id = getattr(obj, field.attname, None)
            field_translations = all_translations.get(t_id, None)
            if not t_id or field_translations is None:
                continue

            obj.translations[t_id] = [
                get_locale_and_string(t, field.remote_field.model)
                for t in field_translations
            ]


def rm_local_tmp_dir(path):
    """Remove a local temp directory.

    This is just a wrapper around shutil.rmtree(). Use it to indicate you are
    certain that your executing code is operating on a local temp dir, not a
    directory managed by the Django Storage API.
    """
    path = force_str(path)
    tmp_path = force_str(settings.TMP_PATH)
    assert path.startswith((tmp_path, tempfile.gettempdir()))
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
                name = key if key else f'{func.__module__}.{func.__name__}'
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
    return (
        os.path.join(basename, filename)
        for basename, dirnames, filenames in os.walk(folder)
        for filename in filenames
        if filename.endswith(suffix)
    )


def utc_millesecs_from_epoch(for_datetime=None):
    """
    Returns millesconds from the Unix epoch in UTC.

    If `for_datetime` is None, the current datetime will be used.
    """
    if not for_datetime:
        for_datetime = datetime.datetime.now()
    # Number of seconds.
    seconds = time.mktime(for_datetime.utctimetuple())
    # timetuple() doesn't care about more precision than seconds, but we do.
    # Add microseconds as a fraction of a second to keep the precision.
    seconds += for_datetime.microsecond / 1000000.0
    # Now convert to milliseconds.
    return int(seconds * 1000)


def extract_colors_from_image(path):
    try:
        image_colors = colorgram.extract(path, 6)
        colors = [
            {
                'h': color.hsl.h,
                's': color.hsl.s,
                'l': color.hsl.l,
                'ratio': color.proportion,
            }
            for color in image_colors
        ]
    except OSError:
        colors = None
    return colors


def use_fake_fxa():
    """Return whether or not to use a fake FxA server for authentication.
    Should always return False in production"""
    return settings.DEBUG and settings.USE_FAKE_FXA_AUTH


class AMOJSONEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Translation):
            return force_str(obj)
        return super().default(obj)


class StopWatch:
    _timestamp = None

    def __init__(self, label_prefix=''):
        self.prefix = label_prefix

    def start(self):
        self._timestamp = datetime.datetime.utcnow()

    def log_interval(self, label):
        if not self._timestamp:
            return
        now = datetime.datetime.utcnow()
        statsd.timing(self.prefix + label, now - self._timestamp)
        log.info('%s: %s', self.prefix + label, now - self._timestamp)
        self._timestamp = now


class HttpResponseTemporaryRedirect(HttpResponseRedirectBase):
    """This is similar to a 302 but keeps the request method and body so we can
    redirect POSTs too."""

    status_code = 307


def is_safe_url(url, request, allowed_hosts=None):
    """Use Django's `url_has_allowed_host_and_scheme()` and pass a configured
    list of allowed hosts and enforce HTTPS.  `allowed_hosts` can be specified."""
    if not allowed_hosts:
        allowed_hosts = (
            settings.DOMAIN,
            urlparse(settings.CODE_MANAGER_URL).netloc,
        )
        if settings.ADDONS_FRONTEND_PROXY_PORT:
            allowed_hosts = allowed_hosts + (
                f'{settings.DOMAIN}:{settings.ADDONS_FRONTEND_PROXY_PORT}',
            )

    require_https = request.is_secure() if request else False
    return url_has_allowed_host_and_scheme(
        url, allowed_hosts=allowed_hosts, require_https=require_https
    )
