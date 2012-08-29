import json
import os
import sys
import traceback

from django import http
from django import forms as django_forms
from django.conf import settings
from django.db import models, transaction
from django.forms.models import model_to_dict
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_view_exempt

import commonware.log
import jingo
import waffle
from session_csrf import anonymous_csrf
from tower import ugettext as _, ugettext_lazy as _lazy
from waffle.decorators import waffle_switch

import amo
import amo.utils
import paypal
from access import acl
from addons import forms as addon_forms
from addons.decorators import can_become_premium
from addons.forms import DeviceTypeForm
from addons.models import Addon, AddonUser
from addons.views import BaseFilter
from amo import messages
from amo.decorators import json_view, login_required, post_required, write
from amo.helpers import absolutify, urlparams
from amo.urlresolvers import reverse
from amo.utils import escape_all
from devhub.forms import VersionForm
from devhub.models import AppLog
from files.models import File, FileUpload
from files.utils import parse_addon
from lib.cef_loggers import inapp_cef
from lib.pay_server import client
from market.models import AddonPaymentData, AddonPremium, Refund
from paypal import PaypalError
from paypal.check import Check
from paypal.decorators import handle_paypal_error
from stats.models import Contribution
from translations.models import delete_translation
from users.models import UserProfile
from users.views import _login
from versions.models import Version

from mkt.developers.decorators import dev_required
from mkt.developers.forms import (AppFormBasic, AppFormDetails, AppFormMedia,
                                  AppFormSupport, CategoryForm, CurrencyForm,
                                  InappConfigForm, PaypalSetupForm,
                                  PreviewFormSet, RegionForm, trap_duplicate)
from mkt.developers.utils import check_upload
from mkt.inapp_pay.models import InappConfig
from mkt.submit.forms import NewWebappForm
from mkt.webapps.tasks import update_manifests, _update_manifest
from mkt.webapps.models import Webapp

from . import forms, tasks

log = commonware.log.getLogger('z.devhub')
paypal_log = commonware.log.getLogger('z.paypal')


# We use a session cookie to make sure people see the dev agreement.
DEV_AGREEMENT_COOKIE = 'yes-I-read-the-dev-agreement'


class AddonFilter(BaseFilter):
    opts = (('name', _lazy(u'Name')),
            ('updated', _lazy(u'Updated')),
            ('created', _lazy(u'Created')),
            ('popular', _lazy(u'Downloads')),
            ('rating', _lazy(u'Rating')))


class AppFilter(BaseFilter):
    opts = (('name', _lazy(u'Name')),
            ('created', _lazy(u'Created')))


def addon_listing(request, default='name', webapp=False):
    """Set up the queryset and filtering for addon listing for Dashboard."""
    Filter = AppFilter if webapp else AddonFilter
    addons = UserProfile.objects.get(pk=request.user.id).addons
    if webapp:
        qs = Webapp.objects.filter(id__in=addons.filter(type=amo.ADDON_WEBAPP))
        model = Webapp
    else:
        qs = addons.exclude(type=amo.ADDON_WEBAPP)
        model = Addon
    filter = Filter(request, qs, 'sort', default, model=model)
    return filter.qs, filter


@anonymous_csrf
def login(request, template=None):
    return _login(request, template='developers/login.html')


def home(request):
    return index(request)


@login_required
def index(request):
    # This is a temporary redirect.
    return redirect('mkt.developers.apps')


@login_required
def dashboard(request, webapp=False):
    addons, filter = addon_listing(request, webapp=webapp)
    addons = amo.utils.paginate(request, addons, per_page=10)
    data = dict(addons=addons, sorting=filter.field, filter=filter,
                sort_opts=filter.opts, webapp=webapp)
    return jingo.render(request, 'developers/apps/dashboard.html', data)


@dev_required(webapp=True)
def edit(request, addon_id, addon, webapp=False):
    data = {
       'page': 'edit',
       'addon': addon,
       'webapp': webapp,
       'valid_slug': addon.app_slug,
       'tags': addon.tags.not_blacklisted().values_list('tag_text', flat=True),
       'previews': addon.get_previews(),
       'device_type_form': DeviceTypeForm(request.POST or None, addon=addon),
    }
    if acl.action_allowed(request, 'Apps', 'Configure'):
        data['admin_settings_form'] = forms.AdminSettingsForm(instance=addon)
    return jingo.render(request, 'developers/apps/edit.html', data)


