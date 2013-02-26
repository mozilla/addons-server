import functools
import hashlib
import json
import random
from urlparse import urlparse
import uuid
from operator import attrgetter

from django import http
from django.conf import settings
from django.db.models import Q
from django.shortcuts import get_list_or_404, get_object_or_404, redirect
from django.utils.translation import trans_real as translation
from django.views.decorators.cache import cache_control
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.vary import vary_on_headers

import caching.base as caching
import jingo
import jinja2
import commonware.log
import session_csrf
from tower import ugettext as _, ugettext_lazy as _lazy
import waffle
from mobility.decorators import mobilized, mobile_template

import amo
from amo import messages
from amo.decorators import login_required, post_required, write
from amo.forms import AbuseForm
from amo.helpers import shared_url
from amo.utils import randslice, sorted_groupby, urlparams
from amo.models import manual_order
from amo import urlresolvers
from amo.urlresolvers import reverse
from abuse.models import send_abuse_report
from bandwagon.models import Collection, CollectionFeature, CollectionPromo
from market.forms import PriceCurrencyForm
import paypal
from reviews.forms import ReviewForm
from reviews.models import Review, GroupedRating
from session_csrf import anonymous_csrf, anonymous_csrf_exempt
from sharing.views import share as share_redirect
from stats.models import Contribution
from translations.query import order_by_translation
from versions.models import Version
from .forms import ContributionForm
from .models import Addon, Persona, FrozenAddon
from .decorators import (addon_view_factory, can_be_purchased, has_purchased,
                         has_not_purchased)
from mkt.webapps.models import Installed

log = commonware.log.getLogger('z.addons')
paypal_log = commonware.log.getLogger('z.paypal')
addon_view = addon_view_factory(qs=Addon.objects.valid)
addon_unreviewed_view = addon_view_factory(qs=Addon.objects.unreviewed)
addon_disabled_view = addon_view_factory(qs=Addon.objects.valid_and_disabled)


def author_addon_clicked(f):
    """Decorator redirecting clicks on "Other add-ons by author"."""
    @functools.wraps(f)
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


@addon_disabled_view
def addon_detail(request, addon):
    """Add-ons details page dispatcher."""
    if addon.is_deleted:
        raise http.Http404
    if addon.is_disabled:
        return jingo.render(request, 'addons/impala/disabled.html',
                            {'addon': addon}, status=404)
    if addon.is_webapp():
        # Apps don't deserve AMO detail pages.
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
                'addons.detail', args=[addon.slug]))


@vary_on_headers('X-Requested-With')
def extension_detail(request, addon):
    """Extensions details page."""
    # If current version is incompatible with this app, redirect.
    comp_apps = addon.compatible_apps
    if comp_apps and request.APP not in comp_apps:
        prefixer = urlresolvers.get_url_prefix()
        prefixer.app = comp_apps.keys()[0].short
        return redirect('addons.detail', addon.slug, permanent=True)

    # get satisfaction only supports en-US.
    lang = translation.to_locale(translation.get_language())
    addon.has_satisfaction = (lang == 'en_US' and
                              addon.get_satisfaction_company)

    # Addon recommendations.
    recommended = Addon.objects.listed(request.APP).filter(
        recommended_for__addon=addon)[:6]

    # Popular collections this addon is part of.
    collections = Collection.objects.listed().filter(
        addons=addon, application__id=request.APP.id)

    ctx = {
        'addon': addon,
        'src': request.GET.get('src', 'dp-btn-primary'),
        'version_src': request.GET.get('src', 'dp-btn-version'),
        'tags': addon.tags.not_blacklisted(),
        'grouped_ratings': GroupedRating.get(addon.id),
        'recommendations': recommended,
        'review_form': ReviewForm(),
        'reviews': Review.objects.valid().filter(addon=addon, is_latest=True),
        'get_replies': Review.get_replies,
        'collections': collections.order_by('-subscribers')[:3],
        'abuse_form': AbuseForm(request=request),
    }

    # details.html just returns the top half of the page for speed. The bottom
    # does a lot more queries we don't want on the initial page load.
    if request.is_ajax():
        # Other add-ons/apps from the same author(s).
        ctx['author_addons'] = addon.authors_other_addons(app=request.APP)[:6]
        return jingo.render(request, 'addons/impala/details-more.html', ctx)
    else:
        if addon.is_webapp():
            ctx['search_placeholder'] = 'apps'
        return jingo.render(request, 'addons/impala/details.html', ctx)


