import json
import os

from django.conf import settings
from django.core.files.storage import default_storage as storage

import mock
from nose import SkipTest
from nose.tools import eq_
from PIL import Image

import amo
import amo.tests
from amo.tests.test_helpers import get_image_path
from amo.urlresolvers import reverse
import paypal
from applications.models import AppVersion
from addons.forms import EditThemeForm, EditThemeOwnerForm, ThemeForm
from addons.models import Addon, Category, Charity, Persona
from devhub import forms
from editors.models import RereviewQueueTheme
from files.helpers import copyfileobj
from files.models import FileUpload
from tags.models import Tag
from users.models import UserProfile
from versions.models import ApplicationsVersions, License


class TestNewAddonForm(amo.tests.TestCase):

    def test_only_valid_uploads(self):
        f = FileUpload.objects.create(valid=False)
        form = forms.NewAddonForm({'upload': f.pk}, request=mock.Mock())
        assert ('There was an error with your upload. Please try again.' in
                form.errors.get('__all__')), form.errors

        f.validation = '{"errors": 0}'
        f.save()
        form = forms.NewAddonForm({'upload': f.pk}, request=mock.Mock())
        assert ('There was an error with your upload. Please try again.' not in
                form.errors.get('__all__')), form.errors


class TestContribForm(amo.tests.TestCase):

    def test_neg_suggested_amount(self):
        form = forms.ContribForm({'suggested_amount': -10})
        assert not form.is_valid()
        eq_(form.errors['suggested_amount'][0],
            'Please enter a suggested amount greater than 0.')

    def test_max_suggested_amount(self):
        form = forms.ContribForm({'suggested_amount':
                            settings.MAX_CONTRIBUTION + 10})
        assert not form.is_valid()
        eq_(form.errors['suggested_amount'][0],
            'Please enter a suggested amount less than $%s.' %
            settings.MAX_CONTRIBUTION)


class TestCharityForm(amo.tests.TestCase):

    def setUp(self):
        self.paypal_mock = mock.Mock()
        self.paypal_mock.return_value = (True, None)
        paypal.check_paypal_id = self.paypal_mock

    def test_always_new(self):
        # Editing a charity should always produce a new row.
        params = dict(name='name', url='http://url.com/', paypal='paypal')
        charity = forms.CharityForm(params).save()
        for k, v in params.items():
            eq_(getattr(charity, k), v)
        assert charity.id

        # Get a fresh instance since the form will mutate it.
        instance = Charity.objects.get(id=charity.id)
        params['name'] = 'new'
        new_charity = forms.CharityForm(params, instance=instance).save()
        for k, v in params.items():
            eq_(getattr(new_charity, k), v)

        assert new_charity.id != charity.id


