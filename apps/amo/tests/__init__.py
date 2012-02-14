from contextlib import contextmanager
from datetime import datetime, timedelta
from functools import partial, wraps
import os
import random
import shutil
import time

from django import forms
from django.conf import settings
from django.forms.fields import Field
from django.test.client import Client
from django.utils import translation

import elasticutils
import nose
import mock
from nose.tools import eq_, nottest
from redisutils import mock_redis, reset_redis
import test_utils

import amo
from amo.urlresolvers import Prefixer, get_url_prefix, reverse, set_url_prefix
from addons.models import Addon, Category, Persona
import addons.search
from applications.models import Application, AppVersion
from files.models import File, Platform
from translations.models import Translation
from versions.models import Version, ApplicationsVersions


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
            e = e.filter('.selected') or e.parents('.selected')
            eq_(e.length, text == selected)


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


class TestCase(RedisTest, test_utils.TestCase):
    """Base class for all amo tests."""
    client_class = TestClient

    def _pre_setup(self):
        super(TestCase, self)._pre_setup()
        self.reset_featured_addons()
        # Mock out ES indexing for non-ES tests.
        if not getattr(self, 'es', False):
            for p in ['addons.tasks.index_addons',
                      'addons.tasks.unindex_addons',
                      'amo.models.SearchMixin']:
                patcher = mock.patch(p)
                patcher.start()
                self.addCleanup(patcher.stop)

    def reset_featured_addons(self):
        from addons.cron import reset_featured_addons
        from addons.utils import FeaturedManager, CreaturedManager
        reset_featured_addons()
        # Clear the in-process caches.
        FeaturedManager.featured_ids.clear()
        CreaturedManager.creatured_ids.clear()

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
                    if msg != '':
                        self.fail('form %r had the following error(s):\n%s'
                                  % (k, msg))
                    self.assertEquals(v.non_field_errors(), [])

    def assertLoginRedirects(self, response, to):
        self.assertRedirects(response,
                             '%s?to=%s' % (reverse('users.login'), to), 302)


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

    @staticmethod
    def sample_key():
        path = 'apps/webapps/tests/sample.key'
        return os.path.join(settings.ROOT, path)


def close_to_now(dt):
    """
    Make sure the datetime is within a minute from `now`.
    """
    dt_ts = time.mktime(dt.timetuple())
    dt_minute_ts = time.mktime((dt + timedelta(minutes=1)).timetuple())
    now_ts = time.mktime(datetime.now().timetuple())

    return now_ts >= dt_ts and now_ts < dt_minute_ts


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


def addon_factory(version_kw={}, file_kw={}, **kw):
    type_ = kw.pop('type', amo.ADDON_EXTENSION)
    if type_ == amo.ADDON_PERSONA:
        # Personas need to start life as an extension for versioning
        a = Addon.objects.create(type=amo.ADDON_EXTENSION)
    else:
        a = Addon.objects.create(type=type_)
    a.status = amo.STATUS_PUBLIC
    a.name = name = 'Addon %s' % a.id
    a.slug = name.replace(' ', '-').lower()
    a.bayesian_rating = random.uniform(1, 5)
    a.average_daily_users = random.randint(200, 2000)
    a.weekly_downloads = random.randint(200, 2000)
    a.created = a.last_updated = datetime(2011, 6, 6, random.randint(0, 23),
                                          random.randint(0, 59))
    version_factory(file_kw, addon=a, **version_kw)
    a.update_version()
    a.status = amo.STATUS_PUBLIC
    for key, value in kw.items():
        setattr(a, key, value)
    if type_ == amo.ADDON_PERSONA:
        a.update(type=type_)
        Persona.objects.create(addon_id=a.id, persona_id=a.id)
    a.save()
    return a


def version_factory(file_kw={}, **kw):
    v = Version.objects.create(version='%.1f' % random.uniform(0, 2),
                               **kw)
    a, _ = Application.objects.get_or_create(id=amo.FIREFOX.id)
    av_min, _ = AppVersion.objects.get_or_create(application=a, version='4.0')
    av_max, _ = AppVersion.objects.get_or_create(application=a, version='5.0')
    ApplicationsVersions.objects.create(application=a, version=v,
                                        min=av_min, max=av_max)
    file_factory(version=v, **file_kw)
    return v


def file_factory(**kw):
    v = kw['version']
    p, _ = Platform.objects.get_or_create(id=amo.PLATFORM_ALL.id)
    f = File.objects.create(filename='%s-%s' % (v.addon_id, v.id),
                            platform=p, status=amo.STATUS_PUBLIC, **kw)
    return f


class ESTestCase(TestCase):
    """Base class for tests that require elasticsearch."""
    # ES is slow to set up so this uses class setup/teardown. That happens
    # outside Django transactions so be careful to clean up afterwards.
    es = True
    use_es = None
    exempt_from_fixture_bundling = True  # ES doesn't support bundling (yet?)

    @classmethod
    def setUpClass(cls):
        cls.es = elasticutils.get_es()

        if ESTestCase.use_es is None:
            for key, index in settings.ES_INDEXES.items():
                settings.ES_INDEXES[key] = 'test_%s' % index
            try:
                cls.es.cluster_health()
                ESTestCase.use_es = True
            except Exception, e:
                print 'Disabling elasticsearch tests.\n%s' % e
                ESTestCase.use_es = False

        if not ESTestCase.use_es:
            raise nose.SkipTest()

        for index in settings.ES_INDEXES.values():
            try:
                cls.es.delete_index(index)
            except Exception, e:
                pass

        super(ESTestCase, cls).setUpClass()
        addons.search.setup_mapping()

    @classmethod
    def setUpIndex(cls):
        cls.add_addons()
        cls.refresh()

    @classmethod
    def tearDownClass(cls):
        # Delete everything in reverse-order of the foreign key dependencies.
        models = (Platform, Category, File, ApplicationsVersions, Version,
                  Translation, Addon, AppVersion, Application)
        for model in models:
            model.objects.all().delete()
        super(ESTestCase, cls).tearDownClass()

    @classmethod
    def refresh(cls, index='default'):
        cls.es.refresh(settings.ES_INDEXES[index], timesleep=0)

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
