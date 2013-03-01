from django import forms
from django.forms.util import ErrorDict

from tower import ugettext_lazy as _lazy

from addons.models import Category
import amo


STATUS_CHOICES = []
for status in amo.WEBAPPS_UNLISTED_STATUSES + (amo.STATUS_PUBLIC,):
    s = amo.STATUS_CHOICES_API[status]
    STATUS_CHOICES.append((s, s))

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

DEVICE_CHOICES_IDS = {
    'desktop': amo.DEVICE_DESKTOP.id,
    'mobile': amo.DEVICE_MOBILE.id,
    'tablet': amo.DEVICE_TABLET.id,
    'gaia': amo.DEVICE_GAIA.id,
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

    def __init__(self, *args, **kw):
        self.request = kw.pop('request', None)
        super(AppSearchForm, self).__init__(*args, **kw)

    def clean_cat(self):
        cat = self.cleaned_data.get('cat')
        try:
            return int(cat)
        except ValueError:
            return None

    def clean_device(self):
        """Ignore the user. Respect the User-Agent."""
        device = self.cleaned_data.get('device') or None
        if self.request.MOBILE:
            device = 'mobile'
        if self.request.TABLET:
            device = 'tablet'
        if self.request.GAIA:
            device = 'gaia'
        return device

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
    q = forms.CharField(required=False)
    status = forms.ChoiceField(required=False, choices=STATUS_CHOICES)
    sort = forms.ChoiceField(required=False, choices=LISTING_SORT_CHOICES)
    cat = forms.TypedChoiceField(required=False, coerce=int, empty_value=None,
                                 choices=[])
    device = forms.ChoiceField(required=False, choices=DEVICE_CHOICES)
    premium_types = forms.MultipleChoiceField(
        required=False,
        choices=tuple((p, p) for p in amo.ADDON_PREMIUM_API.values()))
    app_type = forms.ChoiceField(
        required=False,
        choices=tuple((t, t) for t in amo.ADDON_WEBAPP_TYPES.values()))

    def __init__(self, *args, **kw):
        super(ApiSearchForm, self).__init__(*args, **kw)
        CATS = (Category.objects.filter(type=amo.ADDON_WEBAPP, weight__gte=0)
                         .values_list('id', flat=True))
        self.fields['cat'].choices = [(pk, pk) for pk in CATS]

    def clean_status(self):
        status = self.cleaned_data['status']
        return amo.STATUS_CHOICES_API_LOOKUP.get(status, amo.STATUS_PUBLIC)

    def clean_premium_types(self):
        pt_ids = []
        for pt in self.cleaned_data.get('premium_types'):
            pt_id = amo.ADDON_PREMIUM_API_LOOKUP.get(pt)
            if pt_id is not None:
                pt_ids.append(pt_id)
        if pt_ids:
            return pt_ids
        return []

    def clean_app_type(self):
        app_type = amo.ADDON_WEBAPP_TYPES_LOOKUP.get(
            self.cleaned_data.get('app_type'))
        if app_type:
            return app_type
