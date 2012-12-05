
from django import http
from django.forms.models import model_to_dict
from django.shortcuts import get_object_or_404, redirect

import commonware.log
import jingo
from tower import ugettext as _
import waffle
from waffle.decorators import waffle_switch

import amo
import paypal
from addons.decorators import can_become_premium
from amo import messages
from amo.decorators import json_view, post_required, write
from amo.helpers import absolutify, urlparams
from lib.pay_server import client
from market.models import AddonPaymentData, AddonPremium
from paypal import PaypalError
from paypal.check import Check
from paypal.decorators import handle_paypal_error
from stats.models import Contribution

from mkt.developers.decorators import dev_required
from mkt.developers.forms import PaypalSetupForm

from . import forms

paypal_log = commonware.log.getLogger('z.paypal')


@json_view
@dev_required(owner_for_post=True, webapp=True)
def paypal_setup(request, addon_id, addon, webapp):
    paypal_form = PaypalSetupForm(request.POST or None)

    if paypal_form.is_valid():
        # Don't save the paypal_id into the addon until we set up permissions
        # and confirm it as good.
        request.session['unconfirmed_paypal_id'] = (paypal_form
                                                    .cleaned_data['email'])

        # Go setup your details on paypal.
        paypal_url = get_paypal_bounce_url(request, str(addon_id), addon,
                                           webapp, json_view=True)

        return {'valid': True, 'message': [], 'paypal_url': paypal_url}

    return {'valid': False, 'message': [_('Form not valid.')]}


def get_paypal_bounce_url(request, addon_id, addon, webapp, json_view=False):
    if not addon.paypal_id and not json_view:
        messages.error(request, _('We need a PayPal email before continuing.'))
        return redirect(addon.get_dev_url('paypal_setup'))

    dest = 'developers'
    perms = ['REFUND', 'ACCESS_BASIC_PERSONAL_DATA',
             'ACCESS_ADVANCED_PERSONAL_DATA']
    if waffle.flag_is_active(request, 'solitude-payments'):
        url = addon.get_dev_url('acquire_refund_permission')
        url = absolutify(urlparams(url, dest=dest))
        result = client.post_permission_url(data={'scope': perms, 'url': url})
        paypal_url = result['token']
    # TODO(solitude): remove this.
    else:
        paypal_url = paypal.get_permission_url(addon, dest, perms)
    return paypal_url


@write
@dev_required(webapp=True, skip_submit_check=True)
@handle_paypal_error
def acquire_refund_permission(request, addon_id, addon, webapp=False):
    """This is the callback from Paypal."""
    # Set up our redirects.
    # The management pages are the default.
    on_good = addon.get_dev_url('paypal_setup_confirm')
    on_error = addon.get_dev_url('payments')
    show_good_msgs = True

    if 'request_token' not in request.GET:
        paypal_log.debug('User did not approve permissions for'
                         ' addon: %s' % addon_id)
        messages.error(request, 'You will need to accept the permissions '
                                'to continue.')
        return redirect(on_error)

    paypal_log.debug('User approved permissions for addon: %s' % addon_id)
    if waffle.flag_is_active(request, 'solitude-payments'):
        client.post_permission_token(data={
            'seller': addon, 'token': request.GET['request_token'],
            'verifier': request.GET['verification_code'],
        })
        try:
            data = client.post_personal_basic(data={'seller': addon})
        except client.Error as err:
            paypal_log.debug('%s for addon %s' % (err.message, addon.id))
            messages.warning(request, err.message)
            return redirect(on_error)

        data.update(client.post_personal_advanced(data={'seller': addon}))
    # TODO(solitude): remove these.
    else:
        token = paypal.get_permissions_token(request.GET['request_token'],
                                             request.GET['verification_code'])
        data = paypal.get_personal_data(token)

    # TODO(solitude): remove this. Sadly because the permissions tokens
    # are never being traversed back we have a disconnect between what is
    # happening in solitude and here and this will not easily survive flipping
    # on and off the flag.
    if not waffle.flag_is_active(request, 'solitude-payments'):
        # Set the permissions token that we have just successfully used
        # in get_personal_data.
        addonpremium, created = (AddonPremium.objects
                                             .safer_get_or_create(addon=addon))
        addonpremium.update(paypal_permissions_token=token)

    # TODO(solitude): remove this.
    # Do this after setting permissions token since the previous permissions
    # token becomes invalid after making a call to get_permissions_token.
    email = data.get('email')
    paypal_id = request.session['unconfirmed_paypal_id']
    # If the email from paypal is different, something has gone wrong.
    if email != paypal_id:
        paypal_log.debug('Addon paypal_id and personal data differ: '
                         '%s vs %s' %
                         (email, paypal_id))
        messages.warning(request, _('The email returned by PayPal '
                                    'did not match the PayPal email you '
                                    'entered. Please log in using %s.')
                         % paypal_id)
        return redirect(on_error)

    # Finally update the data returned from PayPal for this addon.
    paypal_log.debug('Updating personal data for: %s' % addon_id)
    # TODO(solitude): delete this, as the data was pulled through solitude
    # it was saved.
    apd, created = AddonPaymentData.objects.safer_get_or_create(addon=addon)
    # This can be deleted with solitude, but this needs to change because
    # data will contain more than the fields on the object, this is a quick
    # workaround.
    for k, v in data.items():
        setattr(apd, k, v)
    apd.save()

    amo.log(amo.LOG.EDIT_PROPERTIES, addon)

    if show_good_msgs:
        messages.success(request, 'Please confirm the data we '
                                  'received from PayPal.')
    return redirect(on_good)
