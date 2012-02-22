import os
import shutil

from django.conf import settings

import mock
from nose.tools import eq_

import amo
import amo.tests
from amo.tests.test_helpers import get_image_path
import paypal
from addons.models import Addon, Charity
from mkt.developers import forms
from files.models import FileUpload


class TestNewAddonForm(amo.tests.TestCase):

    def test_only_valid_uploads(self):
        f = FileUpload.objects.create(valid=False)
        form = forms.NewAddonForm({'upload': f.pk})
        assert 'upload' in form.errors

        f.validation = '{"errors": 0}'
        f.save()
        form = forms.NewAddonForm({'upload': f.pk})
        assert 'upload' not in form.errors


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
        shutil.copyfile(get_image_path(name), os.path.join(self.dest, name))
        assert form.is_valid()
        form.save(addon)
        assert update_mock.called

    def test_preview_size(self):
        addon = Addon.objects.get(pk=3615)
        name = 'non-animated.gif'
        form = forms.PreviewForm({'caption': 'test', 'upload_hash': name,
                                  'position': 1})
        shutil.copyfile(get_image_path(name), os.path.join(self.dest, name))
        assert form.is_valid()
        form.save(addon)
        eq_(addon.previews.all()[0].sizes,
            {u'image': [250, 297], u'thumbnail': [126, 150]})


class TestPaypalSetupForm(amo.tests.TestCase):

    def test_email_not_required(self):
        data = {'business_account': 'no',
                'email': ''}
        assert forms.PaypalSetupForm(data=data).is_valid()

    def test_email_required(self):
        data = {'business_account': 'yes',
                'email': ''}
        assert not forms.PaypalSetupForm(data=data).is_valid()

    def test_email_gotten(self):
        data = {'business_account': 'yes',
                'email': 'foo@bar.com'}
        assert forms.PaypalSetupForm(data=data).is_valid()

    def test_email_malformed(self):
        data = {'business_account': 'yes',
                'email': 'foo'}
        assert not forms.PaypalSetupForm(data=data).is_valid()
