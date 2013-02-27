import math
import os
import random
import shutil
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import partial, wraps
from urlparse import urlsplit, urlunsplit

from django import forms
from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage as storage
from django.forms.fields import Field
from django.test.client import Client
from django.utils import translation

import elasticutils.contrib.django as elasticutils
import mock
import pyes.exceptions as pyes
import test_utils
from nose.exc import SkipTest
from nose.tools import eq_, nottest
from redisutils import mock_redis, reset_redis
from waffle import cache_sample, cache_switch
from waffle.models import Flag, Sample, Switch

import addons.search
import amo
import stats.search
from access.models import Group, GroupUser
from addons.models import Addon, AddonCategory, Category, Persona
from amo.urlresolvers import get_url_prefix, Prefixer, reverse, set_url_prefix
from applications.models import Application, AppVersion
from bandwagon.models import Collection
from files.helpers import copyfileobj
from files.models import File, Platform
from lib.es.signals import reset, process
from market.models import AddonPremium, Price, PriceCurrency
from translations.models import Translation
from versions.models import ApplicationsVersions, Version

import mkt
from mkt.webapps.models import ContentRating
from mkt.zadmin.models import FeaturedApp, FeaturedAppRegion


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


ES_patchers = [mock.patch('elasticutils.get_es', spec=True),
               mock.patch('elasticutils.contrib.django', spec=True)]


def start_es_mock():
    for patch in ES_patchers:
        patch.start()


def stop_es_mock():
    for patch in ES_patchers:
        patch.stop()

    if hasattr(elasticutils._local, 'es'):
        delattr(elasticutils._local, 'es')


def mock_es(f):
    """
    Test decorator for mocking elasticsearch calls in ESTestCase if we don't
    care about ES results.
    """
    @wraps(f)
    def decorated(request, *args, **kwargs):
        start_es_mock()
        try:
            return f(request, *args, **kwargs)
        finally:
            stop_es_mock()
    return decorated


def days_ago(days):
    return datetime.now() - timedelta(days=days)


