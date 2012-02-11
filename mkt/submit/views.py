from django.shortcuts import redirect
from django.views.decorators.vary import vary_on_headers

import jingo

from users.models import UserProfile
from . import forms


def submit(request):
    """Determine which step to redirect user to."""
    # If dev has already agreed, continue to next step.
    user = UserProfile.objects.get(pk=request.user.id)
    if user.read_dev_agreement:
        return redirect('submit.describe')
    else:
        return redirect('submit.terms')


@vary_on_headers('X-PJAX')
def terms(request):
    # If dev has already agreed, continue to next step.
    user = UserProfile.objects.get(pk=request.user.id)
    if user.read_dev_agreement:
        return redirect('submit.describe')
    agreement_form = forms.DevAgreementForm({'read_dev_agreement': True},
                                            instance=request.amo_user)
    ctx = {
        'is_pjax': request.META.get('HTTP_X_PJAX'),
        'agreement_form': agreement_form,
    }
    if request.POST and agreement_form.is_valid():
        agreement_form.save()
        if ctx['is_pjax']:
            return describe(request)
        else:
            return redirect('submit.describe', HTTP_X_PJAX=True)
    return jingo.render(request, 'submit/terms.html', ctx)


@vary_on_headers('X-PJAX')
def describe(request):
    return jingo.render(request, 'submit/describe.html', {
        'is_pjax': request.META.get('HTTP_X_PJAX'),
    })


def media(request):
    return jingo.render(request, 'submit/media.html')


def done(request):
    return jingo.render(request, 'submit/done.html')
