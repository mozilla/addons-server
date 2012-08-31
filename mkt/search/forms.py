from django import forms
from django.forms.util import ErrorDict

from tower import ugettext_lazy as _lazy

from addons.models import Category
import amo


SORT_CHOICES = [
    (None, _lazy(u'Relevance')),
    ('popularity', _lazy(u'Popularity')),
    ('downloads', _lazy(u'Weekly Downloads')),
    ('rating', _lazy(u'Top Rated')),
    ('price', _lazy(u'Price')),
    ('created', _lazy(u'Newest')),
]

FREE_SORT_CHOICES = [(k, v) for k, v in SORT_CHOICES if k != 'price']

PRICE_CHOICES = [
    (None, _lazy(u'All')),
    ('free', _lazy(u'Free')),
    ('paid', _lazy(u'Paid')),
]

DEVICE_CHOICES = [
    (None, _lazy(u'Any Device')),
    ('desktop', _lazy(u'Desktop')),
    ('mobile', _lazy(u'Mobile')),
    ('tablet', _lazy(u'Tablet')),
]

# TODO: Forgo the `DeviceType` model in favor of constants (see bug 727235).
DEVICE_CHOICES_IDS = {
    'desktop': 1,
    'mobile': 2,
    'tablet': 3,
}

# "Relevance" doesn't make sense for Category listing pages.
LISTING_SORT_CHOICES = SORT_CHOICES[1:]
FREE_LISTING_SORT_CHOICES = [(k, v) for k, v in LISTING_SORT_CHOICES
                             if k != 'price']

# Placeholder.
SEARCH_PLACEHOLDERS = {'apps': _lazy(u'Search for apps')}


class SimpleSearchForm(forms.Form):
    """Powers the search box on every page."""
    q = forms.CharField(required=False)
    cat = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_cat(self):
        return self.data.get('cat', 'all')

    def placeholder(self, txt=None):
        return txt or SEARCH_PLACEHOLDERS['apps']


class AppSearchForm(forms.Form):
    q = forms.CharField(required=False)
    cat = forms.CharField(required=False)
    sort = forms.ChoiceField(required=False, choices=SORT_CHOICES)
    price = forms.ChoiceField(required=False, choices=PRICE_CHOICES)
    device = forms.ChoiceField(required=False, choices=DEVICE_CHOICES)

    def clean_cat(self):
        cat = self.cleaned_data.get('cat')
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


class AppListForm(AppSearchForm):
    sort = forms.ChoiceField(required=False, choices=LISTING_SORT_CHOICES)


class ApiSearchForm(forms.Form):
    # Like App search form, but just filtering on categories for now
    # and bit more strict about the filtering.
    sort = forms.ChoiceField(required=False, choices=LISTING_SORT_CHOICES)
    cat = forms.TypedChoiceField(required=False, coerce=int, empty_value=None,
                                 choices=[])

    def __init__(self, *args, **kw):
        super(ApiSearchForm, self).__init__(*args, **kw)
        CATS = (Category.objects.filter(type=amo.ADDON_WEBAPP, weight__gte=0)
                         .values_list('id', flat=True))
        self.fields['cat'].choices = [(pk, pk) for pk in CATS]
