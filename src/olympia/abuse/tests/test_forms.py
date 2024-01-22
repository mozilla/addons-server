from django.core.exceptions import ImproperlyConfigured
from django.test.client import RequestFactory

import pytest

from olympia.abuse.forms import AbuseAppealEmailForm, AbuseAppealForm


def test_abuse_appeal_email_form_no_request_or_expected_email_raises():
    with pytest.raises(KeyError):
        AbuseAppealEmailForm()

    request = RequestFactory().get('/')
    with pytest.raises(KeyError):
        AbuseAppealEmailForm(request=request)

    with pytest.raises(ImproperlyConfigured):
        AbuseAppealEmailForm(request=request, expected_email=None)

    AbuseAppealEmailForm(request=request, expected_email='foo@example.com')


def test_abuse_appeal_email_form_no_request_raises():
    with pytest.raises(KeyError):
        AbuseAppealForm()

    request = RequestFactory().get('/')
    AbuseAppealForm(request=request)
