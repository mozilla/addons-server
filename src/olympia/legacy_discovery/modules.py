# -*- coding: utf-8 -*-
import itertools
import random

from django.template.loader import render_to_string
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import get_language

import jinja2
import six

from olympia import amo
from olympia.addons.models import Addon
from olympia.bandwagon.models import (
    Collection, MonthlyPick as MonthlyPickModel)
from olympia.versions.compare import version_int
from olympia.lib.cache import cache_get_or_set, make_key


# The global registry for promo modules.  Managed through PromoModuleMeta.
registry = {}


# Temporarily here as part of the legacy-api removal
# Simplified a bit by stuff that isn't used
def addon_filter(addons, addon_type, limit, app, platform, version,
                 compat_mode='strict'):
    """
    Filter addons by type, application, app version, and platform.
    Add-ons that support the current locale will be sorted to front of list.
    Shuffling will be applied to the add-ons supporting the locale and the
    others separately.
    Doing this in the database takes too long, so we do it in code and wrap
    it in generous caching.
    """
    APP = app

    def partition(seq, key):
        """Group a sequence based into buckets by key(x)."""
        groups = itertools.groupby(sorted(seq, key=key), key=key)
        return ((k, list(v)) for k, v in groups)

    # Take out personas since they don't have versions.
    groups = dict(partition(addons,
                            lambda x: x.type == amo.ADDON_PERSONA))
    personas, addons = groups.get(True, []), groups.get(False, [])

    platform = platform.lower()
    if platform != 'all' and platform in amo.PLATFORM_DICT:
        def f(ps):
            return pid in ps or amo.PLATFORM_ALL in ps

        pid = amo.PLATFORM_DICT[platform]
        addons = [a for a in addons
                  if f(a.current_version.supported_platforms)]

    if version is not None:
        vint = version_int(version)

        def f_strict(app):
            return app.min.version_int <= vint <= app.max.version_int

        def f_ignore(app):
            return app.min.version_int <= vint

        xs = [(a, a.compatible_apps) for a in addons]

        # Iterate over addons, checking compatibility depending on compat_mode.
        addons = []
        for addon, apps in xs:
            app = apps.get(APP)
            if compat_mode == 'ignore':
                if app and f_ignore(app):
                    addons.append(addon)

    # Put personas back in.
    addons.extend(personas)

    # We prefer add-ons that support the current locale.
    lang = get_language()

    def partitioner(x):
        return x.description is not None and (x.description.locale == lang)

    groups = dict(partition(addons, partitioner))
    good, others = groups.get(True, []), groups.get(False, [])

    random.shuffle(good)
    random.shuffle(others)

    # If limit=0, we return all addons with `good` coming before `others`.
    # Otherwise pad `good` if less than the limit and return the limit.
    if limit > 0:
        if len(good) < limit:
            good.extend(others[:limit - len(good)])
        return good[:limit]
    else:
        good.extend(others)
    return good


class PromoModuleMeta(type):
    """Adds new PromoModules to the module registry."""

    def __new__(mcs, name, bases, dict_):
        cls = type.__new__(mcs, name, bases, dict_)
        if 'abstract' not in dict_:
            registry[cls.slug] = cls
        return cls


class PromoModule(six.with_metaclass(PromoModuleMeta, object)):
    """
    Base class for promo modules in the discovery pane.

    Subclasses should assign a slug and define render().  The slug is only used
    internally, so it doesn't have to really be a slug.
    """
    abstract = True
    slug = None

    def __init__(self, request, platform, version):
        self.request = request
        self.platform = platform
        self.version = version
        self.compat_mode = 'ignore'

    def render(self):
        raise NotImplementedError


class TemplatePromo(PromoModule):
    abstract = True
    template = None

    def context(self, **kwargs):
        return {}

    def render(self, **kw):
        c = dict(self.context(**kw))
        c.update(kw)
        r = render_to_string(self.template, c, request=self.request)
        return jinja2.Markup(r)


class MonthlyPick(TemplatePromo):
    slug = 'Monthly Pick'
    template = 'legacy_discovery/modules/monthly.html'

    def get_pick(self, locale):
        monthly_pick = MonthlyPickModel.objects.filter(locale=locale)[0]
        if not monthly_pick.addon.is_public():
            raise IndexError
        return monthly_pick

    def context(self, **kwargs):
        try:
            monthly_pick = self.get_pick(self.request.LANG)
        except IndexError:
            try:
                # No MonthlyPick available in the user's locale, use '' to get
                # the global pick if there is one.
                monthly_pick = self.get_pick('')
            except IndexError:
                monthly_pick = None
        return {'pick': monthly_pick}


class CollectionPromo(PromoModule):
    abstract = True
    template = 'legacy_discovery/modules/collection.html'
    title = None
    subtitle = None
    cls = 'promo'
    limit = 3
    linkify_title = False

    def __init__(self, *args, **kw):
        super(CollectionPromo, self).__init__(*args, **kw)
        self.collection = None
        try:
            self.collection = Collection.objects.get(
                author__username=self.collection_author,
                slug=self.collection_slug)
        except Collection.DoesNotExist:
            pass

    def get_descriptions(self):
        return {}

    def get_addons(self):
        addons = self.collection.addons.public()
        kw = {
            'addon_type': 'ALL',
            'limit': self.limit,
            'app': self.request.APP,
            'platform': self.platform,
            'version': self.version,
            'compat_mode': self.compat_mode
        }

        def fetch_and_filter_addons():
            return addon_filter(addons, **kw)

        # The cache-key can be very long, let's normalize it to make sure
        # we never hit the 250-char limit of memcached.
        cache_key = make_key(
            'collections-promo-get-addons:{}'.format(repr(kw)),
            normalize=True)
        return cache_get_or_set(cache_key, fetch_and_filter_addons)

    def render(self):
        self.platform = 'ALL'
        self.version = None
        context = {
            'promo': self,
            'descriptions': self.get_descriptions()
        }
        if self.collection:
            context['addons'] = self.get_addons()
        return jinja2.Markup(render_to_string(
            self.template, context, request=self.request))


