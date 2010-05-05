import jingo
from tower import ugettext_lazy as _

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

    def render(self, request):
        raise NotImplementedError


class RockYourFirefox(PromoModule):
    slug = 'Rock Your Firefox'

    def render(self, request):
        return jingo.render_to_string(request, 'discovery/modules/ryf.html',
                                      {'ryf': BlogCacheRyf.objects.get()})


class CollectionPromo(PromoModule):
    abstract = True
    template = 'discovery/modules/collection.html'
    title = None

    def __init__(self):
        super(CollectionPromo, self).__init__()
        self.collection = Collection.objects.get(pk=self.pk)

    def render(self, request):
        c = dict(title=self.title, collection=self.collection,
                 addons=self.collection.addons.all())
        return jingo.render_to_string(request, self.template, c)


class ShoppingCollection(CollectionPromo):
    slug = 'Shopping Collection'
    pk = 16651
    title = _('Save cash and have fun with these shopping add-ons')


class WebdevCollection(CollectionPromo):
    slug = 'Webdev Collection'
    pk = 10
    title = _('Build the perfect website')


class SportsCollectoin(CollectionPromo):
    slug = 'Sports Collection'
    pk = 3217
    title = _('Get the latest scores and higlights')