class TestCompatForm(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/addon_3615']

    def test_mozilla_app(self):
        moz = amo.MOZILLA
        appver = AppVersion.objects.create(application_id=moz.id)
        v = Addon.objects.get(id=3615).current_version
        ApplicationsVersions(application_id=moz.id, version=v,
                             min=appver, max=appver).save()
        fs = forms.CompatFormSet(None, queryset=v.apps.all())
        apps = [f.app for f in fs.forms]
        assert moz in apps


class TestPreviewForm(amo.tests.TestCase):
    fixtures = ['base/addon_3615']

    def setUp(self):
        self.dest = os.path.join(settings.TMP_PATH, 'preview')
        if not os.path.exists(self.dest):
            os.makedirs(self.dest)

    @mock.patch('amo.models.ModelBase.update')
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
        eq_(addon.previews.all()[0].sizes,
            {u'image': [250, 297], u'thumbnail': [126, 150]})


class TestThemeForm(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/user_2519']

    def setUp(self):
        self.populate()
        self.request = mock.Mock()
        self.request.groups = ()
        self.request.amo_user = mock.Mock()
        self.request.amo_user.is_authenticated.return_value = True

    def populate(self):
        self.cat = Category.objects.create(application_id=amo.FIREFOX.id,
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
            eq_(self.form.is_valid(), False)
            eq_(self.form.errors,
                {'name': ['This name is already in use. '
                          'Please choose another.']})

    def test_name_required(self):
        self.post(name='')
        eq_(self.form.is_valid(), False)
        eq_(self.form.errors, {'name': ['This field is required.']})

    def test_name_length(self):
        self.post(name='a' * 51)
        eq_(self.form.is_valid(), False)
        eq_(self.form.errors, {'name': ['Ensure this value has at most '
                                        '50 characters (it has 51).']})

    def test_slug_unique(self):
        # A theme cannot share the same slug as another theme's.
        Addon.objects.create(type=amo.ADDON_PERSONA, slug='harry-potter')
        for slug in ('Harry-Potter', '  harry-potter  ', 'harry-potter'):
            self.post(slug=slug)
            eq_(self.form.is_valid(), False)
            eq_(self.form.errors,
                {'slug': ['This slug is already in use. '
                          'Please choose another.']})

    def test_slug_required(self):
        self.post(slug='')
        eq_(self.form.is_valid(), False)
        eq_(self.form.errors, {'slug': ['This field is required.']})

    def test_slug_length(self):
        self.post(slug='a' * 31)
        eq_(self.form.is_valid(), False)
        eq_(self.form.errors, {'slug': ['Ensure this value has at most '
                                        '30 characters (it has 31).']})

    def test_description_optional(self):
        self.post(description='')
        eq_(self.form.is_valid(), True, self.form.errors)

    def test_description_length(self):
        self.post(description='a' * 501)
        eq_(self.form.is_valid(), False)
        eq_(self.form.errors,
            {'description': ['Ensure this value has at most '
                             '500 characters (it has 501).']})

    def test_categories_required(self):
        self.post(category='')
        eq_(self.form.is_valid(), False)
        eq_(self.form.errors, {'category': ['This field is required.']})

    def test_license_required(self):
        self.post(license='')
        eq_(self.form.is_valid(), False)
        eq_(self.form.errors, {'license': ['A license must be selected.']})

    def test_header_hash_required(self):
        self.post(header_hash='')
        eq_(self.form.is_valid(), False)
        eq_(self.form.errors, {'header_hash': ['This field is required.']})

    def test_footer_hash_required(self):
        self.post(footer_hash='')
        eq_(self.form.is_valid(), False)
        eq_(self.form.errors, {'footer_hash': ['This field is required.']})

    def test_accentcolor_optional(self):
        self.post(accentcolor='')
        eq_(self.form.is_valid(), True, self.form.errors)

    def test_accentcolor_invalid(self):
        self.post(accentcolor='#BALLIN')
        eq_(self.form.is_valid(), False)
        eq_(self.form.errors,
            {'accentcolor': ['This must be a valid hex color code, '
                             'such as #000000.']})

    def test_textcolor_optional(self):
        self.post(textcolor='')
        eq_(self.form.is_valid(), True, self.form.errors)

    def test_textcolor_invalid(self):
        self.post(textcolor='#BALLIN')
        eq_(self.form.is_valid(), False)
        eq_(self.form.errors,
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
        eq_(self.form.fields['header'].widget.attrs,
            {'data-allowed-types': 'image/jpeg|image/png',
             'data-upload-url': header_url})
        eq_(self.form.fields['footer'].widget.attrs,
            {'data-allowed-types': 'image/jpeg|image/png',
             'data-upload-url': footer_url})

    @mock.patch('addons.tasks.make_checksum')
    @mock.patch('addons.tasks.create_persona_preview_images')
    @mock.patch('addons.tasks.save_persona_image')
    def test_success(self, save_persona_image_mock,
                     create_persona_preview_images_mock, make_checksum_mock):
        if not hasattr(Image.core, 'jpeg_encoder'):
            raise SkipTest
        make_checksum_mock.return_value = 'hashyourselfbeforeyoucrashyourself'

        self.request.amo_user = UserProfile.objects.get(pk=2519)

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
        eq_(self.form.is_valid(), True, self.form.errors)
        self.form.save()

        addon = Addon.objects.filter(type=amo.ADDON_PERSONA).order_by('-id')[0]
        persona = addon.persona

        # Test for correct Addon and Persona values.
        eq_(unicode(addon.name), data['name'])
        eq_(addon.slug, data['slug'])
        self.assertSetEqual(addon.categories.values_list('id', flat=True),
                            [self.cat.id])
        self.assertSetEqual(addon.tags.values_list('tag_text', flat=True),
                            data['tags'].split(', '))
        eq_(persona.persona_id, 0)
        eq_(persona.license, data['license'])
        eq_(persona.accentcolor, data['accentcolor'].lstrip('#'))
        eq_(persona.textcolor, data['textcolor'].lstrip('#'))
        eq_(persona.author, self.request.amo_user.username)
        eq_(persona.display_username, self.request.amo_user.name)
        assert not persona.dupe_persona

        v = addon.versions.all()
        eq_(len(v), 1)
        eq_(v[0].version, '0')

        # Test for header, footer, and preview images.
        dst = os.path.join(settings.ADDONS_PATH, str(addon.id))

        header_src = os.path.join(settings.TMP_PATH, 'persona_header',
                                  u'b4ll1n')
        footer_src = os.path.join(settings.TMP_PATH, 'persona_footer',
                                  u'5w4g')

        eq_(save_persona_image_mock.mock_calls,
            [mock.call(src=header_src,
                       full_dst=os.path.join(dst, 'header.png')),
             mock.call(src=footer_src,
                       full_dst=os.path.join(dst, 'footer.png'))])

        create_persona_preview_images_mock.assert_called_with(
            src=header_src,
            full_dst=[os.path.join(dst, 'preview.png'),
                      os.path.join(dst, 'icon.png')],
            set_modified_on=[addon])

    @mock.patch('addons.tasks.create_persona_preview_images')
    @mock.patch('addons.tasks.save_persona_image')
    @mock.patch('addons.tasks.make_checksum')
    def test_dupe_persona(self, make_checksum_mock, mock1, mock2):
        """
        Submitting persona with checksum already in db should be marked
        duplicate.
        """
        make_checksum_mock.return_value = 'cornhash'

        self.request.amo_user = UserProfile.objects.get(pk=2519)

        self.post()
        eq_(self.form.is_valid(), True, self.form.errors)
        self.form.save()

        self.post(name='whatsinaname', slug='metalslug')
        eq_(self.form.is_valid(), True, self.form.errors)
        self.form.save()

        personas = Persona.objects.order_by('addon__name')
        eq_(personas[0].checksum, personas[1].checksum)
        eq_(personas[1].dupe_persona, personas[0])
        eq_(personas[0].dupe_persona, None)


class TestEditThemeForm(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/user_2519']

    def setUp(self):
        self.populate()
        self.request = mock.Mock()
        self.request.groups = ()
        self.request.amo_user = mock.Mock()
        self.request.amo_user.username = 'swagyismymiddlename'
        self.request.amo_user.name = 'Sir Swag A Lot'
        self.request.amo_user.is_authenticated.return_value = True

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
            eq_(self.form.initial[k], eq_data[k])

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
            eq_(self.form.initial[k], eq_data[k])

        eq_(self.form.data, self.data)
        eq_(self.form.is_valid(), True, self.form.errors)
        self.form.save()

    def test_success(self):
        self.save_success()
        self.instance = self.instance.reload()
        eq_(unicode(self.instance.persona.accentcolor),
            self.data['accentcolor'].lstrip('#'))
        eq_(self.instance.categories.all()[0].id, self.data['category'])
        eq_(self.instance.persona.license, self.data['license'])
        eq_(unicode(self.instance.name), self.data['name_en-us'])
        eq_(unicode(self.instance.description), self.data['description_en-us'])
        self.assertSetEqual(
            self.instance.tags.values_list('tag_text', flat=True),
            [self.data['tags']])
        eq_(unicode(self.instance.persona.textcolor),
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
        eq_(self.form.is_valid(), False)
        eq_(self.form.errors, {'name':
            [('en-us', 'This name is already in use. Please choose another.')]
        })

    def test_localize_name_description(self):
        data = self.get_dict(name_de='name_de',
                             description_de='description_de')
        self.form = EditThemeForm(data, request=self.request,
                                  instance=self.instance)
        eq_(self.form.is_valid(), True, self.form.errors)
        self.form.save()

    @mock.patch('addons.tasks.make_checksum')
    @mock.patch('addons.tasks.create_persona_preview_images')
    @mock.patch('addons.tasks.save_persona_image')
    def test_reupload(self, save_persona_image_mock,
                      create_persona_preview_images_mock,
                      make_checksum_mock):
        make_checksum_mock.return_value = 'checksumbeforeyouwrecksome'
        data = self.get_dict(header_hash='y0l0', footer_hash='abab')
        self.form = EditThemeForm(data, request=self.request,
                                  instance=self.instance)
        eq_(self.form.is_valid(), True)
        self.form.save()

        dst = os.path.join(settings.ADDONS_PATH, str(self.instance.id))
        header_src = os.path.join(settings.TMP_PATH, 'persona_header',
                                  u'y0l0')
        footer_src = os.path.join(settings.TMP_PATH, 'persona_footer',
                                  u'abab')

        eq_(save_persona_image_mock.mock_calls,
            [mock.call(src=header_src,
                       full_dst=os.path.join(dst, 'pending_header.png')),
             mock.call(src=footer_src,
                       full_dst=os.path.join(dst, 'pending_footer.png'))])

        rqt = RereviewQueueTheme.objects.filter(theme=self.instance.persona)
        eq_(rqt.count(), 1)
        eq_(rqt[0].header, 'pending_header.png')
        eq_(rqt[0].footer, 'pending_footer.png')
        assert not rqt[0].dupe_persona

    @mock.patch('addons.tasks.create_persona_preview_images', new=mock.Mock)
    @mock.patch('addons.tasks.save_persona_image', new=mock.Mock)
    @mock.patch('addons.tasks.make_checksum')
    def test_reupload_duplicate(self, make_checksum_mock):
        make_checksum_mock.return_value = 'checksumbeforeyouwrecksome'

        theme = amo.tests.addon_factory(type=amo.ADDON_PERSONA)
        theme.persona.checksum = 'checksumbeforeyouwrecksome'
        theme.persona.save()

        data = self.get_dict(header_hash='head', footer_hash='foot')
        self.form = EditThemeForm(data, request=self.request,
                                  instance=self.instance)
        eq_(self.form.is_valid(), True)
        self.form.save()

        rqt = RereviewQueueTheme.objects.get(theme=self.instance.persona)
        eq_(rqt.dupe_persona, theme.persona)

    @mock.patch('addons.tasks.make_checksum', new=mock.Mock)
    @mock.patch('addons.tasks.create_persona_preview_images', new=mock.Mock)
    @mock.patch('addons.tasks.save_persona_image', new=mock.Mock)
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
        eq_(self.form.is_valid(), True)
        self.form.save()

        rqt = RereviewQueueTheme.objects.get()
        eq_(rqt.header, 'pending_header.png')
        eq_(rqt.footer, 'Legacy-footer3H-Copy.jpg')


class TestEditThemeOwnerForm(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users']

    def setUp(self):
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
        eq_(self.form.initial, {})

        self.instance.addonuser_set.create(user_id=999)
        eq_(self.instance.addonuser_set.all()[0].user.email,
            'regular@mozilla.com')
        self.form = EditThemeOwnerForm(None, instance=self.instance)
        eq_(self.form.initial, {'owner': 'regular@mozilla.com'})

    def test_success_change_from_no_owner(self):
        self.form = EditThemeOwnerForm({'owner': 'regular@mozilla.com'},
                                       instance=self.instance)
        eq_(self.form.is_valid(), True, self.form.errors)
        self.form.save()
        eq_(self.instance.addonuser_set.all()[0].user.email,
            'regular@mozilla.com')

    def test_success_replace_owner(self):
        self.instance.addonuser_set.create(user_id=999)
        self.form = EditThemeOwnerForm({'owner': 'regular@mozilla.com'},
                                       instance=self.instance)
        eq_(self.form.is_valid(), True, self.form.errors)
        self.form.save()
        eq_(self.instance.addonuser_set.all()[0].user.email,
            'regular@mozilla.com')

    def test_error_invalid_user(self):
        self.form = EditThemeOwnerForm({'owner': 'omg@org.yes'},
                                       instance=self.instance)
        eq_(self.form.is_valid(), False)
