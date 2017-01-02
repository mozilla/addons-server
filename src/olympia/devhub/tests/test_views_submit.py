import json
from datetime import datetime, timedelta

from django.conf import settings
from django.core.files import temp

import mock
from pyquery import PyQuery as pq
from waffle.testutils import override_switch

from olympia import amo
from olympia.addons.models import Addon, AddonCategory, Category
from olympia.amo.tests import (
    addon_factory, formset, initial, TestCase, version_factory)
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.urlresolvers import reverse
from olympia.devhub import views
from olympia.devhub.models import ActivityLog
from olympia.files.models import FileValidation
from olympia.files.tests.test_models import UploadTest
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
        return Addon.objects.no_cache().get(pk=3615)

    def get_version(self):
        return self.get_addon().versions.latest()


class TestAddonSubmitAgreement(TestSubmitBase):
    def test_step1_submit(self):
        self.user.update(read_dev_agreement=None)
        response = self.client.get(reverse('devhub.submit.agreement'))
        assert response.status_code == 200
        doc = pq(response.content)
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


class TestAddonSubmitDistribution(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestAddonSubmitDistribution, self).setUp()
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
                                    {'channel': 'listed'})
        self.assert3xx(response,
                       reverse('devhub.submit.upload', args=['listed']))

    def test_unlisted_redirects_to_next_step(self):
        response = self.client.post(reverse('devhub.submit.distribution'),
                                    {'channel': 'unlisted'})
        self.assert3xx(response, reverse('devhub.submit.upload',
                                         args=['unlisted']))


class TestAddonSubmitUpload(UploadTest, TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestAddonSubmitUpload, self).setUp()
        self.upload = self.get_upload('extension.xpi')
        assert self.client.login(email='regular@mozilla.com')
        self.client.post(reverse('devhub.submit.agreement'))

    def post(self, supported_platforms=None, expect_errors=False,
             source=None, listed=True, status_code=200):
        if supported_platforms is None:
            supported_platforms = [amo.PLATFORM_ALL]
        d = dict(upload=self.upload.uuid.hex, source=source,
                 supported_platforms=[p.id for p in supported_platforms])
        url = reverse('devhub.submit.upload',
                      args=['listed' if listed else 'unlisted'])
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
        assert Addon.objects.count() == 0
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
        self.post(listed=False)
        addon = Addon.objects.get()
        assert not addon.is_listed
        version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert version
        assert version.channel == amo.RELEASE_CHANNEL_UNLISTED
        assert addon.status == amo.STATUS_NULL
        assert mock_sign_file.called

    @mock.patch('olympia.editors.helpers.sign_file')
    def test_success_unlisted_fail_validation(self, mock_sign_file):
        assert Addon.objects.count() == 0
        self.upload = self.get_upload(
            'extension.xpi',
            validation=json.dumps(dict(errors=0, warnings=0, notices=2,
                                       metadata={}, messages=[],
                                       signing_summary={
                                           'trivial': 0, 'low': 1, 'medium': 0,
                                           'high': 0},
                                       passed_auto_validation=False
                                       )))
        self.post(listed=False)
        addon = Addon.objects.get()
        assert not addon.is_listed
        version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert version
        assert version.channel == amo.RELEASE_CHANNEL_UNLISTED
        assert addon.status == amo.STATUS_NULL
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
                      listed=False)
        addon = Addon.unfiltered.get()
        latest_version = addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.assert3xx(r, reverse('devhub.submit.finish', args=[addon.slug]))
        all_ = sorted([f.filename for f in latest_version.all_files])
        assert all_ == [u'xpi_name-0.1-linux.xpi', u'xpi_name-0.1-mac.xpi']
        mock_auto_sign_file.assert_has_calls(
            [mock.call(f, is_beta=False) for f in latest_version.all_files])

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


