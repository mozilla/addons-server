from django import forms

from tower import ugettext_lazy as _lazy

from addons.models import Category
import amo

from mkt.api.forms import SluggableModelChoiceField


ADDON_CHOICES = [(k, k) for k in amo.MKT_ADDON_TYPES_API.keys()]

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

APP_TYPE_CHOICES = [
    ('', _lazy(u'Any App Type')),
    ('hosted', _lazy(u'Hosted')),
    ('packaged', _lazy(u'Packaged')),
    ('privileged', _lazy(u'Privileged packaged app')),
]

PREMIUM_CHOICES = [
    ('free', _lazy(u'Free')),
    ('free-inapp', _lazy(u'Free with In-app')),
    ('premium', _lazy(u'Premium')),
    ('premium-inapp', _lazy(u'Premium with In-app')),
    ('other', _lazy(u'Other System for In-App')),
]

DEVICE_CHOICES = [
    ('', _lazy(u'Any Device Type')),
    ('desktop', _lazy(u'Desktop')),
    ('mobile', _lazy(u'Mobile')),
    ('tablet', _lazy(u'Tablet')),
    ('firefoxos', _lazy(u'Firefox OS')),
]

DEVICE_CHOICES_IDS = {
    'desktop': amo.DEVICE_DESKTOP.id,
    'mobile': amo.DEVICE_MOBILE.id,
    'tablet': amo.DEVICE_TABLET.id,
    'firefoxos': amo.DEVICE_GAIA.id,
}

# "Relevance" doesn't make sense for Category listing pages.
LISTING_SORT_CHOICES = SORT_CHOICES[1:]
FREE_LISTING_SORT_CHOICES = [(k, v) for k, v in LISTING_SORT_CHOICES
                             if k != 'price']


SEARCH_PLACEHOLDERS = {'apps': _lazy(u'Search for apps')}


class SimpleSearchForm(forms.Form):
    """Powers the search box on every page."""
    q = forms.CharField(required=False)
    cat = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_cat(self):
        return self.data.get('cat', 'all')

    def placeholder(self, txt=None):
        return txt or SEARCH_PLACEHOLDERS['apps']


class ApiSearchForm(forms.Form):
    q = forms.CharField(
        required=False, label=_lazy(u'Search'),
        widget=forms.TextInput(attrs={'autocomplete': 'off',
                                      'placeholder': _lazy(u'Search')}))
    type = forms.ChoiceField(required=False, choices=ADDON_CHOICES,
                             label=_lazy(u'Add-on type'))
    cat = SluggableModelChoiceField(
        queryset=Category.objects.filter(type=amo.ADDON_WEBAPP),
        sluggable_to_field_name='slug', required=False)
    device = forms.ChoiceField(
        required=False, choices=DEVICE_CHOICES, label=_lazy(u'Device type'))
    premium_types = forms.MultipleChoiceField(
        widget=forms.CheckboxSelectMultiple(), required=False,
        label=_lazy(u'Premium types'), choices=PREMIUM_CHOICES)
    # TODO: Make some fancy `MultipleCommaSeperatedChoiceField` field.
    app_type = forms.MultipleChoiceField(required=False,
        widget=forms.CheckboxSelectMultiple(),
        label=_lazy(u'App type'), choices=APP_TYPE_CHOICES)
    manifest_url = forms.CharField(required=False, label=_lazy('Manifest URL'))
    offline = forms.NullBooleanField(required=False,
        label=_lazy('Works offline'))
    languages = forms.CharField(required=False,
        label=_lazy('Supported languages'))

    sort = forms.MultipleChoiceField(required=False,
        choices=LISTING_SORT_CHOICES)
    # TODO: Drop this back to a reasonable value when we do pagination.
    limit = forms.IntegerField(required=False, widget=forms.HiddenInput())

    def __init__(self, *args, **kw):
        super(ApiSearchForm, self).__init__(*args, **kw)

        # Clients understand cats via slugs, Zamboni thinks of them via IDs.
        self.fields['cat'].choices = (
            Category.objects.filter(type=amo.ADDON_WEBAPP, weight__gte=0)
            .values_list('slug', 'id'))

        self.initial.update({
            'type': 'app',
            'status': 'pending',
            'limit': 200,
        })

    def clean_cat(self):
        if self.cleaned_data['cat']:
            return self.cleaned_data['cat'].slug

    def clean_type(self):
            return amo.MKT_ADDON_TYPES_API.get(self.cleaned_data['type'],
                                               amo.ADDON_WEBAPP)

    def clean_premium_types(self):
        """After cleaned, return a list of ints for the constants."""
        pt_ids = []
        for pt in self.cleaned_data.get('premium_types'):
            pt_id = amo.ADDON_PREMIUM_API_LOOKUP.get(pt)
            if pt_id is not None:
                pt_ids.append(pt_id)
        return pt_ids

    def clean_app_type(self):
        """After cleaned, return a list of ints for the constants."""
        at_ids = []
        for at in self.cleaned_data.get('app_type'):
            at_id = amo.ADDON_WEBAPP_TYPES_LOOKUP.get(at)
            if at_id is not None:
                at_ids.append(at_id)
        return at_ids
