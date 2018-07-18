from django import forms
from django.forms.utils import ErrorDict
from django.utils.translation import ugettext_lazy as _

from olympia import amo
from olympia.search.utils import floor_version


PER_PAGE = 20

SEARCH_CHOICES = (
    ('all', _(u'search for add-ons')),
    ('themes', _(u'search for themes')),
    ('apps', _(u'search for apps')),
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
        return self.choices.get(txt or self.clean_cat(), self.choices['all'])


SORT_CHOICES = (
    (None, _(u'Relevance')),
    ('users', _(u'Most Users')),
    ('rating', _(u'Top Rated')),
    ('created', _(u'Newest')),
    # --
    ('name', _(u'Name')),
    ('downloads', _(u'Weekly Downloads')),
    ('updated', _(u'Recently Updated')),
    ('hotness', _(u'Up & Coming')),
)


class ESSearchForm(forms.Form):
    q = forms.CharField(required=False)
    tag = forms.CharField(required=False)
    platform = forms.CharField(required=False)
    appver = forms.CharField(required=False)
    atype = forms.TypedChoiceField(
        required=False, coerce=int, choices=amo.ADDON_TYPES.iteritems()
    )
    cat = forms.CharField(required=False)
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