class TestAddonSubmitDetails(TestSubmitBase):

    def setUp(self):
        super(TestAddonSubmitDetails, self).setUp()
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
        license_form = {'license-builtin': 3}
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
        assert all(self.get_addon().get_required_metadata())
        assert response.status_code == 302
        assert self.get_addon().status == amo.STATUS_NOMINATED
        return response

    def test_submit_success_required(self):
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
        assert addon.all_categories[0].id == 22

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
        assert addon.current_version.approvalnotes == 'approove plz'

    def test_submit_name_existing(self):
        """Test that we can submit two add-ons with the same name."""
        qs = Addon.objects.filter(name__localized_string='Cooliris')
        assert qs.count() == 1
        self.is_success(self.get_dict(name='Cooliris'))
        assert qs.count() == 2

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
        self.is_success(self.get_dict(**{'license-builtin': 3}))
        addon = self.get_addon()
        assert addon.status == amo.STATUS_NOMINATED
        assert addon.current_version.license.builtin == 3
        log_items = ActivityLog.objects.for_addons(self.get_addon())
        assert not log_items.filter(action=amo.LOG.CHANGE_LICENSE.id)

    def test_license_error(self):
        response = self.client.post(
            self.url, self.get_dict(**{'license-builtin': 4}))
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
        self.assert3xx(response, self.next_step)


class TestAddonSubmitFinish(TestSubmitBase):

    def setUp(self):
        super(TestAddonSubmitFinish, self).setUp()
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
        version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        assert version.supported_platforms == ([amo.PLATFORM_ALL])

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
            args=[self.addon.slug, version.id])
        assert links[1].text == (
            'Edit version %s' % version.version)
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
        file_ = latest_version.all_files[-1]
        assert links[0].attrib['href'] == file_.get_url_path('devhub')
        assert links[0].text == (
            'Download %s' % file_.filename)
        # Second back to my submissions.
        assert links[1].attrib['href'] == reverse('devhub.addons')

    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay', new=mock.Mock)
    @override_switch('step-version-upload', active=True)
    def test_finish_submitting_platform_specific_listed_addon(self):
        latest_version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        latest_version.all_files[0].update(
            status=amo.STATUS_AWAITING_REVIEW, platform=amo.PLATFORM_MAC.id)
        latest_version.save()
        assert latest_version.is_allowed_upload()
        r = self.client.get(self.url)
        assert r.status_code == 200
        doc = pq(r.content)

        content = doc('.addon-submission-process')
        links = content('a')
        assert len(links) == 4
        # First link is to edit listing
        assert links[0].attrib['href'] == self.addon.get_dev_url()
        # Second link is to edit the version
        assert links[1].attrib['href'] == reverse(
            'devhub.versions.edit',
            args=[self.addon.slug, latest_version.id])
        assert links[1].text == (
            'Edit version %s' % latest_version.version)
        # Third link is to add a new file.
        assert links[2].attrib['href'] == reverse(
            'devhub.submit.file', args=[self.addon.slug, latest_version.id])
        # Fourth back to my submissions.
        assert links[3].attrib['href'] == reverse('devhub.addons')

    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay', new=mock.Mock)
    @override_switch('step-version-upload', active=True)
    def test_finish_submitting_platform_specific_unlisted_addon(self):
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        latest_version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        latest_version.all_files[0].update(
            status=amo.STATUS_AWAITING_REVIEW, platform=amo.PLATFORM_MAC.id)
        latest_version.save()
        assert latest_version.is_allowed_upload()
        r = self.client.get(self.url)
        assert r.status_code == 200
        doc = pq(r.content)

        content = doc('.addon-submission-process')
        links = content('a')
        assert len(links) == 3
        # First link is to the file download.
        file_ = latest_version.all_files[-1]
        assert links[0].attrib['href'] == file_.get_url_path('devhub')
        assert links[0].text == (
            'Download %s' % file_.filename)
        # Second link is to add a new file.
        assert links[1].attrib['href'] == reverse(
            'devhub.submit.file', args=[self.addon.slug, latest_version.id])
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


class TestAddonSubmitResume(TestSubmitBase):

    def setUp(self):
        super(TestAddonSubmitResume, self).setUp()
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


@override_switch('step-version-upload', active=True)
@override_switch('mixed-listed-unlisted', active=True)
class TestVersionSubmitDistribution(TestSubmitBase):

    def setUp(self):
        super(TestVersionSubmitDistribution, self).setUp()
        self.url = reverse('devhub.submit.version.distribution',
                           args=[self.addon.slug])

    def test_listed_redirects_to_next_step(self):
        response = self.client.post(self.url, {'channel': 'listed'})
        self.assert3xx(
            response,
            reverse('devhub.submit.version.upload', args=[
                self.addon.slug, 'listed']))

    def test_unlisted_redirects_to_next_step(self):
        response = self.client.post(self.url, {'channel': 'unlisted'})
        self.assert3xx(
            response,
            reverse('devhub.submit.version.upload', args=[
                self.addon.slug, 'unlisted']))


