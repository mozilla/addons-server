import json
from datetime import datetime, timedelta

from django.conf import settings
from django.core.files import temp

import mock
from pyquery import PyQuery as pq

from olympia import amo
from olympia.addons.models import Addon, AddonCategory, Category
from olympia.amo.tests import addon_factory, formset, initial, TestCase
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.urlresolvers import reverse
from olympia.devhub.models import ActivityLog
from olympia.files.tests.test_models import UploadTest as BaseUploadTest
from olympia.users.models import UserProfile
from olympia.versions.models import License


def get_addon_count(name):
    """Return the number of addons with the given name."""
    return Addon.unfiltered.filter(name__localized_string=name).count()


class TestSubmitPersona(TestCase):
    fixtures = ['base/user_999']

    def setUp(self):
        super(TestSubmitPersona, self).setUp()
        assert self.client.login(email='regular@mozilla.com')
        self.url = reverse('devhub.themes.submit')

    def get_img_urls(self):
        return (
            reverse('devhub.personas.upload_persona', args=['persona_header']),
            reverse('devhub.personas.upload_persona', args=['persona_footer'])
        )

    def test_img_urls(self):
        r = self.client.get(self.url)
        assert r.status_code == 200
        doc = pq(r.content)
        header_url, footer_url = self.get_img_urls()
        assert doc('#id_header').attr('data-upload-url') == header_url
        assert doc('#id_footer').attr('data-upload-url') == footer_url

    def test_img_size(self):
        img = get_image_path('mozilla.png')
        for url, img_type in zip(self.get_img_urls(), ('header', 'footer')):
            r_ajax = self.client.post(url, {'upload_image': open(img, 'rb')})
            r_json = json.loads(r_ajax.content)
            w, h = amo.PERSONA_IMAGE_SIZES.get(img_type)[1]
            assert r_json['errors'] == [
                'Image must be exactly %s pixels wide '
                'and %s pixels tall.' % (w, h)]

    def test_img_wrongtype(self):
        img = open('static/js/impala/global.js', 'rb')
        for url in self.get_img_urls():
            r_ajax = self.client.post(url, {'upload_image': img})
            r_json = json.loads(r_ajax.content)
            assert r_json['errors'] == ['Images must be either PNG or JPG.']


class TestSubmitBase(TestCase):
    fixtures = ['base/addon_3615', 'base/addon_5579', 'base/users']

    def setUp(self):
        super(TestSubmitBase, self).setUp()
        assert self.client.login(email='del@icio.us')
        self.user = UserProfile.objects.get(email='del@icio.us')
        self.addon = self.get_addon()

    def get_addon(self):
        return Addon.with_unlisted.no_cache().get(pk=3615)

    def get_version(self):
        return self.get_addon().versions.get()