@dev_required(owner_for_post=True, webapp=True)
def delete(request, addon_id, addon, webapp=False):
    # Database deletes only allowed for free or incomplete addons.
    if not addon.can_be_deleted():
        msg = _('Paid apps cannot be deleted. Disable this app instead.')
        messages.error(request, msg)
        return redirect(addon.get_dev_url('versions'))

    # TODO: This short circuits the delete form which checks the password. When
    # BrowserID adds re-auth support, update the form to check with BrowserID
    # and remove the short circuit.
    form = forms.DeleteForm(request)
    if True or form.is_valid():
        addon.delete('Removed via devhub')
        messages.success(request, _('App deleted.'))
        # Preserve query-string parameters if we were directed from Dashboard.
        return redirect(request.GET.get('to') or
                        reverse('mkt.developers.apps'))
    else:
        msg = _('Password was incorrect.  App was not deleted.')
        messages.error(request, msg)
        return redirect(addon.get_dev_url('versions'))


@dev_required
def enable(request, addon_id, addon):
    addon.update(disabled_by_user=False)
    amo.log(amo.LOG.USER_ENABLE, addon)
    return redirect(addon.get_dev_url('versions'))


@dev_required
@post_required
def disable(request, addon_id, addon):
    addon.update(disabled_by_user=True)
    amo.log(amo.LOG.USER_DISABLE, addon)
    return redirect(addon.get_dev_url('versions'))


@dev_required
@post_required
def publicise(request, addon_id, addon):
    if addon.status == amo.STATUS_PUBLIC_WAITING:
        addon.update(status=amo.STATUS_PUBLIC)
        amo.log(amo.LOG.CHANGE_STATUS, addon.get_status_display(), addon)
    return redirect(addon.get_dev_url('versions'))


@dev_required(webapp=True)
def status(request, addon_id, addon, webapp=False):
    form = forms.AppAppealForm(request.POST, product=addon)
    upload_form = NewWebappForm(request.POST or None, is_packaged=True,
                                addon=addon)

    if request.method == 'POST':
        if 'resubmit-app' in request.POST and form.is_valid():
            form.save()
            messages.success(request, _('App successfully resubmitted.'))
            return redirect(addon.get_dev_url('versions'))

        elif 'upload-version' in request.POST and upload_form.is_valid():
            ver = Version.from_upload(upload_form.cleaned_data['upload'],
                                      addon, [amo.PLATFORM_ALL])
            log.info('[Webapp:%s] New version created id=%s from upload: %s'
                     % (addon, ver.pk, upload_form.cleaned_data['upload']))
            return redirect(addon.get_dev_url('versions.edit', args=[ver.pk]))

    ctx = {'addon': addon, 'webapp': webapp, 'form': form,
           'upload_form': upload_form}

    if addon.status == amo.STATUS_REJECTED:
        try:
            entry = (AppLog.objects
                     .filter(addon=addon,
                             activity_log__action=amo.LOG.REJECT_VERSION.id)
                     .order_by('-created'))[0]
        except IndexError:
            entry = None
        # This contains the rejection reason and timestamp.
        ctx['rejection'] = entry and entry.activity_log

    return jingo.render(request, 'developers/apps/status.html', ctx)


@dev_required
def version_edit(request, addon_id, addon, version_id):
    version = get_object_or_404(Version, pk=version_id, addon=addon)
    form = VersionForm(request.POST or None, instance=version)

    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, _('Changes successfully saved.'))
        return redirect(addon.get_dev_url('versions.edit', args=[version.pk]))

    return jingo.render(request, 'developers/apps/version_edit.html', {
        'addon': addon, 'version': version, 'form': form})


@dev_required(owner_for_post=True, webapp=True)
def ownership(request, addon_id, addon, webapp=False):
    # Authors.
    qs = AddonUser.objects.filter(addon=addon).order_by('position')
    user_form = forms.AuthorFormSet(request.POST or None, queryset=qs)

    if request.method == 'POST' and user_form.is_valid():
        # Authors.
        authors = user_form.save(commit=False)
        for author in authors:
            action = None
            if not author.id or author.user_id != author._original_user_id:
                action = amo.LOG.ADD_USER_WITH_ROLE
                author.addon = addon
            elif author.role != author._original_role:
                action = amo.LOG.CHANGE_USER_WITH_ROLE

            author.save()
            if action:
                amo.log(action, author.user, author.get_role_display(), addon)
            if (author._original_user_id and
                author.user_id != author._original_user_id):
                amo.log(amo.LOG.REMOVE_USER_WITH_ROLE,
                        (UserProfile, author._original_user_id),
                        author.get_role_display(), addon)

        for author in user_form.deleted_objects:
            amo.log(amo.LOG.REMOVE_USER_WITH_ROLE, author.user,
                    author.get_role_display(), addon)

        messages.success(request, _('Changes successfully saved.'))

        return redirect(addon.get_dev_url('owner'))

    ctx = dict(addon=addon, webapp=webapp, user_form=user_form)
    return jingo.render(request, 'developers/apps/owner.html', ctx)


