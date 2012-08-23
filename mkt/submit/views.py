from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.forms.models import model_to_dict
from django.shortcuts import redirect
from django.utils.translation.trans_real import to_language

import commonware.log
import jingo
import waffle

import amo
import paypal
from amo.decorators import login_required
from amo.helpers import absolutify, urlparams
from amo.urlresolvers import reverse
from addons.forms import DeviceTypeForm
from addons.models import Addon, AddonUser
from lib.pay_server import client
from market.models import AddonPaymentData
from files.models import Platform
from users.models import UserProfile

from mkt.developers import tasks
from mkt.developers.decorators import dev_required
from mkt.developers.forms import (AppFormMedia, CategoryForm,
                                  PaypalPaymentData, PreviewFormSet)
from mkt.submit.forms import AppDetailsBasicForm, PaypalSetupForm
from mkt.submit.models import AppSubmissionChecklist

from . import forms
from .decorators import read_dev_agreement_required, submit_step


log = commonware.log.getLogger('z.submit')


@login_required
def submit(request):
    """Determine which step to redirect user to."""
    # If dev has already agreed, continue to next step.
    user = UserProfile.objects.get(pk=request.user.id)
    if user.read_dev_agreement:
        if waffle.switch_is_active('allow-packaged-app-uploads'):
            return redirect('submit.app.choose')
        return redirect('submit.app.manifest')
    else:
        return redirect('submit.app.terms')


@login_required
@submit_step('terms')
def terms(request):
    # If dev has already agreed, continue to next step.
    if request.amo_user.read_dev_agreement:
        if waffle.switch_is_active('allow-packaged-app-uploads'):
            return redirect('submit.app.choose')
        return redirect('submit.app.manifest')

    agreement_form = forms.DevAgreementForm(
        request.POST or {'read_dev_agreement': True},
        instance=request.amo_user)
    if request.POST and agreement_form.is_valid():
        agreement_form.save()
        if waffle.switch_is_active('allow-packaged-app-uploads'):
            return redirect('submit.app.choose')
        return redirect('submit.app.manifest')
    return jingo.render(request, 'submit/terms.html', {
        'step': 'terms',
        'agreement_form': agreement_form,
    })


@login_required
@read_dev_agreement_required
@submit_step('manifest')
def choose(request):
    if not waffle.switch_is_active('allow-packaged-app-uploads'):
        return redirect('submit.app.manifest')
    return jingo.render(request, 'submit/choose.html', {
        'step': 'manifest',
    })


@login_required
@read_dev_agreement_required
@submit_step('manifest')
@transaction.commit_on_success
def manifest(request):
    form = forms.NewWebappForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        addon = Addon.from_upload(
            form.cleaned_data['upload'],
            [Platform.objects.get(id=amo.PLATFORM_ALL.id)])

        if addon.has_icon_in_manifest():
            # Fetch the icon, do polling.
            addon.update(icon_type='image/png')
            tasks.fetch_icon.delay(addon)
        else:
            # In this case there is no need to do any polling.
            addon.update(icon_type='')

        AddonUser(addon=addon, user=request.amo_user).save()
        # Checking it once. Checking it twice.
        AppSubmissionChecklist.objects.create(addon=addon, terms=True,
                                              manifest=True)

        return redirect('submit.app.details', addon.app_slug)

    return jingo.render(request, 'submit/manifest.html', {
        'step': 'manifest',
        'form': form,
    })


@login_required
@read_dev_agreement_required
@submit_step('manifest')
def package(request):
    form = forms.NewWebappForm(request.POST or None, is_packaged=True)
    if request.method == 'POST' and form.is_valid():
        addon = Addon.from_upload(
            form.cleaned_data['upload'],
            [Platform.objects.get(id=amo.PLATFORM_ALL.id)])
        addon.get_latest_file().update(is_packaged=True)

        if addon.has_icon_in_manifest():
            # Fetch the icon, do polling.
            addon.update(icon_type='image/png')
            tasks.fetch_icon.delay(addon)
        else:
            # In this case there is no need to do any polling.
            addon.update(icon_type='')

        AddonUser(addon=addon, user=request.amo_user).save()
        AppSubmissionChecklist.objects.create(addon=addon, terms=True,
                                              manifest=True)

        return redirect('submit.app.details', addon.app_slug)

    return jingo.render(request, 'submit/upload.html', {
        'form': form,
        'step': 'manifest',
    })


