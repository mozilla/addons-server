import json
import os
import sys
import traceback
import uuid

from django import http
from django.core.files.storage import default_storage as storage
from django.conf import settings
from django import forms as django_forms
from django.db import models, transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_view_exempt

import commonware.log
import jingo
from session_csrf import anonymous_csrf
from tower import ugettext_lazy as _lazy, ugettext as _
import waffle
from waffle.decorators import waffle_switch

from applications.models import Application, AppVersion
import amo
import amo.utils
from amo import messages
from amo.decorators import (json_view, login_required, no_login_required,
                            post_required, write)
from amo.helpers import loc
from amo.utils import escape_all
from amo.urlresolvers import reverse
from addons import forms as addon_forms
from addons.decorators import can_become_premium
from addons.models import Addon, AddonUser
from addons.views import BaseFilter
from mkt.developers.decorators import dev_required
from mkt.developers.forms import (AppFormBasic, AppFormDetails,
                                  InappConfigForm, PaypalSetupForm)
from files.models import File, FileUpload
from files.utils import parse_addon
from market.models import AddonPremium, Refund, AddonPaymentData
from payments.models import InappConfig
from paypal.check import Check
from paypal.decorators import handle_paypal_error
import paypal
from stats.models import Contribution
from translations.models import delete_translation
from users.models import UserProfile
from users.views import _login
from mkt.webapps.models import Webapp
from zadmin.models import ValidationResult

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
@no_login_required
def login(request, template=None):
    return _login(request, template='developers/login.html')


def home(request):
    return index(request)


@login_required
def index(request):
    # This is a temporary redirect.
    return redirect('mkt.developers.apps')
    # R.I.P. Landing Page. I barely knew ye'.
    #return jingo.render(request, 'developers/index.html')


@login_required
def dashboard(request, webapp=False):
    addons, filter = addon_listing(request, webapp=webapp)
    addons = amo.utils.paginate(request, addons, per_page=10)
    data = dict(addons=addons, sorting=filter.field, filter=filter,
                sort_opts=filter.opts, webapp=webapp)
    return jingo.render(request, 'developers/addons/dashboard.html', data)


@dev_required(webapp=True)
def edit(request, addon_id, addon, webapp=False):
    data = {
       'page': 'edit',
       'addon': addon,
       'webapp': webapp,
       'valid_slug': addon.app_slug,
       'tags': addon.tags.not_blacklisted().values_list('tag_text', flat=True),
       'previews': addon.previews.all(),
    }

    if webapp and waffle.switch_is_active('marketplace'):
        data['device_type_form'] = addon_forms.DeviceTypeForm(
            request.POST or None, addon=addon)

    return jingo.render(request, 'developers/addons/edit.html', data)


@dev_required(owner_for_post=True, webapp=True)
def delete(request, addon_id, addon, webapp=False):
    # Database deletes only allowed for free or incomplete addons.
    if not addon.can_be_deleted():
        msg = loc('App cannot be deleted. Disable this app instead.')
        messages.error(request, msg)
        return redirect(addon.get_dev_url('versions'))

    # TODO: This short circuits the delete form which checks the password. When
    # BrowserID adds re-auth support, update the form to check with BrowserID
    # and remove the short circuit.
    form = forms.DeleteForm(request)
    if True or form.is_valid():
        addon.delete('Removed via devhub')
        messages.success(request, loc('App deleted.'))
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


@dev_required(owner_for_post=True)
def cancel(request, addon_id, addon):
    if addon.status in amo.STATUS_UNDER_REVIEW:
        if addon.status == amo.STATUS_LITE_AND_NOMINATED:
            addon.update(status=amo.STATUS_LITE)
        else:
            addon.update(status=amo.STATUS_NULL)
        amo.log(amo.LOG.CHANGE_STATUS, addon.get_status_display(), addon)
    return redirect(addon.get_dev_url('versions'))


@dev_required
@post_required
def disable(request, addon_id, addon):
    addon.update(disabled_by_user=True)
    amo.log(amo.LOG.USER_DISABLE, addon)
    return redirect(addon.get_dev_url('versions'))


@dev_required(webapp=True)
def status(request, addon_id, addon, webapp=False):
    return jingo.render(request, 'developers/addons/status.html',
                        {'addon': addon, 'webapp': webapp})