class TestSubmitStepAgreement(TestSubmitBase):
    def test_step1_submit(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.get(reverse('devhub.submit.agreement'))
        assert response.status_code == 200
        doc = pq(response.content)
        assert doc('#breadcrumbs a').eq(1).attr('href') == (
            reverse('devhub.addons'))
        links = doc('#agreement-container a')
        assert links
        for ln in links:
            href = ln.attrib['href']
            assert not href.startswith('%'), (
                "Looks like link %r to %r is still a placeholder" %
                (href, ln.text))

    def test_read_dev_agreement_set(self):
        """Store current date when the user agrees with the user agreement."""
        self.user.update(read_dev_agreement=None)

        response = self.client.post(reverse('devhub.submit.agreement'),
                                    follow=True)
        user = response.context['user']
        self.assertCloseToNow(user.read_dev_agreement)

    def test_read_dev_agreement_skip(self):
        # The current user fixture has already read the agreement so we skip
        response = self.client.get(reverse('devhub.submit.agreement'))
        self.assert3xx(response, reverse('devhub.submit.distribution'))


class TestCreateAddon(BaseUploadTest, TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestCreateAddon, self).setUp()
        self.upload = self.get_upload('extension.xpi')
        assert self.client.login(email='regular@mozilla.com')
        self.client.post(reverse('devhub.submit.agreement'))

    def post(self, supported_platforms=None, expect_errors=False,
             source=None, is_listed=True, status_code=200):
        if supported_platforms is None:
            supported_platforms = [amo.PLATFORM_ALL]
        d = dict(upload=self.upload.uuid.hex, source=source,
                 supported_platforms=[p.id for p in supported_platforms])
        url = reverse('devhub.submit.upload',
                      args=['listed' if is_listed else 'unlisted'])
        r = self.client.post(url, d, follow=True)
        assert r.status_code == status_code
        if not expect_errors:
            # Show any unexpected form errors.
            if r.context and 'new_addon_form' in r.context:
                assert r.context['new_addon_form'].errors.as_text() == ''
        return r

    def test_unique_name(self):
        addon_factory(name='xpi name')
        self.post(expect_errors=False)

    def test_unlisted_name_not_unique(self):
        """We don't enforce name uniqueness for unlisted add-ons."""
        addon_factory(name='xpi name', is_listed=False)
        assert get_addon_count('xpi name') == 1
        # We're not passing `expected_errors=True`, so if there was any errors
        # like "This name is already in use. Please choose another one", the
        # test would fail.
        response = self.post()
        # Kind of redundant with the `self.post()` above: we just want to make
        # really sure there's no errors raised by posting an add-on with a name
        # that is already used by an unlisted add-on.
        assert 'new_addon_form' not in response.context
        assert get_addon_count('xpi name') == 2

    def test_name_not_unique_between_types(self):
        """We don't enforce name uniqueness between add-ons types."""
        addon_factory(name='xpi name', type=amo.ADDON_THEME)
        assert get_addon_count('xpi name') == 1
        # We're not passing `expected_errors=True`, so if there was any errors
        # like "This name is already in use. Please choose another one", the
        # test would fail.
        response = self.post()
        # Kind of redundant with the `self.post()` above: we just want to make
        # really sure there's no errors raised by posting an add-on with a name
        # that is already used by an unlisted add-on.
        assert 'new_addon_form' not in response.context
        assert get_addon_count('xpi name') == 2

    def test_success_listed(self):
        assert Addon.objects.count() == 0
        r = self.post()
        addon = Addon.objects.get()
        assert addon.is_listed
        version = addon.find_latest_version(channel=amo.RELEASE_CHANNEL_LISTED)
        assert version
        assert version.channel == amo.RELEASE_CHANNEL_LISTED
        self.assert3xx(r, reverse('devhub.submit.details', args=[addon.slug]))
        log_items = ActivityLog.objects.for_addons(addon)
        assert log_items.filter(action=amo.LOG.CREATE_ADDON.id), (
            'New add-on creation never logged.')

    @mock.patch('olympia.editors.helpers.sign_file')
    def test_success_unlisted(self, mock_sign_file):
        """Sign automatically."""
        assert Addon.with_unlisted.count() == 0
        # No validation errors or warning.
        self.upload = self.get_upload(
            'extension.xpi',
            validation=json.dumps(dict(errors=0, warnings=0, notices=2,
                                       metadata={}, messages=[],
                                       signing_summary={
                                           'trivial': 1, 'low': 0, 'medium': 0,
                                           'high': 0},
                                       passed_auto_validation=True
                                       )))
        self.post(is_listed=False)
        addon = Addon.with_unlisted.get()
        assert not addon.is_listed
        version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert version
        assert version.channel == amo.RELEASE_CHANNEL_UNLISTED
        assert addon.status == amo.STATUS_PUBLIC
        assert mock_sign_file.called

    @mock.patch('olympia.editors.helpers.sign_file')
    def test_success_unlisted_fail_validation(self, mock_sign_file):
        assert Addon.with_unlisted.count() == 0
        self.upload = self.get_upload(
            'extension.xpi',
            validation=json.dumps(dict(errors=0, warnings=0, notices=2,
                                       metadata={}, messages=[],
                                       signing_summary={
                                           'trivial': 0, 'low': 1, 'medium': 0,
                                           'high': 0},
                                       passed_auto_validation=False
                                       )))
        self.post(is_listed=False)
        addon = Addon.with_unlisted.get()
        assert not addon.is_listed
        version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert version
        assert version.channel == amo.RELEASE_CHANNEL_UNLISTED
        assert addon.status == amo.STATUS_PUBLIC
        assert mock_sign_file.called

    def test_missing_platforms(self):
        url = reverse('devhub.submit.upload', args=['listed'])
        r = self.client.post(url, dict(upload=self.upload.uuid.hex))
        assert r.status_code == 200
        assert r.context['new_addon_form'].errors.as_text() == (
            '* supported_platforms\n  * Need at least one platform.')
        doc = pq(r.content)
        assert doc('ul.errorlist').text() == (
            'Need at least one platform.')

    def test_one_xpi_for_multiple_platforms(self):
        assert Addon.objects.count() == 0
        r = self.post(supported_platforms=[amo.PLATFORM_MAC,
                                           amo.PLATFORM_LINUX])
        addon = Addon.objects.get()
        self.assert3xx(r, reverse('devhub.submit.details', args=[addon.slug]))
        all_ = sorted([f.filename for f in addon.current_version.all_files])
        assert all_ == [u'xpi_name-0.1-linux.xpi', u'xpi_name-0.1-mac.xpi']

    @mock.patch('olympia.devhub.views.auto_sign_file')
    def test_one_xpi_for_multiple_platforms_unlisted_addon(
            self, mock_auto_sign_file):
        assert Addon.objects.count() == 0
        r = self.post(supported_platforms=[amo.PLATFORM_MAC,
                                           amo.PLATFORM_LINUX],
                      is_listed=False)
        addon = Addon.unfiltered.get()
        latest_version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.assert3xx(r, reverse('devhub.submit.finish', args=[addon.slug]))
        all_ = sorted([f.filename for f in latest_version.all_files])
        assert all_ == [u'xpi_name-0.1-linux.xpi', u'xpi_name-0.1-mac.xpi']
        mock_auto_sign_file.assert_has_calls(
            [mock.call(f) for f in latest_version.all_files])

    def test_with_source(self):
        tdir = temp.gettempdir()
        source = temp.NamedTemporaryFile(suffix=".zip", dir=tdir)
        source.write('a' * (2 ** 21))
        source.seek(0)
        assert Addon.objects.count() == 0
        r = self.post(source=source)
        addon = Addon.objects.get()
        self.assert3xx(r, reverse('devhub.submit.details', args=[addon.slug]))
        assert addon.current_version.source
        assert Addon.objects.get(pk=addon.pk).admin_review


class TestSubmitStepDistribution(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestSubmitStepDistribution, self).setUp()
        self.client.login(email='regular@mozilla.com')
        self.user = UserProfile.objects.get(email='regular@mozilla.com')

    def test_check_agreement_okay(self):
        r = self.client.post(reverse('devhub.submit.agreement'))
        self.assert3xx(r, reverse('devhub.submit.distribution'))
        r = self.client.get(reverse('devhub.submit.distribution'))
        assert r.status_code == 200

    def test_redirect_back_to_agreement(self):
        # We require a cookie that gets set in step 1.
        self.user.update(read_dev_agreement=None)

        r = self.client.get(reverse('devhub.submit.distribution'), follow=True)
        self.assert3xx(r, reverse('devhub.submit.agreement'))

    def test_listed_redirects_to_next_step(self):
        response = self.client.post(reverse('devhub.submit.distribution'),
                                    {'choices': 'listed'})
        self.assert3xx(response,
                       reverse('devhub.submit.upload', args=['listed']))

    def test_unlisted_redirects_to_next_step(self):
        response = self.client.post(reverse('devhub.submit.distribution'),
                                    {'choices': 'unlisted'})
        self.assert3xx(response, reverse('devhub.submit.upload',
                                         args=['unlisted']))


# Tests for Upload step in TestCreateAddon


class TestSubmitStepDetails(TestSubmitBase):

    def setUp(self):
        super(TestSubmitStepDetails, self).setUp()
        self.url = reverse('devhub.submit.details', args=['a3615'])

        AddonCategory.objects.filter(
            addon=self.get_addon(),
            category=Category.objects.get(id=1)).delete()
        AddonCategory.objects.filter(
            addon=self.get_addon(),
            category=Category.objects.get(id=71)).delete()

        ctx = self.client.get(self.url).context['cat_form']
        self.cat_initial = initial(ctx.initial_forms[0])
        self.next_step = reverse('devhub.submit.finish', args=['a3615'])
        License.objects.create(builtin=3, on_form=True)
        self.get_addon().update(status=amo.STATUS_NULL)

    def get_dict(self, minimal=True, **kw):
        result = {}
        describe_form = {'name': 'Test name', 'slug': 'testname',
                         'summary': 'Hello!', 'is_experimental': True}
        if not minimal:
            describe_form.update({'support_url': 'http://stackoverflow.com',
                                  'support_email': 'black@hole.org'})
        cat_initial = kw.pop('cat_initial', self.cat_initial)
        cat_form = formset(cat_initial, initial_count=1)
        license_form = {'builtin': 3}
        policy_form = {} if minimal else {
            'has_priv': True, 'privacy_policy': 'Ur data belongs to us now.'}
        reviewer_form = {} if minimal else {'approvalnotes': 'approove plz'}
        result.update(describe_form)
        result.update(cat_form)
        result.update(license_form)
        result.update(policy_form)
        result.update(reviewer_form)
        result.update(**kw)
        return result

    def is_success(self, data):
        assert self.get_addon().status == amo.STATUS_NULL
        response = self.client.post(self.url, data)
        assert response.status_code == 302
        assert self.get_addon().status == amo.STATUS_NOMINATED
        return response

    def test_submit_success_minimal(self):
        # Set/change the required fields only
        r = self.client.get(self.url)
        assert r.status_code == 200

        # Post and be redirected - trying to sneak
        # in fields that shouldn't be modified via this form.
        d = self.get_dict(homepage='foo.com',
                          tags='whatevs, whatever')
        self.is_success(d)

        addon = self.get_addon()

        # This fields should not have been modified.
        assert addon.homepage != 'foo.com'
        assert len(addon.tags.values_list()) == 0

        # These are the fields that are expected to be edited here.
        assert addon.name == 'Test name'
        assert addon.slug == 'testname'
        assert addon.summary == 'Hello!'
        assert addon.is_experimental

        # Test add-on log activity.
        log_items = ActivityLog.objects.for_addons(addon)
        assert not log_items.filter(action=amo.LOG.EDIT_PROPERTIES.id), (
            "Setting properties on submit needn't be logged.")

    def test_submit_success_optional_fields(self):
        # Set/change the optional fields too
        # Post and be redirected
        d = self.get_dict(minimal=False)
        self.is_success(d)

        addon = self.get_addon()

        # These are the fields that are expected to be edited here.
        assert addon.support_url == 'http://stackoverflow.com'
        assert addon.support_email == 'black@hole.org'
        assert addon.privacy_policy == 'Ur data belongs to us now.'

    def test_submit_name_unique(self):
        # Make sure name is unique.
        r = self.client.post(self.url, self.get_dict(name='Cooliris'))
        error = 'This name is already in use. Please choose another.'
        self.assertFormError(r, 'form', 'name', error)

    def test_submit_name_unique_only_for_listed(self):
        """A listed add-on can use the same name as unlisted add-ons."""
        # Change the existing add-on with the 'Cooliris' name to be unlisted.
        Addon.objects.get(name__localized_string='Cooliris').update(
            is_listed=False)
        assert get_addon_count('Cooliris') == 1
        # It's allowed for the '3615' listed add-on to reuse the same name as
        # the other 'Cooliris' unlisted add-on.
        self.is_success(self.get_dict(name='Cooliris'))
        assert get_addon_count('Cooliris') == 2

    def test_submit_name_unique_strip(self):
        # Make sure we can't sneak in a name by adding a space or two.
        r = self.client.post(self.url, self.get_dict(name='  Cooliris  '))
        error = 'This name is already in use. Please choose another.'
        self.assertFormError(r, 'form', 'name', error)

    def test_submit_name_unique_case(self):
        # Make sure unique names aren't case sensitive.
        r = self.client.post(self.url, self.get_dict(name='cooliris'))
        error = 'This name is already in use. Please choose another.'
        self.assertFormError(r, 'form', 'name', error)

    def test_submit_name_length(self):
        # Make sure the name isn't too long.
        d = self.get_dict(name='a' * 51)
        r = self.client.post(self.url, d)
        assert r.status_code == 200
        error = 'Ensure this value has at most 50 characters (it has 51).'
        self.assertFormError(r, 'form', 'name', error)

    def test_submit_slug_invalid(self):
        # Submit an invalid slug.
        d = self.get_dict(slug='slug!!! aksl23%%')
        r = self.client.post(self.url, d)
        assert r.status_code == 200
        self.assertFormError(r, 'form', 'slug', "Enter a valid 'slug' " +
                             "consisting of letters, numbers, underscores or "
                             "hyphens.")

    def test_submit_slug_required(self):
        # Make sure the slug is required.
        r = self.client.post(self.url, self.get_dict(slug=''))
        assert r.status_code == 200
        self.assertFormError(r, 'form', 'slug', 'This field is required.')

    def test_submit_summary_required(self):
        # Make sure summary is required.
        r = self.client.post(self.url, self.get_dict(summary=''))
        assert r.status_code == 200
        self.assertFormError(r, 'form', 'summary', 'This field is required.')

    def test_submit_summary_length(self):
        # Summary is too long.
        r = self.client.post(self.url, self.get_dict(summary='a' * 251))
        assert r.status_code == 200
        error = 'Ensure this value has at most 250 characters (it has 251).'
        self.assertFormError(r, 'form', 'summary', error)

    def test_submit_categories_required(self):
        del self.cat_initial['categories']
        r = self.client.post(self.url,
                             self.get_dict(cat_initial=self.cat_initial))
        assert r.context['cat_form'].errors[0]['categories'] == (
            ['This field is required.'])

    def test_submit_categories_max(self):
        assert amo.MAX_CATEGORIES == 2
        self.cat_initial['categories'] = [22, 1, 71]
        r = self.client.post(self.url,
                             self.get_dict(cat_initial=self.cat_initial))
        assert r.context['cat_form'].errors[0]['categories'] == (
            ['You can have only 2 categories.'])

    def test_submit_categories_add(self):
        assert [c.id for c in self.get_addon().all_categories] == [22]
        self.cat_initial['categories'] = [22, 1]

        self.is_success(self.get_dict())

        addon_cats = self.get_addon().categories.values_list('id', flat=True)
        assert sorted(addon_cats) == [1, 22]

    def test_submit_categories_addandremove(self):
        AddonCategory(addon=self.addon, category_id=1).save()
        assert sorted(
            [c.id for c in self.get_addon().all_categories]) == [1, 22]

        self.cat_initial['categories'] = [22, 71]
        self.client.post(self.url, self.get_dict(cat_initial=self.cat_initial))
        category_ids_new = [c.id for c in self.get_addon().all_categories]
        assert sorted(category_ids_new) == [22, 71]

    def test_submit_categories_remove(self):
        c = Category.objects.get(id=1)
        AddonCategory(addon=self.addon, category=c).save()
        assert sorted(
            [a.id for a in self.get_addon().all_categories]) == [1, 22]

        self.cat_initial['categories'] = [22]
        self.client.post(self.url, self.get_dict(cat_initial=self.cat_initial))
        category_ids_new = [cat.id for cat in self.get_addon().all_categories]
        assert category_ids_new == [22]

    def test_set_builtin_license_no_log(self):
        self.is_success(self.get_dict(builtin=3))
        addon = self.get_addon()
        assert addon.status == amo.STATUS_NOMINATED
        assert addon.current_version.license.builtin == 3
        log_items = ActivityLog.objects.for_addons(self.get_addon())
        assert not log_items.filter(action=amo.LOG.CHANGE_LICENSE.id)

    def test_license_error(self):
        response = self.client.post(self.url, self.get_dict(builtin=4))
        assert response.status_code == 200
        self.assertFormError(response, 'license_form', 'builtin',
                             'Select a valid choice. 4 is not one of '
                             'the available choices.')

    def test_set_privacy_nomsg(self):
        """
        You should not get punished with a 500 for not writing your policy...
        but perhaps you should feel shame for lying to us.  This test does not
        test for shame.
        """
        self.get_addon().update(eula=None, privacy_policy=None)
        self.is_success(self.get_dict(has_priv=True))

    def test_nomination_date_set_only_once(self):
        self.get_version().update(nomination=None)
        self.is_success(self.get_dict())
        self.assertCloseToNow(self.get_version().nomination)

        # Check nomination date is only set once, see bug 632191.
        nomdate = datetime.now() - timedelta(days=5)
        self.get_version().update(nomination=nomdate, _signal=False)
        # Update something else in the addon:
        self.get_addon().update(slug='foobar')
        assert self.get_version().nomination.timetuple()[0:5] == (
            nomdate.timetuple()[0:5])

    def test_submit_details_unlisted_should_redirect(self):
        version = self.get_addon().versions.latest()
        version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        self.assert3xx(
            response, reverse('devhub.submit.finish', args=[self.addon.slug]))


class TestSubmitStepFinish(TestSubmitBase):

    def setUp(self):
        super(TestSubmitStepFinish, self).setUp()
        self.url = reverse('devhub.submit.finish', args=[self.addon.slug])

    @mock.patch.object(settings, 'SITE_URL', 'http://b.ro')
    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay')
    def test_welcome_email_for_newbies(self, send_welcome_email_mock):
        self.client.get(self.url)
        context = {
            'app': unicode(amo.FIREFOX.pretty),
            'detail_url': 'http://b.ro/en-US/firefox/addon/a3615/',
            'version_url': 'http://b.ro/en-US/developers/addon/a3615/versions',
            'edit_url': 'http://b.ro/en-US/developers/addon/a3615/edit',
        }
        send_welcome_email_mock.assert_called_with(
            self.addon.id, ['del@icio.us'], context)

    @mock.patch.object(settings, 'SITE_URL', 'http://b.ro')
    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay')
    def test_welcome_email_first_listed_addon(self, send_welcome_email_mock):
        new_addon = addon_factory(is_listed=False)
        new_addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        new_addon.addonuser_set.create(user=self.addon.authors.all()[0])
        self.client.get(self.url)
        context = {
            'app': unicode(amo.FIREFOX.pretty),
            'detail_url': 'http://b.ro/en-US/firefox/addon/a3615/',
            'version_url': 'http://b.ro/en-US/developers/addon/a3615/versions',
            'edit_url': 'http://b.ro/en-US/developers/addon/a3615/edit',
        }
        send_welcome_email_mock.assert_called_with(
            self.addon.id, ['del@icio.us'], context)

    @mock.patch.object(settings, 'SITE_URL', 'http://b.ro')
    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay')
    def test_welcome_email_if_previous_addon_is_incomplete(
            self, send_welcome_email_mock):
        # If the developer already submitted an addon but didn't finish or was
        # rejected, we send the email anyway, it might be a dupe depending on
        # how far they got but it's better than not sending any.
        new_addon = addon_factory(status=amo.STATUS_NULL)
        new_addon.addonuser_set.create(user=self.addon.authors.all()[0])
        self.client.get(self.url)
        context = {
            'app': unicode(amo.FIREFOX.pretty),
            'detail_url': 'http://b.ro/en-US/firefox/addon/a3615/',
            'version_url': 'http://b.ro/en-US/developers/addon/a3615/versions',
            'edit_url': 'http://b.ro/en-US/developers/addon/a3615/edit',
        }
        send_welcome_email_mock.assert_called_with(
            self.addon.id, ['del@icio.us'], context)

    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay')
    def test_no_welcome_email(self, send_welcome_email_mock):
        """You already submitted an add-on? We won't spam again."""
        new_addon = addon_factory(status=amo.STATUS_NOMINATED)
        new_addon.addonuser_set.create(user=self.addon.authors.all()[0])
        self.client.get(self.url)
        assert not send_welcome_email_mock.called

    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay')
    def test_no_welcome_email_if_unlisted(self, send_welcome_email_mock):
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.addon.update(is_listed=False, status=amo.STATUS_PUBLIC)
        self.client.get(self.url)
        assert not send_welcome_email_mock.called

    def test_finish_submitting_listed_addon(self):
        assert self.addon.current_version.supported_platforms == (
            [amo.PLATFORM_ALL])

        r = self.client.get(self.url)
        assert r.status_code == 200
        doc = pq(r.content)

        content = doc('.addon-submission-process')
        links = content('a')
        assert len(links) == 3
        # First link is to edit listing
        assert links[0].attrib['href'] == self.addon.get_dev_url()
        # Second link is to edit the version
        assert links[1].attrib['href'] == reverse(
            'devhub.versions.edit',
            args=[self.addon.slug, self.addon.current_version.id])
        assert links[1].text == (
            'Edit version %s' % self.addon.current_version.version)
        # Third back to my submissions.
        assert links[2].attrib['href'] == reverse('devhub.addons')

    def test_finish_submitting_unlisted_addon(self):
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.addon.update(is_listed=False, status=amo.STATUS_PUBLIC)

        latest_version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        response = self.client.get(self.url)
        assert response.status_code == 200
        doc = pq(response.content)

        content = doc('.addon-submission-process')
        links = content('a')
        assert len(links) == 2
        # First link is to the file download.
        file_ = latest_version.all_files[0]
        assert links[0].attrib['href'] == file_.get_url_path('devhub')
        assert links[0].text == (
            'Download %s' % file_.filename)
        # Second back to my submissions.
        assert links[1].attrib['href'] == reverse('devhub.addons')

    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay', new=mock.Mock)
    def test_finish_submitting_platform_specific_listed_addon(self):
        # mac-only Add-on:
        addon = Addon.objects.get(name__localized_string='Cooliris')
        addon.addonuser_set.create(user_id=55021)
        AddonCategory(addon=addon, category_id=1).save()
        assert addon.has_complete_metadata()  # Otherwise will 302 to details.
        r = self.client.get(reverse('devhub.submit.finish', args=[addon.slug]))
        assert r.status_code == 200
        doc = pq(r.content)

        content = doc('.addon-submission-process')
        links = content('a')
        assert len(links) == 4
        # First link is to edit listing
        assert links[0].attrib['href'] == addon.get_dev_url()
        # Second link is to edit the version
        assert links[1].attrib['href'] == reverse(
            'devhub.versions.edit',
            args=[addon.slug, addon.current_version.id])
        assert links[1].text == (
            'Edit version %s' % addon.current_version.version)
        # Third link is to edit the version (for now, until we have new flow)
        assert links[2].attrib['href'] == reverse(
            'devhub.versions.edit',
            args=[addon.slug, addon.current_version.id])
        # Fourth back to my submissions.
        assert links[3].attrib['href'] == reverse('devhub.addons')

    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay', new=mock.Mock)
    def test_finish_submitting_platform_specific_unlisted_addon(self):
        # mac-only Add-on:
        addon = Addon.objects.get(name__localized_string='Cooliris')
        addon.addonuser_set.create(user_id=55021)
        addon.update(is_listed=False)
        addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        latest_version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        r = self.client.get(reverse('devhub.submit.finish', args=[addon.slug]))
        assert r.status_code == 200
        doc = pq(r.content)

        content = doc('.addon-submission-process')
        links = content('a')
        assert len(links) == 3
        # First link is to the file download.
        file_ = latest_version.all_files[0]
        assert links[0].attrib['href'] == file_.get_url_path('devhub')
        assert links[0].text == (
            'Download %s' % file_.filename)
        # Second link is to edit the version (for now, until we have new flow)
        assert links[1].attrib['href'] == reverse(
            'devhub.versions.edit', args=[addon.slug, latest_version.id])
        # Third back to my submissions.
        assert links[2].attrib['href'] == reverse('devhub.addons')

    def test_addon_no_versions_redirects_to_versions(self):
        self.addon.update(status=amo.STATUS_NULL)
        self.addon.versions.all().delete()
        r = self.client.get(self.url, follow=True)
        self.assert3xx(r, self.addon.get_dev_url('versions'), 302)

    def test_incomplete_directs_to_details(self):
        # We get bounced back to details step.
        self.addon.update(status=amo.STATUS_NULL)
        self.addon.categories.all().delete()
        r = self.client.get(reverse('devhub.submit.finish',
                                    args=['a3615']), follow=True)
        self.assert3xx(r, reverse('devhub.submit.details', args=['a3615']))


class TestResumeStep(TestSubmitBase):

    def setUp(self):
        super(TestResumeStep, self).setUp()
        self.url = reverse('devhub.submit.resume', args=['a3615'])

    def test_addon_no_versions_redirects_to_versions(self):
        self.addon.update(status=amo.STATUS_NULL)
        self.addon.versions.all().delete()
        r = self.client.get(self.url, follow=True)
        self.assert3xx(r, self.addon.get_dev_url('versions'), 302)

    def test_incomplete_directs_to_details(self):
        # We get bounced back to details step.
        self.addon.update(status=amo.STATUS_NULL)
        self.addon.categories.all().delete()
        r = self.client.get(reverse('devhub.submit.finish',
                                    args=['a3615']), follow=True)
        self.assert3xx(r, reverse('devhub.submit.details', args=['a3615']))

    def test_redirect_from_other_pages(self):
        self.addon.update(status=amo.STATUS_NULL)
        self.addon.categories.all().delete()
        r = self.client.get(reverse('devhub.addons.edit', args=['a3615']),
                            follow=True)
        self.assert3xx(r, reverse('devhub.submit.details', args=['a3615']))
