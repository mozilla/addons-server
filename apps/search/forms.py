from django import forms
from django.conf import settings
from django.forms.util import ErrorDict

import happyforms
from tower import ugettext_lazy as _lazy

import amo
from amo import helpers
from search.utils import floor_version

collection_sort_by = (
    ('weekly', _lazy(u'Most popular this week')),
    ('monthly', _lazy(u'Most popular this month')),
    ('all', _lazy(u'Most popular all time')),
    ('rating', _lazy(u'Highest Rated')),
    ('created', _lazy(u'Newest')),
    ('updated', _lazy(u'Recently Updated')),
    ('name', _lazy(u'Name')),
)

PER_PAGE = 20

SEARCH_CHOICES = (
    ('all', _lazy(u'search for add-ons')),
    ('collections', _lazy(u'search for collections')),
    ('themes', _lazy(u'search for themes')),
    ('apps', _lazy(u'search for apps'))
)


class SimpleSearchForm(forms.Form):
    """Powers the search box on every page."""
    q = forms.CharField(required=False)
    cat = forms.CharField(required=False, widget=forms.HiddenInput)
    appver = forms.CharField(required=False, widget=forms.HiddenInput)
    platform = forms.CharField(required=False, widget=forms.HiddenInput)
    choices = dict(SEARCH_CHOICES)

    def clean_cat(self):
        return self.data.get('cat', 'all')

    def placeholder(self, txt=None):
        if settings.APP_PREVIEW:
            return self.choices['apps']
        return self.choices.get(txt or self.clean_cat(), self.choices['all'])


class SecondarySearchForm(forms.Form):
    q = forms.CharField(widget=forms.HiddenInput, required=False)
    cat = forms.CharField(widget=forms.HiddenInput)
    pp = forms.CharField(widget=forms.HiddenInput, required=False)
    sort = forms.ChoiceField(label=_lazy(u'Sort By'), required=False,
                             choices=collection_sort_by, initial='weekly')
    page = forms.IntegerField(widget=forms.HiddenInput, required=False)

    def clean_pp(self):
        try:
            return int(self.cleaned_data.get('pp'))
        except TypeError:
            return PER_PAGE

    def clean(self):
        d = self.cleaned_data
        if not d.get('pp'):
            d['pp'] = PER_PAGE
        return d

    def full_clean(self):
        """
        Cleans all of self.data and populates self._errors and
        self.cleaned_data.
        Does not remove cleaned_data if there are errors.
        """
        self._errors = ErrorDict()
        if not self.is_bound:  # Stop further processing.
            return
        self.cleaned_data = {}
        # If the form is permitted to be empty, and none of the form data
        # has changed from the initial data, short circuit any validation.
        if self.empty_permitted and not self.has_changed():
            return
        self._clean_fields()
        self._clean_form()


SORT_CHOICES = (
    (None, _lazy(u'Relevance')),
    ('users', _lazy(u'Most Users')),
    ('rating', _lazy(u'Top Rated')),
    ('created', _lazy(u'Newest')),
    # --
    ('name', _lazy(u'Name')),
    ('downloads', _lazy(u'Weekly Downloads')),
    ('updated', _lazy(u'Recently Updated')),
    ('hotness', _lazy(u'Up & Coming')),
)

class ESSearchForm(happyforms.Form):
    q = forms.CharField(required=False)
    tag = forms.CharField(required=False)
    platform = forms.CharField(required=False)
    appver = forms.CharField(required=False)
    atype = forms.TypedChoiceField(required=False, coerce=int,
                                   choices=amo.ADDON_TYPES.iteritems())
    cat = forms.CharField(required=False)
    price = forms.CharField(required=False)
    sort = forms.CharField(required=False)

    def __init__(self, *args, **kw):
        self.addon_type = kw.pop('type', None)
        super(ESSearchForm, self).__init__(*args, **kw)
        self.sort_choices = SORT_CHOICES

    def clean_appver(self):
        return floor_version(self.cleaned_data.get('appver'))

    def clean_sort(self):
        sort = self.cleaned_data.get('sort')
        return sort if sort in dict(self.sort_choices) else None

    def clean_cat(self):
        cat = self.cleaned_data.get('cat')
        if ',' in cat:
            try:
                self.cleaned_data['atype'], cat = map(int, cat.split(','))
            except ValueError:
                return None
        else:
            try:
                return int(cat)
            except ValueError:
                return None

    def full_clean(self):
        """
        Cleans self.data and populates self._errors and self.cleaned_data.

        Does not remove cleaned_data if there are errors.
        """
        self._errors = ErrorDict()
        if not self.is_bound:  # Stop further processing.
            return
        self.cleaned_data = {}
        # If the form is permitted to be empty, and none of the form data
        # has changed from the initial data, short circuit any validation.
        if self.empty_permitted and not self.has_changed():
            return
        self._clean_fields()
        self._clean_form()