@mobilized(extension_detail)
def extension_detail(request, addon):
    return jingo.render(request, 'addons/mobile/details.html',
                        {'addon': addon})


def _category_personas(qs, limit):
    f = lambda: randslice(qs, limit=limit)
    key = 'cat-personas:' + qs.query_key()
    return caching.cached(f, key)


@mobile_template('addons/{mobile/}persona_detail.html')
def persona_detail(request, addon, template=None):
    """Details page for Personas."""
    if not addon.is_public():
        raise http.Http404

    persona = addon.persona

    # this persona's categories
    categories = addon.categories.filter(application=request.APP.id)
    category_personas = None
    if categories:
        qs = Addon.objects.public().filter(categories=categories[0])
        category_personas = _category_personas(qs, limit=6)

    data = {
        'addon': addon,
        'persona': persona,
        'categories': categories,
        'author_personas': persona.authors_other_addons(request.APP)[:3],
        'category_personas': category_personas,
    }

    author = None
    if persona.is_new():
        try:
            author = addon.authors.all()[0]
        except IndexError:
            pass
        else:
            author = author.get_url_path(src='addon-detail')
    else:
        author = settings.PERSONAS_USER_ROOT % persona.author
    data['author_gallery'] = author

    if not request.MOBILE:
        # tags
        dev_tags, user_tags = addon.tags_partitioned_by_developer
        data.update({
            'dev_tags': dev_tags,
            'user_tags': user_tags,
            'review_form': ReviewForm(),
            'reviews': Review.objects.valid().filter(addon=addon,
                                                     is_latest=True),
            'get_replies': Review.get_replies,
            'search_cat': 'themes',
            'abuse_form': AbuseForm(request=request),
        })

    return jingo.render(request, template, data)


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

    def __init__(self, request, base, key, default, model=Addon):
        self.opts_dict = dict(self.opts)
        self.extras_dict = dict(self.extras) if hasattr(self, 'extras') else {}
        self.request = request
        self.base_queryset = base
        self.key = key
        self.model = model
        self.field, self.title = self.options(self.request, key, default)
        self.qs = self.filter(self.field)

    def options(self, request, key, default):
        """Get the (option, title) pair we want according to the request."""
        if key in request.GET and (request.GET[key] in self.opts_dict or
                                   request.GET[key] in self.extras_dict):
            opt = request.GET[key]
        else:
            opt = default
        if opt in self.opts_dict:
            title = self.opts_dict[opt]
        else:
            title = self.extras_dict[opt]
        return opt, title

    def all(self):
        """Get a full mapping of {option: queryset}."""
        return dict((field, self.filter(field)) for field in dict(self.opts))

    def filter(self, field):
        """Get the queryset for the given field."""
        filter = self._filter(field) & self.base_queryset
        order = getattr(self, 'order_%s' % field, None)
        if order:
            return order(filter)
        return filter

    def _filter(self, field):
        return getattr(self, 'filter_%s' % field)()

    def filter_featured(self):
        ids = self.model.featured_random(self.request.APP, self.request.LANG)
        return manual_order(self.model.objects, ids, 'addons.id')

    def filter_price(self):
        return self.model.objects.order_by('addonpremium__price__price', 'id')

    def filter_free(self):
        if self.model == Addon:
            return self.model.objects.top_free(self.request.APP, listed=False)
        else:
            return self.model.objects.top_free(listed=False)

    def filter_paid(self):
        if self.model == Addon:
            return self.model.objects.top_paid(self.request.APP, listed=False)
        else:
            return self.model.objects.top_paid(listed=False)

    def filter_popular(self):
        return (self.model.objects.order_by('-weekly_downloads')
                .with_index(addons='downloads_type_idx'))

    def filter_downloads(self):
        return self.filter_popular()

    def filter_users(self):
        return (self.model.objects.order_by('-average_daily_users')
                .with_index(addons='adus_type_idx'))

    def filter_created(self):
        return (self.model.objects.order_by('-created')
                .with_index(addons='created_type_idx'))

    def filter_updated(self):
        return (self.model.objects.order_by('-last_updated')
                .with_index(addons='last_updated_type_idx'))

    def filter_rating(self):
        return (self.model.objects.order_by('-bayesian_rating')
                .with_index(addons='rating_type_idx'))

    def filter_hotness(self):
        return self.model.objects.order_by('-hotness')

    def filter_name(self):
        return order_by_translation(self.model.objects.all(), 'name')


