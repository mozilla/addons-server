import requests

from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _


def validate_criteria(value):
    url = "https://addons.mozilla.org/api/v4/addons/{}"
    response = requests.get(url.format(value))
    results = response.json()
    if response.status_code == 404:
        raise ValidationError(
            _("404 Not Found - Invalid criteria"),
            params={'value': value},)
    if response.status_code == 400:
        raise ValidationError(
            _(results[0]),
            params={'value': value},)
    if response.status_code == 200 and 'results' in results:
        if len(results['results']) == 0:
            raise ValidationError(
                _("Check parameters in criteria - e.g., 'type'"),
                params={'value': value},)