@dev_required
@submit_step('details')
def details(request, addon_id, addon):
    # Name, Slug, Summary, Description, Privacy Policy,
    # Homepage URL, Support URL, Support Email.
    form_basic = AppDetailsBasicForm(request.POST or None, instance=addon,
                                     request=request)
    form_cats = CategoryForm(request.POST or None, product=addon,
                             request=request)
    form_devices = DeviceTypeForm(request.POST or None, addon=addon)
    form_icon = AppFormMedia(request.POST or None, request.FILES or None,
                             instance=addon, request=request)
    form_previews = PreviewFormSet(request.POST or None, prefix='files',
                                   queryset=addon.get_previews())

    # For empty webapp-locale (or no-locale) fields that have
    # form-locale values, duplicate them to satisfy the requirement.
    form_locale = request.COOKIES.get("current_locale", "")
    app_locale = to_language(addon.default_locale)
    for name, value in request.POST.items():
        if value:
            if name.endswith(form_locale):
                basename = name[:-len(form_locale)]
            else:
                basename = name + '_'
            othername = basename + app_locale
            if not request.POST.get(othername, None):
                request.POST[othername] = value
    forms = {
        'form_basic': form_basic,
        'form_devices': form_devices,
        'form_cats': form_cats,
        'form_icon': form_icon,
        'form_previews': form_previews,
    }

    if request.POST and all(f.is_valid() for f in forms.itervalues()):
        addon = form_basic.save(addon)
        form_devices.save(addon)
        form_cats.save()
        form_icon.save(addon)
        for preview in form_previews.forms:
            preview.save(addon)

        checklist = AppSubmissionChecklist.objects.get(addon=addon)

        if waffle.switch_is_active('disable-payments'):
            checklist.update(details=True, payments=True)
            addon.mark_done()
            return redirect('submit.app.done', addon.app_slug)
        else:
            checklist.update(details=True)
            return redirect('submit.app.payments', addon.app_slug)

    ctx = {
        'step': 'details',
        'addon': addon,
    }
    ctx.update(forms)
    return jingo.render(request, 'submit/details.html', ctx)


@dev_required
@submit_step('payments')
def payments(request, addon_id, addon):
    form = forms.PremiumTypeForm(request.POST or None)
    if request.POST and form.is_valid():
        addon.update(premium_type=form.cleaned_data['premium_type'])

        if addon.premium_type in [amo.ADDON_PREMIUM, amo.ADDON_PREMIUM_INAPP]:
            return redirect('submit.app.payments.upsell', addon.app_slug)
        if addon.premium_type == amo.ADDON_FREE_INAPP:
            return redirect('submit.app.payments.paypal', addon.app_slug)

        AppSubmissionChecklist.objects.get(addon=addon).update(payments=True)
        addon.mark_done()
        return redirect('submit.app.done', addon.app_slug)
    return jingo.render(request, 'submit/payments.html', {
                        'step': 'payments',
                        'addon': addon,
                        'form': form
                        })


@dev_required
@submit_step('payments')
def payments_upsell(request, addon_id, addon):
    form = forms.UpsellForm(request.POST or None, request=request,
                            extra={'addon': addon,
                                   'amo_user': request.amo_user})
    if request.POST and form.is_valid():
        form.save()
        return redirect('submit.app.payments.paypal', addon.app_slug)
    return jingo.render(request, 'submit/payments-upsell.html', {
                        'step': 'payments',
                        'addon': addon,
                        'form': form
                        })


