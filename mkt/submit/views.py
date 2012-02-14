from django.shortcuts import redirect

import jingo

from amo.decorators import login_required
from users.models import UserProfile
from . import forms


@login_required
def submit(request):
    """Determine which step to redirect user to."""
    # If dev has already agreed, continue to next step.
    user = UserProfile.objects.get(pk=request.user.id)
    if user.read_dev_agreement:
        return redirect('submit.describe')
    else:
        return redirect('submit.terms')


@login_required
def terms(request):
    # If dev has already agreed, continue to next step.
    # TODO: When this code is finalized, use request.amo_user instead.
    user = UserProfile.objects.get(pk=request.user.id)
    if user.read_dev_agreement:
        return redirect('submit.describe')
    agreement_form = forms.DevAgreementForm({'read_dev_agreement': True},
                                            instance=user)
    if request.POST and agreement_form.is_valid():
        agreement_form.save()
        return redirect('submit.describe')
    return jingo.render(request, 'submit/terms.html', {
        'agreement_form': agreement_form,
    })


def describe(request):
    return jingo.render(request, 'submit/describe.html')


def media(request):
    return jingo.render(request, 'submit/media.html')


def done(request):
    return jingo.render(request, 'submit/done.html')
