import json
import urllib
from datetime import datetime

from django import http
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import get_object_or_404, redirect

import commonware
import jingo
import jinja2
import waffle

from curling.lib import HttpClientError
from jingo import helpers
from tower import ugettext as _
from waffle.decorators import waffle_switch

import amo
from access import acl
from amo import messages
from amo.decorators import json_view, login_required, post_required, write
from amo.urlresolvers import reverse
from constants.payments import (PAYMENT_METHOD_ALL,
                                PAYMENT_METHOD_CARD,
                                PAYMENT_METHOD_OPERATOR)
from lib.crypto import generate_key
from lib.pay_server import client

from market.models import Price
from mkt.constants import DEVICE_LOOKUP
from mkt.developers.decorators import dev_required
from mkt.developers.models import (CantCancel, PaymentAccount, UserInappKey,
                                   uri_to_pk)
from mkt.developers.providers import get_provider

from . import forms, forms_payments


log = commonware.log.getLogger('z.devhub')


@dev_required
@post_required
def disable_payments(request, addon_id, addon):
    addon.update(wants_contributions=False)
    return redirect(addon.get_dev_url('payments'))


@dev_required(owner_for_post=True, webapp=True)
def payments(request, addon_id, addon, webapp=False):
    premium_form = forms_payments.PremiumForm(
        request.POST or None, request=request, addon=addon,
        user=request.amo_user)

    region_form = forms.RegionForm(
        request.POST or None, product=addon, request=request)

    upsell_form = forms_payments.UpsellForm(
        request.POST or None, addon=addon, user=request.amo_user)

    bango_account_list_form = forms_payments.BangoAccountListForm(
        request.POST or None, addon=addon, user=request.amo_user)

    if request.method == 'POST':

        success = all(form.is_valid() for form in
                      [premium_form, region_form, upsell_form,
                       bango_account_list_form])

        if success:
            region_form.save()

            try:
                premium_form.save()
            except client.Error as err:
                success = False
                log.error('Error setting payment information (%s)' % err)
                messages.error(
                    request, _(u'We encountered a problem connecting to the '
                               u'payment server.'))
                raise  # We want to see these exceptions!

            is_free_inapp = addon.premium_type == amo.ADDON_FREE_INAPP
            is_now_paid = (addon.premium_type in amo.ADDON_PREMIUMS
                           or is_free_inapp)

            # If we haven't changed to a free app, check the upsell.
            if is_now_paid and success:
                try:
                    if not is_free_inapp:
                        upsell_form.save()
                    bango_account_list_form.save()
                except client.Error as err:
                    log.error('Error saving payment information (%s)' % err)
                    messages.error(
                        request, _(u'We encountered a problem connecting to '
                                   u'the payment server.'))
                    success = False
                    raise  # We want to see all the solitude errors now.

        # If everything happened successfully, give the user a pat on the back.
        if success:
            messages.success(request, _('Changes successfully saved.'))
            return redirect(addon.get_dev_url('payments'))

    # TODO: This needs to be updated as more platforms support payments.
    cannot_be_paid = (
        addon.premium_type == amo.ADDON_FREE and
        any(premium_form.device_data['free-%s' % x] == y for x, y in
            [('android-mobile', True), ('android-tablet', True),
             ('desktop', True), ('firefoxos', False)]))

    try:
        tier_zero = Price.objects.get(price='0.00', active=True)
        tier_zero_id = tier_zero.pk
    except Price.DoesNotExist:
        tier_zero = None
        tier_zero_id = ''

    # Get the regions based on tier zero. This should be all the
    # regions with payments enabled.
    paid_region_ids_by_slug = []
    if tier_zero:
        paid_region_ids_by_slug = tier_zero.region_ids_by_slug()

    provider = get_provider()

    return jingo.render(
        request, 'developers/payments/premium.html',
        {'addon': addon, 'webapp': webapp, 'premium': addon.premium,
         'form': premium_form, 'upsell_form': upsell_form,
         'tier_zero_id': tier_zero_id,
         'region_form': region_form,
         'DEVICE_LOOKUP': DEVICE_LOOKUP,
         'is_paid': (addon.premium_type in amo.ADDON_PREMIUMS
                     or addon.premium_type == amo.ADDON_FREE_INAPP),
         'no_paid': cannot_be_paid,
         'is_incomplete': addon.status == amo.STATUS_NULL,
         'is_packaged': addon.is_packaged,
         # Bango values
         'account_form': provider.forms['account'](),
         'bango_account_list_form': bango_account_list_form,
         # Waffles
         'payments_enabled':
             waffle.flag_is_active(request, 'allow-b2g-paid-submission') and
             not waffle.switch_is_active('disabled-payments'),
         'api_pricelist_url': reverse('price-list'),
         'payment_methods': {
             PAYMENT_METHOD_ALL: _('All'),
             PAYMENT_METHOD_CARD: _('Credit card'),
             PAYMENT_METHOD_OPERATOR: _('Carrier'),
         },
         'all_paid_region_ids_by_slug': paid_region_ids_by_slug,
         'provider': provider,
        })