@dev_required(owner_for_post=True, webapp=True)
def payments(request, addon_id, addon, webapp=False):
    return _premium(request, addon_id, addon, webapp)


@dev_required(owner_for_post=True, webapp=True)
def paypal_setup(request, addon_id, addon, webapp):
    if addon.premium_type == amo.ADDON_FREE:
        messages.error(request, 'Your app does not use payments.')
        return redirect(addon.get_dev_url('payments'))

    paypal_form = PaypalSetupForm(request.POST or None)
    currency_form = CurrencyForm(request.POST or None,
                        initial={'currencies': addon.premium.currencies
                                               if addon.premium else {}})

    context = {'addon': addon, 'paypal_form': paypal_form,
               'currency_form': currency_form}

    if request.POST.get('form') == 'paypal' and paypal_form.is_valid():
        existing = paypal_form.cleaned_data['business_account']
        if existing != 'yes':
            # Go create an account.
            # TODO: this will either become the API or something some better
            # URL for the future.
            return redirect(settings.PAYPAL_CGI_URL)
        else:
            # Go setup your details on paypal.
            # TODO(solitude): we will remove this.
            addon.update(paypal_id=paypal_form.cleaned_data['email'])

            if waffle.flag_is_active(request, 'solitude-payments'):
                obj = client.create_seller_paypal(addon)
                client.patch_seller_paypal(pk=obj['resource_pk'],
                        data={'paypal_id': paypal_form.cleaned_data['email']})

            if addon.premium and addon.premium.paypal_permissions_token:
                addon.premium.update(paypal_permissions_token='')
            return redirect(addon.get_dev_url('paypal_setup_bounce'))

    if (waffle.switch_is_active('currencies') and
        request.POST.get('form') == 'currency' and currency_form.is_valid()):
        currencies = currency_form.cleaned_data['currencies']
        addon.premium.update(currencies=currencies)
        messages.success(request, _('Currencies updated.'))
        return redirect(addon.get_dev_url('paypal_setup'))

    return jingo.render(request, 'developers/payments/paypal-setup.html',
                        context)


@json_view
@dev_required(owner_for_post=True, webapp=True)
def paypal_setup_check(request, addon_id, addon, webapp):
    if waffle.flag_is_active(request, 'solitude-payments'):
        data = client.post_account_check(data={'seller': addon})
        return {'valid': data['passed'], 'message': data['errors']}
    else:
        if not addon.paypal_id:
            return {'valid': False, 'message': ['No PayPal email.']}

        check = Check(addon=addon)
        check.all()
        return {'valid': check.passed, 'message': check.errors}


@dev_required(owner_for_post=True, webapp=True)
def paypal_setup_bounce(request, addon_id, addon, webapp):
    if not addon.paypal_id:
        messages.error(request, 'We need a PayPal email before continuing.')
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

    return jingo.render(request,
                        'developers/payments/paypal-details-request.html',
                        {'paypal_url': paypal_url, 'addon': addon})


@dev_required(owner_for_post=True, webapp=True)
def paypal_setup_confirm(request, addon_id, addon, webapp, source='paypal'):
    # If you bounce through paypal as you do permissions changes set the
    # source to paypal.
    if source == 'paypal':
        msg = _('PayPal set up complete.')
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
        return redirect(addon.get_dev_url('paypal_setup'))

    return jingo.render(request,
                        'developers/payments/paypal-details-confirm.html',
                        {'addon': addon, 'button': button, 'form': form,
                         'title': title})


@write
@dev_required(webapp=True, skip_submit_check=True)
@handle_paypal_error
def acquire_refund_permission(request, addon_id, addon, webapp=False):
    """This is the callback from Paypal."""
    # Set up our redirects.
    if request.GET.get('dest', '') == 'submission':
        on_good = reverse('submit.app.payments.confirm', args=[addon.app_slug])
        on_error = reverse('submit.app.payments.paypal', args=[addon.app_slug])
        show_good_msgs = False
    else:
        # The management pages are the default.
        on_good = addon.get_dev_url('paypal_setup_confirm')
        on_error = addon.get_dev_url('paypal_setup_bounce')
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

    # TODO(solitude): remove this.
    email = data.get('email')
    # If the email from paypal is different, something has gone wrong.
    if email != addon.paypal_id:
        paypal_log.debug('Addon paypal_id and personal data differ: '
                         '%s vs %s' % (email, addon.paypal_id))
        messages.warning(request, _('The email returned by Paypal, '
                                    'did not match the PayPal email you '
                                    'entered. Please login using %s.')
                         % email)
        return redirect(on_error)

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


