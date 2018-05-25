# -*- coding: utf-8 -*-
from django.template.loader import render_to_string
from django.utils.translation import ugettext_lazy as _

import jinja2

from olympia.addons.models import Addon
from olympia.bandwagon.models import (
    Collection, MonthlyPick as MonthlyPickModel)
from olympia.legacy_api.views import addon_filter
from olympia.versions.compare import version_int
from olympia.lib.cache import cached


# The global registry for promo modules.  Managed through PromoModuleMeta.
registry = {}


class PromoModuleMeta(type):
    """Adds new PromoModules to the module registry."""

    def __new__(mcs, name, bases, dict_):
        cls = type.__new__(mcs, name, bases, dict_)
        if 'abstract' not in dict_:
            registry[cls.slug] = cls
        return cls


class PromoModule(object):
    """
    Base class for promo modules in the discovery pane.

    Subclasses should assign a slug and define render().  The slug is only used
    internally, so it doesn't have to really be a slug.
    """
    __metaclass__ = PromoModuleMeta
    abstract = True
    slug = None

    def __init__(self, request, platform, version):
        self.request = request
        self.platform = platform
        self.version = version
        self.compat_mode = 'strict'
        if version_int(self.version) >= version_int('10.0'):
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
        return {'pick': monthly_pick, 'module_context': 'discovery'}


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

        return cached(
            fetch_and_filter_addons,
            'collections-promo-get-addons:{}'.format(repr(kw)))

    def render(self, module_context='discovery'):
        if module_context == 'home':
            self.platform = 'ALL'
            self.version = None
        context = {
            'promo': self,
            'module_context': module_context,
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

    def context(self, **kwargs):
        return {'module_context': 'discovery'}


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