@dev_required(owner_for_post=True, webapp=True)
def ownership(request, addon_id, addon, webapp=False):
    fs, ctx = [], {}
    # Authors.
    qs = AddonUser.objects.filter(addon=addon).order_by('position')
    user_form = forms.AuthorFormSet(request.POST or None, queryset=qs)
    fs.append(user_form)

    if request.method == 'POST' and all([form.is_valid() for form in fs]):
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

    ctx.update(addon=addon, webapp=webapp, user_form=user_form)
    return jingo.render(request, 'developers/addons/owner.html', ctx)


@dev_required(owner_for_post=True, webapp=True)
def payments(request, addon_id, addon, webapp=False):
    return _premium(request, addon_id, addon, webapp)


# PayPal config, the next generation.
@dev_required(owner_for_post=True, webapp=True)
def paypal_setup(request, addon_id, addon, webapp):
    if addon.premium_type == amo.ADDON_FREE:
        messages.error(request, 'Your app does not use payments.')
        return redirect(addon.get_dev_url('payments'))

    form = PaypalSetupForm(request.POST or None)
    context = {'addon': addon, 'form': form}
    if form.is_valid():
        existing = form.cleaned_data['business_account']
        if existing != 'yes':
            # Go create an account.
            # TODO: this will either become the API or something some better
            # URL for the future.
            return redirect(settings.PAYPAL_CGI_URL)
        else:
            # Go setup your details on paypal.
            addon.update(paypal_id=form.cleaned_data['email'])
            if addon.premium and addon.premium.paypal_permissions_token:
                addon.premium.update(paypal_permissions_token='')
            return redirect(addon.get_dev_url('paypal_setup_bounce'))

    return jingo.render(request, 'developers/payments/paypal-setup.html',
                        context)


@json_view
@dev_required(owner_for_post=True, webapp=True)
def paypal_setup_check(request, addon_id, addon, webapp):
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
    paypal_url = paypal.get_permission_url(addon, 'management',
                                        ['REFUND',
                                         'ACCESS_BASIC_PERSONAL_DATA',
                                         'ACCESS_ADVANCED_PERSONAL_DATA'])

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
        title = loc('Contact Details')
        button = _('Save')

    adp, created = AddonPaymentData.objects.safer_get_or_create(addon=addon)
    form = forms.PaypalPaymentData(request.POST or None, instance=adp)
    if request.method == 'POST' and form.is_valid():
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

    token = paypal.get_permissions_token(request.GET['request_token'],
                                         request.GET['verification_code'])
    paypal_log.debug('Got refund token for addon: %s, token: %s....' %
                     (addon_id, token[:10]))

    # Sadly this is an update on a GET.
    addonpremium, created = (AddonPremium.objects
                                         .safer_get_or_create(addon=addon))

    paypal_log.debug('AddonPremium %s for: %s' %
                     ('created' if created else 'updated', addon.pk))
    addonpremium.update(paypal_permissions_token=token)
    paypal_log.debug('AddonPremium saved with token: %s' % addonpremium.pk)

    paypal_log.debug('Getting personal data for token: %s' % addonpremium.pk)
    apd, created = AddonPaymentData.objects.safer_get_or_create(addon=addon)

    # A sanity check, I'm not sure if this should be fatal and will
    # occur on the prod server or it's just sandbox weirdness.
    data = paypal.get_personal_data(token)
    email = data.get('email')
    if email != addon.paypal_id:
        paypal_log.debug('Addon paypal_id and personal data differ: '
                         '%s vs %s' % (email, addon.paypal_id))
        messages.warning(request, 'Warning the email returned by Paypal (%s) '
                         'did not match the PayPal email you entered (%s), '
                         'please be sure that you have the correct account.'
                         % (email, addon.paypal_id))
    apd.update(**data)
    paypal_log.debug('Updating personal data for: %s' % apd.pk)

    paypal_log.debug('AddonPremium saved with token: %s' % addonpremium.pk)
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
        if not new_inapp.private_key:
            new_inapp.private_key = InappConfig.generate_private_key()
        new_inapp.save()

        messages.success(request, _('Changes successfully saved.'))
        return redirect(addon.get_dev_url('in_app_config'))

    return jingo.render(request, 'developers/payments/in-app-config.html',
                        dict(addon=addon, inapp_form=inapp_form,
                             inapp_config=inapp_config))