@waffle_switch('in-app-payments')
@dev_required(owner_for_post=True, webapp=True)
@transaction.commit_on_success
def in_app_config(request, addon_id, addon, webapp=True):
    if addon.premium_type not in amo.ADDON_INAPPS:
        messages.error(request, 'Your app does not use payments.')
        return redirect(addon.get_dev_url('payments'))

    try:
        inapp_config = InappConfig.objects.get(addon=addon,
                                               status=amo.INAPP_STATUS_ACTIVE)
    except models.ObjectDoesNotExist:
        inapp_config = None

    inapp_form = InappConfigForm(request.POST or None,
                                 instance=inapp_config)

    if request.method == 'POST' and inapp_form.is_valid():
        new_inapp = inapp_form.save(commit=False)
        new_inapp.addon = addon
        new_inapp.status = amo.INAPP_STATUS_ACTIVE
        if not new_inapp.public_key:
            new_inapp.public_key = InappConfig.generate_public_key()
        new_inapp.save()
        if not new_inapp.has_private_key():
            new_inapp.set_private_key(InappConfig.generate_private_key())

        messages.success(request, _('Changes successfully saved.'))
        return redirect(addon.get_dev_url('in_app_config'))

    return jingo.render(request, 'developers/payments/in-app-config.html',
                        dict(addon=addon, inapp_form=inapp_form,
                             inapp_config=inapp_config))


@waffle_switch('in-app-payments')
@dev_required(owner_for_post=True, webapp=True)
@post_required
@transaction.commit_on_success
def reset_in_app_config(request, addon_id, addon, config_id, webapp=True):
    if addon.premium_type not in amo.ADDON_INAPPS:
        messages.error(request, 'Your app does not use payments.')
        return redirect(addon.get_dev_url('payments'))

    cfg = get_object_or_404(InappConfig, addon=addon,
                            status=amo.INAPP_STATUS_ACTIVE)
    msg = ('user reset in-app payment config %s; '
           'key: %r; app: %s' % (cfg.pk, cfg.public_key, addon.pk))
    log.info(msg)
    inapp_cef.log(request, addon, 'inapp_reset', msg,
                  severity=6)
    cfg.update(status=amo.INAPP_STATUS_REVOKED)
    kw = dict(addon=cfg.addon,
              status=amo.INAPP_STATUS_ACTIVE,
              postback_url=cfg.postback_url,
              chargeback_url=cfg.chargeback_url,
              public_key=InappConfig.generate_public_key())
    new_cfg = InappConfig.objects.create(**kw)
    new_cfg.set_private_key(InappConfig.generate_private_key())
    messages.success(request,
                     _('Old credentials revoked; '
                       'new credentials were generated successfully.'))
    return redirect(addon.get_dev_url('in_app_config'))


@waffle_switch('in-app-payments')
@dev_required(owner_for_post=True, webapp=True)
def in_app_secret(request, addon_id, addon, webapp=True):
    inapp_config = get_object_or_404(InappConfig, addon=addon,
                                     status=amo.INAPP_STATUS_ACTIVE)
    return http.HttpResponse(inapp_config.get_private_key())


def _premium(request, addon_id, addon, webapp=False):
    premium_form = forms.PremiumForm(request.POST or None,
                                     request=request,
                                     extra={'addon': addon,
                                            'amo_user': request.amo_user,
                                            'dest': 'payment'})

    if request.method == 'POST' and premium_form.is_valid():
        premium_form.save()
        messages.success(request, _('Changes successfully saved.'))
        return redirect(addon.get_dev_url('payments'))
    return jingo.render(request, 'developers/payments/premium.html',
                        dict(addon=addon, webapp=webapp, premium=addon.premium,
                             form=premium_form))


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
                    response = client.post_refund(data={'uuid':
                                                 contribution.transaction_id})
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
                        _("A refund can't be issued at this time. We've "
                          "notified an admin; please try again later."))
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


