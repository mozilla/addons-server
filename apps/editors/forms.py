from datetime import timedelta

from django import forms

import happyforms
from tower import ugettext_lazy as _lazy

import amo

ACTION_FILTERS = (('', ''), ('approved', _lazy('Approved reviews')),
                  ('deleted', _lazy('Deleted reviews')))

ACTION_DICT = dict(approved=amo.LOG.APPROVE_REVIEW,
                   deleted=amo.LOG.DELETE_REVIEW)


class EventLogForm(happyforms.Form):
    start = forms.DateField(required=False,
                            label=_lazy(u'View entries between'))
    end = forms.DateField(required=False,
                          label=_lazy(u'and'))
    filter = forms.ChoiceField(required=False, choices=ACTION_FILTERS,
                               label=_lazy(u'Filter by type/action'))

    def clean(self):
        data = self.cleaned_data
        # We want this to be inclusive of the end date.
        if data['end']:
            data['end'] += timedelta(days=1)

        if data['filter']:
            data['filter'] = ACTION_DICT[data['filter']]
        return data
