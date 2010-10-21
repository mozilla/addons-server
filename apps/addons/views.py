import hashlib
import uuid

from django import http
from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.utils.translation import trans_real as translation
from django.utils import http as urllib

import caching.base as caching
import jingo
from tower import ugettext_lazy as _lazy
from tower import ugettext as _

import amo
from amo.utils import sorted_groupby, randslice
from amo.helpers import absolutify
from amo import urlresolvers
from amo.urlresolvers import reverse
from bandwagon.models import Collection, CollectionFeature, CollectionPromo
from reviews.forms import ReviewForm
from reviews.models import Review
from sharing.views import share as share_redirect
from stats.models import GlobalStat, Contribution
from tags.models import Tag
from translations.query import order_by_translation
from translations.helpers import truncate
from versions.models import Version
from .models import Addon


def author_addon_clicked(f):
    """Decorator redirecting clicks on "Other add-ons by author"."""
    def decorated(request, *args, **kwargs):
        redirect_id = request.GET.get('addons-author-addons-select', None)
        if not redirect_id:
            return f(request, *args, **kwargs)
        try:
            target_id = int(redirect_id)
            return http.HttpResponsePermanentRedirect(reverse(
                'addons.detail', args=[target_id]))
        except ValueError:
            return http.HttpResponseBadRequest('Invalid add-on ID.')
    return decorated


@author_addon_clicked
def addon_detail(request, addon_id):
    """Add-ons details page dispatcher."""
    addon = get_object_or_404(Addon.objects.valid(), id=addon_id)

    if settings.SANDBOX_PANIC and addon.status in amo.UNREVIEWED_STATUSES:
        raise http.Http404

    # addon needs to have a version and be valid for this app.
    if addon.type in request.APP.types:
        if addon.type == amo.ADDON_PERSONA:
            return persona_detail(request, addon)
        else:
            if not addon.current_version:
                raise http.Http404

            return extension_detail(request, addon)
    else:
        # Redirect to an app that supports this type.
        try:
            new_app = [a for a in amo.APP_USAGE if addon.type
                       in a.types][0]
        except IndexError:
            raise http.Http404
        else:
            prefixer = urlresolvers.get_url_prefix()
            prefixer.app = new_app.short
            return http.HttpResponsePermanentRedirect(reverse(
                'addons.detail', args=[addon.id]))


def extension_detail(request, addon):
    """Extensions details page."""

    # if current version is incompatible with this app, redirect
    comp_apps = addon.compatible_apps
    if comp_apps and request.APP not in comp_apps:
        prefixer = urlresolvers.get_url_prefix()
        prefixer.app = comp_apps.keys()[0].short
        return http.HttpResponsePermanentRedirect(reverse(
            'addons.detail', args=[addon.id]))

    # source tracking
    src = request.GET.get('src', 'addondetail')

    # get satisfaction only supports en-US
    lang = translation.to_locale(translation.get_language())
    addon.has_satisfaction = (lang == 'en_US' and
                              addon.get_satisfaction_company)

    # other add-ons from the same author(s)
    author_addons = order_by_translation(addon.authors_other_addons, 'name')

    # tags
    dev_tags, user_tags = addon.tags_partitioned_by_developer

    current_user_tags = []

    if request.user.is_authenticated():
        current_user_tags = user_tags.filter(
                addon_tags__user=request.amo_user)

    # addon recommendations
    recommended = Addon.objects.valid().only_translations().filter(
        recommended_for__addon=addon)[:5]

    # popular collections this addon is part of
    collections = Collection.objects.listed().filter(
        addons=addon, application__id=request.APP.id)

    data = {
        'addon': addon,
        'author_addons': author_addons,

        'src': src,

        'dev_tags': dev_tags,
        'user_tags': user_tags,
        'current_user_tags': current_user_tags,

        'recommendations': recommended,
        'review_form': ReviewForm(),
        'reviews': Review.objects.latest().filter(addon=addon),
        'get_replies': Review.get_replies,

        'collections': collections.order_by('-subscribers')[:3],
    }
    return jingo.render(request, 'addons/details.html', data)


def _category_personas(qs, limit):
    f = lambda: randslice(qs, limit=limit)
    key = 'cat-personas:' + qs.query_key()
    return caching.cached(f, key)


def persona_detail(request, addon):
    """Details page for Personas."""
    persona = addon.persona

    # this persona's categories
    categories = addon.categories.filter(application=request.APP.id)
    if categories:
        qs = Addon.objects.valid().filter(categories=categories[0])
        category_personas = _category_personas(qs, limit=6)
    else:
        category_personas = None

    # tags
    dev_tags, user_tags = addon.tags_partitioned_by_developer

    # other personas from the same author(s)
    author_personas = Addon.objects.valid().filter(
        persona__author=persona.author,
        type=amo.ADDON_PERSONA).exclude(
            pk=addon.pk).select_related('persona')[:3]

    data = {
        'addon': addon,
        'persona': persona,
        'categories': categories,
        'author_personas': author_personas,
        'category_personas': category_personas,
        'dev_tags': dev_tags,
        'user_tags': user_tags,
        'review_form': ReviewForm(),
        'reviews': Review.objects.latest().filter(addon=addon),
        'get_replies': Review.get_replies,
        # Remora users persona.author despite there being a display_username
        'author_gallery': settings.PERSONAS_USER_ROOT % persona.author,
        'search_cat': 'personas',
    }

    return jingo.render(request, 'addons/personas_detail.html', data)