@waffle_switch('allow-refund')
@dev_required(support=True, webapp=True)
def refunds(request, addon_id, addon, webapp=False):
    ctx = {'addon': addon, 'webapp': webapp}
    queues = {
        'pending': Refund.objects.pending(addon).order_by('requested'),
        'approved': Refund.objects.approved(addon).order_by('-requested'),
        'instant': Refund.objects.instant(addon).order_by('-requested'),
        'declined': Refund.objects.declined(addon).order_by('-requested'),
        'failed': Refund.objects.failed(addon).order_by('-requested'),
    }
    for status, refunds in queues.iteritems():
        ctx[status] = amo.utils.paginate(request, refunds, per_page=50)
    return jingo.render(request, 'developers/payments/refunds.html', ctx)


@dev_required
@post_required
def disable_payments(request, addon_id, addon):
    addon.update(wants_contributions=False)
    return redirect(addon.get_dev_url('payments'))


@dev_required(webapp=True)
@post_required
def remove_profile(request, addon_id, addon, webapp=False):
    delete_translation(addon, 'the_reason')
    delete_translation(addon, 'the_future')
    if addon.wants_contributions:
        addon.update(wants_contributions=False)
    return redirect(addon.get_dev_url('profile'))


@dev_required(webapp=True)
def profile(request, addon_id, addon, webapp=False):
    profile_form = forms.ProfileForm(request.POST or None, instance=addon)

    if request.method == 'POST' and profile_form.is_valid():
        profile_form.save()
        amo.log(amo.LOG.EDIT_PROPERTIES, addon)
        messages.success(request, _('Changes successfully saved.'))
        return redirect(addon.get_dev_url('profile'))

    return jingo.render(request, 'developers/apps/profile.html',
                        dict(addon=addon, webapp=webapp,
                             profile_form=profile_form))


@login_required
def validate_addon(request):
    return jingo.render(request, 'developers/validate_addon.html', {
        'title': _('Validate Add-on'),
        'upload_url': reverse('mkt.developers.standalone_upload'),
    })


@login_required
@post_required
def upload(request, addon_slug=None, is_standalone=False):
    filedata = request.FILES['upload']

    fu = FileUpload.from_post(filedata, filedata.name, filedata.size,
                              is_webapp=True)
    log.info('Packaged App FileUpload created: %s' % fu.pk)
    if request.user.is_authenticated():
        fu.user = request.amo_user
        fu.save()
    tasks.validator.delay(fu.pk)
    if addon_slug:
        return redirect('mkt.developers.upload_detail_for_addon',
                        addon_slug, fu.pk)
    elif is_standalone:
        return redirect('mkt.developers.standalone_upload_detail', fu.pk)
    else:
        return redirect('mkt.developers.upload_detail', fu.pk, 'json')


@dev_required
def refresh_manifest(request, addon_id, addon, webapp=False):
    log.info('Manifest %s refreshed for %s' % (addon.manifest_url, addon))
    _update_manifest(addon_id)
    return http.HttpResponse(status=204)


@login_required
@post_required
@json_view
def upload_manifest(request):
    form = forms.NewManifestForm(request.POST)
    if waffle.switch_is_active('webapps-unique-by-domain'):
        # Helpful error if user already submitted the same manifest.
        dup_msg = trap_duplicate(request, request.POST.get('manifest'))
        if dup_msg:
            return {'validation': {'errors': 1, 'success': False,
                    'messages': [{'type': 'error', 'message': dup_msg,
                                  'tier': 1}]}}
    if form.is_valid():
        upload = FileUpload.objects.create()
        tasks.fetch_manifest.delay(form.cleaned_data['manifest'], upload.pk)
        return redirect('mkt.developers.upload_detail', upload.pk, 'json')
    else:
        error_text = _('There was an error with the submission.')
        if 'manifest' in form.errors:
            error_text = ' '.join(form.errors['manifest'])
        error_message = {'type': 'error', 'message': error_text, 'tier': 1}

        v = {'errors': 1, 'success': False, 'messages': [error_message]}
        return make_validation_result(dict(validation=v, error=error_text))


@login_required
@post_required
def standalone_upload(request):
    return upload(request, is_standalone=True)


@login_required
@json_view
def standalone_upload_detail(request, uuid):
    upload = get_object_or_404(FileUpload.uncached, uuid=uuid)
    url = reverse('mkt.developers.standalone_upload_detail', args=[uuid])
    return upload_validation_context(request, upload, url=url)


@post_required
@dev_required
def upload_for_addon(request, addon_id, addon):
    return upload(request, addon_slug=addon.slug)


