import math
import os
import random
import shutil
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import partial, wraps
from urlparse import urlsplit, urlunsplit

from django import forms
from django.conf import settings
from django.core.cache import cache
from django.db.models.signals import post_save
from django.forms.fields import Field
from django.http import SimpleCookie
from django.test.client import Client
from django.utils import translation

import caching
import mock
import test_utils
import tower
from dateutil.parser import parse as dateutil_parser
from nose.exc import SkipTest
from nose.tools import eq_, nottest
from pyquery import PyQuery as pq
from redisutils import mock_redis, reset_redis
from test_utils import RequestFactory
from waffle import cache_sample, cache_switch
from waffle.models import Flag, Sample, Switch

from access.acl import check_ownership
import addons.search
import amo
import amo.search
import stats.search
from access.models import Group, GroupUser
from addons.models import (Addon, Persona,
                           update_search_index as addon_update_search_index)
from addons.tasks import unindex_addons
from amo.urlresolvers import get_url_prefix, Prefixer, reverse, set_url_prefix
from applications.models import Application, AppVersion
from bandwagon.models import Collection
from files.models import File, Platform
from lib.es.signals import process, reset
from translations.hold import clean_translations
from translations.models import Translation
from versions.models import ApplicationsVersions, Version
from users.models import RequestUser, UserProfile


# We might now have gettext available in jinja2.env.globals when running tests.
# It's only added to the globals when activating a language with tower (which
# is usually done in the middlewares). During tests, however, we might not be
# running middlewares, and thus not activating a language, and thus not
# installing gettext in the globals, and thus not have it in the context when
# rendering templates.
tower.activate('en')


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


def assert_required(error_msg):
    eq_(error_msg, unicode(Field.default_error_messages['required']))


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
            eq_(e.text(), text)
        if link is not None:
            # If we passed an <li>, try to find an <a>.
            if not e.filter('a'):
                e = e.find('a')
            eq_(e.attr('href'), link)
            if verify and link != '#':
                eq_(Client().head(link, follow=True).status_code, 200,
                    '%r is dead' % link)
        if text is not None and selected is not None:
            e = e.filter('.selected, .sel') or e.parents('.selected, .sel')
            eq_(bool(e.length), text == selected)


def check_selected(expected, links, selected):
    check_links(expected, links, verify=True, selected=selected)


class RedisTest(object):
    """Mixin for when you need to mock redis for testing."""

    def _pre_setup(self):
        self._redis = mock_redis()
        super(RedisTest, self)._pre_setup()

    def _post_teardown(self):
        super(RedisTest, self)._post_teardown()
        reset_redis(self._redis)


class MobileTest(object):
    """Mixing for when you want to hit a mobile view."""

    def _pre_setup(self):
        super(MobileTest, self)._pre_setup()
        MobileTest._mobile_init(self)

    def mobile_init(self):
        MobileTest._mobile_init(self)

    # This is a static method so we can call it in @mobile_test.
    @staticmethod
    def _mobile_init(self):
        self.client.cookies['mamo'] = 'on'
        self.client.defaults['SERVER_NAME'] = settings.MOBILE_DOMAIN
        self.request = mock.Mock()
        self.MOBILE = self.request.MOBILE = True


@nottest
def mobile_test(f):
    """Test decorator for hitting mobile views."""
    @wraps(f)
    def wrapper(self, *args, **kw):
        MobileTest._mobile_init(self)
        return f(self, *args, **kw)
    return wrapper


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


Mocked_ES = mock.patch('amo.search.get_es', spec=True)


def mock_es(f):
    """
    Test decorator for mocking elasticsearch calls in ESTestCase if we don't
    care about ES results.
    """
    @wraps(f)
    def decorated(request, *args, **kwargs):
        Mocked_ES.start()
        try:
            return f(request, *args, **kwargs)
        finally:
            Mocked_ES.stop()
    return decorated