@waffle_switch('in-app-payments')
@dev_required(owner_for_post=True, webapp=True)
def in_app_secret(request, addon_id, addon, webapp=True):
    inapp_config = get_object_or_404(InappConfig, addon=addon,
                                     status=amo.INAPP_STATUS_ACTIVE)
    return http.HttpResponse(inapp_config.private_key)


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
@dev_required(webapp=True)
def issue_refund(request, addon_id, addon, webapp=False):
    txn_id = request.REQUEST.get('transaction_id')
    if not txn_id:
        raise http.Http404
    form_enabled = True
    contribution = get_object_or_404(Contribution, transaction_id=txn_id,
                                     type=amo.CONTRIB_PURCHASE)
    if Refund.objects.filter(contribution=contribution).exists():
        messages.error(request, _('Refund already processed.'))
        form_enabled = False

    elif request.method == 'POST':
        if 'issue' in request.POST:
            results = paypal.refund(contribution.paykey)
            for res in results:
                if res['refundStatus'] == 'ALREADY_REVERSED_OR_REFUNDED':
                    paypal_log.debug(
                        'Refund attempt for already-refunded paykey: %s, %s' %
                        (contribution.paykey, res['receiver.email']))
                    messages.error(request, _('Refund was previously issued; '
                                              'no action taken.'))
                    return redirect(addon.get_dev_url('refunds'))
            contribution.mail_approved()
            refund = contribution.enqueue_refund(amo.REFUND_APPROVED)
            paypal_log.info('Refund %r issued for contribution %r' %
                            (refund.pk, contribution.pk))
            messages.success(request, _('Refund issued.'))
        else:
            contribution.mail_declined()
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
@dev_required(webapp=True)
# TODO: Make sure 'Support' staff can access this.
def refunds(request, addon_id, addon, webapp=False):
    ctx = {'addon': addon, 'webapp': webapp}
    queues = {
        'pending': Refund.objects.pending(addon),
        'approved': Refund.objects.approved(addon),
        'instant': Refund.objects.instant(addon),
        'declined': Refund.objects.declined(addon),
    }
    # For now set the limit to something stupid so this is stupid easy to QA.
    for status, refunds in queues.iteritems():
        ctx[status] = amo.utils.paginate(request, refunds, per_page=5)
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

    return jingo.render(request, 'developers/addons/profile.html',
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

    fu = FileUpload.from_post(filedata, filedata.name, filedata.size)
    log.info('FileUpload created: %s' % fu.pk)
    if request.user.is_authenticated():
        fu.user = request.amo_user
        fu.save()
    if request.POST.get('app_id') and request.POST.get('version_id'):
        app = get_object_or_404(Application, pk=request.POST['app_id'])
        ver = get_object_or_404(AppVersion, pk=request.POST['version_id'])
        tasks.compatibility_check.delay(fu.pk, app.guid, ver.version)
    else:
        tasks.validator.delay(fu.pk)
    if (waffle.flag_is_active(request, 'form-errors-in-validation')
        and addon_slug):
        return redirect('mkt.developers.upload_detail_for_addon',
                        addon_slug, fu.pk)
    elif is_standalone:
        return redirect('mkt.developers.standalone_upload_detail', fu.pk)
    else:
        return redirect('mkt.developers.upload_detail', fu.pk, 'json')


@login_required
@post_required
@json_view
def upload_manifest(request):
    form = forms.NewManifestForm(request.POST)
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

    v = reverse('mkt.developers.json_file_validation',
                args=[addon.slug, file.id])
    return jingo.render(request, 'developers/validation.html',
                        dict(validate_url=v, filename=file.filename,
                             timestamp=file.created,
                             addon=addon))


@dev_required(allow_editors=True)
def bulk_compat_result(request, addon_id, addon, result_id):
    qs = ValidationResult.objects.exclude(completed=None)
    result = get_object_or_404(qs, pk=result_id)
    job = result.validation_job
    revalidate_url = reverse('mkt.developers.json_bulk_compat_result',
                             args=[addon.slug, result.id])
    return _compat_result(request, revalidate_url,
                          job.application, job.target_version,
                          for_addon=result.file.version.addon,
                          validated_filename=result.file.filename,
                          validated_ts=result.completed)


def _compat_result(request, revalidate_url, target_app, target_version,
                   validated_filename=None, validated_ts=None,
                   for_addon=None):
    app_trans = dict((g, unicode(a.pretty)) for g, a in amo.APP_GUIDS.items())
    ff_versions = (AppVersion.objects.filter(application=amo.FIREFOX.id,
                                             version_int__gte=4000000000000)
                   .values_list('application', 'version')
                   .order_by('version_int'))
    tpl = 'https://developer.mozilla.org/en/Firefox_%s_for_developers'
    change_links = dict()
    for app, ver in ff_versions:
        major = ver[0]  # 4.0b3 -> 4
        change_links['%s %s' % (amo.APP_IDS[app].guid, ver)] = tpl % major
    return jingo.render(request, 'developers/validation.html',
                        dict(validate_url=revalidate_url,
                             filename=validated_filename,
                             timestamp=validated_ts,
                             target_app=target_app,
                             target_version=target_version,
                             addon=for_addon,
                             result_type='compat',
                             app_trans=app_trans,
                             version_change_links=change_links))


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
@csrf_view_exempt
@post_required
@dev_required(allow_editors=True)
def json_bulk_compat_result(request, addon_id, addon, result_id):
    qs = ValidationResult.objects.exclude(completed=None)
    result = get_object_or_404(qs, pk=result_id)
    if result.task_error:
        return make_validation_result({'validation': '',
                                       'error': result.task_error})
    else:
        validation = json.loads(result.validation)
        return make_validation_result(dict(validation=validation, error=None))


@json_view
def json_upload_detail(request, upload, addon_slug=None):
    addon = None
    if addon_slug:
        addon = get_object_or_404(Addon, slug=addon_slug)
    result = upload_validation_context(request, upload, addon=addon)
    plat_exclude = []
    if result['validation']:
        if result['validation']['errors'] == 0:
            try:
                pkg = parse_addon(upload, addon=addon)
                app_ids = set([a.id for a in pkg.get('apps', [])])
                supported_platforms = []
                for app in (amo.MOBILE, amo.ANDROID):
                    if app.id in app_ids:
                        supported_platforms.extend(amo.MOBILE_PLATFORMS.keys())
                        app_ids.remove(app.id)
                if len(app_ids):
                    # Targets any other non-mobile app:
                    supported_platforms.extend(amo.DESKTOP_PLATFORMS.keys())
                s = amo.SUPPORTED_PLATFORMS.keys()
                plat_exclude = set(s) - set(supported_platforms)
                plat_exclude = [str(p) for p in plat_exclude]
            except django_forms.ValidationError, exc:
                if waffle.flag_is_active(request,
                                         'form-errors-in-validation'):
                    m = []
                    for msg in exc.messages:
                        # Simulate a validation error so the UI displays
                        # it as such
                        m.append({'type': 'error',
                                  'message': msg, 'tier': 1})
                    v = make_validation_result(
                            dict(error='', validation=dict(messages=m)))
                    return json_view.error(v)
                else:
                    log.error("XPI parsing error, ignored: %s" % exc)

    result['platforms_to_exclude'] = plat_exclude
    return result


def upload_validation_context(request, upload, addon_slug=None, addon=None,
                                       url=None):
    if addon_slug and not addon:
        addon = get_object_or_404(Addon, slug=addon_slug)
    if not settings.VALIDATE_ADDONS:
        upload.task_error = ''
        upload.validation = json.dumps({'errors': 0, 'messages': [],
                                        'metadata': {}, 'notices': 0,
                                        'warnings': 0})
        upload.save()

    validation = json.loads(upload.validation) if upload.validation else ""
    if not url:
        if (waffle.flag_is_active(request, 'form-errors-in-validation')
            and addon):
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


@dev_required(webapp=True)
def addons_section(request, addon_id, addon, section, editable=False,
                   webapp=False):
    basic = AppFormBasic if webapp else addon_forms.AddonFormBasic
    models = {'basic': basic,
              'media': addon_forms.AddonFormMedia,
              'details': AppFormDetails,
              'support': addon_forms.AddonFormSupport,
              'technical': addon_forms.AddonFormTechnical}

    if section not in models:
        raise http.Http404()

    tags = previews = restricted_tags = []
    cat_form = dependency_form = device_type_form = None

    if section == 'basic':
        tags = addon.tags.not_blacklisted().values_list('tag_text', flat=True)
        cat_form = addon_forms.CategoryFormSet(request.POST or None,
                                               addon=addon, request=request)
        restricted_tags = addon.tags.filter(restricted=True)
        if webapp and waffle.switch_is_active('marketplace'):
            device_type_form = addon_forms.DeviceTypeForm(request.POST or None,
                                                          addon=addon)

    elif section == 'media':
        previews = forms.PreviewFormSet(request.POST or None,
            prefix='files', queryset=addon.previews.all())

    elif section == 'technical':
        if not webapp:
            dependency_form = forms.DependencyFormSet(request.POST or None,
                queryset=addon.addons_dependencies.all(), addon=addon,
                prefix='dependencies')

    # Get the slug before the form alters it to the form data.
    valid_slug = addon.app_slug
    if editable:
        if request.method == 'POST':
            form = models[section](request.POST, request.FILES,
                                   instance=addon, request=request)
            if form.is_valid() and (not previews or previews.is_valid()):
                addon = form.save(addon)

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
            if dependency_form:
                if dependency_form.is_valid():
                    dependency_form.save()
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
            'dependency_form': dependency_form,
            'valid_slug': valid_slug,
            'device_type_form': device_type_form}

    return jingo.render(request,
                        'developers/addons/edit/%s.html' % section, data)


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
                   for p in addon.previews.all())
    return {'overall': icons and previews,
            'icons': icons,
            'previews': previews}


