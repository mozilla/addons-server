import caching.base as caching
import jingo
from tower import ugettext_lazy as _

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


class RockYourFirefox(PromoModule):
    slug = 'Rock Your Firefox'

    def render(self):
        return jingo.render_to_string(
            self.request, 'discovery/modules/ryf.html',
            {'ryf': BlogCacheRyf.objects.get()})


class CollectionPromo(PromoModule):
    abstract = True
    template = 'discovery/modules/collection.html'
    title = None
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
        c = dict(title=self.title, collection=self.collection,
                 cls=self.cls, addons=self.get_addons())
        return jingo.render_to_string(self.request, self.template, c)


class ShoppingCollection(CollectionPromo):
    slug = 'Shopping Collection'
    pk = 16651
    cls = 'shopping'
    title = _('Save cash and have fun with these shopping add-ons')


class WebdevCollection(CollectionPromo):
    slug = 'Webdev Collection'
    pk = 10
    cls = 'webdev'
    title = _('Build the perfect website')


class TesterCollection(CollectionPromo):
    slug = 'Firefox Tester Tools'
    pk = 82266
    cls = 'tester'
    title = _('Help test Firefox with these tools')