def days_ago(days):
    return datetime.now().replace(microsecond=0) - timedelta(days=days)


class MockEsMixin(object):
    mock_es = True

    @classmethod
    def setUpClass(cls):
        if cls.mock_es:
            Mocked_ES.start()
        try:
            reset.send(None)  # Reset all the ES tasks on hold.
            super(MockEsMixin, cls).setUpClass()
        except Exception:
            # We need to unpatch here because tearDownClass will not be
            # called.
            if cls.mock_es:
                Mocked_ES.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            super(MockEsMixin, cls).tearDownClass()
        finally:
            if cls.mock_es:
                Mocked_ES.stop()


class TestCase(MockEsMixin, RedisTest, test_utils.TestCase):
    """Base class for all amo tests."""
    client_class = TestClient

    def shortDescription(self):
        # Stop nose using the test docstring and instead the test method name.
        pass

    def _post_teardown(self):
        amo.set_user(None)
        clean_translations(None)  # Make sure queued translations are removed.
        super(TestCase, self)._post_teardown()

    def _pre_setup(self):
        super(TestCase, self)._pre_setup()
        cache.clear()
        # Override django-cache-machine caching.base.TIMEOUT because it's
        # computed too early, before settings_test.py is imported.
        caching.base.TIMEOUT = settings.CACHE_COUNT_TIMEOUT

    @contextmanager
    def activate(self, locale=None, app=None):
        """Active an app or a locale."""
        prefixer = old_prefix = get_url_prefix()
        old_app = old_prefix.app
        old_locale = translation.get_language()
        if locale:
            rf = test_utils.RequestFactory()
            prefixer = Prefixer(rf.get('/%s/' % (locale,)))
            tower.activate(locale)
        if app:
            prefixer.app = app
        set_url_prefix(prefixer)
        yield
        old_prefix.app = old_app
        set_url_prefix(old_prefix)
        tower.activate(old_locale)

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
                        self.assertEquals(v.non_field_errors(), [])
                    if hasattr(v, 'non_form_errors'):
                        self.assertEquals(v.non_form_errors(), [])

    def assertLoginRedirects(self, response, to, status_code=302):
        # Not using urlparams, because that escapes the variables, which
        # is good, but bad for assertRedirects which will fail.
        self.assert3xx(response,
            '%s?to=%s' % (reverse('users.login'), to), status_code)

    def assert3xx(self, response, expected_url, status_code=302,
                  target_status_code=200):
        """Asserts redirect and final redirect matches expected URL.

        Similar to Django's `assertRedirects` but skips the final GET
        verification for speed.

        """
        if hasattr(response, 'redirect_chain'):
            # The request was a followed redirect
            self.assertTrue(len(response.redirect_chain) > 0,
                "Response didn't redirect as expected: Response"
                " code was %d (expected %d)" %
                    (response.status_code, status_code))

            url, status_code = response.redirect_chain[-1]

            self.assertEqual(response.status_code, target_status_code,
                "Response didn't redirect as expected: Final"
                " Response code was %d (expected %d)" %
                    (response.status_code, target_status_code))

        else:
            # Not a followed redirect
            self.assertEqual(response.status_code, status_code,
                "Response didn't redirect as expected: Response"
                " code was %d (expected %d)" %
                    (response.status_code, status_code))
            url = response['Location']

        scheme, netloc, path, query, fragment = urlsplit(url)
        e_scheme, e_netloc, e_path, e_query, e_fragment = urlsplit(
            expected_url)
        if (scheme and not e_scheme) and (netloc and not e_netloc):
            expected_url = urlunsplit(('http', 'testserver', e_path, e_query,
                                       e_fragment))

        self.assertEqual(url, expected_url,
            "Response redirected to '%s', expected '%s'" % (url, expected_url))

    def assertLoginRequired(self, response, status_code=302):
        """
        A simpler version of assertLoginRedirects that just checks that we
        get the matched status code and bounced to the correct login page.
        """
        assert response.status_code == status_code, (
                'Response returned: %s, expected: %s'
                % (response.status_code, status_code))

        path = urlsplit(response['Location'])[2]
        assert path == reverse('users.login'), (
                'Redirected to: %s, expected: %s'
                % (path, reverse('users.login')))

    def assertSetEqual(self, a, b, message=None):
        """
        This is a thing in unittest in 2.7,
        but until then this is the thing.

        Oh, and Django's `assertSetEqual` is lame and requires actual sets:
        http://bit.ly/RO9sTr
        """
        eq_(set(a), set(b), message)
        eq_(len(a), len(b), message)

    def assertCloseToNow(self, dt, now=None):
        """
        Make sure the datetime is within a minute from `now`.
        """

        # Try parsing the string if it's not a datetime.
        if isinstance(dt, basestring):
            try:
                dt = dateutil_parser(dt)
            except ValueError, e:
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
        eq_(res['Access-Control-Allow-Origin'], '*')
        assert 'API-Status' in res['Access-Control-Expose-Headers']
        assert 'API-Version' in res['Access-Control-Expose-Headers']

        verbs = map(str.upper, verbs) + ['OPTIONS']
        actual = res['Access-Control-Allow-Methods'].split(', ')
        self.assertSetEqual(verbs, actual)
        eq_(res['Access-Control-Allow-Headers'],
            'X-HTTP-Method-Override, Content-Type')

    def update_session(self, session):
        """
        Update the session on the client. Needed if you manipulate the session
        in the test. Needed when we use signed cookies for sessions.
        """
        cookie = SimpleCookie()
        cookie[settings.SESSION_COOKIE_NAME] = session._get_session_key()
        self.client.cookies.update(cookie)

    def create_sample(self, name=None, db=False, **kw):
        if name is not None:
            kw['name'] = name
        kw.setdefault('percent', 100)
        sample = Sample(**kw)
        sample.save() if db else cache_sample(instance=sample)
        return sample

    def create_switch(self, name=None, db=False, **kw):
        kw.setdefault('active', True)
        if name is not None:
            kw['name'] = name
        switch = Switch(**kw)
        switch.save() if db else cache_switch(instance=switch)
        return switch

    def create_flag(self, name=None, **kw):
        if name is not None:
            kw['name'] = name
        kw.setdefault('everyone', True)
        return Flag.objects.create(**kw)

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
        assert self.client.login(username=email, password='password')

    def trans_eq(self, trans, locale, localized_string):
        eq_(Translation.objects.get(id=trans.id,
                                    locale=locale).localized_string,
            localized_string)

    def extract_script_template(self, html, template_selector):
        """Extracts the inner JavaScript text/template from a html page.

        Example::

            >>> template = extract_script_template(res.content, '#template-id')
            >>> template('#my-jquery-selector')

        Returns a PyQuery object that you can refine using jQuery selectors.
        """
        return pq(pq(html)(template_selector).html())


