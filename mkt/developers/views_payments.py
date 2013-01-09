from django import http
from django.shortcuts import get_object_or_404, redirect

import commonware
import jingo
import waffle
from tower import ugettext as _

import amo
from amo import messages
from amo.decorators import login_required, post_required, write
from lib.pay_server import client

from mkt.constants import DEVICE_LOOKUP
from mkt.developers.decorators import dev_required

from . import forms, models


log = commonware.log.getLogger('z.devhub')


@dev_required
@post_required
def disable_payments(request, addon_id, addon):
    addon.update(wants_contributions=False)
    return redirect(addon.get_dev_url('payments'))


@dev_required(owner_for_post=True, webapp=True)
def payments(request, addon_id, addon, webapp=False):
    premium_form = forms.PremiumForm(
        request.POST or None, request=request, addon=addon,
        user=request.amo_user)

    region_form = forms.RegionForm(
        request.POST or None, product=addon)

    upsell_form = forms.UpsellForm(
        request.POST or None, addon=addon, user=request.amo_user)

    bango_account_list_form = forms.BangoAccountListForm(
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
         # Bango values
         'bango_account_form': forms.BangoPaymentAccountForm(),
         'bango_account_list_form': bango_account_list_form,
         # Waffles
         'payments_enabled':
             waffle.switch_is_active('allow-b2g-paid-submission') and
             not waffle.switch_is_active('disabled-payments')})


@write
@login_required
def payments_accounts(request):
    bango_account_form = forms.BangoAccountListForm(
        user=request.amo_user, addon=None)
    return jingo.render(
        request, 'developers/payments/includes/bango_accounts.html',
        {'bango_account_list_form': bango_account_form})


@write
@post_required
@login_required
def payments_accounts_add(request):
    form = forms.BangoPaymentAccountForm(request.POST)
    if not form.is_valid():
        return http.HttpResponse(form.happy_errors, status=400)

    try:
        models.PaymentAccount.create_bango(
            request.amo_user, form.cleaned_data)
    except client.Error as e:
        log.error('Error creating Bango payment account; %s' % e)
        raise  # We want to see these exceptions!
        return http.HttpResponse(
            _(u'Could not connect to payment server.'), status=400)
    return redirect('mkt.developers.bango.payment_accounts')


@write
@post_required
@login_required
def payments_accounts_delete(request, id):
    account = get_object_or_404(models.PaymentAccount, pk=id,
                                user=request.user)
    account.cancel()
    log.info('Account cancelled: %s' % id)
    return http.HttpResponse('success')
