from django import forms

import happyforms
from tower import ugettext_lazy as _lazy


INTERVAL_CHOICES = (
    # Elasticsearch supports minute and hour but we don't.
    ('day', _lazy('Day')),
    ('week', _lazy('Week')),
    ('month', _lazy('Month')),
    ('quarter', _lazy('Quarter')),
    ('year', _lazy('Year')),
)


DATE_INPUT_FORMATS = ('%Y-%m-%d', '%Y%m%d')


class StatsForm(happyforms.Form):
    start = forms.DateField(required=True, input_formats=DATE_INPUT_FORMATS)
    end = forms.DateField(required=True, input_formats=DATE_INPUT_FORMATS)
    interval = forms.ChoiceField(required=True, choices=INTERVAL_CHOICES,
                                 initial='day')
