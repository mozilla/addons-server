from django.shortcuts import redirect

import jingo

import amo
from amo.decorators import login_required
from addons.forms import DeviceTypeForm
from addons.models import Addon, AddonUser
from mkt.developers import tasks
from mkt.developers.decorators import dev_required
from mkt.submit.forms import AppDetailsBasicForm
from mkt.submit.models import AppSubmissionChecklist
from files.models import Platform
from users.models import UserProfile
from . import forms
from .decorators import submit_step


@login_required
def submit(request):
    """Determine which step to redirect user to."""
    # If dev has already agreed, continue to next step.
    user = UserProfile.objects.get(pk=request.user.id)
    if user.read_dev_agreement:
        # TODO: Have decorator redirect to next step.
        return redirect('submit.app.manifest')
    else:
        return redirect('submit.app.terms')


@login_required
@submit_step('terms')
def terms(request):
    # If dev has already agreed, continue to next step.
    # TODO: When this code is finalized, use request.amo_user instead.
    user = UserProfile.objects.get(pk=request.user.id)
    if user.read_dev_agreement:
        # TODO: Have decorator redirect to next step.
        return redirect('submit.app.manifest')

    agreement_form = forms.DevAgreementForm({'read_dev_agreement': True},
                                            instance=user)
    if request.POST and agreement_form.is_valid():
        agreement_form.save()
        return redirect('submit.app.manifest')
    return jingo.render(request, 'submit/terms.html', {
        'step': 'terms',
        'agreement_form': agreement_form,
    })


@login_required
@submit_step('manifest')
def manifest(request):
    # TODO: Have decorator handle the redirection.
    user = UserProfile.objects.get(pk=request.user.id)
    if not user.read_dev_agreement:
        # And we start back at one...
        return redirect('submit.app')

    form = forms.NewWebappForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data

        plats = [Platform.objects.get(id=amo.PLATFORM_ALL.id)]
        addon = Addon.from_upload(data['upload'], plats)
        tasks.fetch_icon.delay(addon)
        AddonUser(addon=addon, user=request.amo_user).save()

        # Checking it once. Checking it twice.
        AppSubmissionChecklist.objects.create(addon=addon, terms=True,
                                              manifest=True)

        return redirect('submit.app.details', addon.app_slug)

    return jingo.render(request, 'submit/manifest.html', {
        'step': 'manifest',
        'form': form,
    })


@dev_required
@submit_step('details')
def details(request, addon_id, addon):
    # Name, Slug, Summary, Description, Privacy Policy.
    form_basic = AppDetailsBasicForm(request.POST or None, instance=addon,
                                     request=request)

    # Device Types.
    form_devices = DeviceTypeForm(request.POST or None, addon=addon)

    forms = {
        'form_basic': form_basic,
        'form_devices': form_devices,
    }

    if request.POST and all(f.is_valid() for f in forms.values()):
        addon = form_basic.save(addon)
        AppSubmissionChecklist.objects.get(addon=addon).update(details=True)
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
        # Save this to the addon, eg:
        addon.update(premium_type=form.cleaned_data['premium_type'])
        AppSubmissionChecklist.objects.get(addon=addon).update(payments=True)
        return redirect('submit.app.done', addon.app_slug)
    return jingo.render(request, 'submit/payments.html', {
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