@json_view
def ajax_upload_image(request, upload_type):
    errors = []
    upload_hash = ''

    if 'upload_image' in request.FILES:
        upload_preview = request.FILES['upload_image']
        upload_preview.seek(0)

        upload_hash = uuid.uuid4().hex
        loc = os.path.join(settings.TMP_PATH, upload_type, upload_hash)

        with storage.open(loc, 'wb') as fd:
            for chunk in upload_preview:
                fd.write(chunk)
        is_icon = upload_type == 'icon'

        check = amo.utils.ImageCheck(upload_preview)
        if (not check.is_image() or
            upload_preview.content_type not in amo.IMG_TYPES):
            if is_icon:
                errors.append(_('Icons must be either PNG or JPG.'))
            else:
                errors.append(_('Images must be either PNG or JPG.'))

        if check.is_animated():
            if is_icon:
                errors.append(_('Icons cannot be animated.'))
            else:
                errors.append(_('Images cannot be animated.'))

        max_size = None
        if is_icon:
            max_size = settings.MAX_ICON_UPLOAD_SIZE

        if max_size and upload_preview.size > max_size:
            if is_icon:
                errors.append(_('Please use images smaller than %dMB.') % (
                    max_size / 1024 / 1024 - 1))
    else:
        errors.append(_('There was an error uploading your preview.'))

    if errors:
        upload_hash = ''

    return {'upload_hash': upload_hash, 'errors': errors}