class ESBaseFilter(BaseFilter):
    """BaseFilter that uses elasticsearch."""

    def __init__(self, request, base, key, default):
        super(ESBaseFilter, self).__init__(request, base, key, default)

    def filter(self, field):
        sorts = {'name': 'name_sort',
                 'created': '-created',
                 'updated': '-last_updated',
                 'popular': '-weekly_downloads',
                 'users': '-average_daily_users',
                 'rating': '-bayesian_rating'}
        return self.base_queryset.order_by(sorts[field])


class HomepageFilter(BaseFilter):
    opts = (('featured', _lazy(u'Featured')),
            ('popular', _lazy(u'Popular')),
            ('new', _lazy(u'Recently Added')),
            ('updated', _lazy(u'Recently Updated')))

    filter_new = BaseFilter.filter_created


def home(request):
    # Add-ons.
    base = Addon.objects.listed(request.APP).filter(type=amo.ADDON_EXTENSION)
    # This is lame for performance. Kill it with ES.
    frozen = list(FrozenAddon.objects.values_list('addon', flat=True))

    # Collections.
    collections = Collection.objects.filter(listed=True,
                                            application=request.APP.id,
                                            type=amo.COLLECTION_FEATURED)
    featured = Addon.objects.featured(request.APP, request.LANG,
                                      amo.ADDON_EXTENSION)[:18]
    popular = base.exclude(id__in=frozen).order_by('-average_daily_users')[:10]
    hotness = base.exclude(id__in=frozen).order_by('-hotness')[:18]
    personas = Addon.objects.featured(request.APP, request.LANG,
                                      amo.ADDON_PERSONA)[:18]
    return jingo.render(request, 'addons/home.html',
                        {'popular': popular, 'featured': featured,
                         'hotness': hotness, 'personas': personas,
                         'src': 'homepage', 'collections': collections})


@mobilized(home)
def home(request):
    # Shuffle the list and get 3 items.
    rand = lambda xs: random.shuffle(xs) or xs[:3]
    # Get some featured add-ons with randomness.
    featured = Addon.featured_random(request.APP, request.LANG)[:3]
    # Get 10 popular add-ons, then pick 3 at random.
    qs = list(Addon.objects.listed(request.APP)
                   .filter(type=amo.ADDON_EXTENSION)
                   .order_by('-average_daily_users')
                   .values_list('id', flat=True)[:10])
    popular = rand(qs)
    # Do one query and split up the add-ons.
    addons = (Addon.objects.filter(id__in=featured + popular)
              .filter(type=amo.ADDON_EXTENSION))
    featured = [a for a in addons if a.id in featured]
    popular = sorted([a for a in addons if a.id in popular],
                     key=attrgetter('average_daily_users'), reverse=True)
    return jingo.render(request, 'addons/mobile/home.html',
                        {'featured': featured, 'popular': popular})


def homepage_promos(request):
    from discovery.views import promos
    version, platform = request.GET.get('version'), request.GET.get('platform')
    if not (platform or version):
        raise http.Http404
    return promos(request, 'home', version, platform)


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


@addon_view
def eula(request, addon, file_id=None):
    if not addon.eula:
        return http.HttpResponseRedirect(addon.get_url_path())
    if file_id:
        version = get_object_or_404(addon.versions, files__id=file_id)
    else:
        version = addon.current_version
    return jingo.render(request, 'addons/eula.html',
                        {'addon': addon, 'version': version})


@addon_view
def privacy(request, addon):
    if not addon.privacy_policy:
        return http.HttpResponseRedirect(addon.get_url_path())

    return jingo.render(request, 'addons/privacy.html', {'addon': addon})


@addon_view
def developers(request, addon, page):
    if addon.is_persona():
        raise http.Http404()
    if 'version' in request.GET:
        qs = addon.versions.filter(files__status__in=amo.VALID_STATUSES)
        version = get_list_or_404(qs, version=request.GET['version'])[0]
    else:
        version = addon.current_version

    if 'src' in request.GET:
        contribution_src = src = request.GET['src']
    else:
        page_srcs = {
            'developers': ('developers', 'meet-developers'),
            'installed': ('meet-the-developer-post-install', 'post-download'),
            'roadblock': ('meetthedeveloper_roadblock', 'roadblock'),
        }
        # Download src and contribution_src are different.
        src, contribution_src = page_srcs.get(page)
    return jingo.render(request, 'addons/impala/developers.html',
                        {'addon': addon, 'page': page, 'src': src,
                         'contribution_src': contribution_src,
                         'version': version})


