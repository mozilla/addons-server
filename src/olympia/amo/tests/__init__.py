# -*- coding: utf-8 -*-
import math
import os
import random
import shutil
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import partial
from importlib import import_module
from tempfile import NamedTemporaryFile
from urlparse import parse_qs, urlparse

from django import forms, test
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core import signing
from django.core.management import call_command
from django.db.models.signals import post_save
from django.http import HttpRequest, SimpleCookie
from django.test.client import Client, RequestFactory
from django.test.utils import override_settings
from django.conf import urls as django_urls
from django.utils import translation
from django.utils.encoding import force_str

import mock
import pytest
from dateutil.parser import parse as dateutil_parser
from rest_framework.views import APIView
from rest_framework.test import APIClient
from waffle.models import Flag, Sample, Switch

from olympia import amo
from olympia.access.acl import check_ownership
from olympia.api.authentication import WebTokenAuthentication
from olympia.search import indexers as search_indexers
from olympia.stats import search as stats_search
from olympia.amo import search as amo_search
from olympia.access.models import Group, GroupUser
from olympia.accounts.utils import fxa_login_url
from olympia.addons.models import (
    Addon, AddonCategory, Category, Persona,
    update_search_index as addon_update_search_index)
from olympia.addons.tasks import version_changed
from olympia.amo.urlresolvers import get_url_prefix, Prefixer, set_url_prefix
from olympia.addons.tasks import unindex_addons
from olympia.applications.models import AppVersion
from olympia.bandwagon.models import Collection
from olympia.constants.categories import CATEGORIES
from olympia.files.models import File
from olympia.lib.es.utils import timestamp_index
from olympia.tags.models import Tag
from olympia.translations.models import Translation
from olympia.versions.models import ApplicationsVersions, License, Version
from olympia.users.models import UserProfile

from . import dynamic_urls


# We might not have gettext available in jinja2.env.globals when running tests.
# It's only added to the globals when activating a language (which
# is usually done in the middlewares). During tests, however, we might not be
# running middlewares, and thus not activating a language, and thus not
# installing gettext in the globals, and thus not have it in the context when
# rendering templates.
translation.activate('en-us')

# We need ES indexes aliases to match prod behaviour, but also we need the
# names need to stay consistent during the whole test run, so we generate
# them at import time. Note that this works because pytest overrides
# ES_INDEXES before the test run even begins - if we were using
# override_settings() on ES_INDEXES we'd be in trouble.
ES_INDEX_SUFFIXES = {
    key: timestamp_index('')
    for key in settings.ES_INDEXES.keys()}


def get_es_index_name(key):
    """Return the name of the actual index used in tests for a given key
    taken from settings.ES_INDEXES.

    Can be used to check whether aliases have been set properly -
    ES_INDEXES will give the aliases, and this method will give the indices
    the aliases point to."""
    value = settings.ES_INDEXES[key]
    return '%s%s' % (value, ES_INDEX_SUFFIXES[key])


def setup_es_test_data(es):
    try:
        es.cluster.health()
    except Exception as e:
        e.args = tuple(
            [u"%s (it looks like ES is not running, try starting it or "
             u"don't run ES tests: make test_no_es)" % e.args[0]] +
            list(e.args[1:]))
        raise

    aliases_and_indexes = set(settings.ES_INDEXES.values() +
                              es.indices.get_alias().keys())

    for key in aliases_and_indexes:
        if key.startswith('test_'):
            es.indices.delete(key, ignore=[404])

    # Figure out the name of the indices we're going to create from the
    # suffixes generated at import time. Like the aliases later, the name
    # has been prefixed by pytest, we need to add a suffix that is unique
    # to this test run.
    actual_indices = {key: get_es_index_name(key)
                      for key in settings.ES_INDEXES.keys()}

    # Create new search and stats indexes with the timestamped name.
    # This is crucial to set up the correct mappings before we start
    # indexing things in tests.
    search_indexers.create_new_index(index_name=actual_indices['default'])
    stats_search.create_new_index(index_name=actual_indices['stats'])

    # Alias it to the name the code is going to use (which is suffixed by
    # pytest to avoid clashing with the real thing).
    actions = [
        {'add': {'index': actual_indices['default'],
                 'alias': settings.ES_INDEXES['default']}},
        {'add': {'index': actual_indices['stats'],
                 'alias': settings.ES_INDEXES['stats']}}
    ]

    es.indices.update_aliases({'actions': actions})