@login_required
@json_view
def payment_accounts(request):
    app_slug = request.GET.get('app-slug', '')
    accounts = PaymentAccount.objects.filter(
        user=request.amo_user, inactive=False)

    def account(acc):
        app_names = (', '.join(unicode(apa.addon.name)
                     for apa in acc.addonpaymentaccount_set.all()))
        data = {
            'id': acc.pk,
            'name': jinja2.escape(unicode(acc)),
            'app-names': jinja2.escape(app_names),
            'account-url':
                reverse('mkt.developers.bango.payment_account', args=[acc.pk]),
            'delete-url':
                reverse('mkt.developers.bango.delete_payment_account',
                        args=[acc.pk]),
            'agreement-url': acc.get_agreement_url(),
            'agreement': 'accepted' if acc.agreed_tos else 'rejected',
            'shared': acc.shared
        }
        if waffle.switch_is_active('bango-portal') and app_slug:
            data['portal-url'] = reverse(
                'mkt.developers.apps.payments.bango_portal_from_addon',
                args=[app_slug])
        return data

    return map(account, accounts)


@login_required
def payment_accounts_form(request):
    bango_account_form = forms_payments.BangoAccountListForm(
        user=request.amo_user, addon=None)
    return jingo.render(
        request, 'developers/payments/includes/bango_accounts_form.html',
        {'bango_account_list_form': bango_account_form})


@write
@post_required
@login_required
@json_view
def payments_accounts_add(request):
    provider = get_provider()
    form = provider.forms['account'](request.POST)
    if not form.is_valid():
        return json_view.error(form.errors)

    try:
        obj = provider.account_create(request.amo_user, form.cleaned_data)
    except HttpClientError as e:
        log.error('Client error create {0} account: {1}'.format(
            provider.name, e))
        return http.HttpResponseBadRequest(json.dumps(e.content))

    return {'pk': obj.pk, 'agreement-url': obj.get_agreement_url()}


@write
@login_required
@json_view
def payments_account(request, id):
    account = get_object_or_404(PaymentAccount, pk=id, user=request.user)
    if request.POST:
        form = forms_payments.BangoPaymentAccountForm(
            request.POST, account=account)
        if form.is_valid():
            form.save()
        else:
            return json_view.error(form.errors)

    return account.get_details()


@write
@post_required
@login_required
def payments_accounts_delete(request, id):
    account = get_object_or_404(PaymentAccount, pk=id, user=request.user)
    try:
        account.cancel(disable_refs=True)
    except CantCancel:
        log.info('Could not cancel account.')
        return http.HttpResponse('Cannot cancel account', status=409)

    log.info('Account cancelled: %s' % id)
    return http.HttpResponse('success')


@login_required
@waffle_switch('in-app-sandbox')
def in_app_keys(request):
    keys = (UserInappKey.objects.no_cache()
            .filter(solitude_seller__user=request.amo_user))
    # TODO(Kumar) support multiple test keys. For now there's only one.
    if keys.count():
        key = keys.get()
    else:
        key = None
    if request.method == 'POST':
        if key:
            key.reset()
            messages.success(request, _('Secret was reset successfully.'))
        else:
            UserInappKey.create(request.amo_user)
            messages.success(request,
                             _('Key and secret were created successfully.'))
        return redirect(reverse('mkt.developers.apps.in_app_keys'))

    return jingo.render(request, 'developers/payments/in-app-keys.html',
                        {'key': key})


@login_required
@waffle_switch('in-app-sandbox')
def in_app_key_secret(request, pk):
    key = (UserInappKey.objects.no_cache()
           .filter(solitude_seller__user=request.amo_user, pk=pk))
    if not key.count():
        # Either the record does not exist or it's not owned by the
        # logged in user.
        return http.HttpResponseForbidden()
    return http.HttpResponse(key.get().secret())


