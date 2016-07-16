import json
import os

from django.conf import settings
from django.core.files.storage import default_storage as storage

import mock
import pytest
from PIL import Image

from olympia import amo, paypal
from olympia.amo.tests import TestCase
from olympia.amo.tests.test_helpers import get_image_path
from olympia.amo.urlresolvers import reverse
from olympia.amo.helpers import user_media_path
from olympia.applications.models import AppVersion
from olympia.addons.forms import EditThemeForm, EditThemeOwnerForm, ThemeForm
from olympia.addons.models import Addon, Category, Charity, Persona
from olympia.devhub import forms
from olympia.editors.models import RereviewQueueTheme
from olympia.files.helpers import copyfileobj
from olympia.files.models import FileUpload
from olympia.tags.models import Tag
from olympia.users.models import UserProfile
from olympia.versions.models import ApplicationsVersions, License, Version


class TestNewAddonForm(TestCase):

    def test_only_valid_uploads(self):
        upload = FileUpload.objects.create(valid=False)
        form = forms.NewAddonForm(
            {'upload': upload.uuid, 'supported_platforms': [1]},
            request=mock.Mock())
        assert ('There was an error with your upload. Please try again.' in
                form.errors.get('__all__')), form.errors

        upload.validation = '{"errors": 0}'
        upload.save()
        form = forms.NewAddonForm(
            {'upload': upload.uuid, 'supported_platforms': [1]},
            request=mock.Mock())
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
        form = forms.NewAddonForm(
            {'upload': upload.uuid, 'supported_platforms': [1]},
            request=mock.Mock())
        form.clean()
        assert mock_check_xpi_info.called


class TestNewVersionForm(TestCase):

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
        form = forms.NewVersionForm(
            {'upload': upload.uuid, 'supported_platforms': [1],
             'nomination_type': amo.STATUS_NOMINATED},
            addon=addon,
            request=mock.Mock())
        form.clean()
        assert mock_check_xpi_info.called


class TestNewFileForm(TestCase):

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
        version = Version.objects.create(addon=addon)
        version.compatible_platforms = mock.Mock()
        version.compatible_platforms.return_value = amo.SUPPORTED_PLATFORMS
        form = forms.NewFileForm(
            {'upload': upload.uuid, 'supported_platforms': [1],
             'nomination_type': amo.STATUS_NOMINATED,
             'platform': '1'},
            addon=addon,
            version=version,
            request=mock.Mock())
        form.clean()
        assert mock_check_xpi_info.called


class TestContribForm(TestCase):

    def test_neg_suggested_amount(self):
        form = forms.ContribForm({'suggested_amount': -10})
        assert not form.is_valid()
        assert form.errors['suggested_amount'][0] == (
            'Please enter a suggested amount greater than 0.')

    def test_max_suggested_amount(self):
        form = forms.ContribForm(
            {'suggested_amount': settings.MAX_CONTRIBUTION + 10})
        assert not form.is_valid()
        assert form.errors['suggested_amount'][0] == (
            'Please enter a suggested amount less than $%s.' %
            settings.MAX_CONTRIBUTION)


class TestCharityForm(TestCase):

    def setUp(self):
        super(TestCharityForm, self).setUp()
        self.paypal_mock = mock.Mock()
        self.paypal_mock.return_value = (True, None)
        paypal.check_paypal_id = self.paypal_mock

    def test_always_new(self):
        # Editing a charity should always produce a new row.
        params = dict(name='name', url='http://url.com/', paypal='paypal')
        charity = forms.CharityForm(params).save()
        for k, v in params.items():
            assert getattr(charity, k) == v
        assert charity.id

        # Get a fresh instance since the form will mutate it.
        instance = Charity.objects.get(id=charity.id)
        params['name'] = 'new'
        new_charity = forms.CharityForm(params, instance=instance).save()
        for k, v in params.items():
            assert getattr(new_charity, k) == v

        assert new_charity.id != charity.id