class BaseFilter(object):
    """
    Filters help generate querysets for add-on listings.

    You have to define ``opts`` on the subclass as a sequence of (key, title)
    pairs.  The key is used in GET parameters and the title can be used in the
    view.

    The chosen filter field is combined with the ``base`` queryset using
    the ``key`` found in request.GET.  ``default`` should be a key in ``opts``
    that's used if nothing good is found in request.GET.
    """

    def __init__(self, request, base, key, default):
        self.opts_dict = dict(self.opts)
        self.request = request
        self.base_queryset = base
        self.key = key
        self.field, self.title = self.options(self.request, key, default)
        self.qs = self.filter(self.field)

    def options(self, request, key, default):
        """Get the (option, title) pair we want according to the request."""
        if key in request.GET and request.GET[key] in self.opts_dict:
            opt = request.GET[key]
        else:
            opt = default
        return opt, self.opts_dict[opt]

    def all(self):
        """Get a full mapping of {option: queryset}."""
        return dict((field, self.filter(field)) for field in dict(self.opts))

    def filter(self, field):
        """Get the queryset for the given field."""
        return self._filter(field) & self.base_queryset

    def _filter(self, field):
        return getattr(self, 'filter_%s' % field)()

    def filter_popular(self):
        return (Addon.objects.order_by('-weekly_downloads')
                .with_index(addons='downloads_type_idx'))

    def filter_created(self):
        return (Addon.objects.order_by('-created')
                .with_index(addons='created_type_idx'))

    def filter_updated(self):
        return (Addon.objects.order_by('-last_updated')
                .with_index(addons='last_updated_type_idx'))

    def filter_rating(self):
        return (Addon.objects.order_by('-bayesian_rating')
                .with_index(addons='rating_type_idx'))

    def filter_name(self):
        return order_by_translation(Addon.objects.all(), 'name')


class HomepageFilter(BaseFilter):
    opts = (('featured', _lazy('Featured')),
            ('popular', _lazy('Popular')),
            ('new', _lazy('Recently Added')),
            ('updated', _lazy('Recently Updated')))

    filter_new = BaseFilter.filter_created

    def filter_featured(self):
        # It's ok to cache this for a while...it'll expire eventually.
        return Addon.objects.featured(self.request.APP).order_by('?')


def home(request):
    # Add-ons.
    base = Addon.objects.listed(request.APP).exclude(type=amo.ADDON_PERSONA)
    filter = HomepageFilter(request, base, key='browse', default='featured')
    addon_sets = dict((key, qs[:4]) for key, qs in filter.all().items())

    # Collections.
    q = Collection.objects.filter(listed=True, application=request.APP.id)
    collections = q.order_by('-weekly_subscribers')[:3]
    promobox = CollectionPromoBox(request)

    # Global stats.
    try:
        gs = GlobalStat.objects
        downloads = gs.filter(name='addon_total_downloads').latest()
        pings = gs.filter(name='addon_total_updatepings').latest()
    except GlobalStat.DoesNotExist:
        downloads = pings = None

    # Top tags.
    top_tags = Tag.objects.not_blacklisted().select_related(
        'tagstat').order_by('-tagstat__num_addons')[:10]

    return jingo.render(request, 'addons/home.html',
                        {'downloads': downloads, 'pings': pings,
                         'filter': filter, 'addon_sets': addon_sets,
                         'collections': collections, 'promobox': promobox,
                         'top_tags': top_tags,
                        })


class CollectionPromoBox(object):

    def __init__(self, request):
        self.request = request

    def features(self):
        return CollectionFeature.objects.all()

    def collections(self):
        features = self.features()
        lang = translation.to_language(translation.get_language())
        locale = Q(locale='') | Q(locale=lang)
        promos = (CollectionPromo.objects.filter(locale)
                  .filter(collection_feature__in=features)
                  .transform(CollectionPromo.transformer))
        groups = sorted_groupby(promos, 'collection_feature_id')

        # We key by feature_id and locale, so we can favor locale specific
        # promos.
        promo_dict = {}
        for feature_id, v in groups:
            promo = v.next()
            key = (feature_id, translation.to_language(promo.locale))
            promo_dict[key] = promo

        rv = {}
        # If we can, we favor locale specific collections.
        for feature in features:
            key = (feature.id, lang)
            if key not in promo_dict:
                key = (feature.id, '')
                if key not in promo_dict:
                    continue

            # We only want to see public add-ons on the front page.
            c = promo_dict[key].collection
            c.public_addons = c.addons.all() & Addon.objects.public()
            rv[feature] = c

        return rv

    def __nonzero__(self):
        return self.request.APP == amo.FIREFOX