# TODO(andym): remove this once we figure out how to process for
# anonymous users. For now we are concentrating on logged in users.
@login_required
@addon_view
@can_be_purchased
@has_not_purchased
@write
@post_required
def purchase(request, addon):
    log.debug('Starting purchase of addon: %s by user: %s'
              % (addon.pk, request.amo_user.pk))
    amount = addon.premium.get_price()
    source = request.POST.get('source', '')
    uuid_ = hashlib.md5(str(uuid.uuid4())).hexdigest()
    # l10n: {0} is the addon name
    contrib_for = _(u'Purchase of {0}').format(jinja2.escape(addon.name))

    # Default is USD.
    amount, currency = addon.premium.get_price(), 'USD'

    # If tier is specified, then let's look it up.
    form = PriceCurrencyForm(data=request.POST, addon=addon)
    if form.is_valid():
        tier = form.get_tier()
        if tier:
            amount, currency = tier.price, tier.currency

    paykey, status, error = '', '', ''
    preapproval = None
    if waffle.flag_is_active(request, 'allow-pre-auth') and request.amo_user:
        preapproval = request.amo_user.get_preapproval()

    try:
        pattern = 'addons.purchase.finished'
        slug = addon.slug
        if addon.is_webapp():
            pattern = 'apps.purchase.finished'
            slug = addon.app_slug

        paykey, status = paypal.get_paykey(
            dict(amount=amount,
                 chains=settings.PAYPAL_CHAINS,
                 currency=currency,
                 email=addon.paypal_id,
                 ip=request.META.get('REMOTE_ADDR'),
                 memo=contrib_for,
                 pattern=pattern,
                 preapproval=preapproval, qs={'realurl':
                                              request.POST.get('realurl')},
                 slug=slug, uuid=uuid_))
    except paypal.PaypalError as error:
        paypal.paypal_log_cef(request, addon, uuid_,
                              'PayKey Failure', 'PAYKEYFAIL',
                              'There was an error getting the paykey')
        log.error('Error getting paykey, purchase of addon: %s' % addon.pk,
                  exc_info=True)

    if paykey:
        contrib = Contribution(addon_id=addon.id, amount=amount,
                               source=source, source_locale=request.LANG,
                               uuid=str(uuid_), type=amo.CONTRIB_PENDING,
                               paykey=paykey, user=request.amo_user)
        log.debug('Storing contrib for uuid: %s' % uuid_)

        # If this was a pre-approval, it's completed already, we'll
        # double check this with PayPal, just to be sure nothing went wrong.
        if status == 'COMPLETED':
            paypal.paypal_log_cef(request, addon, uuid_,
                                  'Purchase', 'PURCHASE',
                                  'A user purchased using pre-approval')

            log.debug('Status is completed for uuid: %s' % uuid_)
            if paypal.check_purchase(paykey) == 'COMPLETED':
                log.debug('Check purchase is completed for uuid: %s' % uuid_)
                contrib.type = amo.CONTRIB_PURCHASE
            else:
                # In this case PayPal disagreed, we should not be trusting
                # what get_paykey said. Which is a worry.
                log.error('Check purchase failed on uuid: %s' % uuid_)
                status = 'NOT-COMPLETED'

        contrib.save()

    else:
        log.error('No paykey present for uuid: %s' % uuid_)

    log.debug('Got paykey for addon: %s by user: %s'
              % (addon.pk, request.amo_user.pk))
    url = '%s?paykey=%s' % (settings.PAYPAL_FLOW_URL, paykey)
    if request.POST.get('result_type') == 'json' or request.is_ajax():
        return http.HttpResponse(json.dumps({'url': url,
                                             'paykey': paykey,
                                             'error': str(error),
                                             'status': status}),
                                 content_type='application/json')

    # This is the non-Ajax fallback.
    if status != 'COMPLETED':
        return http.HttpResponseRedirect(url)

    messages.success(request, _('Purchase complete'))
    return http.HttpResponseRedirect(shared_url('addons.detail', addon))