@dev_required
@submit_step('payments')
def payments_paypal(request, addon_id, addon):
    form = PaypalSetupForm(request.POST or None)
    if request.POST and form.is_valid():
        existing = form.cleaned_data['business_account']
        if existing == 'later':
            # We'll have a premium or similar account with no PayPal id
            # at this point.
            (AppSubmissionChecklist.objects.get(addon=addon)
                                           .update(payments=True))
            return redirect('submit.app.done', addon.app_slug)
        if existing != 'yes':
            # Go create an account.
            # TODO: this will either become the API or something some better
            # URL for the future.
            return redirect(settings.PAYPAL_CGI_URL)

        if waffle.flag_is_active(request, 'solitude-payments'):
            obj = client.create_seller_paypal(addon)
            client.patch_seller_paypal(pk=obj['resource_pk'],
                         data={'paypal_id': form.cleaned_data['email']})

        addon.update(paypal_id=form.cleaned_data['email'])
        return redirect('submit.app.payments.bounce', addon.app_slug)
    return jingo.render(request, 'submit/payments-paypal.html', {
                        'step': 'payments',
                        'addon': addon,
                        'form': form
                        })


@dev_required
@submit_step('payments')
def payments_bounce(request, addon_id, addon):
    dest = 'submission'
    perms = ['REFUND', 'ACCESS_BASIC_PERSONAL_DATA',
             'ACCESS_ADVANCED_PERSONAL_DATA']
    if waffle.flag_is_active(request, 'solitude-payments'):
        url = addon.get_dev_url('acquire_refund_permission')
        url = absolutify(urlparams(url, dest=dest))
        result = client.post_permission_url(data={'scope': perms, 'url': url})
        paypal_url = result['token']
    #TODO(solitude): remove these
    else:
        paypal_url = paypal.get_permission_url(addon, dest, perms)

    return jingo.render(request, 'submit/payments-bounce.html', {
                        'step': 'payments',
                        'paypal_url': paypal_url,
                        'addon': addon
                        })


@dev_required
@submit_step('payments')
def payments_confirm(request, addon_id, addon):
    data = {}
    # TODO(solitude): remove all references to AddonPaymentData.
    if waffle.flag_is_active(request, 'solitude-payments'):
        data = client.get_seller_paypal_if_exists(addon) or {}

    adp, created = AddonPaymentData.objects.safer_get_or_create(addon=addon)
    if not data:
        data = model_to_dict(adp)

    form = PaypalPaymentData(request.POST or data)
    if request.method == 'POST' and form.is_valid():
        if waffle.flag_is_active(request, 'solitude-payments'):
            # TODO(solitude): when the migration of data is completed, we
            # will be able to remove this.
            pk = client.create_seller_for_pay(addon)
            client.patch_seller_paypal(pk=pk, data=form.cleaned_data)

        # TODO(solitude): remove this.
        adp.update(**form.cleaned_data)
        AppSubmissionChecklist.objects.get(addon=addon).update(payments=True)
        addon.mark_done()
        return redirect('submit.app.done', addon.app_slug)

    return jingo.render(request, 'submit/payments-confirm.html', {
                        'step': 'payments',
                        'addon': addon,
                        'form': form
                        })


@dev_required
def done(request, addon_id, addon):
    # No submit step forced on this page, we don't really care.
    return jingo.render(request, 'submit/done.html', {
                        'step': 'done', 'addon': addon
                        })


@dev_required
def resume(request, addon_id, addon):
    try:
        # If it didn't go through the app submission
        # checklist. Don't die. This will be useful for
        # creating apps with an API later.
        step = addon.appsubmissionchecklist.get_next()
    except ObjectDoesNotExist:
        step = None

    # If there is not a Free app and there's no PayPal id, they
    # clicked "later" in the submission flow.
    if not step and addon.premium_type != amo.ADDON_FREE:
        return redirect(addon.get_dev_url('paypal_setup'))

    return _resume(addon, step)


def _resume(addon, step):
    if step:
        if step in ['terms', 'manifest']:
            return redirect('submit.app.%s' % step)
        return redirect(reverse('submit.app.%s' % step,
                                args=[addon.app_slug]))

    return redirect(addon.get_dev_url('edit'))