def formset(*args, **kw):
    """
    Build up a formset-happy POST.

    *args is a sequence of forms going into the formset.
    prefix and initial_count can be set in **kw.
    """
    prefix = kw.pop('prefix', 'form')
    total_count = kw.pop('total_count', len(args))
    initial_count = kw.pop('initial_count', len(args))
    data = {prefix + '-TOTAL_FORMS': total_count,
            prefix + '-INITIAL_FORMS': initial_count}
    for idx, d in enumerate(args):
        data.update(('%s-%s-%s' % (prefix, idx, k), v)
                    for k, v in d.items())
    data.update(kw)
    return data


def initial(form):
    """Gather initial data from the form into a dict."""
    data = {}
    for name, field in form.fields.items():
        if form.is_bound:
            data[name] = form[name].data
        else:
            data[name] = form.initial.get(name, field.initial)
        # The browser sends nothing for an unchecked checkbox.
        if isinstance(field, forms.BooleanField):
            val = field.to_python(data[name])
            if not val:
                del data[name]
    return data


def check_links(expected, elements, selected=None, verify=True):
    """Useful for comparing an `expected` list of links against PyQuery
    `elements`. Expected format of links is a list of tuples, like so:

    [
        ('Home', '/'),
        ('Extensions', reverse('browse.extensions')),
        ...
    ]

    If you'd like to check if a particular item in the list is selected,
    pass as `selected` the title of the link.

    Links are verified by default.

    """
    for idx, item in enumerate(expected):
        # List item could be `(text, link)`.
        if isinstance(item, tuple):
            text, link = item
        # Or list item could be `link`.
        elif isinstance(item, basestring):
            text, link = None, item

        e = elements.eq(idx)
        if text is not None:
            assert e.text() == text, u'Expected %s, got %s' % (text, e.text())
        if link is not None:
            # If we passed an <li>, try to find an <a>.
            if not e.filter('a'):
                e = e.find('a')
            assert_url_equal(e.attr('href'), link)
            if verify and link != '#':
                assert Client().head(link, follow=True).status_code == 200
        if text is not None and selected is not None:
            e = e.filter('.selected, .sel') or e.parents('.selected, .sel')
            assert bool(e.length) == (text == selected)


def assert_url_equal(url, expected, compare_host=False):
    """Compare url paths and query strings."""
    parsed = urlparse(unicode(url))
    parsed_expected = urlparse(unicode(expected))
    compare_url_part(parsed.path, parsed_expected.path)
    compare_url_part(parse_qs(parsed.query), parse_qs(parsed_expected.query))
    if compare_host:
        compare_url_part(parsed.netloc, parsed_expected.netloc)


def compare_url_part(part, expected):
    assert part == expected, u'Expected %s, got %s' % (expected, part)


def create_sample(name=None, **kw):
    if name is not None:
        kw['name'] = name
    kw.setdefault('percent', 100)
    sample, created = Sample.objects.get_or_create(name=name, defaults=kw)
    if not created:
        sample.__dict__.update(kw)
        sample.save()
    return sample


def create_switch(name=None, **kw):
    kw.setdefault('active', True)
    if name is not None:
        kw['name'] = name
    switch, created = Switch.objects.get_or_create(name=name, defaults=kw)
    if not created:
        switch.__dict__.update(kw)
        switch.save()
    return switch


def create_flag(name=None, **kw):
    if name is not None:
        kw['name'] = name
    kw.setdefault('everyone', True)
    flag, created = Flag.objects.get_or_create(name=name, defaults=kw)
    if not created:
        flag.__dict__.update(kw)
        flag.save()
    return flag


class PatchMixin(object):

    def patch(self, thing):
        patcher = mock.patch(thing)
        self.addCleanup(patcher.stop)
        return patcher.start()


def initialize_session(request, session_data):
    # This is taken from django's login method.
    # https://github.com/django/django/blob/9d915ac1be1e7b8cfea3c92f707a4aeff4e62583/django/test/client.py#L541
    engine = import_module(settings.SESSION_ENGINE)
    request.session = engine.SessionStore()
    request.session.update(session_data)
    # Save the session values.
    request.session.save()


