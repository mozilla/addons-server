from django.conf import settings

import fudge
import mock
import waffle
from fudge.inspector import arg
from nose.tools import eq_
from pyquery import PyQuery as pq

import amo
import amo.tests
from addons.models import Addon
from market.models import Price

from mkt.inapp_pay.models import InappConfig
from mkt.site.fixtures import fixture


def create_inapp_config(public_key='pub-key', private_key='priv-key',
                        status=amo.INAPP_STATUS_ACTIVE, addon=None,
                        postback_url='/postback',
                        chargeback_url='/chargeback'):
    if not addon:
        addon = Addon.objects.create(type=amo.ADDON_WEBAPP)
    cfg = InappConfig.objects.create(public_key=public_key,
                                     addon=addon,
                                     status=status,
                                     postback_url=postback_url,
                                     chargeback_url=chargeback_url)
    cfg.set_private_key(private_key)
    return cfg


class InappTest(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube']

    def setUp(self):
        waffle.models.Switch.objects.create(name='in-app-payments',
                                            active=True)
        assert self.client.login(username='admin@mozilla.com',
                                 password='password')
        self.webapp = Addon.objects.get(id=337141)
        self.webapp.update(premium_type=amo.ADDON_PREMIUM_INAPP)

    def config(self, public_key='pub-key', private_key='priv-key',
               status=amo.INAPP_STATUS_ACTIVE, addon=None,
               postback_url='/postback', chargeback_url='/chargeback'):
        if not addon:
            addon = self.webapp
        return create_inapp_config(public_key=public_key,
                                   private_key=private_key,
                                   status=status,
                                   postback_url=postback_url,
                                   addon=addon,
                                   chargeback_url=chargeback_url)


@mock.patch.object(settings, 'DEBUG', True)
class TestInappConfig(InappTest):

    def setUp(self):
        super(TestInappConfig, self).setUp()
        self.url = self.webapp.get_dev_url('in_app_config')

    def post(self, data, expect_error=False):
        resp = self.client.post(self.url, data, follow=True)
        if not expect_error:
            self.assertNoFormErrors(resp)
        eq_(resp.status_code, 200)
        return resp

    def test_key_generation(self):
        self.post(dict(chargeback_url='/chargeback', postback_url='/postback'))
        inapp = InappConfig.objects.get(addon=self.webapp)
        eq_(inapp.chargeback_url, '/chargeback')
        eq_(inapp.postback_url, '/postback')
        eq_(inapp.status, amo.INAPP_STATUS_ACTIVE)
        assert inapp.public_key, 'public key was not generated'
        assert inapp.has_private_key(), 'private key was not generated'

    def test_key_gen_is_per_app(self):
        # Sigh. Don't ask why this test is here.
        self.config(public_key='first', private_key='first', addon=self.webapp)
        first = InappConfig.objects.get(addon=self.webapp)
        addon2 = Addon.objects.create(type=amo.ADDON_WEBAPP)
        self.config(public_key='second', private_key='second', addon=addon2)
        second = InappConfig.objects.get(addon=addon2)
        key1 = first.get_private_key()
        key2 = second.get_private_key()
        assert key1 != key2, ('keys cannot be the same: %r' % key1)

    def test_hide_inactive_keys(self):
        self.config(status=amo.INAPP_STATUS_INACTIVE)
        resp = self.client.get(self.url)
        doc = pq(resp.content)
        assert doc('#in-app-public-key').hasClass('not-generated')
        assert doc('#in-app-private-key').hasClass('not-generated')

    def test_view_state_when_not_configured(self):
        resp = self.client.get(self.url)
        doc = pq(resp.content)
        assert doc('#in-app-public-key').hasClass('not-generated')
        assert doc('#in-app-private-key').hasClass('not-generated')

    def test_regenerate_keys_when_inactive(self):
        old_inapp = self.config(status=amo.INAPP_STATUS_INACTIVE)
        old_secret = old_inapp.get_private_key()
        self.post(dict(chargeback_url='/chargeback', postback_url='/postback'))
        inapp = InappConfig.objects.get(addon=self.webapp,
                                        status=amo.INAPP_STATUS_ACTIVE)
        new_secret = inapp.get_private_key()
        assert new_secret != old_secret, '%s != %s' % (new_secret, old_secret)

    def test_bad_urls(self):
        resp = self.post(dict(chargeback_url='chargeback',
                              postback_url='postback'),
                         expect_error=True)
        error = ('This URL is relative to your app domain so it must start '
                 'with a slash.')
        eq_(resp.context['inapp_form'].errors,
            {'postback_url': [error], 'chargeback_url': [error]})

    def test_keys_are_preserved_on_edit(self):
        self.config(public_key='exisiting-pub-key',
                    private_key='exisiting-priv-key')
        self.post(dict(chargeback_url='/new/chargeback',
                       postback_url='/new/postback'))
        inapp = InappConfig.objects.filter(addon=self.webapp)[0]
        eq_(inapp.chargeback_url, '/new/chargeback')
        eq_(inapp.postback_url, '/new/postback')
        eq_(inapp.status, amo.INAPP_STATUS_ACTIVE)
        eq_(inapp.public_key, 'exisiting-pub-key')
        eq_(inapp.get_private_key(), 'exisiting-priv-key')

    def test_show_secret(self):
        self.config(private_key='123456')
        resp = self.client.get(self.webapp.get_dev_url('in_app_secret'))
        eq_(resp.content, '123456')

    def test_deny_secret_to_no_auth(self):
        self.config()
        self.client.logout()
        # Paranoid sanity check!
        resp = self.client.get(self.webapp.get_dev_url('in_app_secret'))
        eq_(resp.status_code, 302)

    def test_deny_secret_to_non_owner(self):
        self.config()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        # Paranoid sanity check!
        resp = self.client.get(self.webapp.get_dev_url('in_app_secret'))
        eq_(resp.status_code, 403)

    def test_deny_inactive_secrets(self):
        self.config(status=amo.INAPP_STATUS_INACTIVE)
        resp = self.client.get(self.webapp.get_dev_url('in_app_secret'))
        eq_(resp.status_code, 404)

    def test_not_inapp(self):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM)
        res = self.client.get(self.url)
        eq_(res.status_code, 302)


