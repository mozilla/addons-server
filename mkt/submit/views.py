from django.conf import settings

import jingo

import amo
from . import forms


def submit(request):
    #if settings.APP_PREVIEW:
    #    # This can be a permanent redirect when we finalize devhub for apps.
    #    return redirect('devhub.submit_apps.1')
    return jingo.render(request, 'hub/submit.html')


def terms(request):
    agreement_form = forms.DevAgreementForm(request.POST or None,
                                            instance=request.amo_user)
    if agreement_form.is_valid():
        agreement_form.save()
        return redirect('hub.index')
    return jingo.render(request, 'submit/terms.html', {
        'agreement_form': agreement_form,
    })


def describe(request):
    return jingo.render(request, 'hub/describe.html')


def media(request):
    return jingo.render(request, 'hub/media.html')


def done(request):
    return jingo.render(request, 'hub/done.html')
