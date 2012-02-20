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
        return redirect('submit.app')
    return jingo.render(request, 'submit/manifest.html', {'step': 'manifest'})


@login_required
def details(request):
    return jingo.render(request, 'submit/details.html', {'step': 'details'})


@login_required
def payments(request):
    pass


@login_required
def done(request):
    pass