# TODO(andym): again, remove this once we figure out logged out flow.
@csrf_exempt
@login_required
@addon_view
@can_be_purchased
@write
def purchase_complete(request, addon, status):
    result = ''
    if status == 'complete':
        uuid_ = request.GET.get('uuid')
        log.debug('Looking up contrib for uuid: %s' % uuid_)

        # The IPN may, or may not have come through. Which means looking for
        # a for pre or post IPN contributions. If both fail, then we've not
        # got a matching contribution.
        lookup = (Q(uuid=uuid_, type=amo.CONTRIB_PENDING) |
                  Q(transaction_id=uuid_, type=amo.CONTRIB_PURCHASE))
        con = get_object_or_404(Contribution, lookup)

        log.debug('Check purchase paypal addon: %s, user: %s, paykey: %s'
                  % (addon.pk, request.amo_user.pk, con.paykey[:10]))
        try:
            result = paypal.check_purchase(con.paykey)
            if result == 'ERROR':
                paypal.paypal_log_cef(request, addon, uuid_, 'Purchase Fail',
                                      'PURCHASEFAIL',
                                      'Checking purchase state returned error')
                raise
        except:
            paypal.paypal_log_cef(request, addon, uuid_, 'Purchase Fail',
                                  'PURCHASEFAIL',
                                  'There was an error checking purchase state')
            log.error('Check purchase paypal addon: %s, user: %s, paykey: %s'
                      % (addon.pk, request.amo_user.pk, con.paykey[:10]),
                      exc_info=True)
            result = 'ERROR'
            status = 'error'

        log.debug('Paypal returned: %s for paykey: %s'
                  % (result, con.paykey[:10]))
        if result == 'COMPLETED' and con.type == amo.CONTRIB_PENDING:
            con.update(type=amo.CONTRIB_PURCHASE)

    context = {'realurl': request.GET.get('realurl', ''),
               'status': status, 'result': result}

    # For mobile, bounce back to the details page.
    if request.MOBILE:
        url = urlparams(shared_url('detail', addon), **context)
        return http.HttpResponseRedirect(url)

    context.update({'addon': addon})
    response = jingo.render(request, 'addons/paypal_result.html', context)
    response['x-frame-options'] = 'allow'
    return response


@login_required
@addon_view
@can_be_purchased
@has_purchased
def purchase_thanks(request, addon):
    download = urlparse(request.GET.get('realurl', '')).path

    data = {'addon': addon, 'is_ajax': request.is_ajax(),
            'download': download}

    if addon.is_webapp():
        installed, c = Installed.objects.safer_get_or_create(
            addon=addon, user=request.amo_user)
        data['receipt'] = installed.receipt

    return jingo.render(request, 'addons/paypal_thanks.html', data)


@login_required
@addon_view
@can_be_purchased
def purchase_error(request, addon):
    data = {'addon': addon, 'is_ajax': request.is_ajax()}
    return jingo.render(request, 'addons/paypal_error.html', data)


