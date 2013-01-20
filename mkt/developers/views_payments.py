import json

from django import http
from django.shortcuts import get_object_or_404, redirect

import commonware
import jingo
import waffle
from tower import ugettext as _
from waffle.decorators import waffle_switch

import amo
from access import acl
from amo import messages
from amo.decorators import json_view, login_required, post_required, write
from amo.urlresolvers import reverse
from lib.crypto import generate_key
from lib.pay_server import client

from mkt.constants import DEVICE_LOOKUP
from mkt.developers.decorators import dev_required

from . import forms, forms_payments, models


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
        request.POST or None, product=addon)

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

            is_now_paid = addon.premium_type in amo.ADDON_PREMIUMS

            # If we haven't changed to a free app, check the upsell.
            if is_now_paid and success:
                try:
                    upsell_form.save()
                    bango_account_list_form.save()
                except client.Error as err:
                    log.error('Error saving payment information (%s)' % err)
                    messages.error(
                        request, _(u'We encountered a problem connecting to '
                                   u'the payment server.'))
                    success = False
                    raise  # We want to see all the solitude errors now.

            # Test again in case a call to Solitude failed.
            if is_now_paid and success:
                # Update the product's price if we need to.
                try:
                    apa = models.AddonPaymentAccount.objects.get(addon=addon)
                    apa.update_price(addon.addonpremium.price.price)
                except models.AddonPaymentAccount.DoesNotExist:
                    pass
                except client.Error:
                    log.error('Error updating AddonPaymentAccount (%s) price' %
                                  apa.pk)
                    messages.error(
                        request, _(u'We encountered a problem while updating '
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

    return jingo.render(
        request, 'developers/payments/premium.html',
        {'addon': addon, 'webapp': webapp, 'premium': addon.premium,
         'form': premium_form, 'upsell_form': upsell_form,
         'region_form': region_form,
         'DEVICE_LOOKUP': DEVICE_LOOKUP,
         'is_paid': addon.premium_type in amo.ADDON_PREMIUMS,
         'no_paid': cannot_be_paid,
         'is_incomplete': addon.status == amo.STATUS_NULL,
         'is_packaged': addon.is_packaged,
         # Bango values
         'bango_account_form': forms_payments.BangoPaymentAccountForm(),
         'bango_account_list_form': bango_account_list_form,
         # Waffles
         'payments_enabled':
             waffle.switch_is_active('allow-b2g-paid-submission') and
             not waffle.switch_is_active('disabled-payments')})


@login_required
@json_view
def payment_accounts(request):
    accounts = models.PaymentAccount.objects.filter(
        user=request.amo_user, inactive=False)

    def account(acc):
        return {
            'id': acc.pk,
            'name': unicode(acc),
            'account-url':
                reverse('mkt.developers.bango.payment_account', args=[acc.pk]),
            'delete-url':
                reverse('mkt.developers.bango.delete_payment_account',
                        args=[acc.pk])
        }

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
def payments_accounts_add(request):
    form = forms_payments.BangoPaymentAccountForm(request.POST)
    if not form.is_valid():
        return http.HttpResponse(json.dumps(form.errors), status=400)

    try:
        models.PaymentAccount.create_bango(
            request.amo_user, form.cleaned_data)
    except client.Error as e:
        log.error('Error creating Bango payment account; %s' % e)
        raise  # We want to see these exceptions!
        return http.HttpResponse(
            _(u'Could not connect to payment server.'), status=400)
    return redirect('mkt.developers.bango.payment_accounts_form')


@write
@login_required
@json_view
def payments_account(request, id):
    account = get_object_or_404(models.PaymentAccount, pk=id,
                                user=request.user)
    if request.POST:
        form = forms_payments.BangoPaymentAccountForm(
            request.POST, account=account)
        if form.is_valid():
            form.save()
        else:
            return http.HttpResponse(json.dumps(form.errors), status=400)

    return account.get_details()


@write
@post_required
@login_required
def payments_accounts_delete(request, id):
    account = get_object_or_404(models.PaymentAccount, pk=id,
                                user=request.user)
    account.cancel()
    log.info('Account cancelled: %s' % id)
    return http.HttpResponse('success')


@login_required
@waffle_switch('in-app-payments')
@dev_required(owner_for_post=True, webapp=True)
def in_app_config(request, addon_id, addon, webapp=True):
    account = addon.app_payment_account
    seller_config = (client.api.generic
                           .product(account.uri_to_pk(account.product_uri))
                           .get_object_or_404())

    owner = acl.check_addon_ownership(request, addon)
    if request.method == 'POST':
        (client.api.generic
               .product(seller_config['resource_pk'])
               .patch(data={'secret':generate_key(48)}))
        messages.success(request, _('Changes successfully saved.'))
        return redirect(reverse('mkt.developers.apps.in_app_config',
                                args=[addon.app_slug]))

    return jingo.render(request, 'developers/payments/in-app-config.html',
                        {'addon': addon, 'seller_config': seller_config,
                         'account': account, 'owner': owner})


@login_required
@waffle_switch('in-app-payments')
@dev_required(webapp=True)
def in_app_secret(request, addon_id, addon, webapp=True):
    account = addon.app_payment_account
    seller_config = (client.api.generic
                           .product(account.uri_to_pk(account.product_uri))
                           .get_object_or_404())
    return http.HttpResponse(seller_config['secret'])
