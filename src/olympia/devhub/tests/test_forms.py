# -*- coding: utf-8 -*-
import json
import os
import shutil

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.utils import translation

import mock
import pytest

from PIL import Image

from olympia import amo
from olympia.addons.forms import EditThemeForm, EditThemeOwnerForm, ThemeForm
from olympia.addons.models import Addon, Category, Persona
from olympia.amo.templatetags.jinja_helpers import user_media_path
from olympia.amo.tests import TestCase
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.urlresolvers import reverse
from olympia.applications.models import AppVersion
from olympia.devhub import forms
from olympia.files.models import FileUpload
from olympia.reviewers.models import RereviewQueueTheme
from olympia.tags.models import Tag
from olympia.users.models import UserProfile
from olympia.versions.models import License


class TestNewUploadForm(TestCase):

    def test_only_valid_uploads(self):
        upload = FileUpload.objects.create(valid=False)
        form = forms.NewUploadForm(
            {'upload': upload.uuid, 'supported_platforms': [1]},
            request=mock.Mock())
        assert ('There was an error with your upload. Please try again.' in
                form.errors.get('__all__')), form.errors

        # Admin override makes the form ignore the brokenness
        with mock.patch('olympia.access.acl.action_allowed_user') as acl:
            # For the 'Addons:Edit' permission check.
            acl.return_value = True
            form = forms.NewUploadForm(
                {'upload': upload.uuid, 'supported_platforms': [1],
                    'admin_override_validation': True},
                request=mock.Mock())
            assert ('There was an error with your upload. Please try' not in
                    form.errors.get('__all__')), form.errors

        upload.validation = '{"errors": 0}'
        upload.save()
        addon = Addon.objects.create()
        form = forms.NewUploadForm(
            {'upload': upload.uuid, 'supported_platforms': [1]},
            addon=addon, request=mock.Mock())
        assert ('There was an error with your upload. Please try again.' not in
                form.errors.get('__all__')), form.errors

    # Those three patches are so files.utils.parse_addon doesn't fail on a
    # non-existent file even before having a chance to call check_xpi_info.
    @mock.patch('olympia.files.utils.Extractor.parse')
    @mock.patch('olympia.files.utils.extract_xpi', lambda xpi, path: None)
    @mock.patch('olympia.files.utils.get_file', lambda xpi: None)
    # This is the one we want to test.
    @mock.patch('olympia.files.utils.check_xpi_info')
    def test_check_xpi_called(self, mock_check_xpi_info, mock_parse):
        """Make sure the check_xpi_info helper is called.

        There's some important checks made in check_xpi_info, if we ever
        refactor the form to not call it anymore, we need to make sure those
        checks are run at some point.
        """
        mock_parse.return_value = None
        mock_check_xpi_info.return_value = {'name': 'foo', 'type': 2}
        upload = FileUpload.objects.create(valid=True)
        addon = Addon.objects.create()
        form = forms.NewUploadForm(
            {'upload': upload.uuid, 'supported_platforms': [1]},
            addon=addon, request=mock.Mock())
        form.clean()
        assert mock_check_xpi_info.called