class TestCompatForm(TestCase):
    fixtures = ['base/addon_3615']

    def test_mozilla_app(self):
        moz = amo.MOZILLA
        appver = AppVersion.objects.create(application=moz.id)
        v = Addon.objects.get(id=3615).current_version
        ApplicationsVersions(application=moz.id, version=v,
                             min=appver, max=appver).save()
        fs = forms.CompatFormSet(None, queryset=v.apps.all())
        apps = [f.app for f in fs.forms]
        assert moz in apps


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
            copyfileobj(open(get_image_path(name)), f)
        assert form.is_valid()
        form.save(addon)
        assert update_mock.called

    def test_preview_size(self):
        addon = Addon.objects.get(pk=3615)
        name = 'non-animated.gif'
        form = forms.PreviewForm({'caption': 'test', 'upload_hash': name,
                                  'position': 1})
        with storage.open(os.path.join(self.dest, name), 'w') as f:
            copyfileobj(open(get_image_path(name)), f)
        assert form.is_valid()
        form.save(addon)
        assert addon.previews.all()[0].sizes == (
            {u'image': [250, 297], u'thumbnail': [126, 150]})


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
                                           type=amo.ADDON_PERSONA, name='xxxx')
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
            'header_hash': 'b4ll1n',
            'footer_hash': '5w4g'
        }
        data.update(**kw)
        return data

    def post(self, **kw):
        self.form = ThemeForm(self.get_dict(**kw), request=self.request)
        return self.form

    def test_name_unique(self):
        # A theme cannot share the same name as another theme's.
        Addon.objects.create(type=amo.ADDON_PERSONA, name='harry-potter')
        for name in ('Harry-Potter', '  harry-potter  ', 'harry-potter'):
            self.post(name=name)
            assert not self.form.is_valid()
            assert self.form.errors == (
                {'name': ['This name is already in use. '
                          'Please choose another.']})

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

    def test_footer_hash_optional(self):
        self.post(footer_hash='')
        assert self.form.is_valid()

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
        return (
            reverse('devhub.personas.upload_persona', args=['persona_header']),
            reverse('devhub.personas.upload_persona', args=['persona_footer'])
        )

    def test_img_attrs(self):
        header_url, footer_url = self.get_img_urls()

        self.post()
        assert self.form.fields['header'].widget.attrs == (
            {'data-allowed-types': 'image/jpeg|image/png',
             'data-upload-url': header_url})
        assert self.form.fields['footer'].widget.attrs == (
            {'data-allowed-types': 'image/jpeg|image/png',
             'data-upload-url': footer_url})

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
        header_url, footer_url = self.get_img_urls()

        # Upload header image.
        img = open(get_image_path('persona-header.jpg'), 'rb')
        r_ajax = self.client.post(header_url, {'upload_image': img})
        data.update(header_hash=json.loads(r_ajax.content)['upload_hash'])

        # Upload footer image.
        img = open(get_image_path('persona-footer.jpg'), 'rb')
        r_ajax = self.client.post(footer_url, {'upload_image': img})
        data.update(footer_hash=json.loads(r_ajax.content)['upload_hash'])

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

        # Test for header, footer, and preview images.
        dst = os.path.join(user_media_path('addons'), str(addon.id))

        header_src = os.path.join(settings.TMP_PATH, 'persona_header',
                                  u'b4ll1n')
        footer_src = os.path.join(settings.TMP_PATH, 'persona_footer',
                                  u'5w4g')

        assert save_persona_image_mock.mock_calls == (
            [mock.call(src=header_src,
                       full_dst=os.path.join(dst, 'header.png')),
             mock.call(src=footer_src,
                       full_dst=os.path.join(dst, 'footer.png'))])

        create_persona_preview_images_mock.assert_called_with(
            src=header_src,
            full_dst=[os.path.join(dst, 'preview.png'),
                      os.path.join(dst, 'icon.png')],
            set_modified_on=[addon])

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
            type=amo.ADDON_PERSONA, name='xxxx')
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

    def test_name_unique(self):
        data = self.get_dict(**{'name_en-us': 'Bands Make You Dance'})
        Addon.objects.create(type=amo.ADDON_PERSONA, status=amo.STATUS_PUBLIC,
                             name=data['name_en-us'])
        self.form = EditThemeForm(data, request=self.request,
                                  instance=self.instance)
        assert not self.form.is_valid()
        assert self.form.errors == {
            'name':
            [('en-us', 'This name is already in use. Please choose another.')]}

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
        data = self.get_dict(header_hash='y0l0', footer_hash='abab')
        self.form = EditThemeForm(data, request=self.request,
                                  instance=self.instance)
        assert self.form.is_valid()
        self.form.save()

        dst = os.path.join(user_media_path('addons'), str(self.instance.id))
        header_src = os.path.join(settings.TMP_PATH, 'persona_header',
                                  u'y0l0')
        footer_src = os.path.join(settings.TMP_PATH, 'persona_footer',
                                  u'abab')

        assert save_persona_image_mock.mock_calls == (
            [mock.call(src=header_src,
                       full_dst=os.path.join(dst, 'pending_header.png')),
             mock.call(src=footer_src,
                       full_dst=os.path.join(dst, 'pending_footer.png'))])

        rqt = RereviewQueueTheme.objects.filter(theme=self.instance.persona)
        assert rqt.count() == 1
        assert rqt[0].header == 'pending_header.png'
        assert rqt[0].footer == 'pending_footer.png'
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

        data = self.get_dict(header_hash='head', footer_hash='foot')
        self.form = EditThemeForm(data, request=self.request,
                                  instance=self.instance)
        assert self.form.is_valid()
        self.form.save()

        rqt = RereviewQueueTheme.objects.get(theme=self.instance.persona)
        assert rqt.dupe_persona == theme.persona

    @mock.patch('olympia.addons.tasks.make_checksum', new=mock.Mock)
    @mock.patch('olympia.addons.tasks.create_persona_preview_images',
                new=mock.Mock)
    @mock.patch('olympia.addons.tasks.save_persona_image', new=mock.Mock)
    def test_reupload_legacy_header_only(self):
        """
        STR the bug this test fixes:

        - Reupload a legacy theme (/w footer == leg.png) legacy, header only.
        - The header would get saved as 'pending_header.png'.
        - The footer would get saved as 'footer.png'.
        - On approving, it would see 'footer.png' !== 'leg.png'
        - It run move_stored_file('footer.png', 'leg.png').
        - But footer.png does not exist. BAM BUG.
        """
        self.theme.header = 'Legacy-header3H.png'
        self.theme.footer = 'Legacy-footer3H-Copy.jpg'
        self.theme.save()

        data = self.get_dict(header_hash='arthro')
        self.form = EditThemeForm(data, request=self.request,
                                  instance=self.instance)
        assert self.form.is_valid()
        self.form.save()

        rqt = RereviewQueueTheme.objects.get()
        assert rqt.header == 'pending_header.png'
        assert rqt.footer == 'Legacy-footer3H-Copy.jpg'

    @mock.patch('olympia.addons.tasks.make_checksum')
    @mock.patch('olympia.addons.tasks.create_persona_preview_images')
    @mock.patch('olympia.addons.tasks.save_persona_image')
    def test_reupload_no_footer(self, save_persona_image_mock,
                                create_persona_preview_images_mock,
                                make_checksum_mock):
        make_checksum_mock.return_value = 'checksumbeforeyouwrecksome'
        data = self.get_dict(header_hash='y0l0', footer_hash='')
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
        assert rqt[0].footer == ''
        assert not rqt[0].dupe_persona


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