@dev_required
@json_view
def upload_detail_for_addon(request, addon_id, addon, uuid):
    upload = get_object_or_404(FileUpload.uncached, uuid=uuid)
    return json_upload_detail(request, upload, addon_slug=addon.slug)


def make_validation_result(data, is_compatibility=False):
    """Safe wrapper around JSON dict containing a validation result.

    Keyword Arguments

    **is_compatibility=False**
        When True, errors will be summarized as if they were in a regular
        validation result.
    """
    if not settings.EXPOSE_VALIDATOR_TRACEBACKS:
        if data['error']:
            # Just expose the message, not the traceback
            data['error'] = data['error'].strip().split('\n')[-1].strip()
    if data['validation']:
        ending_tier = 0
        for msg in data['validation']['messages']:
            if msg['tier'] > ending_tier:
                ending_tier = msg['tier']
            if msg['tier'] == 0:
                # We can't display a message if it's on tier 0.
                # Should get fixed soon in bug 617481
                msg['tier'] = 1
            for k, v in msg.items():
                msg[k] = escape_all(v)
        if is_compatibility:
            compat = data['validation']['compatibility_summary']
            for k in ('errors', 'warnings', 'notices'):
                data['validation'][k] = compat[k]
            for msg in data['validation']['messages']:
                if msg['compatibility_type']:
                    msg['type'] = msg['compatibility_type']
        data['validation']['ending_tier'] = ending_tier
    return data


@dev_required(allow_editors=True)
def file_validation(request, addon_id, addon, file_id):
    file = get_object_or_404(File, id=file_id)

    v = addon.get_dev_url('json_file_validation', args=[file.id])
    return jingo.render(request, 'developers/validation.html',
                        dict(validate_url=v, filename=file.filename,
                             timestamp=file.created,
                             addon=addon))


@json_view
@csrf_view_exempt
@dev_required(allow_editors=True)
def json_file_validation(request, addon_id, addon, file_id):
    file = get_object_or_404(File, id=file_id)
    if not file.has_been_validated == True:
        if request.method != 'POST':
            return http.HttpResponseNotAllowed(['POST'])

        try:
            v_result = tasks.file_validator(file.id)
        except Exception, exc:
            log.error('file_validator(%s): %s' % (file.id, exc))
            error = "\n".join(traceback.format_exception(*sys.exc_info()))
            return make_validation_result({'validation': '',
                                           'error': error})
    else:
        v_result = file.validation
    validation = json.loads(v_result.validation)

    return make_validation_result(dict(validation=validation,
                                       error=None))


@json_view
def json_upload_detail(request, upload, addon_slug=None):
    addon = None
    if addon_slug:
        addon = get_object_or_404(Addon, slug=addon_slug)
    result = upload_validation_context(request, upload, addon=addon)
    if result['validation']:
        if result['validation']['errors'] == 0:
            try:
                parse_addon(upload, addon=addon)
            except django_forms.ValidationError, exc:
                m = []
                for msg in exc.messages:
                    # Simulate a validation error so the UI displays it.
                    m.append({'type': 'error', 'message': msg, 'tier': 1})
                v = make_validation_result(dict(error='',
                                                validation=dict(messages=m)))
                return json_view.error(v)
    return result


def upload_validation_context(request, upload, addon_slug=None, addon=None,
                                       url=None):
    if addon_slug and not addon:
        addon = get_object_or_404(Addon, slug=addon_slug)
    if not settings.VALIDATE_ADDONS:
        upload.task_error = ''
        upload.is_webapp = True
        upload.validation = json.dumps({'errors': 0, 'messages': [],
                                        'metadata': {}, 'notices': 0,
                                        'warnings': 0})
        upload.save()

    validation = json.loads(upload.validation) if upload.validation else ''
    if not url:
        if addon:
            url = reverse('mkt.developers.upload_detail_for_addon',
                          args=[addon.slug, upload.uuid])
        else:
            url = reverse('mkt.developers.upload_detail',
                          args=[upload.uuid, 'json'])
    full_report_url = reverse('mkt.developers.upload_detail',
                              args=[upload.uuid])

    return make_validation_result(dict(upload=upload.uuid,
                                       validation=validation,
                                       error=upload.task_error, url=url,
                                       full_report_url=full_report_url),
                                  is_compatibility=upload.compat_with_app)


@login_required
def upload_detail(request, uuid, format='html'):
    upload = get_object_or_404(FileUpload.uncached, uuid=uuid)

    if format == 'json' or request.is_ajax():
        return json_upload_detail(request, upload)

    validate_url = reverse('mkt.developers.standalone_upload_detail',
                           args=[upload.uuid])
    return jingo.render(request, 'developers/validation.html',
                        dict(validate_url=validate_url, filename=upload.name,
                             timestamp=upload.created))


