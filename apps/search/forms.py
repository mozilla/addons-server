import collections

from django import forms
from django.forms.util import ErrorDict

from tower import ugettext as _, ugettext_lazy as _lazy

import amo
from amo import helpers
from applications.models import AppVersion

types = (amo.ADDON_ANY, amo.ADDON_EXTENSION, amo.ADDON_THEME, amo.ADDON_DICT,
         amo.ADDON_SEARCH, amo.ADDON_LPAPP, amo.ADDON_PERSONA,)

updated = (
    ('', _lazy(u'Any time')),
    ('1 day ago', _lazy(u'Past Day')),
    ('1 week ago', _lazy(u'Past Week')),
    ('1 month ago', _lazy(u'Past Month')),
    ('3 months ago', _lazy(u'Past 3 Months')),
    ('6 months ago', _lazy(u'Past 6 Months')),
    ('1 year ago', _lazy(u'Past Year')),
)

# TODO(davedash): Remove 'name' altogether if nobody complains.
sort_by = (
    ('', _lazy(u'Keyword Match')),
    ('newest', _lazy(u'Newest', 'advanced_search_form_newest')),
    ('updated', _lazy(u'Updated', 'advanced_search_form_updated')),
    ('name', _lazy(u'Name', 'advanced_search_form_name')),
    ('averagerating', _lazy(u'Rating', 'advanced_search_form_rating')),
    ('weeklydownloads', _lazy(u'Popularity',
                              'advanced_search_form_popularity')),
)

collection_sort_by = (
    ('weekly', _lazy('Most popular this week')),
    ('monthly', _lazy('Most popular this month')),
    ('all', _lazy('Most popular all time')),
    ('rating', _lazy('Highest Rated')),
    ('newest', _lazy('Newest')),
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
    amo.SUNBIRD: tuplize(amo.SUNBIRD.min_display_version),
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
    for type_ in (amo.ADDON_DICT, amo.ADDON_SEARCH, amo.ADDON_THEME):
        sub.append(_Cat(0, amo.ADDON_TYPES[type_], 0, type_))
    sub.extend(helpers.sidebar(app)[0])
    sub = [('%s,%s' % (a.type, a.id), a.name) for a in
           sorted(sub, key=lambda x: (x.weight, x.name))]
    top_level = [('all', _('all add-ons')),
                 ('collections', _('all collections')), ]

    if amo.ADDON_PERSONA in app.types:
        top_level += (('personas', _('all personas')),)

    return top_level[:1] + sub + top_level[1:], top_level


def SearchForm(request):

    current_app = request.APP or amo.FIREFOX
    search_groups, top_level = get_search_groups(current_app)

    class _SearchForm(forms.Form):
        q = forms.CharField(required=False)

        cat = forms.ChoiceField(choices=search_groups, required=False)

        # TODO(davedash): Remove when we're done with remora.
        appid = forms.TypedChoiceField(label=_('Application'),
            choices=[(app.id, app.pretty) for app in amo.APP_USAGE],
            required=False, coerce=int)

        # This gets replaced by a <select> with js.
        lver = forms.ChoiceField(
                label=_(u'{0} Version').format(unicode(current_app.pretty)),
                choices=get_app_versions(current_app), required=False)

        atype = forms.TypedChoiceField(label=_('Type'),
            choices=[(t, amo.ADDON_TYPE[t]) for t in types], required=False,
            coerce=int, empty_value=amo.ADDON_ANY)

        pid = forms.TypedChoiceField(label=_('Platform'),
                choices=[(p[0], p[1].name) for p in amo.PLATFORMS.iteritems()
                         if p[1] != amo.PLATFORM_ANY], required=False,
                coerce=int, empty_value=amo.PLATFORM_ALL.id)

        lup = forms.ChoiceField(label=_('Last Updated'), choices=updated,
                                required=False)

        sort = forms.ChoiceField(label=_('Sort By'), choices=sort_by,
                                 required=False)

        pp = forms.TypedChoiceField(label=_('Per Page'),
               choices=zip(per_page, per_page), required=False, coerce=int,
               empty_value=per_page[0])

        advanced = forms.BooleanField(widget=forms.HiddenInput, required=False)
        tag = forms.CharField(widget=forms.HiddenInput, required=False)
        page = forms.IntegerField(widget=forms.HiddenInput, required=False)

        # Attach these to the form for usage in the template.
        top_level_cat = dict(top_level)

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
    sortby = forms.ChoiceField(label=_lazy('Sort By'),
                               choices=collection_sort_by,
                               initial='weekly', required=False)
    page = forms.IntegerField(widget=forms.HiddenInput, required=False)

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