@dev_required
def upload_image(request, addon_id, addon, upload_type):
    return ajax_upload_image(request, upload_type)


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
    POST = request.POST
    if 'locale' in POST and POST['locale'] != addon.default_locale:
        addon.remove_locale(POST['locale'])
        return http.HttpResponse()
    return http.HttpResponseBadRequest()


# You can only request one of the new review tracks.
REQUEST_REVIEW = (amo.STATUS_PUBLIC, amo.STATUS_LITE)


@dev_required
@post_required
def request_review(request, addon_id, addon, status):
    status_req = int(status)
    if status_req not in addon.can_request_review():
        return http.HttpResponseBadRequest()
    elif status_req == amo.STATUS_PUBLIC:
        if addon.status == amo.STATUS_LITE:
            new_status = amo.STATUS_LITE_AND_NOMINATED
        else:
            new_status = amo.STATUS_NOMINATED
    elif status_req == amo.STATUS_LITE:
        if addon.status in (amo.STATUS_PUBLIC, amo.STATUS_LITE_AND_NOMINATED):
            new_status = amo.STATUS_LITE
        else:
            new_status = amo.STATUS_UNREVIEWED

    addon.update(status=new_status)
    msg = {amo.STATUS_LITE: _('Preliminary Review Requested.'),
           amo.STATUS_PUBLIC: _('Full Review Requested.')}
    messages.success(request, msg[status_req])
    amo.log(amo.LOG.CHANGE_STATUS, addon.get_status_display(), addon)
    return redirect(addon.get_dev_url('versions'))


def docs(request, doc_name=None, doc_page=None):
    filename = ''

    all_docs = {'getting-started': [],
                'reference': [],
                'policies': ['agreement'],
                'case-studies': [],
                'how-to': []}

    if waffle.switch_is_active('marketplace'):
        all_docs['marketplace'] = ['voluntary']

    if doc_name and doc_name in all_docs:
        filename = '%s.html' % doc_name
        if doc_page and doc_page in all_docs[doc_name]:
            filename = '%s-%s.html' % (doc_name, doc_page)
        else:
            # TODO: Temporary until we have a `policies` docs index.
            filename = None

    if not filename:
        return redirect('mkt.developers.index')

    return jingo.render(request, 'developers/docs/%s' % filename)