class ShoppingCollection(CollectionPromo):
    slug = 'Shopping Collection'
    collection_author, collection_slug = 'mozilla', 'onlineshopping'
    cls = 'promo promo-purple'
    title = _(u'Shopping Made Easy')
    subtitle = _(u'Save on your favorite items '
                 u'from the comfort of your browser.')


class WebdevCollection(CollectionPromo):
    slug = 'Webdev Collection'
    collection_author, collection_slug = 'mozilla', 'webdeveloper'
    cls = 'webdev'
    title = _(u'Build the perfect website')


class TestPilot(TemplatePromo):
    slug = 'Test Pilot'
    cls = 'promo promo-test-pilot'
    template = 'legacy_discovery/modules/testpilot.html'


class StarterPack(CollectionPromo):
    slug = 'Starter Pack'
    collection_author, collection_slug = 'mozilla', 'starter'
    id = 'starter'
    cls = 'promo'
    title = _(u'First time with Add-ons?')
    subtitle = _(u'Not to worry, here are three to get started.')

    def get_descriptions(self):
        return {
            2257: _(u'Translate content on the web from and into over 40 '
                    'languages.'),
            1833: _(u"Easily connect to your social networks, and share or "
                    "comment on the page you're visiting."),
            11377: _(u'A quick view to compare prices when you shop online '
                     'or search for flights.')
        }


class StPatricksPersonas(CollectionPromo):
    slug = 'St. Pat Themes'
    collection_author, collection_slug = 'mozilla', 'st-patricks-day'
    id = 'st-patricks'
    cls = 'promo'
    title = _(u'St. Patrick&rsquo;s Day Themes')
    subtitle = _(u'Decorate your browser to celebrate '
                 'St. Patrick&rsquo;s Day.')


class SchoolCollection(CollectionPromo):
    slug = 'School'
    collection_author, collection_slug = 'mozilla', 'back-to-school'
    id = 'school'
    cls = 'promo'
    title = _(u'A+ add-ons for School')
    subtitle = _(u'Add-ons for teachers, parents, and students heading back '
                 'to school.')

    def get_descriptions(self):
        return {
            3456: _(u'Would you like to know which websites you can trust?'),
            2410: _(u'Xmarks is the #1 bookmarking add-on.'),
            2444: _(u'Web page and text translator, dictionary, and more!')
        }


# The add-ons that go with the promo modal. Not an actual PromoModule
class PromoVideoCollection():
    items = (349111, 349155, 349157, 52659, 5579, 252539, 11377, 2257)

    def get_items(self):
        items = Addon.objects.in_bulk(self.items)
        return [items[i] for i in self.items if i in items]


class ValentinesDay(CollectionPromo):
    slug = 'Valentines Day'
    collection_author, collection_slug = 'mozilla', 'bemine'
    id = 'valentines'
    title = _(u'Love is in the Air')
    subtitle = _(u'Add some romance to your Firefox.')


class Fitness(CollectionPromo):
    slug = 'Fitness'
    cls = 'promo promo-yellow'
    collection_author, collection_slug = 'mozilla', 'fitness'
    title = _(u'Get up and move!')
    subtitle = _(u'Install these fitness add-ons to keep you active and '
                 u'healthy.')


class UpAndComing(CollectionPromo):
    slug = 'Up & Coming'
    cls = 'promo promo-blue'
    collection_author, collection_slug = 'mozilla', 'up_coming'
    title = _(u'New &amp; Now')
    subtitle = _(u'Get the latest, must-have add-ons of the moment.')


class Privacy(CollectionPromo):
    slug = 'Privacy Collection'
    cls = 'promo promo-purple'
    collection_author, collection_slug = 'mozilla', 'privacy'
    title = _(u'Worry-free browsing')
    subtitle = _(u'Protect your privacy online with the add-ons in this '
                 u'collection.')


class Featured(CollectionPromo):
    slug = 'Featured Add-ons Collection'
    cls = 'promo promo-yellow'
    collection_author, collection_slug = 'mozilla', 'featured-add-ons'
    title = _(u'Featured Add-ons')
    subtitle = _(u'Great add-ons for work, fun, privacy, productivity&hellip; '
                 u'just about anything!')


class Games(CollectionPromo):
    slug = 'Games!'
    cls = 'promo promo-purple'
    collection_author, collection_slug = 'mozilla', 'games'
    title = _(u'Games!')
    subtitle = _(u'Add more fun to your Firefox. Play dozens of games right '
                 u'from your browser—puzzles, classic arcade, action games, '
                 u'and more!')
    linkify_title = True


class MustHaveMedia(CollectionPromo):
    slug = 'Must-Have Media'
    cls = 'promo promo-purple'
    collection_author, collection_slug = 'mozilla', 'must-have-media'
    title = _(u'Must-Have Media')
    subtitle = _(u'Take better screenshots, improve your online video '
                 u'experience, finally learn how to make a GIF, and other '
                 u'great media tools.')
    linkify_title = True