class TestCase(RedisTest, test_utils.TestCase):
    """Base class for all amo tests."""
    client_class = TestClient
    mock_es = True

    def shortDescription(self):
        # Stop nose using the test docstring and instead the test method name.
        pass

    @classmethod
    def setUpClass(cls):
        if cls.mock_es:
            start_es_mock()
        try:
            reset.send(None)  # Reset all the ES tasks on hold.
            super(TestCase, cls).setUpClass()
        except Exception:
            # We need to unpatch here because tearDownClass will not be
            # called.
            if cls.mock_es:
                stop_es_mock()
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            super(TestCase, cls).tearDownClass()
        finally:
            if cls.mock_es:
                stop_es_mock()

    def _pre_setup(self):
        super(TestCase, self)._pre_setup()
        cache.clear()

    @contextmanager
    def activate(self, locale=None, app=None):
        """Active an app or a locale."""
        prefixer = old_prefix = get_url_prefix()
        old_app = old_prefix.app
        old_locale = translation.get_language()
        if locale:
            rf = test_utils.RequestFactory()
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
                if (isinstance(v, forms.BaseForm) or
                    isinstance(v, forms.formsets.BaseFormSet)):
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

        Oh, and Dyango's `assertSetEqual` is lame and requires actual sets:
        http://bit.ly/RO9sTr
        """
        eq_(set(a), set(b), message)
        eq_(len(a), len(b), message)

    def assertCloseToNow(self, dt, now=None):
        """
        Make sure the datetime is within a minute from `now`.
        """
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

    def make_premium(self, addon, price='1.00', currencies=None):
        price_obj = Price.objects.create(price=price)
        if currencies:
            for currency in currencies:
                PriceCurrency.objects.create(currency=currency,
                                             price=price, tier=price_obj)
        addon.update(premium_type=amo.ADDON_PREMIUM)
        AddonPremium.objects.create(addon=addon, price=price_obj)

    def make_featured(self, app, category=None, region=mkt.regions.US):
        f = FeaturedApp.objects.create(app=app, category=category)
        # Feature in some specific region.
        FeaturedAppRegion.objects.create(featured_app=f, region=region.id)
        return f

    def create_sample(self, name=None, db=False, **kw):
        if name is not None:
            kw['name'] = name
        kw.setdefault('percent', 100)
        sample = Sample(**kw)
        sample.save() if db else cache_sample(instance=sample)

    def create_switch(self, name=None, db=False, **kw):
        kw.setdefault('active', True)
        if name is not None:
            kw['name'] = name
        switch = Switch(**kw)
        switch.save() if db else cache_switch(instance=switch)

    def create_flag(self, name=None, **kw):
        if name is not None:
            kw['name'] = name
        kw.setdefault('everyone', True)
        Flag.objects.create(**kw)

    def skip_if_disabled(self, setting):
        """Skips a test if a particular setting is disabled."""
        if not setting:
            raise SkipTest('Skipping since setting is disabled')

    def grant_permission(self, user_obj, rules, name='Test Group'):
        """Creates group with rule, and adds user to group."""
        group = Group.objects.create(name=name, rules=rules)
        GroupUser.objects.create(group=group, user=user_obj)

    def days_ago(self, days):
        return days_ago(days)

    def login(self, profile):
        assert self.client.login(username=profile.email, password='password')

    def trans_eq(self, trans, locale, localized_string):
        eq_(Translation.objects.get(id=trans.id,
                                    locale=locale).localized_string,
            localized_string)


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

    def manifest_path(self, name):
        return os.path.join(settings.ROOT,
                            'mkt/submit/tests/webapps/%s' % name)

    def manifest_copy_over(self, dest, name):
        with storage.open(dest, 'wb') as f:
            copyfileobj(open(self.manifest_path(name)), f)

    @staticmethod
    def sample_key():
        return os.path.join(settings.ROOT,
                            'mkt/webapps/tests/sample.key')

    def sample_packaged_key(self):
        return os.path.join(settings.ROOT,
                            'mkt/webapps/tests/sample.packaged.pem')

    def mozball_image(self):
        return os.path.join(settings.ROOT,
                            'mkt/developers/tests/addons/mozball-128.png')

    def preview_image(self):
        return os.path.join(settings.ROOT,
                            'apps/amo/tests/images/preview.jpg')

    def packaged_app_path(self, name):
        return os.path.join(
            settings.ROOT, 'mkt/submit/tests/packaged/%s' % name)

    def packaged_copy_over(self, dest, name):
        with storage.open(dest, 'wb') as f:
            copyfileobj(open(self.packaged_app_path(name)), f)


def assert_no_validation_errors(validation):
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


def app_factory(**kw):
    kw.update(type=amo.ADDON_WEBAPP)
    return amo.tests.addon_factory(**kw)


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


def addon_factory(version_kw={}, file_kw={}, **kw):
    type_ = kw.pop('type', amo.ADDON_EXTENSION)
    popularity = kw.pop('popularity', None)
    # Save 1.
    if type_ == amo.ADDON_PERSONA:
        # Personas need to start life as an extension for versioning
        a = Addon.objects.create(type=amo.ADDON_EXTENSION)
    else:
        a = Addon.objects.create(type=type_)
    a.status = amo.STATUS_PUBLIC
    a.name = name = 'Addon %s' % a.id
    a.slug = name.replace(' ', '-').lower()
    a.bayesian_rating = random.uniform(1, 5)
    a.average_daily_users = popularity or random.randint(200, 2000)
    a.weekly_downloads = popularity or random.randint(200, 2000)
    a.created = a.last_updated = _get_created(kw.pop('created', None))
    version_factory(file_kw, addon=a, **version_kw)  # Save 2.
    a.update_version()
    a.status = amo.STATUS_PUBLIC
    for key, value in kw.items():
        setattr(a, key, value)
    if type_ == amo.ADDON_PERSONA:
        a.type = type_
        Persona.objects.create(addon_id=a.id, persona_id=a.id,
                               popularity=a.weekly_downloads)  # Save 3.
    a.save()  # Save 4.
    return a


def version_factory(file_kw={}, **kw):
    min_app_version = kw.pop('min_app_version', '4.0')
    max_app_version = kw.pop('max_app_version', '5.0')
    version = kw.pop('version', '%.1f' % random.uniform(0, 2))
    v = Version.objects.create(version=version, **kw)
    v.created = v.last_updated = _get_created(kw.pop('created', 'now'))
    v.save()
    if kw.get('addon').type not in (amo.ADDON_PERSONA, amo.ADDON_WEBAPP):
        a, _ = Application.objects.get_or_create(id=amo.FIREFOX.id)
        av_min, _ = AppVersion.objects.get_or_create(application=a,
                                                     version=min_app_version)
        av_max, _ = AppVersion.objects.get_or_create(application=a,
                                                     version=max_app_version)
        ApplicationsVersions.objects.get_or_create(application=a, version=v,
                                                   min=av_min, max=av_max)
    file_factory(version=v, **file_kw)
    return v


def file_factory(**kw):
    v = kw['version']
    p, _ = Platform.objects.get_or_create(id=amo.PLATFORM_ALL.id)
    status = kw.pop('status', amo.STATUS_PUBLIC)
    f = File.objects.create(filename='%s-%s' % (v.addon_id, v.id),
                            platform=p, status=status, **kw)
    return f


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


class ESTestCase(TestCase):
    """Base class for tests that require elasticsearch."""
    # ES is slow to set up so this uses class setup/teardown. That happens
    # outside Django transactions so be careful to clean up afterwards.
    es = True
    mock_es = False
    exempt_from_fixture_bundling = True  # ES doesn't support bundling (yet?)

    @classmethod
    def setUpClass(cls):
        if not settings.RUN_ES_TESTS:
            raise SkipTest('ES disabled')
        cls.es = elasticutils.get_es(timeout=settings.ES_TIMEOUT)

        # The ES setting are set before we call super()
        # because we may have indexation occuring in upper classes.
        for key, index in settings.ES_INDEXES.items():
            if not index.startswith('test_'):
                settings.ES_INDEXES[key] = 'test_%s' % index

        super(ESTestCase, cls).setUpClass()
        try:
            cls.es.cluster_health()
        except Exception, e:
            e.args = tuple([u'%s (it looks like ES is not running, '
                            'try starting it or set RUN_ES_TESTS=False)'
                            % e.args[0]] + list(e.args[1:]))
            raise

        for index in set(settings.ES_INDEXES.values()):
            # getting the index that's pointed by the alias
            try:
                indices = cls.es.get_alias(index)
                index = indices[0]
            except pyes.IndexMissingException:
                pass

            # this removes any alias as well
            try:
                cls.es.delete_index(index)
            except pyes.IndexMissingException, exc:
                print 'Could not delete index %r: %s' % (index, exc)

        addons.search.setup_mapping()
        stats.search.setup_indexes()
        if settings.MARKETPLACE:
            import mkt.stats.search
            mkt.stats.search.setup_mkt_indexes()

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
        cls.es.refresh(settings.ES_INDEXES[index], timesleep=timesleep)

    @classmethod
    def reindex(cls, model):
        # Emit post-save signal so all of the objects get reindexed.
        [o.save() for o in model.objects.all()]
        cls.refresh()

    @classmethod
    def add_addons(cls):
        addon_factory(name='user-disabled', disabled_by_user=True)
        addon_factory(name='admin-disabled', status=amo.STATUS_DISABLED)
        addon_factory(status=amo.STATUS_UNREVIEWED)
        addon_factory()
        addon_factory()
        addon_factory()


class WebappTestCase(TestCase):
    fixtures = ['webapps/337141-steamcube']

    def setUp(self):
        self.app = self.get_app()

    def get_app(self):
        return Addon.objects.get(id=337141)

    def make_game(self, rated=False):
        cat, created = Category.objects.get_or_create(slug='games',
            type=amo.ADDON_WEBAPP)
        AddonCategory.objects.get_or_create(addon=self.app, category=cat)
        if rated:
            ContentRating.objects.get_or_create(addon=self.app,
                ratings_body=mkt.ratingsbodies.DJCTQ.id,
                rating=mkt.ratingsbodies.DJCTQ_18.id)
            ContentRating.objects.get_or_create(addon=self.app,
                ratings_body=mkt.ratingsbodies.DJCTQ.id,
                rating=mkt.ratingsbodies.DJCTQ_L.id)
        self.app = self.get_app()