@mock.patch.object(settings, 'DEBUG', True)
class TestInappConfigReset(InappTest):

    def setUp(self):
        super(TestInappConfigReset, self).setUp()

    def get_url(self, config_id):
        return self.webapp.get_dev_url('reset_in_app_config', [config_id])

    @fudge.patch('mkt.developers.views.inapp_cef.log')
    def test_reset(self, cef):
        cfg = self.config(public_key='old-key',
                          private_key='old-secret')

        def inspect_msg(msg):
            assert 'old-key' in msg, 'CEF should log old key'
            return True

        cef.expects_call().with_args(arg.any(),
                                     cfg.addon,
                                     'inapp_reset',
                                     arg.passes_test(inspect_msg),
                                     severity=6)
        res = self.client.post(self.get_url(cfg.pk))
        self.assertRedirects(res, self.webapp.get_dev_url('in_app_config'))
        old_cfg = InappConfig.objects.get(pk=cfg.pk)
        eq_(old_cfg.status, amo.INAPP_STATUS_REVOKED)
        inapp = InappConfig.objects.get(addon=self.webapp,
                                        status=amo.INAPP_STATUS_ACTIVE)
        eq_(inapp.chargeback_url, cfg.chargeback_url)
        eq_(inapp.postback_url, cfg.postback_url)
        assert inapp.public_key != cfg.public_key, (
                                    'Unexpected: %s' % inapp.public_key)
        pk = inapp.get_private_key()
        assert pk != cfg.get_private_key, ('Unexpected: %s' % pk)

    def test_reset_requires_auth(self):
        cfg = self.config()
        self.client.logout()
        self.assertLoginRequired(self.client.post(self.get_url(cfg.pk)))

    def test_reset_requires_owner(self):
        cfg = self.config()
        self.client.logout()
        assert self.client.login(username='regular@mozilla.com',
                                 password='password')
        url = self.get_url(cfg.pk)
        res = self.client.post(url)
        eq_(res.status_code, 403)

    def test_reset_requires_app_with_payments(self):
        cfg = self.config()
        for st in (amo.ADDON_FREE, amo.ADDON_PREMIUM):
            self.webapp.update(premium_type=st)
            url = self.get_url(cfg.pk)
            res = self.client.post(url)
            self.assertRedirects(res, self.webapp.get_dev_url('payments'))

    def test_reset_non_existant_config(self):
        url = self.get_url(9999)
        res = self.client.post(url)
        eq_(res.status_code, 404)


# Testing the payments page.
class TestPayments(amo.tests.TestCase):
    fixtures = ['base/apps', 'base/users', 'webapps/337141-steamcube',
                'market/prices']

    def setUp(self):
        self.webapp = self.get_webapp()
        self.url = self.webapp.get_dev_url('payments')
        self.client.login(username='admin@mozilla.com', password='password')
        self.price = Price.objects.filter()[0]

    def get_webapp(self):
        return Addon.objects.get(pk=337141)

    def test_free(self):
        res = self.client.post(self.url, {'toggle-paid': 'free'})
        self.assert3xx(res, self.url)
        eq_(self.get_webapp().premium_type, amo.ADDON_FREE)

    def test_premium_passes(self):
        self.webapp.update(premium_type=amo.ADDON_FREE)
        res = self.client.post(self.url, {'toggle-paid': 'paid'})
        self.assert3xx(res, self.url)
        eq_(self.get_webapp().premium_type, amo.ADDON_PREMIUM)

    def test_premium_in_app_passes(self):
        self.webapp.update(premium_type=amo.ADDON_FREE)
        res = self.client.post(self.url, {'toggle-paid': 'paid'})
        self.assert3xx(res, self.url)
        res = self.client.post(self.url, {'allow_inapp': True,
                                          'price': self.price.pk})
        self.assert3xx(res, self.url)
        eq_(self.get_webapp().premium_type, amo.ADDON_PREMIUM_INAPP)

    def test_later_then_free(self):
        self.webapp.update(premium_type=amo.ADDON_PREMIUM,
                           status=amo.STATUS_NULL,
                           highest_status=amo.STATUS_PENDING)
        res = self.client.post(self.url, {'toggle-paid': 'free',
                                          'price': self.price.pk})
        self.assert3xx(res, self.url)
        eq_(self.get_webapp().status, amo.STATUS_PENDING)

    def test_premium_price_initial_already_set(self):
        Price.objects.create(price='0.00')  # Make a free tier for measure.
        self.make_premium(self.webapp)
        r = self.client.get(self.url)
        eq_(pq(r.content)('select[name=price] option[selected]').attr('value'),
            str(self.webapp.premium.price.id))

    def test_premium_price_initial_use_default(self):
        Price.objects.create(price='10.00')  # Make one more tier.

        self.webapp.update(premium_type=amo.ADDON_FREE)
        res = self.client.post(self.url, {'toggle-paid': 'paid'}, follow=True)
        pqr = pq(res.content)
        eq_(pqr('select[name=price] option[selected]').attr('value'),
            str(Price.objects.get(price='0.99').id))