@addon_view
@anonymous_csrf_exempt
@post_required
def contribute(request, addon):
    webapp = addon.is_webapp()
    contrib_type = request.POST.get('type', 'suggested')
    is_suggested = contrib_type == 'suggested'
    source = request.POST.get('source', '')
    comment = request.POST.get('comment', '')

    amount = {
        'suggested': addon.suggested_amount,
        'onetime': request.POST.get('onetime-amount', '')
    }.get(contrib_type, '')
    if not amount:
        amount = settings.DEFAULT_SUGGESTED_CONTRIBUTION

    # This is all going to get shoved into solitude. Temporary.
    form = ContributionForm({'amount': amount})
    if not form.is_valid():
        return http.HttpResponse(json.dumps({'error': 'Invalid data.',
                                             'status': '', 'url': '',
                                             'paykey': ''}),
                                 content_type='application/json')

    contribution_uuid = hashlib.md5(str(uuid.uuid4())).hexdigest()

    if addon.charity:
        # TODO(andym): Figure out how to get this in the addon authors
        # locale, rather than the contributors locale.
        name, paypal_id = (u'%s: %s' % (addon.name, addon.charity.name),
                           addon.charity.paypal)
    else:
        name, paypal_id = addon.name, addon.paypal_id
    # l10n: {0} is the addon name
    contrib_for = _(u'Contribution for {0}').format(jinja2.escape(name))

    preapproval = None
    if waffle.flag_is_active(request, 'allow-pre-auth') and request.amo_user:
        preapproval = request.amo_user.get_preapproval()

    paykey, error, status = '', '', ''
    try:
        paykey, status = paypal.get_paykey(
            dict(amount=amount,
                 email=paypal_id,
                 ip=request.META.get('REMOTE_ADDR'),
                 memo=contrib_for,
                 pattern='%s.paypal' % ('apps' if webapp else 'addons'),
                 preapproval=preapproval,
                 slug=addon.slug,
                 uuid=contribution_uuid))
    except paypal.PaypalError as error:
        paypal.paypal_log_cef(request, addon, contribution_uuid,
                              'PayKey Failure', 'PAYKEYFAIL',
                              'There was an error getting the paykey')
        log.error('Error getting paykey, contribution for addon: %s'
                  % addon.pk, exc_info=True)

    if paykey:
        contrib = Contribution(addon_id=addon.id, charity_id=addon.charity_id,
                               amount=amount, source=source,
                               source_locale=request.LANG,
                               annoying=addon.annoying,
                               uuid=str(contribution_uuid),
                               is_suggested=is_suggested,
                               suggested_amount=addon.suggested_amount,
                               comment=comment, paykey=paykey)
        contrib.save()

    url = '%s?paykey=%s' % (settings.PAYPAL_FLOW_URL, paykey)
    if request.GET.get('result_type') == 'json' or request.is_ajax():
        # If there was an error getting the paykey, then JSON will
        # not have a paykey and the JS can cope appropriately.
        return http.HttpResponse(json.dumps({'url': url,
                                             'paykey': paykey,
                                             'error': str(error),
                                             'status': status}),
                                 content_type='application/json')
    return http.HttpResponseRedirect(url)


@csrf_exempt
@addon_view
def paypal_result(request, addon, status):
    uuid = request.GET.get('uuid')
    if not uuid:
        raise http.Http404()
    if status == 'cancel':
        log.info('User cancelled contribution: %s' % uuid)
    else:
        log.info('User completed contribution: %s' % uuid)
    response = jingo.render(request, 'addons/paypal_result.html',
                            {'addon': addon, 'status': status})
    response['x-frame-options'] = 'allow'
    return response


@addon_view
@can_be_purchased
@anonymous_csrf
def paypal_start(request, addon=None):
    download = urlparse(request.GET.get('realurl', '')).path
    data = {'addon': addon, 'is_ajax': request.is_ajax(),
            'download': download,
            'currencies': addon.premium.price.currencies()}

    if request.user.is_authenticated():
        return jingo.render(request, 'addons/paypal_start.html', data)

    from users.views import _login
    return _login(request, data=data, template='addons/paypal_start.html',
                  dont_redirect=True)


@addon_view
def share(request, addon):
    """Add-on sharing"""
    return share_redirect(request, addon, addon.name, addon.summary)


@addon_view
def license(request, addon, version=None):
    if version is not None:
        qs = addon.versions.filter(files__status__in=amo.VALID_STATUSES)
        version = get_list_or_404(qs, version=version)[0]
    else:
        version = addon.current_version
    if not (version and version.license):
        raise http.Http404
    return jingo.render(request, 'addons/impala/license.html',
                        dict(addon=addon, version=version))


def license_redirect(request, version):
    version = get_object_or_404(Version, pk=version)
    return redirect(version.license_url(), permanent=True)


@session_csrf.anonymous_csrf_exempt
@addon_view
def report_abuse(request, addon):
    form = AbuseForm(request.POST or None, request=request)
    if request.method == "POST" and form.is_valid():
        send_abuse_report(request, addon, form.cleaned_data['text'])
        messages.success(request, _('Abuse reported.'))
        return http.HttpResponseRedirect(addon.get_url_path())
    else:
        return jingo.render(request, 'addons/report_abuse_full.html',
                            {'addon': addon, 'abuse_form': form, })


@cache_control(max_age=60 * 60 * 24)
def persona_redirect(request, persona_id):
    persona = get_object_or_404(Persona, persona_id=persona_id)
    to = reverse('addons.detail', args=[persona.addon.slug])
    return http.HttpResponsePermanentRedirect(to)
