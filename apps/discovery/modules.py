import caching.base as caching
import jingo
import jinja2
from tower import ugettext_lazy as _

from addons.models import Addon
from api.views import addon_filter
from bandwagon.models import Collection
from .models import BlogCacheRyf


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

    def render(self):
        raise NotImplementedError


class TemplatePromo(PromoModule):
    abstract = True
    template = None

    def context(self):
        return {}

    def render(self):
        r = jingo.render_to_string(self.request, self.template, self.context())
        return jinja2.Markup(r)


class RockYourFirefox(TemplatePromo):
    slug = 'Rock Your Firefox'
    template = 'discovery/modules/ryf.html'

    def context(self):
        return {'ryf': BlogCacheRyf.objects.get()}


class MonthlyPick(TemplatePromo):
    slug = 'Monthly Pick'
    template = 'discovery/modules/monthly.html'

    def context(self):
        return {'addon': Addon.objects.get(id=197224)}


class GoMobile(TemplatePromo):
    slug = 'Go Mobile'
    template = 'discovery/modules/go-mobile.html'


class CollectionPromo(PromoModule):
    abstract = True
    template = 'discovery/modules/collection.html'
    title = None
    subtitle = None
    limit = 3

    def __init__(self, *args, **kw):
        super(CollectionPromo, self).__init__(*args, **kw)
        self.collection = Collection.objects.get(pk=self.pk)

    def get_addons(self):
        addons = self.collection.addons.all()
        kw = dict(addon_type='ALL', limit=self.limit, app=self.request.APP,
                  platform=self.platform, version=self.version, shuffle=True)
        f = lambda: addon_filter(addons, **kw)
        return caching.cached_with(addons, f, repr(kw))

    def render(self):
        c = dict(promo=self, addons=self.get_addons())
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
    pk = 10
    id = 'starter'
    title = _(u'First time with Add-ons?')
    subtitle = _(u' Not to worry, here are three to get started.')


class Fx4Collection(CollectionPromo):
    slug = 'Fx4 Collection'
    pk = 10
    id = 'fx4-collection'
    title = _(u'Firefox 4 Collection')
    subtitle = _(u'Here are some great add-ons for Firefox 4.')


class StPatricksPersonas(CollectionPromo):
    slug = 'St. Pat Personas'
    pk = 10
    id = 'st-patricks'
    title = jinja2.Markup(_(u'St. Patrick&rsquo;s Day Personas'))
    subtitle = jinja2.Markup(
        _(u'Decorate your browser to celebrate St. Patrick&rsquo;s Day.'))