class InitializeSessionMixin(object):

    def initialize_session(self, session_data):
        request = HttpRequest()
        initialize_session(request, session_data)
        # Set the cookie to represent the session.
        session_cookie = settings.SESSION_COOKIE_NAME
        self.client.cookies[session_cookie] = request.session.session_key
        cookie_data = {
            'max-age': None,
            'path': '/',
            'domain': settings.SESSION_COOKIE_DOMAIN,
            'secure': settings.SESSION_COOKIE_SECURE,
            'expires': None,
        }
        self.client.cookies[session_cookie].update(cookie_data)


class TestClient(Client):

    def __getattr__(self, name):
        """
        Provides get_ajax, post_ajax, head_ajax methods etc in the
        test_client so that you don't need to specify the headers.
        """
        if name.endswith('_ajax'):
            method = getattr(self, name.split('_')[0])
            return partial(method, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        else:
            raise AttributeError


class APITestClient(APIClient):

    def generate_api_token(self, user, **payload_overrides):
        """
        Creates a jwt token for this user.
        """
        data = {
            'auth_hash': user.get_session_auth_hash(),
            'user_id': user.pk,
        }
        data.update(payload_overrides)
        token = signing.dumps(data, salt=WebTokenAuthentication.salt)
        return token

    def login_api(self, user):
        """
        Creates a jwt token for this user as if they just logged in. This token
        will be sent in an Authorization header with all future requests for
        this client.
        """
        prefix = WebTokenAuthentication.auth_header_prefix
        token = self.generate_api_token(user)
        self.defaults['HTTP_AUTHORIZATION'] = '{0} {1}'.format(prefix, token)

    def logout_api(self):
        """
        Removes the Authorization header from future requests.
        """
        self.defaults.pop('HTTP_AUTHORIZATION', None)


def days_ago(days):
    return datetime.now().replace(microsecond=0) - timedelta(days=days)


ES_patchers = [
    # We technically only need to mock get_es() to prevent ES calls from being
    # made in non-es tests, but by mocking the specific tasks as well, we gain
    # some significant execution time by avoiding a round-trip through celery
    # task handling code.
    mock.patch('olympia.amo.search.get_es', spec=True),
    mock.patch('elasticsearch.Elasticsearch'),
    mock.patch('olympia.addons.models.update_search_index', spec=True),
    mock.patch('olympia.addons.tasks.index_addons', spec=True),
    mock.patch('olympia.bandwagon.tasks.index_collections', spec=True),
    mock.patch('olympia.bandwagon.tasks.unindex_collections', spec=True),
]


def start_es_mocks():
    for patch in ES_patchers:
        patch.start()


def stop_es_mocks():
    for patch in ES_patchers:
        try:
            patch.stop()
        except RuntimeError:
            # Ignore already stopped patches.
            pass


class BaseTestCase(test.TestCase):
    """Base test case that most test cases should inherit from."""

    def _pre_setup(self):
        super(BaseTestCase, self)._pre_setup()
        self.client = self.client_class()

    def trans_eq(self, trans, localized_string, locale):
        assert trans.id
        translation = Translation.objects.get(id=trans.id, locale=locale)
        assert translation.localized_string == localized_string

    def assertUrlEqual(self, url, other, compare_host=False):
        """Compare url paths and query strings."""
        assert_url_equal(url, other, compare_host=compare_host)


def fxa_login_link(response=None, to=None, request=None):
    if request is not None:
        state = request.session['fxa_state']
    elif response is not None:
        state = response.wsgi_request.session['fxa_state']
    else:
        raise RuntimeError('Must specify request or response')
    return fxa_login_url(
        config=settings.FXA_CONFIG['default'],
        state=state,
        next_path=to,
        action='signin')


class TestCase(PatchMixin, InitializeSessionMixin, BaseTestCase):
    """Base class for all amo tests."""
    client_class = TestClient

    @contextmanager
    def activate(self, locale=None, app=None):
        """Active an app or a locale."""
        prefixer = old_prefix = get_url_prefix()
        old_app = old_prefix.app
        old_locale = translation.get_language()
        if locale:
            rf = RequestFactory()
            prefixer = Prefixer(rf.get('/%s/' % (locale,)))
            translation.activate(locale)
        if app:
            prefixer.app = app
        set_url_prefix(prefixer)
        yield
        old_prefix.app = old_app
        set_url_prefix(old_prefix)
        translation.activate(old_locale)

    def assertNoFormErrors(self, response):
        """Asserts that no form in the context has errors.

        If you add this check before checking the status code of the response
        you'll see a more informative error.
        """
        # TODO(Kumar) liberate upstream to Django?
        if response.context is None:
            # It's probably a redirect.
            return
        if len(response.templates) == 1:
            tpl = [response.context]
        else:
            # There are multiple contexts so iter all of them.
            tpl = response.context
        for ctx in tpl:
            for k, v in ctx.iteritems():
                if isinstance(v, (forms.BaseForm, forms.formsets.BaseFormSet)):
                    if isinstance(v, forms.formsets.BaseFormSet):
                        # Concatenate errors from each form in the formset.
                        msg = '\n'.join(f.errors.as_text() for f in v.forms)
                    else:
                        # Otherwise, just return the errors for this form.
                        msg = v.errors.as_text()
                    msg = msg.strip()
                    if msg != '':
                        self.fail('form %r had the following error(s):\n%s'
                                  % (k, msg))
                    if hasattr(v, 'non_field_errors'):
                        assert v.non_field_errors() == []
                    if hasattr(v, 'non_form_errors'):
                        assert v.non_form_errors() == []

    def assertLoginRedirects(self, response, to, status_code=302):
        fxa_url = fxa_login_link(response, to)
        self.assert3xx(
            response=response,
            expected_url=fxa_url,
            status_code=status_code)

    def assert3xx(self, *args, **kwargs):
        """
        Same as Django's assertRedirects but skips the final GET verification
        step for performance reasons and backwards compatibility.
        """
        kwargs.setdefault('fetch_redirect_response', False)
        return self.assertRedirects(*args, **kwargs)

    def assertCloseToNow(self, dt, now=None):
        """
        Make sure the datetime is within a minute from `now`.
        """

        # Try parsing the string if it's not a datetime.
        if isinstance(dt, basestring):
            try:
                dt = dateutil_parser(dt)
            except ValueError as e:
                raise AssertionError(
                    'Expected valid date; got %s\n%s' % (dt, e))

        if not dt:
            raise AssertionError('Expected datetime; got %s' % dt)

        dt_later_ts = time.mktime((dt + timedelta(minutes=1)).timetuple())
        dt_earlier_ts = time.mktime((dt - timedelta(minutes=1)).timetuple())
        if not now:
            now = datetime.now()
        now_ts = time.mktime(now.timetuple())

        assert dt_earlier_ts < now_ts < dt_later_ts, (
            'Expected datetime to be within a minute of %s. Got %r.' % (now,
                                                                        dt))

    def assertQuerySetEqual(self, qs1, qs2):
        """
        Assertion to check the equality of two querysets
        """
        return self.assertSetEqual(qs1.values_list('id', flat=True),
                                   qs2.values_list('id', flat=True))

    def assertCORS(self, res, *verbs):
        """
        Determines if a response has suitable CORS headers. Appends 'OPTIONS'
        on to the list of verbs.
        """
        assert res['Access-Control-Allow-Origin'] == '*'
        assert 'API-Status' in res['Access-Control-Expose-Headers']
        assert 'API-Version' in res['Access-Control-Expose-Headers']

        verbs = map(str.upper, verbs) + ['OPTIONS']
        actual = res['Access-Control-Allow-Methods'].split(', ')
        self.assertSetEqual(verbs, actual)
        assert res['Access-Control-Allow-Headers'] == (
            'X-HTTP-Method-Override, Content-Type')

    def update_session(self, session):
        """
        Update the session on the client. Needed if you manipulate the session
        in the test. Needed when we use signed cookies for sessions.
        """
        cookie = SimpleCookie()
        cookie[settings.SESSION_COOKIE_NAME] = session._get_session_key()
        self.client.cookies.update(cookie)

    def create_sample(self, *args, **kwargs):
        return create_sample(*args, **kwargs)

    def create_switch(self, *args, **kwargs):
        return create_switch(*args, **kwargs)

    def create_flag(self, *args, **kwargs):
        return create_flag(*args, **kwargs)

    def grant_permission(self, user_obj, rules, name='Test Group'):
        """Creates group with rule, and adds user to group."""
        group = Group.objects.create(name=name, rules=rules)
        GroupUser.objects.create(group=group, user=user_obj)

    def days_ago(self, days):
        return days_ago(days)

    def login(self, profile):
        email = getattr(profile, 'email', profile)
        if '@' not in email:
            email += '@mozilla.com'
        assert self.client.login(email=email)

    def assertUrlEqual(self, url, other, compare_host=False):
        """Compare url paths and query strings."""
        assert_url_equal(url, other, compare_host)

    def enable_messages(self, request):
        setattr(request, 'session', 'session')
        messages = FallbackStorage(request)
        setattr(request, '_messages', messages)
        return request

    def make_addon_unlisted(self, addon):
        self.change_channel_for_addon(addon, False)

    def make_addon_listed(self, addon):
        self.change_channel_for_addon(addon, True)

    def change_channel_for_addon(self, addon, listed):
        channel = (amo.RELEASE_CHANNEL_LISTED if listed else
                   amo.RELEASE_CHANNEL_UNLISTED)
        for version in addon.versions.all():
            version.update(channel=channel)


class AMOPaths(object):
    """Mixin for getting common AMO Paths."""

    def file_fixture_path(self, name):
        path = 'src/olympia/files/fixtures/files/%s' % name
        return os.path.join(settings.ROOT, path)

    def xpi_path(self, name):
        if os.path.splitext(name)[-1] not in ['.xml', '.xpi', '.jar']:
            return self.file_fixture_path(name + '.xpi')
        return self.file_fixture_path(name)

    def xpi_copy_over(self, file, name):
        """Copies over a file into place for tests."""
        if not os.path.exists(os.path.dirname(file.file_path)):
            os.makedirs(os.path.dirname(file.file_path))
        shutil.copyfile(self.xpi_path(name), file.file_path)


def _get_created(created):
    """
    Returns a datetime.

    If `created` is "now", it returns `datetime.datetime.now()`. If `created`
    is set use that. Otherwise generate a random datetime in the year 2011.
    """
    if created == 'now':
        return datetime.now()
    elif created:
        return created
    else:
        return datetime(2011,
                        random.randint(1, 12),  # Month
                        random.randint(1, 28),  # Day
                        random.randint(0, 23),  # Hour
                        random.randint(0, 59),  # Minute
                        random.randint(0, 59))  # Seconds


def addon_factory(
        status=amo.STATUS_PUBLIC, version_kw=None, file_kw=None, **kw):
    version_kw = version_kw or {}

    # Disconnect signals until the last save.
    post_save.disconnect(addon_update_search_index, sender=Addon,
                         dispatch_uid='addons.search.index')

    type_ = kw.pop('type', amo.ADDON_EXTENSION)
    popularity = kw.pop('popularity', None)
    persona_id = kw.pop('persona_id', None)
    tags = kw.pop('tags', [])
    users = kw.pop('users', [])
    when = _get_created(kw.pop('created', None))
    category = kw.pop('category', None)
    default_locale = kw.get('default_locale', settings.LANGUAGE_CODE)

    # Keep as much unique data as possible in the uuid: '-' aren't important.
    name = kw.pop('name', u'Addôn %s' % unicode(uuid.uuid4()).replace('-', ''))
    slug = kw.pop('slug', None)
    if slug is None:
        slug = name.replace(' ', '-').lower()[:30]

    kwargs = {
        # Set artificially the status to STATUS_PUBLIC for now, the real
        # status will be set a few lines below, after the update_version()
        # call. This prevents issues when calling addon_factory with
        # STATUS_DELETED.
        'status': amo.STATUS_PUBLIC,
        'default_locale': default_locale,
        'name': name,
        'slug': slug,
        'average_daily_users': popularity or random.randint(200, 2000),
        'weekly_downloads': popularity or random.randint(200, 2000),
        'created': when,
        'last_updated': when,
    }
    if type_ != amo.ADDON_PERSONA:
        # Personas don't have a summary.
        kwargs['summary'] = u'Summary for %s' % name
    if type_ not in [amo.ADDON_PERSONA, amo.ADDON_SEARCH]:
        # Personas and search engines don't need guids
        kwargs['guid'] = kw.pop('guid', '{%s}' % unicode(uuid.uuid4()))
    kwargs.update(kw)

    # Save 1.
    with translation.override(default_locale):
        addon = Addon.objects.create(type=type_, **kwargs)

    # Save 2.
    version = version_factory(file_kw, addon=addon, **version_kw)
    if addon.type == amo.ADDON_PERSONA:
        addon._current_version = version
        persona_id = persona_id if persona_id is not None else addon.id

        # Save 3.
        Persona.objects.create(
            addon=addon, popularity=addon.average_daily_users,
            persona_id=persona_id)

    addon.update_version()
    addon.status = status

    for tag in tags:
        Tag(tag_text=tag).save_tag(addon)

    for user in users:
        addon.addonuser_set.create(user=user)

    application = version_kw.get('application', amo.FIREFOX.id)
    if not category:
        static_category = random.choice(
            CATEGORIES[application][addon.type].values())
        category = Category.from_static_category(static_category, True)
    AddonCategory.objects.create(addon=addon, category=category)

    # Put signals back.
    post_save.connect(addon_update_search_index, sender=Addon,
                      dispatch_uid='addons.search.index')

    # Save 4.
    addon.save()

    if addon.type == amo.ADDON_PERSONA:
        # Personas only have one version and signals.version_changed is never
        # fired for them - instead it gets updated through a cron (!). We do
        # need to get it right in some tests like the ui tests, so we call the
        # task ourselves.
        version_changed(addon.pk)

    # Potentially update is_public on authors
    [user.update_is_public() for user in users]

    if 'nomination' in version_kw:
        # If a nomination date was set on the version, then it might have been
        # erased at post_save by addons.models.watch_status()
        version.save()

    return addon


def collection_factory(**kw):
    data = {
        'type': amo.COLLECTION_NORMAL,
        'application': amo.FIREFOX.id,
        'name': 'Collection %s' % abs(hash(datetime.now())),
        'description': 'Its a collection %s' % abs(hash(datetime.now())),
        'addon_count': random.randint(200, 2000),
        'subscribers': random.randint(1000, 5000),
        'monthly_subscribers': random.randint(100, 500),
        'weekly_subscribers': random.randint(10, 50),
        'upvotes': random.randint(100, 500),
        'downvotes': random.randint(100, 500),
        'listed': True,
    }
    data.update(kw)
    c = Collection(**data)
    if c.slug is None:
        c.slug = data['name'].replace(' ', '-').lower()
    c.rating = (c.upvotes - c.downvotes) * math.log(c.upvotes + c.downvotes)
    c.created = c.modified = datetime(2011, 11, 11, random.randint(0, 23),
                                      random.randint(0, 59))
    c.save()
    return c


def license_factory(**kw):
    data = {
        'name': {
            'en-US': u'My License',
            'fr': u'Mä Licence',
        },
        'text': {
            'en-US': u'Lorem ipsum dolor sit amet, has nemore patrioqué',
        },
        'url': 'http://license.example.com/',
    }
    data.update(**kw)
    return License.objects.create(**data)


def file_factory(**kw):
    version = kw['version']
    filename = kw.pop('filename', '%s-%s' % (version.addon_id, version.id))
    status = kw.pop('status', amo.STATUS_PUBLIC)
    platform = kw.pop('platform', amo.PLATFORM_ALL.id)
    file_ = File.objects.create(filename=filename,
                                platform=platform, status=status, **kw)
    return file_


def req_factory_factory(url, user=None, post=False, data=None, session=None):
    """Creates a request factory, logged in with the user."""
    req = RequestFactory()
    if post:
        req = req.post(url, data or {})
    else:
        req = req.get(url, data or {})
    if user:
        req.user = UserProfile.objects.get(id=user.id)
    else:
        req.user = AnonymousUser()
    if session is not None:
        req.session = session
    req.APP = None
    req.check_ownership = partial(check_ownership, req)
    return req


user_factory_counter = 0


def user_factory(**kw):
    global user_factory_counter
    username = kw.pop('username', u'factoryûser%d' % user_factory_counter)
    email = kw.pop(
        'email', u'factoryuser%d@mozîlla.com' % user_factory_counter)
    user = UserProfile.objects.create(username=username, email=email, **kw)

    if 'username' not in kw:
        user_factory_counter = user.id + 1
    return user


def version_factory(file_kw=None, **kw):
    # We can't create duplicates of AppVersions, so make sure the versions are
    # not already created in fixtures (use fake versions).
    addon_type = getattr(kw.get('addon'), 'type', None)
    min_app_version = kw.pop('min_app_version', '4.0.99')
    max_app_version = kw.pop('max_app_version', '5.0.99')
    version_str = kw.pop('version', '%.1f' % random.uniform(0, 2))
    application = kw.pop('application', amo.FIREFOX.id)
    if not kw.get('license') and not kw.get('license_id'):
        # Is there a built-in one we can use?
        builtins = License.objects.builtins()
        if builtins.exists():
            kw['license_id'] = builtins[0].id
        else:
            license_kw = {'builtin': 99}
            license_kw.update(kw.get('license_kw', {}))
            kw['license'] = license_factory(**license_kw)
    ver = Version.objects.create(version=version_str, **kw)
    ver.created = ver.last_updated = _get_created(kw.pop('created', 'now'))
    ver.save()
    if addon_type not in amo.NO_COMPAT:
        av_min, _ = AppVersion.objects.get_or_create(application=application,
                                                     version=min_app_version)
        av_max, _ = AppVersion.objects.get_or_create(application=application,
                                                     version=max_app_version)
        ApplicationsVersions.objects.get_or_create(application=application,
                                                   version=ver, min=av_min,
                                                   max=av_max)
    if addon_type != amo.ADDON_PERSONA and file_kw is not False:
        file_kw = file_kw or {}
        file_factory(version=ver, **file_kw)
    return ver


@pytest.mark.es_tests
class ESTestCase(TestCase):
    @classmethod
    def get_index_name(cls, key):
        return get_es_index_name(key)

    def setUp(self):
        stop_es_mocks()
        super(ESTestCase, self).setUp()

    @classmethod
    def setUpClass(cls):
        stop_es_mocks()
        cls.es = amo_search.get_es(timeout=settings.ES_TIMEOUT)
        cls._SEARCH_ANALYZER_MAP = amo.SEARCH_ANALYZER_MAP
        amo.SEARCH_ANALYZER_MAP = {
            'english': ['en-us'],
            'spanish': ['es'],
        }
        super(ESTestCase, cls).setUpClass()

    @classmethod
    def setUpTestData(cls):
        stop_es_mocks()
        setup_es_test_data(cls.es)

        super(ESTestCase, cls).setUpTestData()

    @classmethod
    def tearDownClass(cls):
        amo.SEARCH_ANALYZER_MAP = cls._SEARCH_ANALYZER_MAP
        super(ESTestCase, cls).tearDownClass()

    @classmethod
    def refresh(cls, index='default'):
        cls.es.indices.refresh(settings.ES_INDEXES[index])

    @classmethod
    def reindex(cls, model, index='default'):
        # Emit post-save signal so all of the objects get reindexed.
        manager = getattr(model, 'unfiltered', model.objects)
        [post_save.send(
            model, instance=o, created=False) for o in manager.all()]
        cls.refresh(index)

    @classmethod
    def empty_index(cls, index):
        # Try to make sure that all changes are properly flushed.
        cls.refresh()
        cls.es.delete_by_query(
            settings.ES_INDEXES[index],
            body={'query': {'match_all': {}}},
            conflicts='proceed',
        )


class ESTestCaseWithAddons(ESTestCase):

    @classmethod
    def setUpTestData(cls):
        super(ESTestCaseWithAddons, cls).setUpTestData()
        # Load the fixture here, to not be overloaded by a child class'
        # fixture attribute.
        call_command('loaddata', 'addons/base_es')
        addon_ids = [1, 2, 3, 4, 5, 6]  # From the addons/base_es fixture.
        cls._addons = list(Addon.objects.filter(pk__in=addon_ids)
                           .order_by('id'))
        from olympia.addons.tasks import index_addons
        index_addons(addon_ids)
        # Refresh ES.
        cls.refresh()

    @classmethod
    def tearDownClass(cls):
        try:
            unindex_addons([a.id for a in cls._addons])
            cls._addons = []
        finally:
            super(ESTestCaseWithAddons, cls).tearDownClass()


class TestXss(TestCase):
    fixtures = ['base/addon_3615', 'users/test_backends', ]

    def setUp(self):
        super(TestXss, self).setUp()
        self.addon = Addon.objects.get(id=3615)
        self.name = "<script>alert('hé')</script>"
        self.escaped = (
            "&lt;script&gt;alert(&#39;h\xc3\xa9&#39;)&lt;/script&gt;")
        self.addon.name = self.name
        self.addon.save()
        u = UserProfile.objects.get(email='del@icio.us')
        GroupUser.objects.create(group=Group.objects.get(name='Admins'),
                                 user=u)
        self.client.login(email='del@icio.us')

    def assertNameAndNoXSS(self, url):
        response = self.client.get(url)
        assert self.name not in response.content
        assert self.escaped in response.content


@contextmanager
def copy_file(source, dest, overwrite=False):
    """Context manager that copies the source file to the destination.

    The files are relative to the root folder (containing the settings file).

    The copied file is removed on exit."""
    source = os.path.join(settings.ROOT, source)
    dest = os.path.join(settings.ROOT, dest)
    if not overwrite:
        assert not os.path.exists(dest)
    if not os.path.exists(os.path.dirname(dest)):
        os.makedirs(os.path.dirname(dest))
    shutil.copyfile(source, dest)
    yield
    if os.path.exists(dest):
        os.unlink(dest)


@contextmanager
def copy_file_to_temp(source):
    """Context manager that copies the source file to a temporary destination.

    The files are relative to the root folder (containing the settings file).
    The temporary file is yielded by the context manager.

    The copied file is removed on exit."""
    temp_filename = get_temp_filename()
    with copy_file(source, temp_filename):
        yield temp_filename


# This sets up a module that we can patch dynamically with URLs.
@override_settings(ROOT_URLCONF='olympia.amo.tests.dynamic_urls')
class WithDynamicEndpoints(TestCase):
    """
    Mixin to allow registration of ad-hoc views.
    """

    def endpoint(self, view, url_regex=None):
        """
        Register a view function or view class temporarily
        as the handler for requests to /dynamic-endpoint
        """
        url_regex = url_regex or r'^dynamic-endpoint$'
        try:
            is_class = issubclass(view, APIView)
        except TypeError:
            is_class = False
        if is_class:
            view = view.as_view()

        dynamic_urls.urlpatterns = [django_urls.url(url_regex, view)]

        self.addCleanup(self._clean_up_dynamic_urls)

    def _clean_up_dynamic_urls(self):
        dynamic_urls.urlpatterns = []


def get_temp_filename():
    """Get a unique, non existing, temporary filename."""
    with NamedTemporaryFile(dir=settings.TMP_PATH) as tempfile:
        return tempfile.name


def safe_exec(string, value=None, globals_=None, locals_=None):
    """Safely execute python code.

    This is used to test custom migrations.
    Copied and adapted from django/tests/migrations/test_writer.py
    """
    locals_ = locals_ or {}
    try:
        exec(force_str(string), globals_ or globals(), locals_)
    except Exception as e:
        if value:
            raise AssertionError(
                'Could not exec %r (from value %r): %s'
                % (string.strip(), value, e))
        else:
            raise AssertionError('Could not exec %r: %s' % (string.strip(), e))
    return locals_


def prefix_indexes(config):
    """Prefix all ES index names and cache keys with `test_` and, if running
    under xdist, the ID of the current slave.

    Note that this is a pytest helper that is primarily used in conftest.
    """
    if hasattr(config, 'slaveinput'):
        prefix = 'test_{[slaveid]}'.format(config.slaveinput)
    else:
        prefix = 'test'

    # Ideally, this should be a session-scoped fixture that gets injected into
    # any test that requires ES. This would be especially useful, as it would
    # allow xdist to transparently group all ES tests into a single process.
    # Unfurtunately, it's surprisingly difficult to achieve with our current
    # unittest-based setup.

    for key, index in settings.ES_INDEXES.items():
        if not index.startswith(prefix):
            settings.ES_INDEXES[key] = '{prefix}_amo_{index}'.format(
                prefix=prefix, index=index)

    settings.CACHE_PREFIX = 'amo:{0}:'.format(prefix)
    settings.KEY_PREFIX = settings.CACHE_PREFIX
