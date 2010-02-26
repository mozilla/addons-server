import collections
import itertools

from django import forms

from l10n import ugettext as _

import amo
from amo import helpers
from applications.models import AppVersion


types = (amo.ADDON_ANY, amo.ADDON_EXTENSION, amo.ADDON_THEME,
         amo.ADDON_DICT, amo.ADDON_SEARCH, amo.ADDON_LPAPP)

platforms = (amo.PLATFORM_ANY, amo.PLATFORM_BSD, amo.PLATFORM_LINUX,
             amo.PLATFORM_MAC, amo.PLATFORM_SUN, amo.PLATFORM_WIN)

updated = (
    ('', _('Any time')),
    ('1 day ago', _('Past Day')),
    ('1 week ago', _('Past Week')),
    ('1 month ago', _('Past Month')),
    ('3 months ago', _('Past 3 Months')),
    ('6 months ago', _('Past 6 Months')),
    ('1 year ago', _('Past Year')),
)

sort_by = (
    ('', _('Keyword Match')),
    ('newest', _('Newest', 'advanced_search_form_newest')),
    ('name', _('Name', 'advanced_search_form_name')),
    ('averagerating', _('Rating', 'advanced_search_form_rating')),
    ('weeklydownloads', _('Popularity', 'advanced_search_form_popularity')),
)

per_page = (20, 50, 100)

# These releases were so minor that we don't want to search for them.
skip_versions = collections.defaultdict(list)
skip_versions[amo.FIREFOX] = ((1, 4), (3, 1))

min_version = collections.defaultdict(lambda: (0, 0))
min_version.update({
    amo.FIREFOX: (1, 0),
    amo.THUNDERBIRD: (1, 0),
    amo.SEAMONKEY: (1, 0),
    amo.SUNBIRD: (0, 2),
})


def get_app_versions():
    rv = {}
    for id, app in amo.APP_IDS.items():
        min_ver, skip = min_version[app], skip_versions[app]
        versions = [(a.major, a.minor1) for a in
                    AppVersion.objects.filter(application=id)]
        groups = itertools.groupby(sorted(versions))
        strings = ['%s.%s' % v for v, group in groups
                   if v >= min_ver and v not in skip]
        rv[id] = [(s, s) for s in strings] + [(_('Any'), 'any')]
    return rv


# Fake categories to slip some add-on types into the search groups.
_Cat = collections.namedtuple('Cat', 'id name weight type_id')

def get_search_groups(app):
    sub = []
    for type_ in (amo.ADDON_DICT, amo.ADDON_SEARCH, amo.ADDON_THEME):
        sub.append(_Cat(0, amo.ADDON_TYPES[type_], 0, type_))
    sub.extend(helpers.sidebar(app)[0])
    sub = [('%s,%s' % (a.type_id, a.id), a.name) for a in
           sorted(sub, key=lambda x: (x.weight, x.name))]
    top_level =  [('all', _('all add-ons')),
                  ('collections', _('all collections')),
                  ('personas', _('all personas'))]
    return top_level[:1] + sub + top_level[1:], top_level


def SearchForm(request):

    search_groups, top_level = get_search_groups(request.APP or amo.FIREFOX)

    class _SearchForm(forms.Form):
        q = forms.CharField()

        cat = forms.ChoiceField(choices=search_groups)

        appid = forms.ChoiceField(label=_('Application'),
            choices=[(app.id, app.pretty) for app in amo.APP_USAGE])

        # This gets replaced by a <select> with js.
        lver = forms.CharField(label=_('Version'))

        atype = forms.ChoiceField(label=_('Type'),
            choices=[(t, amo.ADDON_TYPE[t]) for t in types])

        # TODO(jbalogh): why not use the platform id?
        pid = forms.ChoiceField(label=_('Platform'),
            choices=[(idx, amo.PLATFORMS[p]) for idx, p in enumerate(platforms)])

        lup = forms.ChoiceField(label=_('Last Updated'), choices=updated)

        sort = forms.ChoiceField(label=_('Sort By'), choices=sort_by)

        pp = forms.ChoiceField(label=_('Per Page'),
                               choices=zip(per_page, per_page))

        advanced = forms.BooleanField(widget=forms.HiddenInput)

        # Attach these to the form for usage in the template.
        app_versions = get_app_versions()
        top_level_cat = dict(top_level)

        # TODO(jbalogh): when we start using this form for zamboni search, it
        # should check that the appid and lver match up using app_versions.

    d = request.GET.copy()
    if 'appid' not in d and request.APP:
        d['appid'] = request.APP.id
    return _SearchForm(d)