class AMOPaths(object):
    """Mixin for getting common AMO Paths."""

    def file_fixture_path(self, name):
        path = 'apps/files/fixtures/files/%s' % name
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


def assert_no_validation_exceptions(validation):
    """Assert that the validation (JSON) does not contain a traceback.

    Note that this does not test whether the addon passed
    validation or not.
    """
    if hasattr(validation, 'task_error'):
        # FileUpload object:
        error = validation.task_error
    else:
        # Upload detail - JSON output
        error = validation['error']
    if error:
        print '-' * 70
        print error
        print '-' * 70
        raise AssertionError("Unexpected task error: %s" %
                             error.rstrip().split("\n")[-1])


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


def addon_factory(status=amo.STATUS_PUBLIC, version_kw={}, file_kw={}, **kw):
    # Disconnect signals until the last save.
    post_save.disconnect(addon_update_search_index, sender=Addon,
                         dispatch_uid='addons.search.index')

    type_ = kw.pop('type', amo.ADDON_EXTENSION)
    popularity = kw.pop('popularity', None)
    when = _get_created(kw.pop('created', None))

    # Keep as much unique data as possible in the uuid: '-' aren't important.
    name = kw.pop('name', u'Addon %s' % unicode(uuid.uuid4()).replace('-', ''))

    kwargs = {
        # Set artificially the status to STATUS_PUBLIC for now, , the real
        # status will be set a few lines below, after the update_version()
        # call. This prevents issues when calling addon_factory with
        # STATUS_DELETED.
        'status': amo.STATUS_PUBLIC,
        'name': name,
        'slug': name.replace(' ', '-').lower()[:30],
        'bayesian_rating': random.uniform(1, 5),
        'average_daily_users': popularity or random.randint(200, 2000),
        'weekly_downloads': popularity or random.randint(200, 2000),
        'created': when,
        'last_updated': when,
    }
    kwargs.update(kw)

    # Save 1.
    if type_ == amo.ADDON_PERSONA:
        # Personas need to start life as an extension for versioning.
        a = Addon.objects.create(type=amo.ADDON_EXTENSION, **kwargs)
    else:
        a = Addon.objects.create(type=type_, **kwargs)
    version = version_factory(file_kw, addon=a, **version_kw)  # Save 2.
    a.update_version()
    a.status = status
    if type_ == amo.ADDON_PERSONA:
        a.type = type_
        Persona.objects.create(addon=a, persona_id=a.id,
                               popularity=a.weekly_downloads)  # Save 3.

    # Put signals back.
    post_save.connect(addon_update_search_index, sender=Addon,
                      dispatch_uid='addons.search.index')

    a.save()  # Save 4.

    if 'nomination' in version_kw:
        # If a nomination date was set on the version, then it might have been
        # erased at post_save by addons.models.watch_status()
        version.save()
    return a


