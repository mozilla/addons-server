import collections

from django import forms
from django.conf import settings
from django.forms.util import ErrorDict

from tower import ugettext as _, ugettext_lazy as _lazy

import amo
from amo import helpers
from applications.models import AppVersion
from search.utils import floor_version

sort_by = (
    ('', _lazy(u'Keyword Match')),
    ('updated', _lazy(u'Updated', 'advanced_search_form_updated')),
    ('newest', _lazy(u'Created', 'advanced_search_form_newest')),
    ('weeklydownloads', _lazy(u'Downloads')),
    ('users', _lazy(u'Users')),
    ('averagerating', _lazy(u'Rating', 'advanced_search_form_rating')),
)

collection_sort_by = (
    ('weekly', _lazy(u'Most popular this week')),
    ('monthly', _lazy(u'Most popular this month')),
    ('all', _lazy(u'Most popular all time')),
    ('rating', _lazy(u'Highest Rated')),
    ('created', _lazy(u'Newest')),
)
es_collection_sort_by = collection_sort_by + (
    ('updated', _lazy(u'Recently Updated')),
    ('name', _lazy(u'Name')),
)

per_page = (20, 50, )

tuplize = lambda x: divmod(int(x * 10), 10)

# These releases were so minor that we don't want to search for them.
skip_versions = collections.defaultdict(list)
skip_versions[amo.FIREFOX] = [tuplize(v) for v in amo.FIREFOX.exclude_versions]

min_version = collections.defaultdict(lambda: (0, 0))
min_version.update({
    amo.FIREFOX: tuplize(amo.FIREFOX.min_display_version),
    amo.THUNDERBIRD: tuplize(amo.THUNDERBIRD.min_display_version),
    amo.SEAMONKEY: tuplize(amo.SEAMONKEY.min_display_version),
})


def get_app_versions(app):
    appversions = AppVersion.objects.filter(application=app.id)
    min_ver, skip = min_version[app], skip_versions[app]
    versions = [(a.major, a.minor1) for a in appversions]
    strings = ['%s.%s' % v for v in sorted(set(versions), reverse=True)
               if v >= min_ver and v not in skip]

    return [('any', _('Any'))] + zip(strings, strings)


# Fake categories to slip some add-on types into the search groups.
_Cat = collections.namedtuple('Cat', 'id name weight type')


def get_search_groups(app):
    sub = []

    types_ = [t for t in (amo.ADDON_DICT, amo.ADDON_SEARCH, amo.ADDON_THEME)
                if t in app.types]

    for type_ in types_:
        sub.append(_Cat(0, amo.ADDON_TYPES[type_], 0, type_))
    sub.extend(helpers.sidebar(app)[0])
    sub = [('%s,%s' % (a.type, a.id), a.name) for a in
           sorted(sub, key=lambda x: (x.weight, x.name))]
    top_level = [('all', _('all add-ons')),
                 ('collections', _('all collections')), ]

    if amo.ADDON_PERSONA in app.types:
        top_level += (('personas', _('all personas')),)

    return top_level[:1] + sub + top_level[1:], top_level


SEARCH_CHOICES = (
    ('all', _lazy(u'search for add-ons')),
    ('collections', _lazy(u'search for collections')),
    ('personas', _lazy(u'search for personas')),
    ('apps', _lazy(u'search for apps')))


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