@dev_required(webapp=True, staff=True)
def addons_section(request, addon_id, addon, section, editable=False,
                   webapp=False):
    basic = AppFormBasic if webapp else addon_forms.AddonFormBasic
    models = {'basic': basic,
              'media': AppFormMedia,
              'details': AppFormDetails,
              'support': AppFormSupport,
              'technical': addon_forms.AddonFormTechnical,
              'admin': forms.AdminSettingsForm}

    if section not in models:
        raise http.Http404()

    tags = previews = restricted_tags = []
    cat_form = device_type_form = region_form = None

    if section == 'basic':
        tags = addon.tags.not_blacklisted().values_list('tag_text', flat=True)
        cat_form = CategoryForm(request.POST or None, product=addon,
                                request=request)
        restricted_tags = addon.tags.filter(restricted=True)
        device_type_form = DeviceTypeForm(request.POST or None, addon=addon)

    elif section == 'media':
        previews = PreviewFormSet(request.POST or None, prefix='files',
            queryset=addon.get_previews())

    elif section == 'details' and settings.REGION_STORES:
        region_form = RegionForm(request.POST or None, product=addon)

    elif (section == 'admin' and
          not acl.action_allowed(request, 'Apps', 'Configure') and
          not acl.action_allowed(request, 'Apps', 'ViewConfiguration')):
        return http.HttpResponseForbidden()

    # Get the slug before the form alters it to the form data.
    valid_slug = addon.app_slug
    if editable:
        if request.method == 'POST':

            if (section == 'admin' and
                not acl.action_allowed(request, 'Apps', 'Configure')):
                return http.HttpResponseForbidden()

            form = models[section](request.POST, request.FILES,
                                   instance=addon, request=request)
            if (form.is_valid() and (not previews or previews.is_valid())
                and (not region_form or region_form.is_valid())):

                if region_form:
                    region_form.save()

                addon = form.save(addon)

                if 'manifest_url' in form.changed_data:
                    addon.update(
                        app_domain=addon.domain_from_url(addon.manifest_url))
                    update_manifests([addon.pk])

                if previews:
                    for preview in previews.forms:
                        preview.save(addon)

                editable = False
                if section == 'media':
                    amo.log(amo.LOG.CHANGE_ICON, addon)
                else:
                    amo.log(amo.LOG.EDIT_PROPERTIES, addon)

                valid_slug = addon.app_slug
            if cat_form:
                if cat_form.is_valid():
                    cat_form.save()
                    addon.save()
                else:
                    editable = True
            if device_type_form:
                if device_type_form.is_valid():
                    device_type_form.save(addon)
                    addon.save()
                else:
                    editable = True
        else:
            form = models[section](instance=addon, request=request)
    else:
        form = False

    data = {'addon': addon,
            'webapp': webapp,
            'form': form,
            'editable': editable,
            'tags': tags,
            'restricted_tags': restricted_tags,
            'cat_form': cat_form,
            'preview_form': previews,
            'valid_slug': valid_slug,
            'device_type_form': device_type_form,
            'region_form': region_form}

    return jingo.render(request,
                        'developers/apps/edit/%s.html' % section, data)


@never_cache
@dev_required(skip_submit_check=True)
@json_view
def image_status(request, addon_id, addon, icon_size=64):
    # Default icon needs no checking.
    if not addon.icon_type or addon.icon_type.split('/')[0] == 'icon':
        icons = True
    # Persona icon is handled differently.
    elif addon.type == amo.ADDON_PERSONA:
        icons = True
    else:
        icons = os.path.exists(os.path.join(addon.get_icon_dir(),
                                            '%s-%s.png' %
                                            (addon.id, icon_size)))
    previews = all(os.path.exists(p.thumbnail_path)
                   for p in addon.get_previews())
    return {'overall': icons and previews,
            'icons': icons,
            'previews': previews}


@json_view
def ajax_upload_media(request, upload_type):
    errors = []
    upload_hash = ''

    if 'upload_image' in request.FILES:
        upload_preview = request.FILES['upload_image']
        upload_preview.seek(0)
        content_type = upload_preview.content_type
        errors, upload_hash = check_upload(upload_preview, upload_type,
                                           content_type)

    else:
        errors.append(_('There was an error uploading your preview.'))

    if errors:
        upload_hash = ''

    return {'upload_hash': upload_hash, 'errors': errors}


