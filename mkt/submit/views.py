from django.shortcuts import redirect

import jingo

import amo
from amo.decorators import login_required
from addons.models import Addon, AddonUser
from mkt.developers.decorators import dev_required
from mkt.developers.forms import AppFormBasic
from files.models import Platform
from mkt.developers import tasks
from mkt.submit.models import AppSubmissionChecklist
from users.models import UserProfile
from . import forms


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
def details(request, addon_id, addon):
    form_basic = AppFormBasic(request.POST or None, instance=addon,
                              request=request)
    if request.POST and form_basic.is_valid():
        addon = form_basic.save(addon)
        AppSubmissionChecklist.objects.get(addon=addon).update(details=True)
        return redirect('submit.app.payments', addon.app_slug)
    return jingo.render(request, 'submit/details.html', {
        'step': 'details',
        'addon': addon,
        'form_basic': form_basic,
    })


@dev_required
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
    return jingo.render(request, 'submit/done.html', {
                        'step': 'done', 'addon': addon
                        })
