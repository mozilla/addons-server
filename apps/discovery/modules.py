import caching.base as caching
import jingo
import jinja2
from tower import ugettext_lazy as _
import waffle

import amo
from addons.models import Addon
from api.views import addon_filter
from bandwagon.models import Collection, MonthlyPick as MP
from versions.compare import version_int


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
        if (waffle.switch_is_active('d2c-at-the-disco') and
            version_int(self.version) >= version_int('10.0')):
            self.compat_mode = 'ignore'

    def render(self):
        raise NotImplementedError


class TemplatePromo(PromoModule):
    abstract = True
    template = None

    def context(self):
        return {}

    def render(self, **kw):
        c = dict(self.context())
        c.update(kw)
        r = jingo.render_to_string(self.request, self.template, c)
        return jinja2.Markup(r)


class MonthlyPick(TemplatePromo):
    slug = 'Monthly Pick'
    template = 'discovery/modules/monthly.html'

    def context(self):
        try:
            pick = MP.objects.filter(locale=self.request.LANG)[0]
        except IndexError:
            try:
                pick = MP.objects.filter(locale='')[0]
            except IndexError:
                pick = None
        return {'pick': pick, 'module_context': 'discovery'}


class GoMobile(TemplatePromo):
    slug = 'Go Mobile'
    template = 'discovery/modules/go-mobile.html'


class CollectionPromo(PromoModule):
    abstract = True
    template = 'discovery/modules/collection.html'
    title = None
    subtitle = None
    cls = 'promo'
    limit = 3
    linkify_title = False

    def __init__(self, *args, **kw):
        super(CollectionPromo, self).__init__(*args, **kw)
        self.collection = None
        if hasattr(self, 'pk'):
            try:
                self.collection = Collection.objects.get(pk=self.pk)
            except Collection.DoesNotExist:
                pass
        elif (hasattr(self, 'collection_author') and
              hasattr(self, 'collection_slug')):
            try:
                self.collection = Collection.objects.get(
                    author__username=self.collection_author,
                    slug=self.collection_slug)
            except Collection.DoesNotExist:
                pass

    def get_descriptions(self):
        return {}

    def get_addons(self):
        addons = self.collection.addons.filter(status=amo.STATUS_PUBLIC)
        kw = dict(addon_type='ALL', limit=self.limit, app=self.request.APP,
                  platform=self.platform, version=self.version,
                  compat_mode=self.compat_mode)
        f = lambda: addon_filter(addons, **kw)
        return caching.cached_with(addons, f, repr(kw))

    def render(self, module_context='discovery'):
        if module_context == 'home':
            self.platform = 'ALL'
            self.version = None
        c = dict(promo=self, module_context=module_context,
                 descriptions=self.get_descriptions())
        if self.collection:
            c.update(addons=self.get_addons())
        return jinja2.Markup(
            jingo.render_to_string(self.request, self.template, c))


class ShoppingCollection(CollectionPromo):
    slug = 'Shopping Collection'
    pk = 16651
    cls = 'shopping'
    title = _(u'Save cash and have fun with these shopping add-ons')


class WebdevCollection(CollectionPromo):
    slug = 'Webdev Collection'
    pk = 10
    cls = 'webdev'
    title = _(u'Build the perfect website')


class TesterCollection(CollectionPromo):
    slug = 'Firefox Tester Tools'
    pk = 82266
    cls = 'tester'
    title = _(u'Help test Firefox with these tools')


class StarterPack(CollectionPromo):
    slug = 'Starter Pack'
    pk = 153649
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


class Fx4Collection(CollectionPromo):
    slug = 'Fx4 Collection'
    pk = 153651
    id = 'fx4-collection'
    cls = 'promo'
    title = _(u'Firefox 4 Collection')
    subtitle = _(u'Here are some great add-ons for Firefox 4.')
    linkify_title = True


class StPatricksPersonas(CollectionPromo):
    slug = 'St. Pat Themes'
    pk = 666627
    id = 'st-patricks'
    cls = 'promo'
    title = _(u'St. Patrick&rsquo;s Day Themes')
    subtitle = _(u'Decorate your browser to celebrate '
                 'St. Patrick&rsquo;s Day.')


class FxSummerCollection(CollectionPromo):
    slug = 'Fx Summer Collection'
    pk = 2128026
    id = 'fx4-collection'
    cls = 'promo'
    title = _(u'Firefox Summer Collection')
    subtitle = _(u'Here are some great add-ons for Firefox.')


class ThunderbirdCollection(CollectionPromo):
    slug = 'Thunderbird Collection'
    pk = 2128303
    id = 'tb-collection'
    cls = 'promo'
    title = _(u'Thunderbird Collection')
    subtitle = _(u'Here are some great add-ons for Thunderbird.')


class TravelCollection(CollectionPromo):
    slug = 'Travelers Pack'
    pk = 4
    id = 'travel'
    cls = 'promo'
    title = _(u'Sit Back and Relax')
    subtitle = _(u'Add-ons that help you on your travels!')

    def get_descriptions(self):
        return {
            5791: _(u"Displays a country flag depicting the location of the "
                    "current website's server and more."),
            1117: _(u'FoxClocks let you keep an eye on the time around the '
                    'world.'),
            11377: _(u'Automatically get the lowest price when you shop '
                     'online or search for flights.')
        }


class SchoolCollection(CollectionPromo):
    slug = 'School'
    pk = 2133887
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


class NewYearCollection(CollectionPromo):
    slug = 'New Year'
    collection_author, collection_slug = 'mozilla', 'newyear_2012'
    id = 'new-year'
    title = _(u'Add-ons to help you on your way in 2012')


class ValentinesDay(CollectionPromo):
    slug = 'Valentines Day'
    collection_author, collection_slug = 'amoteam', 'va'
    id = 'valentines'
    title = _(u'Love is in the Air')
    subtitle = _(u'Add some romance to your Firefox.')


class Olympics(TemplatePromo):
    slug = 'Olympics'
    template = 'discovery/modules/olympics.html'


class ContestWinners(TemplatePromo):
    slug = 'Contest Winners'
    template = 'discovery/modules/contest-winners.html'

    def render(self, module_context='discovery'):
        # Hide on discovery pane.
        if module_context == 'home':
            return super(ContestWinners, self).render()


class Holiday(TemplatePromo):
    slug = 'Holiday'
    template = 'discovery/modules/holiday.html'

    def render(self, module_context='discovery'):
        # Hide on discovery pane.
        if module_context == 'home':
            return super(Holiday, self).render()