@dev_required
def upload_media(request, addon_id, addon, upload_type):
    return ajax_upload_media(request, upload_type)


@dev_required(webapp=True)
@can_become_premium
def marketplace_paypal(request, addon_id, addon, webapp=False):
    """
    Start of the marketplace wizard, none of this means anything until
    addon-premium is set, so we'll just save as we go along. Further
    we might have the PayPal permissions bounce happen at any time
    so we'll need to cope with AddonPremium being incomplete.
    """
    form = forms.PremiumForm(request.POST or None,
                             request=request,
                             extra={'addon': addon,
                                    'amo_user': request.amo_user,
                                    'dest': 'wizard',
                                    'exclude': ['price']})
    if form.is_valid():
        form.save()
        return redirect(addon.get_dev_url('market.2'))

    return jingo.render(request, 'developers/payments/paypal.html',
                        {'form': form, 'addon': addon, 'webapp': webapp,
                         'premium': addon.premium})


@dev_required(webapp=True)
@can_become_premium
def marketplace_pricing(request, addon_id, addon, webapp=False):
    form = forms.PremiumForm(request.POST or None,
                             request=request,
                             extra={'addon': addon,
                                    'amo_user': request.amo_user,
                                    'dest': 'wizard',
                                    'exclude': ['paypal_id',
                                                'support_email']})
    if form.is_valid():
        form.save()
        if not (form.fields['free'].queryset.count()):
            return redirect(addon.get_dev_url('market.4'))
        return redirect(addon.get_dev_url('market.3'))
    return jingo.render(request, 'developers/payments/tier.html',
                        {'form': form, 'addon': addon, 'webapp': webapp,
                         'premium': addon.premium})


@dev_required(webapp=True)
@can_become_premium
def marketplace_upsell(request, addon_id, addon, webapp=False):
    form = forms.PremiumForm(request.POST or None,
                             request=request,
                             extra={'addon': addon,
                                    'amo_user': request.amo_user,
                                    'dest': 'wizard',
                                    'exclude': ['price', 'paypal_id',
                                                'support_email']})
    if form.is_valid():
        form.save()
        return redirect(addon.get_dev_url('market.4'))
    return jingo.render(request, 'developers/payments/upsell.html',
                        {'form': form, 'addon': addon, 'webapp': webapp,
                         'premium': addon.premium})


@dev_required(webapp=True)
@can_become_premium
def marketplace_confirm(request, addon_id, addon, webapp=False):
    if request.method == 'POST':
        if (addon.premium and addon.premium.is_complete()
            and addon.premium.has_permissions_token()):
            if addon.status == amo.STATUS_UNREVIEWED:
                addon.status = amo.STATUS_NOMINATED
            addon.premium_type = amo.ADDON_PREMIUM
            addon.save()
            amo.log(amo.LOG.MAKE_PREMIUM, addon)
            return redirect(addon.get_dev_url('payments'))

        messages.error(request, 'Some required details are missing.')
        return redirect(addon.get_dev_url('market.1'))

    return jingo.render(request, 'developers/payments/second-confirm.html',
                        {'addon': addon, 'webapp': webapp,
                         'upsell': addon.upsold, 'premium': addon.premium})


@dev_required
@post_required
def remove_locale(request, addon_id, addon):
    locale = request.POST.get('locale')
    if locale and locale != addon.default_locale:
        addon.remove_locale(locale)
        return http.HttpResponse()
    return http.HttpResponseBadRequest()


def docs(request, doc_name=None, doc_page=None):
    filename = ''

    all_docs = {'policies': ['agreement']}

    if doc_name and doc_name in all_docs:
        filename = '%s.html' % doc_name
        if doc_page and doc_page in all_docs[doc_name]:
            filename = '%s-%s.html' % (doc_name, doc_page)
        else:
            # TODO: Temporary until we have a `policies` docs index.
            filename = None

    if not filename:
        return redirect('ecosystem.landing')

    return jingo.render(request, 'developers/docs/%s' % filename)


@login_required
def terms(request):
    form = forms.DevAgreementForm({'read_dev_agreement': True},
                                  instance=request.amo_user)
    if request.POST and form.is_valid():
        form.save()
        log.info('Dev agreement agreed for user: %s' % request.amo_user.pk)
        messages.success(request, _('Terms of service accepted.'))
    return jingo.render(request, 'developers/terms.html',
                        {'accepted': request.amo_user.read_dev_agreement,
                         'agreement_form': form})