@override_switch('step-version-upload', active=True)
@override_switch('mixed-listed-unlisted', active=True)
class TestVersionSubmitAutoChannel(TestSubmitBase):
    """ Just check we chose the right upload channel.  The upload tests
    themselves are in other tests. """

    def setUp(self):
        super(TestVersionSubmitAutoChannel, self).setUp()
        self.url = reverse('devhub.submit.version', args=[self.addon.slug])

    @mock.patch('olympia.devhub.views._submit_upload',
                side_effect=views._submit_upload)
    def test_listed_last_uses_listed_upload(self, _submit_upload_mock):
        version_factory(addon=self.addon, channel=amo.RELEASE_CHANNEL_LISTED)
        self.client.post(self.url)
        args, _ = _submit_upload_mock.call_args
        assert args[1:] == (
            self.addon, amo.RELEASE_CHANNEL_LISTED,
            'devhub.submit.version.details', 'devhub.submit.version.finish')

    @mock.patch('olympia.devhub.views._submit_upload',
                side_effect=views._submit_upload)
    def test_unlisted_last_uses_unlisted_upload(self, _submit_upload_mock):
        version_factory(addon=self.addon, channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.client.post(self.url)
        args, _ = _submit_upload_mock.call_args
        assert args[1:] == (
            self.addon, amo.RELEASE_CHANNEL_UNLISTED,
            'devhub.submit.version.details', 'devhub.submit.version.finish')

    def test_no_versions_redirects_to_distribution(self):
        [v.delete() for v in self.addon.versions.all()]
        response = self.client.post(self.url)
        self.assert3xx(
            response,
            reverse('devhub.submit.version.distribution',
                    args=[self.addon.slug]))


@override_switch('step-version-upload', active=True)
@override_switch('mixed-listed-unlisted', active=False)
class TestVersionSubmitAutoChannelNoMixed(TestSubmitBase):

    def setUp(self):
        super(TestVersionSubmitAutoChannelNoMixed, self).setUp()
        self.url = reverse('devhub.submit.version', args=[self.addon.slug])

    @mock.patch('olympia.devhub.views._submit_upload',
                side_effect=views._submit_upload)
    def test_redirect_listed_based_on_is_listed(self, _submit_upload_mock):
        self.addon.update(is_listed=True)
        self.client.post(self.url)
        args, _ = _submit_upload_mock.call_args
        assert args[1:] == (
            self.addon, amo.RELEASE_CHANNEL_LISTED,
            'devhub.submit.version.details', 'devhub.submit.version.finish')

    @mock.patch('olympia.devhub.views._submit_upload',
                side_effect=views._submit_upload)
    def test_redirect_unlisted_based_on_is_listed(self, _submit_upload_mock):
        self.addon.update(is_listed=False)
        self.client.post(self.url)
        args, _ = _submit_upload_mock.call_args
        assert args[1:] == (
            self.addon, amo.RELEASE_CHANNEL_UNLISTED,
            'devhub.submit.version.details', 'devhub.submit.version.finish')


class VersionSubmitUploadMixin(object):
    channel = None
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(VersionSubmitUploadMixin, self).setUp()
        self.upload = self.get_upload('extension.xpi')
        self.addon = Addon.objects.get(id=3615)
        self.version = self.addon.current_version
        self.addon.update(guid='guid@xpi')
        assert self.client.login(email='del@icio.us')
        self.addon.update(
            is_listed=(self.channel == amo.RELEASE_CHANNEL_LISTED))
        self.addon.versions.update(channel=self.channel)
        channel = ('listed' if self.channel == amo.RELEASE_CHANNEL_LISTED else
                   'unlisted')
        self.url = reverse('devhub.submit.version.upload',
                           args=[self.addon.slug, channel])
        assert self.addon.has_complete_metadata()

    def post(self, supported_platforms=None,
             override_validation=False, expected_status=302, source=None,
             beta=False):
        if supported_platforms is None:
            supported_platforms = [amo.PLATFORM_MAC]
        d = dict(upload=self.upload.uuid.hex, source=source,
                 supported_platforms=[p.id for p in supported_platforms],
                 admin_override_validation=override_validation, beta=beta)
        r = self.client.post(self.url, d)
        assert r.status_code == expected_status
        return r

    def get_next_url(self, version):
        raise NotImplementedError

    def test_with_source(self):
        tdir = temp.gettempdir()
        source = temp.NamedTemporaryFile(suffix=".zip", dir=tdir)
        source.write('a' * (2 ** 21))
        source.seek(0)
        response = self.post(source=source)
        version = self.addon.find_latest_version(channel=self.channel)
        assert version.source
        self.assert3xx(response, self.get_next_url(version))
        assert self.addon.reload().admin_review

    def test_with_bad_source_format(self):
        tdir = temp.gettempdir()
        source = temp.NamedTemporaryFile(suffix=".exe", dir=tdir)
        source.write('a' * (2 ** 21))
        source.seek(0)
        response = self.post(source=source, expected_status=200)
        assert response.context['new_addon_form'].errors.as_text().startswith(
            '* source\n  * Unsupported file type, please upload an archive ')

    def test_missing_platforms(self):
        r = self.client.post(self.url, dict(upload=self.upload.uuid.hex))
        assert r.status_code == 200
        assert r.context['new_addon_form'].errors.as_text() == (
            '* supported_platforms\n  * Need at least one platform.')

    def test_one_xpi_for_multiple_platforms(self):
        response = self.post(supported_platforms=[amo.PLATFORM_MAC,
                                                  amo.PLATFORM_LINUX])
        version = self.addon.find_latest_version(channel=self.channel)
        self.assert3xx(response, self.get_next_url(version))
        all_ = sorted([f.filename for f in version.all_files])
        assert all_ == [u'delicious_bookmarks-0.1-linux.xpi',
                        u'delicious_bookmarks-0.1-mac.xpi']

    def test_unique_version_num(self):
        self.version.update(version='0.1')
        r = self.post(expected_status=200)
        assert pq(r.content)('ul.errorlist').text() == (
            'Version 0.1 already exists, or was uploaded before.')

    def test_same_version_if_previous_is_rejected(self):
        # We can't re-use the same version number, even if the previous
        # versions have been disabled/rejected.
        self.version.update(version='0.1')
        self.version.files.update(status=amo.STATUS_DISABLED)
        r = self.post(expected_status=200)
        assert pq(r.content)('ul.errorlist').text() == (
            'Version 0.1 already exists, or was uploaded before.')

    def test_same_version_if_previous_is_deleted(self):
        # We can't re-use the same version number if the previous
        # versions has been deleted either.
        self.version.update(version='0.1')
        self.version.delete()
        r = self.post(expected_status=200)
        assert pq(r.content)('ul.errorlist').text() == (
            'Version 0.1 already exists, or was uploaded before.')

    @override_switch('mixed-listed-unlisted', active=True)
    def test_distribution_link(self):
        response = self.client.get(self.url)
        channel_text = ('listed' if self.channel == amo.RELEASE_CHANNEL_LISTED
                        else 'unlisted')
        distribution_url = reverse('devhub.submit.version.distribution',
                                   args=[self.addon.slug])
        doc = pq(response.content)
        assert doc('.addon-submit-distribute a').attr('href') == (
            distribution_url + '?channel=' + channel_text)

    @override_switch('mixed-listed-unlisted', active=False)
    def test_distribution_link_hidden(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.addon-submit-distribute a').length == 0

    def test_beta_field(self):
        response = self.client.get(self.url)
        doc = pq(response.content)
        assert doc('.beta-status').length

    def test_url_is_404_for_disabled_addons(self):
        self.addon.update(status=amo.STATUS_DISABLED)
        r = self.client.get(self.url)
        assert r.status_code == 404


@override_switch('step-version-upload', active=True)
class TestVersionSubmitUploadListed(VersionSubmitUploadMixin, UploadTest):
    channel = amo.RELEASE_CHANNEL_LISTED

    def get_next_url(self, version):
        return reverse('devhub.submit.version.details', args=[
            self.addon.slug, version.pk])

    def test_success(self):
        response = self.post()
        version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        assert version.channel == amo.RELEASE_CHANNEL_LISTED
        assert version.all_files[0].status == amo.STATUS_AWAITING_REVIEW
        self.assert3xx(response, self.get_next_url(version))
        log_items = ActivityLog.objects.for_addons(self.addon)
        assert log_items.filter(action=amo.LOG.ADD_VERSION.id)

    @mock.patch('olympia.devhub.views.sign_file')
    def test_experiments_are_auto_signed(self, mock_sign_file):
        """Experiment extensions (bug 1220097) are auto-signed."""
        # We're going to sign even if it has signing related errors/warnings.
        self.upload = self.get_upload(
            'telemetry_experiment.xpi',
            validation=json.dumps({
                "notices": 2, "errors": 0, "messages": [],
                "metadata": {}, "warnings": 1,
                "signing_summary": {"trivial": 1, "low": 0,
                                    "medium": 0, "high": 1},
                "passed_auto_validation": 0}))
        self.addon.update(guid='experiment@xpi', is_listed=True,
                          status=amo.STATUS_PUBLIC)
        self.post()
        # Make sure the file created and signed is for this addon.
        assert mock_sign_file.call_count == 1
        mock_sign_file_call = mock_sign_file.call_args[0]
        signed_file = mock_sign_file_call[0]
        assert signed_file.version.addon == self.addon
        assert signed_file.version.channel == amo.RELEASE_CHANNEL_LISTED
        # There is a log for that file (with passed validation).
        log = ActivityLog.objects.latest(field_name='id')
        assert log.action == amo.LOG.EXPERIMENT_SIGNED.id

    def test_force_beta(self):
        self.post(beta=True)
        # Need latest() rather than find_latest_version as Beta isn't returned.
        version = self.addon.versions.latest()
        assert version.all_files[0].status == amo.STATUS_BETA

    def test_incomplete_addon_now_nominated(self):
        """Uploading a new version for an incomplete addon should set it to
        nominated."""
        self.addon.current_version.files.update(status=amo.STATUS_DISABLED)
        self.addon.update_status()
        # Deleting all the versions should make it null.
        assert self.addon.status == amo.STATUS_NULL
        self.post()
        self.addon.reload()
        assert self.addon.status == amo.STATUS_NOMINATED


@override_switch('step-version-upload', active=True)
class TestVersionSubmitUploadUnlisted(VersionSubmitUploadMixin, UploadTest):
    channel = amo.RELEASE_CHANNEL_UNLISTED

    def get_next_url(self, version):
        return reverse('devhub.submit.version.finish', args=[
            self.addon.slug, version.pk])

    @mock.patch('olympia.editors.helpers.sign_file')
    def test_success(self, mock_sign_file):
        """Sign automatically."""
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
        response = self.post()
        version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert version.channel == amo.RELEASE_CHANNEL_UNLISTED
        assert version.all_files[0].status == amo.STATUS_PUBLIC
        self.assert3xx(response, self.get_next_url(version))
        assert mock_sign_file.called

    @mock.patch('olympia.editors.helpers.sign_file')
    def test_success_fail_validation(self, mock_sign_file):
        self.upload = self.get_upload(
            'extension.xpi',
            validation=json.dumps(dict(errors=0, warnings=0, notices=2,
                                       metadata={}, messages=[],
                                       signing_summary={
                                           'trivial': 0, 'low': 1, 'medium': 0,
                                           'high': 0},
                                       passed_auto_validation=False
                                       )))
        response = self.post()
        version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert version.channel == amo.RELEASE_CHANNEL_UNLISTED
        assert version.all_files[0].status == amo.STATUS_PUBLIC
        self.assert3xx(response, self.get_next_url(version))
        assert mock_sign_file.called

    @mock.patch('olympia.devhub.views.auto_sign_file')
    def test_one_xpi_for_multiple_platforms(self, mock_auto_sign_file):
        super(TestVersionSubmitUploadUnlisted,
              self).test_one_xpi_for_multiple_platforms()
        version = self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        mock_auto_sign_file.assert_has_calls(
            [mock.call(f, is_beta=False) for f in version.all_files])

    def test_no_force_beta_for_unlisted(self):
        """No beta version for unlisted addons."""
        self.post(beta=True)
        # Need latest() rather than find_latest_version as Beta isn't returned.
        version = self.addon.versions.latest()
        assert version.all_files[0].status != amo.STATUS_BETA


@override_switch('step-version-upload', active=True)
class TestVersionSubmitDetails(TestSubmitBase):

    def setUp(self):
        super(TestVersionSubmitDetails, self).setUp()
        addon = self.get_addon()
        self.version = version_factory(
            addon=addon,
            channel=amo.RELEASE_CHANNEL_LISTED,
            license_id=addon.versions.latest().license_id)
        self.url = reverse('devhub.submit.version.details',
                           args=[addon.slug, self.version.pk])

    def test_submit_empty_is_okay(self):
        assert all(self.get_addon().get_required_metadata())
        r = self.client.get(self.url)
        assert r.status_code == 200

        response = self.client.post(self.url, {})
        self.assert3xx(
            response, reverse('devhub.submit.version.finish',
                              args=[self.addon.slug, self.version.pk]))

        assert not self.version.approvalnotes
        assert not self.version.releasenotes

    def test_submit_success(self):
        assert all(self.get_addon().get_required_metadata())
        r = self.client.get(self.url)
        assert r.status_code == 200

        # Post and be redirected - trying to sneak in a field that shouldn't
        # be modified when this is not the first listed version.
        data = {'approvalnotes': 'approove plz',
                'releasenotes': 'loadsa stuff', 'name': 'foo'}
        response = self.client.post(self.url, data)
        self.assert3xx(
            response, reverse('devhub.submit.version.finish',
                              args=[self.addon.slug, self.version.pk]))

        # This field should not have been modified.
        assert self.get_addon().name != 'foo'

        self.version.reload()
        assert self.version.approvalnotes == 'approove plz'
        assert self.version.releasenotes == 'loadsa stuff'

    def test_submit_details_unlisted_should_redirect(self):
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        assert all(self.get_addon().get_required_metadata())
        response = self.client.get(self.url)
        self.assert3xx(
            response, reverse('devhub.submit.version.finish',
                              args=[self.addon.slug, self.version.pk]))


@override_switch('step-version-upload', active=True)
class TestVersionSubmitDetailsFirstListed(TestAddonSubmitDetails):
    """ Testing the case of a listed version being submitted on an add-on that
    previously only had unlisted versions - so is missing metadata."""
    def setUp(self):
        super(TestVersionSubmitDetailsFirstListed, self).setUp()
        self.addon.versions.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        self.version = version_factory(addon=self.addon,
                                       channel=amo.RELEASE_CHANNEL_LISTED)
        self.url = reverse('devhub.submit.version.details',
                           args=['a3615', self.version.pk])
        self.next_step = reverse('devhub.submit.version.finish',
                                 args=['a3615', self.version.pk])


@override_switch('step-version-upload', active=True)
class TestVersionSubmitFinish(TestAddonSubmitFinish):

    def setUp(self):
        super(TestVersionSubmitFinish, self).setUp()
        addon = self.get_addon()
        self.version = version_factory(
            addon=addon,
            channel=amo.RELEASE_CHANNEL_LISTED,
            license_id=addon.versions.latest().license_id,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        self.url = reverse('devhub.submit.version.finish',
                           args=[addon.slug, self.version.pk])

    @mock.patch('olympia.devhub.tasks.send_welcome_email.delay')
    def test_no_welcome_email(self, send_welcome_email_mock):
        """No emails for version finish."""
        self.client.get(self.url)
        assert not send_welcome_email_mock.called

    def test_addon_no_versions_redirects_to_versions(self):
        # No versions makes getting to this step difficult!
        pass

    # No emails for any of these cases so ignore them.
    def test_welcome_email_for_newbies(self):
        pass

    def test_welcome_email_first_listed_addon(self):
        pass

    def test_welcome_email_if_previous_addon_is_incomplete(self):
        pass

    def test_no_welcome_email_if_unlisted(self):
        pass


@override_switch('step-version-upload', active=True)
class TestFileSubmitUpload(UploadTest):
    fixtures = ['base/users', 'base/addon_3615']

    def setUp(self):
        super(TestFileSubmitUpload, self).setUp()
        self.upload = self.get_upload('extension.xpi')
        self.addon = Addon.objects.get(id=3615)
        self.version = version_factory(
            addon=self.addon,
            channel=amo.RELEASE_CHANNEL_LISTED,
            license_id=self.addon.versions.latest().license_id,
            version='0.1',
            file_kw={
                'status': amo.STATUS_AWAITING_REVIEW,
                'platform': amo.PLATFORM_WIN.id})
        self.addon.update(guid='guid@xpi')
        assert self.client.login(email='del@icio.us')
        self.url = reverse('devhub.submit.file',
                           args=[self.addon.slug, self.version.pk])
        assert self.addon.has_complete_metadata()

    def post(self, supported_platforms=None,
             override_validation=False, expected_status=302, source=None,
             beta=False):
        if supported_platforms is None:
            supported_platforms = [amo.PLATFORM_MAC]
        d = dict(upload=self.upload.uuid.hex, source=source,
                 supported_platforms=[p.id for p in supported_platforms],
                 admin_override_validation=override_validation, beta=beta)
        r = self.client.post(self.url, d)
        assert r.status_code == expected_status, r.content
        return r

    def test_success_listed(self):
        files_pre = self.version.all_files
        response = self.post()
        assert self.version == self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_LISTED)
        del self.version.all_files
        files_post = self.version.all_files
        assert files_pre != files_post
        assert files_pre == files_post[:-1]
        new_file = self.version.all_files[-1]
        assert new_file.status == amo.STATUS_AWAITING_REVIEW
        assert new_file.platform == amo.PLATFORM_MAC.id
        next_url = reverse('devhub.submit.file.finish',
                           args=[self.addon.slug, self.version.pk])
        self.assert3xx(response, next_url)
        log_items = ActivityLog.objects.for_addons(self.addon)
        assert not log_items.filter(action=amo.LOG.ADD_VERSION.id).exists()

    def test_success_unlisted(self):
        self.version.update(channel=amo.RELEASE_CHANNEL_UNLISTED)
        files_pre = self.version.all_files
        FileValidation.from_json(
            files_pre[0],
            json.dumps(dict(errors=0, warnings=0, notices=2, metadata={},
                            messages=[],
                            signing_summary={'trivial': 1, 'low': 0,
                                             'medium': 0, 'high': 0},
                            passed_auto_validation=True)))
        response = self.post()
        assert self.version == self.addon.find_latest_version(
            channel=amo.RELEASE_CHANNEL_UNLISTED)
        del self.version.all_files
        files_post = self.version.all_files
        assert files_pre != files_post
        assert files_pre == files_post[:-1]
        new_file = self.version.all_files[-1]
        assert new_file.status == amo.STATUS_PUBLIC
        assert new_file.platform == amo.PLATFORM_MAC.id
        next_url = reverse('devhub.submit.file.finish',
                           args=[self.addon.slug, self.version.pk])
        self.assert3xx(response, next_url)
        log_items = ActivityLog.objects.for_addons(self.addon)
        assert not log_items.filter(action=amo.LOG.ADD_VERSION.id).exists()

    def test_failure_when_cant_upload_more(self):
        """e.g. when the version is already reviewed.  The button shouldn't be
        shown but upload should fail anyways."""
        self.version.all_files[0].update(status=amo.STATUS_PUBLIC)
        assert not self.version.is_allowed_upload()

        r = self.post(expected_status=200)
        assert pq(r.content)('ul.errorlist').text() == (
            'You cannot upload any more files for this version.')

    def test_failure_when_version_number_doesnt_match(self):
        self.version.update(version='99')
        r = self.post(expected_status=200)
        assert pq(r.content)('ul.errorlist').text() == (
            "Version doesn't match")

    def test_force_beta_is_ignored(self):
        """Files must have the same beta status as the existing version."""
        self.post(beta=True)
        # Need latest() rather than find_latest_version as Beta isn't returned.
        version = self.addon.versions.latest()
        assert version.all_files[0].status != amo.STATUS_BETA

    def test_beta_automatically_if_version_is_beta(self):
        """Files must have the same beta status as the existing version."""
        existing_file = self.version.all_files[0]
        existing_file.update(status=amo.STATUS_BETA)
        FileValidation.from_json(
            existing_file,
            json.dumps(dict(errors=0, warnings=0, notices=2, metadata={},
                            messages=[],
                            signing_summary={'trivial': 1, 'low': 0,
                                             'medium': 0, 'high': 0},
                            passed_auto_validation=True)))
        self.version.save()

        self.post(beta=False)
        # Need latest() rather than find_latest_version as Beta isn't returned.
        version = self.addon.versions.latest()
        assert version.all_files[0].status == amo.STATUS_BETA