# End of new paypal stuff.


@dev_required(owner_for_post=True, webapp=True)
def paypal_setup_confirm(request, addon_id, addon, webapp, source='paypal'):
    # If you bounce through paypal as you do permissions changes set the
    # source to paypal.
    if source == 'paypal':
        msg = _('PayPal setup complete.')
        title = _('Confirm Details')
        button = _('Continue')
    # If you just hit this page from the Manage Paypal, show some less
    # wizardy stuff.
    else:
        msg = _('Changes saved.')
        title = _('Contact Details')
        button = _('Save')

    data = {}
    if waffle.flag_is_active(request, 'solitude-payments'):
        data = client.get_seller_paypal_if_exists(addon) or {}

    # TODO(solitude): remove this bit.
    # If it's not in solitude, use the local version
    adp, created = (AddonPaymentData.objects
                                    .safer_get_or_create(addon=addon))
    if not data:
        data = model_to_dict(adp)

    form = forms.PaypalPaymentData(request.POST or data)
    if request.method == 'POST' and form.is_valid():

        # TODO(solitude): we will remove this.
        # Everything is finally set up so now save the paypal_id and token
        # to the addon.
        addon.update(paypal_id=request.session['unconfirmed_paypal_id'])
        if waffle.flag_is_active(request, 'solitude-payments'):
            obj = client.create_seller_paypal(addon)
            client.patch_seller_paypal(pk=obj['resource_pk'],
                                       data={'paypal_id': addon.paypal_id})

        if waffle.flag_is_active(request, 'solitude-payments'):
            # TODO(solitude): when the migration of data is completed, we
            # will be able to remove this.
            pk = client.create_seller_for_pay(addon)
            client.patch_seller_paypal(pk=pk, data=form.cleaned_data)

        # TODO(solitude): remove this.
        adp.update(**form.cleaned_data)

        messages.success(request, msg)
        if source == 'paypal' and addon.is_incomplete() and addon.paypal_id:
            addon.mark_done()
        return redirect(addon.get_dev_url('payments'))

    return jingo.render(request,
                        'developers/payments/paypal-details-confirm.html',
                        {'addon': addon, 'button': button, 'form': form,
                         'title': title})


@json_view
@dev_required(owner_for_post=True, webapp=True)
def paypal_setup_check(request, addon_id, addon, webapp):
    if waffle.flag_is_active(request, 'solitude-payments'):
        data = client.post_account_check(data={'seller': addon})
        return {'valid': data['passed'], 'message': data['errors']}
    else:
        if not addon.paypal_id:
            return {'valid': False, 'message': [_('No PayPal email.')]}

        check = Check(addon=addon)
        check.all()
        return {'valid': check.passed, 'message': check.errors}