@login_required
@waffle_switch('in-app-payments')
@dev_required(owner_for_post=True, webapp=True)
def in_app_config(request, addon_id, addon, webapp=True):
    inapp = addon.premium_type in amo.ADDON_INAPPS
    if not inapp:
        messages.error(request,
                       _('Your app is not configured for in-app payments.'))
        return redirect(reverse('mkt.developers.apps.payments',
                                args=[addon.app_slug]))
    try:
        account = addon.app_payment_account
    except ObjectDoesNotExist:
        messages.error(request, _('No payment account for this app.'))
        return redirect(reverse('mkt.developers.apps.payments',
                                args=[addon.app_slug]))

    seller_config = get_seller_product(account)

    owner = acl.check_addon_ownership(request, addon)
    if request.method == 'POST':
        # Reset the in-app secret for the app.
        (client.api.generic
               .product(seller_config['resource_pk'])
               .patch(data={'secret': generate_key(48)}))
        messages.success(request, _('Changes successfully saved.'))
        return redirect(reverse('mkt.developers.apps.in_app_config',
                                args=[addon.app_slug]))

    return jingo.render(request, 'developers/payments/in-app-config.html',
                        {'addon': addon, 'owner': owner,
                         'seller_config': seller_config})


@login_required
@waffle_switch('in-app-payments')
@dev_required(webapp=True)
def in_app_secret(request, addon_id, addon, webapp=True):
    seller_config = get_seller_product(addon.app_payment_account)
    return http.HttpResponse(seller_config['secret'])


@waffle_switch('bango-portal')
@dev_required(webapp=True)
def bango_portal_from_addon(request, addon_id, addon, webapp=True):
    if not ((addon.authors.filter(user=request.user,
                addonuser__role=amo.AUTHOR_ROLE_OWNER).exists()) and
            (addon.app_payment_account.payment_account.solitude_seller.user.id
                == request.user.id)):
        log.error(('User not allowed to reach the Bango portal; '
                   'pk=%s') % request.user.pk)
        return http.HttpResponseForbidden()

    package_id = addon.app_payment_account.payment_account.account_id
    return _redirect_to_bango_portal(package_id, 'addon_id: %s' % addon_id)


def _redirect_to_bango_portal(package_id, source):
    try:
        bango_token = client.api.bango.login.post({'packageId': package_id})
    except HttpClientError as e:
        log.error('Failed to authenticate against Bango portal; %s' % source,
                  exc_info=True)
        return http.HttpResponseBadRequest(json.dumps(e.content))

    bango_url = '{base_url}{parameters}'.format(**{
        'base_url': settings.BANGO_BASE_PORTAL_URL,
        'parameters': urllib.urlencode({
            'authenticationToken': bango_token['authentication_token'],
            'emailAddress': bango_token['email_address'],
            'packageId': package_id,
            'personId': bango_token['person_id'],
        })
    })
    response = http.HttpResponse(status=204)
    response['Location'] = bango_url
    return response


def get_seller_product(account):
    """
    Get the solitude seller_product for a payment account object.
    """
    bango_product = (client.api.bango
                           .product(uri_to_pk(account.product_uri))
                           .get_object_or_404())
    # TODO(Kumar): we can optimize this by storing the seller_product
    # when we create it in developers/models.py or allowing solitude
    # to filter on both fields.
    return (client.api.generic
                  .product(uri_to_pk(bango_product['seller_product']))
                  .get_object_or_404())


# TODO(andym): move these into a tastypie API.
@login_required
@json_view
def agreement(request, id):
    account = get_object_or_404(PaymentAccount, pk=id, user=request.user)
    # It's a shame we have to do another get to find this out.
    package = client.api.bango.package(account.uri).get_object_or_404()
    if request.method == 'POST':
        # Set the agreement.
        account.update(agreed_tos=True)
        return (client.api.bango.sbi.post(
                data={'seller_bango': package['resource_uri']}))
    res = (client.api.bango.sbi.agreement
            .get_object(data={'seller_bango': package['resource_uri']}))
    res['valid'] = helpers.datetime(
            datetime.strptime(res['valid'], '%Y-%m-%dT%H:%M:%S'))
    return res