def collection_factory(**kw):
    data = {
        'type': amo.COLLECTION_NORMAL,
        'application_id': amo.FIREFOX.id,
        'name': 'Collection %s' % abs(hash(datetime.now())),
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
    c.slug = data['name'].replace(' ', '-').lower()
    c.rating = (c.upvotes - c.downvotes) * math.log(c.upvotes + c.downvotes)
    c.created = c.modified = datetime(2011, 11, 11, random.randint(0, 23),
                                      random.randint(0, 59))
    c.save()
    return c


def file_factory(**kw):
    v = kw['version']
    p, _ = Platform.objects.get_or_create(id=amo.PLATFORM_ALL.id)
    status = kw.pop('status', amo.STATUS_PUBLIC)
    f = File.objects.create(filename='%s-%s' % (v.addon_id, v.id),
                            platform=p, status=status, **kw)
    return f


def req_factory_factory(url, user=None, post=False, data=None):
    """Creates a request factory, logged in with the user."""
    req = RequestFactory()
    if post:
        req = req.post(url, data or {})
    else:
        req = req.get(url, data or {})
    if user:
        req.amo_user = RequestUser.objects.get(id=user.id)
        req.user = user
        req.groups = user.groups.all()
    req.APP = None
    req.check_ownership = partial(check_ownership, req)
    return req


user_factory_counter = 0


def user_factory(**kw):
    global user_factory_counter
    username = kw.pop('username', 'factoryuser%d' % user_factory_counter)

    user = UserProfile.objects.create(
        username=username, email='%s@mozilla.com' % username, **kw)

    if 'username' not in kw:
        user_factory_counter = user.id + 1
    return user


def version_factory(file_kw={}, **kw):
    # We can't create duplicates of AppVersions, so make sure the versions are
    # not already created in fixtures (use fake versions).
    min_app_version = kw.pop('min_app_version', '4.0.99')
    max_app_version = kw.pop('max_app_version', '5.0.99')
    version = kw.pop('version', '%.1f' % random.uniform(0, 2))
    v = Version.objects.create(version=version, **kw)
    v.created = v.last_updated = _get_created(kw.pop('created', 'now'))
    v.save()
    if kw.get('addon').type != amo.ADDON_PERSONA:
        a, _ = Application.objects.get_or_create(id=amo.FIREFOX.id)
        av_min, _ = AppVersion.objects.get_or_create(application=a,
                                                     version=min_app_version)
        av_max, _ = AppVersion.objects.get_or_create(application=a,
                                                     version=max_app_version)
        ApplicationsVersions.objects.get_or_create(application=a, version=v,
                                                   min=av_min, max=av_max)
    file_factory(version=v, **file_kw)
    return v


class ESTestCase(TestCase):
    """Base class for tests that require elasticsearch."""
    # ES is slow to set up so this uses class setup/teardown. That happens
    # outside Django transactions so be careful to clean up afterwards.
    test_es = True
    mock_es = False
    exempt_from_fixture_bundling = True  # ES doesn't support bundling (yet?)

    @classmethod
    def setUpClass(cls):
        if not settings.RUN_ES_TESTS:
            raise SkipTest('ES disabled')
        cls.es = amo.search.get_es(timeout=settings.ES_TIMEOUT)

        # The ES setting are set before we call super()
        # because we may have indexation occuring in upper classes.
        for key, index in settings.ES_INDEXES.items():
            if not index.startswith('test_'):
                settings.ES_INDEXES[key] = 'test_%s_%s' % ('amo', index)

        super(ESTestCase, cls).setUpClass()
        try:
            cls.es.cluster.health()
        except Exception, e:
            e.args = tuple([u'%s (it looks like ES is not running, '
                            'try starting it or set RUN_ES_TESTS=False)'
                            % e.args[0]] + list(e.args[1:]))
            raise

        cls._SEARCH_ANALYZER_MAP = amo.SEARCH_ANALYZER_MAP
        amo.SEARCH_ANALYZER_MAP = {
            'english': ['en-us'],
            'spanish': ['es'],
        }

        for index in set(settings.ES_INDEXES.values()):
            cls.es.indices.delete(index, ignore=[404])

        addons.search.create_new_index()
        stats.search.create_new_index()

    @classmethod
    def tearDownClass(cls):
        try:
            if hasattr(cls, '_addons'):
                Addon.objects.filter(
                    pk__in=[a.id for a in cls._addons]).delete()
                unindex_addons([a.id for a in cls._addons])
            amo.SEARCH_ANALYZER_MAP = cls._SEARCH_ANALYZER_MAP
        finally:
            # Make sure we're calling super's tearDownClass even if something
            # went wrong in the code above, as otherwise we'd run into bug
            # 960598.
            super(ESTestCase, cls).tearDownClass()

    @classmethod
    def setUpIndex(cls):
        cls.add_addons()
        cls.refresh()

    @classmethod
    def send(cls):
        # Send all the ES tasks on hold.
        process.send(None)

    @classmethod
    def refresh(cls, index='default', timesleep=0):
        process.send(None)
        cls.es.indices.refresh(settings.ES_INDEXES[index])

    @classmethod
    def reindex(cls, model, index='default'):
        # Emit post-save signal so all of the objects get reindexed.
        [o.save() for o in model.objects.all()]
        cls.refresh(index)

    @classmethod
    def add_addons(cls):
        cls._addons = [
            addon_factory(name='user-disabled', disabled_by_user=True),
            addon_factory(name='admin-disabled', status=amo.STATUS_DISABLED),
            addon_factory(status=amo.STATUS_UNREVIEWED),
            addon_factory(),
            addon_factory(),
            addon_factory(),
        ]

    @classmethod
    def empty_index(cls, index):
        cls.es.delete_by_query(
            settings.ES_INDEXES[index],
            body={"query": {"match_all": {}}}
        )