class TestCompatForm(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestCompatForm, self).setUp()
        AppVersion.objects.create(
            application=amo.THUNDERBIRD.id, version='50.0')
        AppVersion.objects.create(
            application=amo.THUNDERBIRD.id, version='58.0')
        AppVersion.objects.create(
            application=amo.FIREFOX.id, version='56.0')
        AppVersion.objects.create(
            application=amo.FIREFOX.id, version='56.*')
        AppVersion.objects.create(
            application=amo.FIREFOX.id, version='57.0')
        AppVersion.objects.create(
            application=amo.FIREFOX.id, version='57.*')

    def test_forms(self):
        version = Addon.objects.get(id=3615).current_version
        formset = forms.CompatFormSet(None, queryset=version.apps.all(),
                                      form_kwargs={'version': version})
        apps = [form.app for form in formset.forms]
        assert set(apps) == set(amo.APP_USAGE)

    def test_forms_disallow_thunderbird_and_seamonkey(self):
        self.create_switch('disallow-thunderbird-and-seamonkey')
        version = Addon.objects.get(id=3615).current_version
        formset = forms.CompatFormSet(None, queryset=version.apps.all(),
                                      form_kwargs={'version': version})
        apps = [form.app for form in formset.forms]
        assert set(apps) == set(amo.APP_USAGE_FIREFOXES_ONLY)

    def test_form_initial(self):
        version = Addon.objects.get(id=3615).current_version
        current_min = version.apps.filter(application=amo.FIREFOX.id).get().min
        current_max = version.apps.filter(application=amo.FIREFOX.id).get().max
        formset = forms.CompatFormSet(None, queryset=version.apps.all(),
                                      form_kwargs={'version': version})
        form = formset.forms[0]
        assert form.app == amo.FIREFOX
        assert form.initial['application'] == amo.FIREFOX.id
        assert form.initial['min'] == current_min.pk
        assert form.initial['max'] == current_max.pk

    def _test_form_choices_expect_all_versions(self, version):
        expected_min_choices = [(u'', u'---------')] + list(
            AppVersion.objects.filter(application=amo.FIREFOX.id)
                              .exclude(version__contains='*')
                              .values_list('pk', 'version')
                              .order_by('version_int'))
        expected_max_choices = [(u'', u'---------')] + list(
            AppVersion.objects.filter(application=amo.FIREFOX.id)
                              .values_list('pk', 'version')
                              .order_by('version_int'))

        formset = forms.CompatFormSet(None, queryset=version.apps.all(),
                                      form_kwargs={'version': version})
        form = formset.forms[0]
        assert form.app == amo.FIREFOX
        assert list(form.fields['min'].choices) == expected_min_choices
        assert list(form.fields['max'].choices) == expected_max_choices

    def test_form_choices(self):
        version = Addon.objects.get(id=3615).current_version
        version.files.all().update(is_webextension=True)
        del version.all_files
        self._test_form_choices_expect_all_versions(version)

    def test_form_choices_no_compat(self):
        version = Addon.objects.get(id=3615).current_version
        version.files.all().update(is_webextension=False)
        version.addon.update(type=amo.ADDON_DICT)
        del version.all_files
        self._test_form_choices_expect_all_versions(version)

    def test_form_choices_language_pack(self):
        version = Addon.objects.get(id=3615).current_version
        version.files.all().update(is_webextension=False)
        version.addon.update(type=amo.ADDON_LPAPP)
        del version.all_files
        self._test_form_choices_expect_all_versions(version)

    def test_form_choices_legacy(self):
        version = Addon.objects.get(id=3615).current_version
        version.files.all().update(is_webextension=False)
        del version.all_files

        firefox_57 = AppVersion.objects.get(
            application=amo.FIREFOX.id, version='57.0')
        firefox_57_s = AppVersion.objects.get(
            application=amo.FIREFOX.id, version='57.*')

        expected_min_choices = [(u'', u'---------')] + list(
            AppVersion.objects.filter(application=amo.FIREFOX.id)
                              .exclude(version__contains='*')
                              .exclude(pk__in=(firefox_57.pk, firefox_57_s.pk))
                              .values_list('pk', 'version')
                              .order_by('version_int'))
        expected_max_choices = [(u'', u'---------')] + list(
            AppVersion.objects.filter(application=amo.FIREFOX.id)
                              .exclude(pk__in=(firefox_57.pk, firefox_57_s.pk))
                              .values_list('pk', 'version')
                              .order_by('version_int'))

        formset = forms.CompatFormSet(None, queryset=version.apps.all(),
                                      form_kwargs={'version': version})
        form = formset.forms[0]
        assert form.app == amo.FIREFOX
        assert list(form.fields['min'].choices) == expected_min_choices
        assert list(form.fields['max'].choices) == expected_max_choices

        expected_tb_choices = [(u'', u'---------')] + list(
            AppVersion.objects.filter(application=amo.THUNDERBIRD.id)
            .values_list('pk', 'version').order_by('version_int'))
        form = formset.forms[1]
        assert form.app == amo.THUNDERBIRD
        assert list(form.fields['min'].choices) == expected_tb_choices
        assert list(form.fields['max'].choices) == expected_tb_choices

    def test_form_choices_mozilla_signed_legacy(self):
        version = Addon.objects.get(id=3615).current_version
        version.files.all().update(
            is_webextension=False,
            is_mozilla_signed_extension=True)
        del version.all_files
        self._test_form_choices_expect_all_versions(version)

    def test_static_theme(self):
        version = Addon.objects.get(id=3615).current_version
        version.files.all().update(is_webextension=True)
        version.addon.update(type=amo.ADDON_STATICTHEME)
        del version.all_files
        self._test_form_choices_expect_all_versions(version)

        formset = forms.CompatFormSet(None, queryset=version.apps.all(),
                                      form_kwargs={'version': version})
        assert formset.can_delete is False  # No deleting Firefox app plz.
        assert formset.extra == 0  # And lets not extra apps be added.