@json_view
@post_required
@dev_required(owner_for_post=True, webapp=True)
def paypal_remove(request, addon_id, addon, webapp):
    """
    Unregisters PayPal account from app.
    """
    try:
        addon.update(paypal_id='')
        addonpremium, created = (AddonPremium.objects
                                 .safer_get_or_create(addon=addon))
        addonpremium.update(paypal_permissions_token='')
    except Exception as e:
        return {'error': True, 'message': [e]}
    return {'error': False, 'message': []}


@waffle_switch('allow-refund')
@dev_required(support=True, webapp=True)
def issue_refund(request, addon_id, addon, webapp=False):
    txn_id = request.REQUEST.get('transaction_id')
    if not txn_id:
        raise http.Http404
    form_enabled = True
    contribution = get_object_or_404(Contribution, transaction_id=txn_id,
                                     type__in=[amo.CONTRIB_PURCHASE,
                                               amo.CONTRIB_INAPP])

    if (hasattr(contribution, 'refund') and
        contribution.refund.status not in (amo.REFUND_PENDING,
                                           amo.REFUND_FAILED)):
        # If it's not pending, we've already taken action.
        messages.error(request, _('Refund already processed.'))
        form_enabled = False

    elif request.method == 'POST':
        if 'issue' in request.POST:
            if waffle.flag_is_active(request, 'solitude-payments'):
                try:
                    response = client.post_refund(
                        data={'uuid': contribution.transaction_id})
                except client.Error, e:
                    contribution.record_failed_refund(e)
                    paypal_log.error('Refund failed for: %s' % txn_id,
                                     exc_info=True)
                    messages.error(request, _('There was an error with '
                                              'the refund.'))
                    return redirect(addon.get_dev_url('refunds'))
                results = response['response']

            else:
                # TODO(solitude): remove this.
                try:
                    results = paypal.refund(contribution.paykey)
                except PaypalError, e:
                    contribution.record_failed_refund(e)
                    paypal_log.error('Refund failed for: %s' % txn_id,
                                     exc_info=True)
                    messages.error(request, _('There was an error with '
                                              'the refund.'))
                    return redirect(addon.get_dev_url('refunds'))

            for res in results:
                if res['refundStatus'] == 'ALREADY_REVERSED_OR_REFUNDED':
                    paypal_log.debug(
                        'Refund attempt for already-refunded paykey: %s, %s' %
                        (contribution.paykey, res['receiver.email']))
                    messages.error(request, _('Refund was previously issued; '
                                              'no action taken.'))
                    return redirect(addon.get_dev_url('refunds'))
                elif res['refundStatus'] == 'NO_API_ACCESS_TO_RECEIVER':
                    paypal_log.debug('Refund attempt for product %s with no '
                                     'refund token: %s, %s' %
                                    (contribution.addon.pk,
                                     contribution.paykey,
                                     res['receiver.email']))
                    messages.error(request,
                                   _("A refund can't be issued at this time. "
                                     "We've notified an admin; please try "
                                     "again later."))
                    return redirect(addon.get_dev_url('refunds'))

            contribution.mail_approved()
            amo.log(amo.LOG.REFUND_GRANTED, addon, contribution.user)
            refund = contribution.enqueue_refund(amo.REFUND_APPROVED)
            paypal_log.info('Refund %r issued for contribution %r' %
                            (refund.pk, contribution.pk))
            messages.success(request, _('Refund issued.'))
        else:
            contribution.mail_declined()
            amo.log(amo.LOG.REFUND_DECLINED, addon, contribution.user)
            # TODO: Consider requiring a rejection reason for declined refunds.
            refund = contribution.enqueue_refund(amo.REFUND_DECLINED)
            paypal_log.info('Refund %r declined for contribution %r' %
                            (refund.pk, contribution.pk))
            messages.success(request, _('Refund declined.'))
        return redirect(addon.get_dev_url('refunds'))

    return jingo.render(request, 'developers/payments/issue-refund.html',
                        {'enabled': form_enabled,
                         'contribution': contribution,
                         'addon': addon,
                         'webapp': webapp,
                         'transaction_id': txn_id})