def SearchForm(request):

    current_app = request.APP or amo.FIREFOX
    search_groups, top_level = get_search_groups(current_app)

    class _SearchForm(SimpleSearchForm):

        cat = forms.ChoiceField(choices=search_groups, required=False)

        # This gets replaced by a <select> with js.
        lver = forms.ChoiceField(
            # L10n: {0} is the name of an app. Ex: Firefox
            label=_lazy(u'{0} Version').format(unicode(current_app.pretty)),
            choices=get_app_versions(current_app), required=False)
        appver = forms.CharField(required=False)

        atype = forms.TypedChoiceField(label=_lazy(u'Type'),
            choices=[(t, amo.ADDON_TYPE[t])
                     for t in amo.get_addon_search_types()],
            required=False, coerce=int, empty_value=amo.ADDON_ANY)

        pid = forms.TypedChoiceField(label=_lazy(u'Platform'),
            choices=[(p[0], p[1].name) for p in amo.PLATFORMS.iteritems()
                     if p[1] != amo.PLATFORM_ANY], required=False,
            coerce=int, empty_value=amo.PLATFORM_ANY.id)
        platform = forms.ChoiceField(required=False,
            choices=[[p.shortname, p.id] for p in amo.PLATFORMS.values()])

        sort = forms.ChoiceField(label=_lazy(u'Sort By'), choices=sort_by,
                                 required=False)

        pp = forms.TypedChoiceField(label=_lazy(u'Per Page'),
           choices=zip(per_page, per_page), required=False, coerce=int,
           empty_value=per_page[0])

        advanced = forms.BooleanField(widget=forms.HiddenInput, required=False)
        tag = forms.CharField(widget=forms.HiddenInput, required=False)
        page = forms.IntegerField(widget=forms.HiddenInput, required=False)

        # Attach these to the form for usage in the template.
        top_level_cat = dict(top_level)

        def clean_platform(self):
            p = self.cleaned_data.get('platform')
            choices = dict(self.fields['platform'].choices)
            return choices.get(p)

        # TODO(jbalogh): when we start using this form for zamboni search, it
        # should check that the appid and lver match up using app_versions.
        def clean(self):
            d = self.cleaned_data
            raw = self.data

            # Set some defaults
            if not d.get('appid'):
                d['appid'] = request.APP.id

            # Since not all categories are listed in this form, we use the raw
            # data.
            if 'cat' in raw:
                if ',' in raw['cat']:
                    try:
                        d['atype'], d['cat'] = map(int, raw['cat'].split(','))
                    except ValueError:
                        d['cat'] = None
                elif raw['cat'] == 'all':
                    d['cat'] = None

            if 'page' not in d or not d['page'] or d['page'] < 1:
                d['page'] = 1
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

    d = request.GET.copy()

    return _SearchForm(d)


class SecondarySearchForm(forms.Form):
    q = forms.CharField(widget=forms.HiddenInput, required=False)
    cat = forms.CharField(widget=forms.HiddenInput)
    pp = forms.CharField(widget=forms.HiddenInput, required=False)
    sort = forms.ChoiceField(label=_lazy(u'Sort By'),
                             choices=collection_sort_by,
                             initial='weekly', required=False)
    page = forms.IntegerField(widget=forms.HiddenInput, required=False)

    def __init__(self, *args, **kw):
        super(SecondarySearchForm, self).__init__(*args, **kw)
        # This adds the "Name" sort option for ES results.
        self.fields['sort'].choices = es_collection_sort_by

    def clean_pp(self):
        d = self.cleaned_data['pp']

        try:
            return int(d)
        except:
            return per_page[0]

    def clean(self):
        d = self.cleaned_data

        if not d.get('pp'):
            d['pp'] = per_page[0]

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
    #('price', helpers.loc(u'Price')),
    ('updated', _lazy(u'Recently Updated')),
    ('hotness', _lazy(u'Up & Coming')),
)

APP_SORT_CHOICES = (
    (None, _lazy(u'Relevance')),
    ('downloads', _lazy(u'Weekly Downloads')),
    ('rating', _lazy(u'Top Rated')),
    ('price', helpers.loc(u'Price')),
    # --
    ('name', _lazy(u'Name')),
    ('created', _lazy(u'Newest')),
)


class ESSearchForm(forms.Form):
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
        self.webapp = self.addon_type == amo.ADDON_WEBAPP
        if self.webapp:
            self.fields['atype'].choices = [
                (amo.ADDON_WEBAPP, amo.ADDON_TYPE[amo.ADDON_WEBAPP])
            ]
            self.data['atype'] = amo.ADDON_WEBAPP
            self.sort_choices = APP_SORT_CHOICES

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