class TestPreviewForm(TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        super(TestPreviewForm, self).setUp()
        self.dest = os.path.join(settings.TMP_PATH, 'preview')
        if not os.path.exists(self.dest):
            os.makedirs(self.dest)

    @mock.patch('olympia.amo.models.ModelBase.update')
    def test_preview_modified(self, update_mock):
        addon = Addon.objects.get(pk=3615)
        name = 'transparent.png'
        form = forms.PreviewForm({'caption': 'test', 'upload_hash': name,
                                  'position': 1})
        with storage.open(os.path.join(self.dest, name), 'w') as f:
            shutil.copyfileobj(open(get_image_path(name)), f)
        assert form.is_valid()
        form.save(addon)
        assert update_mock.called

    @mock.patch('olympia.amo.utils.pngcrush_image')
    def test_preview_size(self, pngcrush_image_mock):
        addon = Addon.objects.get(pk=3615)
        name = 'non-animated.gif'
        form = forms.PreviewForm({'caption': 'test', 'upload_hash': name,
                                  'position': 1})
        with storage.open(os.path.join(self.dest, name), 'w') as f:
            shutil.copyfileobj(open(get_image_path(name)), f)
        assert form.is_valid()
        form.save(addon)
        preview = addon.previews.all()[0]
        assert preview.sizes == (
            {u'image': [250, 297], u'thumbnail': [126, 150],
             u'original': [250, 297]})
        assert os.path.exists(preview.image_path)
        assert os.path.exists(preview.thumbnail_path)
        assert os.path.exists(preview.original_path)

        assert pngcrush_image_mock.call_count == 2
        assert pngcrush_image_mock.call_args_list[0][0][0] == (
            preview.thumbnail_path)
        assert pngcrush_image_mock.call_args_list[1][0][0] == (
            preview.image_path)


class TestThemeForm(TestCase):
    fixtures = ['base/user_2519']

    def setUp(self):
        super(TestThemeForm, self).setUp()
        self.populate()
        self.request = mock.Mock()
        self.request.user = mock.Mock()
        self.request.user.groups_list = []
        self.request.user.is_authenticated.return_value = True

    def populate(self):
        self.cat = Category.objects.create(application=amo.FIREFOX.id,
                                           type=amo.ADDON_PERSONA)
        License.objects.create(id=amo.LICENSE_CC_BY.id)

    def get_dict(self, **kw):
        data = {
            'name': 'new name',
            'slug': 'special-slug',
            'category': self.cat.id,
            'accentcolor': '#003366',
            'textcolor': '#C0FFEE',
            'description': 'new description',
            'tags': 'tag1, tag2, tag3',
            'license': amo.LICENSE_CC_BY.id,
            'agreed': True,
            'header_hash': 'b4ll1n'
        }
        data.update(**kw)
        return data

    def post(self, **kw):
        self.form = ThemeForm(self.get_dict(**kw), request=self.request)
        return self.form

    def test_name_required(self):
        self.post(name='')
        assert not self.form.is_valid()
        assert self.form.errors == {'name': ['This field is required.']}

    def test_name_length(self):
        self.post(name='a' * 51)
        assert not self.form.is_valid()
        assert self.form.errors == {
            'name': ['Ensure this value has at most '
                     '50 characters (it has 51).']}

    def test_slug_unique(self):
        # A theme cannot share the same slug as another theme's.
        Addon.objects.create(type=amo.ADDON_PERSONA, slug='harry-potter')
        for slug in ('Harry-Potter', '  harry-potter  ', 'harry-potter'):
            self.post(slug=slug)
            assert not self.form.is_valid()
            assert self.form.errors == {
                'slug': ['This slug is already in use. '
                         'Please choose another.']}

    def test_slug_required(self):
        self.post(slug='')
        assert not self.form.is_valid()
        assert self.form.errors == {'slug': ['This field is required.']}

    def test_slug_length(self):
        self.post(slug='a' * 31)
        assert not self.form.is_valid()
        assert self.form.errors == {
            'slug': ['Ensure this value has at most 30 characters '
                     '(it has 31).']}

    def test_description_optional(self):
        self.post(description='')
        assert self.form.is_valid()

    def test_description_length(self):
        self.post(description='a' * 501)
        assert not self.form.is_valid()
        assert self.form.errors == (
            {'description': ['Ensure this value has at most '
                             '500 characters (it has 501).']})

    def test_categories_required(self):
        self.post(category='')
        assert not self.form.is_valid()
        assert self.form.errors == {'category': ['This field is required.']}

    def test_license_required(self):
        self.post(license='')
        assert not self.form.is_valid()
        assert self.form.errors == {'license': ['A license must be selected.']}

    def test_header_hash_required(self):
        self.post(header_hash='')
        assert not self.form.is_valid()
        assert self.form.errors == {'header_hash': ['This field is required.']}

    def test_accentcolor_optional(self):
        self.post(accentcolor='')
        assert self.form.is_valid()

    def test_accentcolor_invalid(self):
        self.post(accentcolor='#BALLIN')
        assert not self.form.is_valid()
        assert self.form.errors == (
            {'accentcolor': ['This must be a valid hex color code, '
                             'such as #000000.']})

    def test_textcolor_optional(self):
        self.post(textcolor='')
        assert self.form.is_valid(), self.form.errors

    def test_textcolor_invalid(self):
        self.post(textcolor='#BALLIN')
        assert not self.form.is_valid()
        assert self.form.errors == (
            {'textcolor': ['This must be a valid hex color code, '
                           'such as #000000.']})

    def get_img_urls(self):
        return reverse('devhub.personas.upload_persona',
                       args=['persona_header'])

    def test_img_attrs(self):
        header_url = self.get_img_urls()

        self.post()
        assert self.form.fields['header'].widget.attrs == (
            {'data-allowed-types': amo.SUPPORTED_IMAGE_TYPES,
             'data-upload-url': header_url})

    @mock.patch('olympia.addons.tasks.make_checksum')
    @mock.patch('olympia.addons.tasks.create_persona_preview_images')
    @mock.patch('olympia.addons.tasks.save_persona_image')
    @pytest.mark.skipif(not hasattr(Image.core, 'jpeg_encoder'),
                        reason='Not having a jpeg encoder makes test sad')
    def test_success(self, save_persona_image_mock,
                     create_persona_preview_images_mock, make_checksum_mock):
        make_checksum_mock.return_value = 'hashyourselfbeforeyoucrashyourself'

        self.request.user = UserProfile.objects.get(pk=2519)

        data = self.get_dict()
        header_url = self.get_img_urls()

        # Upload header image.
        img = open(get_image_path('persona-header.jpg'), 'rb')
        r_ajax = self.client.post(header_url, {'upload_image': img})
        data.update(header_hash=json.loads(r_ajax.content)['upload_hash'])

        # Populate and save form.
        self.post()
        assert self.form.is_valid(), self.form.errors
        self.form.save()

        addon = Addon.objects.filter(type=amo.ADDON_PERSONA).order_by('-id')[0]
        persona = addon.persona

        # Test for correct Addon and Persona values.
        assert unicode(addon.name) == data['name']
        assert addon.slug == data['slug']
        self.assertSetEqual(set(addon.categories.values_list('id', flat=True)),
                            {self.cat.id})
        self.assertSetEqual(set(addon.tags.values_list('tag_text', flat=True)),
                            set(data['tags'].split(', ')))
        assert persona.persona_id == 0
        assert persona.license == data['license']
        assert persona.accentcolor == data['accentcolor'].lstrip('#')
        assert persona.textcolor == data['textcolor'].lstrip('#')
        assert persona.author == self.request.user.username
        assert persona.display_username == self.request.user.name
        assert not persona.dupe_persona

        v = addon.versions.all()
        assert len(v) == 1
        assert v[0].version == '0'

        # Test for header and preview images.
        dst = os.path.join(user_media_path('addons'), str(addon.id))

        header_src = os.path.join(settings.TMP_PATH, 'persona_header',
                                  u'b4ll1n')

        assert save_persona_image_mock.mock_calls == (
            [mock.call(src=header_src,
                       full_dst=os.path.join(dst, 'header.png'))])

        create_persona_preview_images_mock.assert_called_with(
            src=header_src,
            full_dst=[os.path.join(dst, 'preview.png'),
                      os.path.join(dst, 'icon.png')],
            set_modified_on=addon.serializable_reference())

    @mock.patch('olympia.addons.tasks.create_persona_preview_images')
    @mock.patch('olympia.addons.tasks.save_persona_image')
    @mock.patch('olympia.addons.tasks.make_checksum')
    def test_dupe_persona(self, make_checksum_mock, mock1, mock2):
        """
        Submitting persona with checksum already in db should be marked
        duplicate.
        """
        make_checksum_mock.return_value = 'cornhash'

        self.request.user = UserProfile.objects.get(pk=2519)

        self.post()
        assert self.form.is_valid(), self.form.errors
        self.form.save()

        self.post(name='whatsinaname', slug='metalslug')
        assert self.form.is_valid(), self.form.errors
        self.form.save()

        personas = Persona.objects.order_by('addon__name')
        assert personas[0].checksum == personas[1].checksum
        assert personas[1].dupe_persona == personas[0]
        assert personas[0].dupe_persona is None


class TestEditThemeForm(TestCase):
    fixtures = ['base/user_2519']

    def setUp(self):
        super(TestEditThemeForm, self).setUp()
        self.populate()
        self.request = mock.Mock()
        self.request.user = mock.Mock()
        self.request.user.groups_list = []
        self.request.user.username = 'swagyismymiddlename'
        self.request.user.name = 'Sir Swag A Lot'
        self.request.user.is_authenticated.return_value = True

    def populate(self):
        self.instance = Addon.objects.create(
            type=amo.ADDON_PERSONA, status=amo.STATUS_PUBLIC,
            slug='swag-overload', name='Bands Make Me Dance',
            description='tha description')
        self.cat = Category.objects.create(
            type=amo.ADDON_PERSONA, db_name='xxxx')
        self.instance.addoncategory_set.create(category=self.cat)
        self.license = amo.LICENSE_CC_BY.id
        self.theme = Persona.objects.create(
            persona_id=0, addon_id=self.instance.id, license=self.license,
            accentcolor='C0FFEE', textcolor='EFFFFF')
        Tag(tag_text='sw').save_tag(self.instance)
        Tag(tag_text='ag').save_tag(self.instance)

    def get_dict(self, **kw):
        data = {
            'accentcolor': '#C0FFEE',
            'category': self.cat.id,
            'license': self.license,
            'slug': self.instance.slug,
            'tags': 'ag, sw',
            'textcolor': '#EFFFFF',

            'name_en-us': unicode(self.instance.name),
            'description_en-us': unicode(self.instance.description),
        }
        data.update(**kw)
        return data

    def test_initial(self):
        self.form = EditThemeForm(None, request=self.request,
                                  instance=self.instance)

        # Compare form initial data with post data.
        eq_data = self.get_dict()
        for k in [k for k in self.form.initial.keys()
                  if k not in ['name', 'description']]:
            assert self.form.initial[k] == eq_data[k]

    def save_success(self):
        other_cat = Category.objects.create(type=amo.ADDON_PERSONA)
        self.data = {
            'accentcolor': '#EFF0FF',
            'category': other_cat.id,
            'license': amo.LICENSE_CC_BY_NC_SA.id,
            'slug': 'swag-lifestyle',
            'tags': 'ag',
            'textcolor': '#CACACA',

            'name_en-us': 'All Day I Dream About Swag',
            'description_en-us': 'ADIDAS',
        }
        self.form = EditThemeForm(self.data, request=self.request,
                                  instance=self.instance)

        # Compare form initial data with post data.
        eq_data = self.get_dict()
        for k in [k for k in self.form.initial.keys()
                  if k not in ['name', 'description']]:
            assert self.form.initial[k] == eq_data[k]

        assert self.form.data == self.data
        assert self.form.is_valid(), self.form.errors
        self.form.save()

    def test_success(self):
        self.save_success()
        self.instance = self.instance.reload()
        assert unicode(self.instance.persona.accentcolor) == (
            self.data['accentcolor'].lstrip('#'))
        assert self.instance.categories.all()[0].id == self.data['category']
        assert self.instance.persona.license == self.data['license']
        assert unicode(self.instance.name) == self.data['name_en-us']
        assert unicode(self.instance.description) == (
            self.data['description_en-us'])
        self.assertSetEqual(
            set(self.instance.tags.values_list('tag_text', flat=True)),
            {self.data['tags']})
        assert unicode(self.instance.persona.textcolor) == (
            self.data['textcolor'].lstrip('#'))

    def test_success_twice(self):
        """Form should be just fine when POSTing twice."""
        self.save_success()
        self.form.save()

    def test_localize_name_description(self):
        data = self.get_dict(name_de='name_de',
                             description_de='description_de')
        self.form = EditThemeForm(data, request=self.request,
                                  instance=self.instance)
        assert self.form.is_valid(), self.form.errors
        self.form.save()

    @mock.patch('olympia.addons.tasks.make_checksum')
    @mock.patch('olympia.addons.tasks.create_persona_preview_images')
    @mock.patch('olympia.addons.tasks.save_persona_image')
    def test_reupload(self, save_persona_image_mock,
                      create_persona_preview_images_mock,
                      make_checksum_mock):
        make_checksum_mock.return_value = 'checksumbeforeyouwrecksome'
        data = self.get_dict(header_hash='y0l0')
        self.form = EditThemeForm(data, request=self.request,
                                  instance=self.instance)
        assert self.form.is_valid()
        self.form.save()

        dst = os.path.join(user_media_path('addons'), str(self.instance.id))
        header_src = os.path.join(settings.TMP_PATH, 'persona_header',
                                  u'y0l0')

        assert save_persona_image_mock.mock_calls == (
            [mock.call(src=header_src,
                       full_dst=os.path.join(dst, 'pending_header.png'))])

        rqt = RereviewQueueTheme.objects.filter(theme=self.instance.persona)
        assert rqt.count() == 1
        assert rqt[0].header == 'pending_header.png'
        assert not rqt[0].dupe_persona

    @mock.patch('olympia.addons.tasks.create_persona_preview_images',
                new=mock.Mock)
    @mock.patch('olympia.addons.tasks.save_persona_image', new=mock.Mock)
    @mock.patch('olympia.addons.tasks.make_checksum')
    def test_reupload_duplicate(self, make_checksum_mock):
        make_checksum_mock.return_value = 'checksumbeforeyouwrecksome'

        theme = amo.tests.addon_factory(type=amo.ADDON_PERSONA)
        theme.persona.checksum = 'checksumbeforeyouwrecksome'
        theme.persona.save()

        data = self.get_dict(header_hash='head')
        self.form = EditThemeForm(data, request=self.request,
                                  instance=self.instance)
        assert self.form.is_valid()
        self.form.save()

        rqt = RereviewQueueTheme.objects.get(theme=self.instance.persona)
        assert rqt.dupe_persona == theme.persona

    @mock.patch('olympia.addons.tasks.make_checksum')
    @mock.patch('olympia.addons.tasks.create_persona_preview_images',
                new=mock.Mock)
    @mock.patch('olympia.addons.tasks.save_persona_image', new=mock.Mock)
    def test_reupload_legacy_header_only(self, make_checksum_mock):
        """
        STR the bug this test fixes:

        - Reupload a legacy theme (/w footer == leg.png) legacy, header only.
        - The header would get saved as 'pending_header.png'.
        - The footer would get saved as 'footer.png'.
        - On approving, it would see 'footer.png' !== 'leg.png'
        - It run move_stored_file('footer.png', 'leg.png').
        - But footer.png does not exist. BAM BUG.

        Footer has been removed in Issue #5379
        https://github.com/mozilla/addons-server/issues/5379
        """
        make_checksum_mock.return_value = 'comechecksome'

        self.theme.header = 'Legacy-header3H.png'
        self.theme.save()

        data = self.get_dict(header_hash='arthro')
        self.form = EditThemeForm(data, request=self.request,
                                  instance=self.instance)
        assert self.form.is_valid()
        self.form.save()

        rqt = RereviewQueueTheme.objects.get()
        assert rqt.header == 'pending_header.png'


class TestEditThemeOwnerForm(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestEditThemeOwnerForm, self).setUp()
        self.instance = Addon.objects.create(
            type=amo.ADDON_PERSONA,
            status=amo.STATUS_PUBLIC, slug='swag-overload',
            name='Bands Make Me Dance', description='tha description')
        Persona.objects.create(
            persona_id=0, addon_id=self.instance.id,
            license=amo.LICENSE_CC_BY.id, accentcolor='C0FFEE',
            textcolor='EFFFFF')

    def test_initial(self):
        self.form = EditThemeOwnerForm(None, instance=self.instance)
        assert self.form.initial == {}

        self.instance.addonuser_set.create(user_id=999)
        assert self.instance.addonuser_set.all()[0].user.email == (
            'regular@mozilla.com')
        self.form = EditThemeOwnerForm(None, instance=self.instance)
        assert self.form.initial == {'owner': 'regular@mozilla.com'}

    def test_success_change_from_no_owner(self):
        self.form = EditThemeOwnerForm({'owner': 'regular@mozilla.com'},
                                       instance=self.instance)
        assert self.form.is_valid(), self.form.errors
        self.form.save()
        assert self.instance.addonuser_set.all()[0].user.email == (
            'regular@mozilla.com')

    def test_success_replace_owner(self):
        self.instance.addonuser_set.create(user_id=999)
        self.form = EditThemeOwnerForm({'owner': 'regular@mozilla.com'},
                                       instance=self.instance)
        assert self.form.is_valid(), self.form.errors
        self.form.save()
        assert self.instance.addonuser_set.all()[0].user.email == (
            'regular@mozilla.com')

    def test_error_invalid_user(self):
        self.form = EditThemeOwnerForm({'owner': 'omg@org.yes'},
                                       instance=self.instance)
        assert not self.form.is_valid()


class TestDistributionChoiceForm(TestCase):

    @pytest.mark.needs_locales_compilation
    def test_lazy_choice_labels(self):
        """Tests that the labels in `choices` are still lazy

        We had a problem that the labels weren't properly marked as lazy
        which led to labels being returned in mixed languages depending
        on what server we hit in production.
        """
        with translation.override('en-US'):
            form = forms.DistributionChoiceForm()
            label = form.fields['channel'].choices[0][1]

            expected = 'On this site.'
            label = unicode(label)
            assert label.startswith(expected)

        with translation.override('de'):
            form = forms.DistributionChoiceForm()
            label = form.fields['channel'].choices[0][1]

            expected = 'Auf dieser Website.'
            label = unicode(label)
            assert label.startswith(expected)
