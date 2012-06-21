import os
import shutil

import mock

from django.core.files.storage import default_storage as storage
from django.conf import settings

import amo
import amo.tests
from amo.tests.test_helpers import get_image_path
import paypal
from applications.models import AppVersion
from addons.models import Addon, Charity
from devhub import forms
from files.helpers import copyfileobj
from files.models import FileUpload
from market.models import AddonPremium
from users.models import UserProfile
from versions.models import ApplicationsVersions

from nose.tools import eq_
from pyquery import PyQuery as pq


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


@mock.patch('market.models.AddonPremium.has_valid_permissions_token',
            lambda z: True)
@mock.patch('devhub.forms.check_paypal_id', lambda z: True)
class TestPremiumForm(amo.tests.TestCase):
    fixtures = ['base/addon_3615', 'base/users', 'market/prices']

    def complete(self, data, exclude, dest='payment'):
        return forms.PremiumForm(data, request=None, extra={
            'addon': Addon.objects.get(pk=3615),
            'amo_user': UserProfile.objects.get(pk=999),
            'exclude': exclude,
            'dest': dest})

    @mock.patch('devhub.forms.check_paypal_id', lambda z: True)
    @mock.patch('django.contrib.messages.warning')
    def test_remove_token(self, error):
        addon = Addon.objects.get(pk=3615)
        addon.update(paypal_id='')
        ap = AddonPremium.objects.create(paypal_permissions_token='1',
                                         addon=addon, price_id=1)
        data = {'support_email': 'foo@bar.com', 'paypal_id': 'foo@bar.com'}
        form = self.complete(data, ['price'])
        assert form.is_valid()
        form.save()
        # Do not remove the token, we had no paypal_id.
        assert AddonPremium.objects.get(pk=ap.pk).paypal_permissions_token

        data['paypal_id'] = 'fooa@bar.com'
        errmsgs = []
        error.side_effect = lambda req, msg: errmsgs.append(msg)
        form = self.complete(data, ['price'])
        # Remove the token and fail the form.
        assert not form.is_valid()
        assert not AddonPremium.objects.get(pk=ap.pk).paypal_permissions_token
        assert 'refund token' in errmsgs[0]
        eq_(len(errmsgs), 1)
        AddonPremium.objects.get(pk=ap.pk).update(paypal_permissions_token='a')
        form = self.complete(data, ['price'])
        # Do not remove the token if the paypal_id hasn't changed.
        assert form.is_valid()
        assert AddonPremium.objects.get(pk=ap.pk).paypal_permissions_token

    def test_no_paypal_id(self):
        addon = Addon.objects.get(pk=3615)
        addon.update(paypal_id='some@id.com')
        AddonPremium.objects.create(paypal_permissions_token='1',
                                    addon=addon)
        form = self.complete({}, ['paypal_id', 'support_email'])
        assert not form.is_valid()
        eq_(['price'], form.errors.keys())