def eula(request, addon_id, file_id=None):
    addon = get_object_or_404(Addon.objects.valid(), id=addon_id)
    # redirect back to detail if no eula
    # Todo(skeen): think of a better solution
    if not addon.eula:
        return http.HttpResponseRedirect(addon.get_url_path())
    if file_id is not None:
        version = get_object_or_404(addon.versions, files__id=file_id)
    else:
        version = addon.current_version

    return jingo.render(request, 'addons/eula.html',
                        {'addon': addon, 'version': version})


def privacy(request, addon_id):
    addon = get_object_or_404(Addon.objects.valid(), id=addon_id)
    if not addon.privacy_policy:
        return http.HttpResponseRedirect(addon.get_url_path())

    return jingo.render(request, 'addons/privacy.html', {'addon': addon})


def developers(request, addon_id, page):
    addon = get_object_or_404(Addon.objects.valid(), id=addon_id)
    if 'version' in request.GET:
        version = get_object_or_404(addon.versions,
                                    version=request.GET['version'])
    else:
        version = addon.current_version
    if addon.is_persona():
        raise http.Http404()
    author_addons = order_by_translation(addon.authors_other_addons, 'name')
    return jingo.render(request, 'addons/developers.html',
                        {'addon': addon, 'author_addons': author_addons,
                         'page': page, 'version': version})


def contribute(request, addon_id):
    addon = get_object_or_404(Addon.objects.valid(), id=addon_id)

    contrib_type = request.GET.get('type', '')
    is_suggested = contrib_type == 'suggested'
    source = request.GET.get('source', '')
    comment = request.GET.get('comment', '')

    amount = {
        'suggested': addon.suggested_amount,
        'onetime': request.GET.get('onetime-amount', ''),
        'monthly': request.GET.get('monthly-amount', '')}.get(contrib_type, '')

    contribution_uuid = hashlib.md5(str(uuid.uuid4())).hexdigest()

    contrib = Contribution(addon_id=addon.id,
                           amount=amount,
                           source=source,
                           source_locale=request.LANG,
                           annoying=addon.annoying,
                           uuid=str(contribution_uuid),
                           is_suggested=is_suggested,
                           suggested_amount=addon.suggested_amount,
                           comment=comment)
    contrib.save()

    return_url = "%s?%s" % (reverse('addons.thanks', args=[addon.id]),
                            urllib.urlencode({'uuid': contribution_uuid}))
    # L10n: {0} is an add-on name.
    contrib_for = _(u'Contribution for {0}').format(addon.name)
    redirect_url_params = contribute_url_params(
                            addon.paypal_id,
                            addon.id,
                            contrib_for,
                            absolutify(return_url),
                            amount,
                            contribution_uuid,
                            contrib_type == 'monthly',
                            comment)

    return http.HttpResponseRedirect(settings.PAYPAL_CGI_URL
                                     + '?'
                                     + urllib.urlencode(redirect_url_params))


def contribute_url_params(business, addon_id, item_name, return_url,
                          amount='', item_number='',
                          monthly=False, comment=''):

    lang = translation.get_language()
    try:
        paypal_lang = settings.PAYPAL_COUNTRYMAP[lang]
    except KeyError:
        lang = lang.split('-')[0]
        paypal_lang = settings.PAYPAL_COUNTRYMAP.get(lang, 'US')

    # Get all the data elements that will be URL params
    # on the Paypal redirect URL.
    data = {'business': business,
            'item_name': item_name,
            'item_number': item_number,
            'bn': settings.PAYPAL_BN + '-AddonID' + str(addon_id),
            'no_shipping': '1',
            'return': return_url,
            'charset': 'utf-8',
            'lc': paypal_lang,
            'notify_url': "%s%s" % (settings.SERVICES_URL,
                                    reverse('amo.paypal'))}

    if not monthly:
        data['cmd'] = '_donations'
        if amount:
            data['amount'] = amount
    else:
        data.update({
            'cmd': '_xclick-subscriptions',
            'p3': '12',  # duration: for 12 months
            't3': 'M',  # time unit, 'M' for month
            'a3': amount,  # recurring contribution amount
            'no_note': '1'})  # required: no "note" text field for user

    if comment:
        data['custom'] = comment

    return data


def share(request, addon_id):
    """Add-on sharing"""
    addon = get_object_or_404(Addon.objects.valid(), id=addon_id)
    return share_redirect(request, addon, name=addon.name,
                          description=truncate(addon.summary, length=250))


def license(request, addon_id, version=None):
    addon = get_object_or_404(Addon.objects.valid(), id=addon_id)
    if version is not None:
        version = get_object_or_404(addon.versions, version=version)
    else:
        version = addon.current_version
    if not (version and version.license):
        raise http.Http404()
    return jingo.render(request, 'addons/license.html',
                        dict(addon=addon, version=version))


def license_redirect(request, version):
    version = get_object_or_404(Version, pk=version)
    return redirect(version.license_url(), permanent=True)
