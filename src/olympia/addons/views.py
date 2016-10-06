import functools
import hashlib
import json
import random
import re
import uuid
from operator import attrgetter

from django import http
from django.conf import settings
from django.db.transaction import non_atomic_requests
from django.shortcuts import get_list_or_404, get_object_or_404, redirect
from django.utils.translation import ugettext as _
from django.views.decorators.cache import cache_control
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.vary import vary_on_headers

import caching.base as caching
import jinja2
import commonware.log
import session_csrf
import waffle
from elasticsearch_dsl import Search
from mobility.decorators import mobilized, mobile_template
from rest_framework.decorators import detail_route
from rest_framework.exceptions import ParseError
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.viewsets import GenericViewSet
from session_csrf import anonymous_csrf_exempt

from olympia import amo
from olympia.amo import messages
from olympia.amo.decorators import post_required
from olympia.amo.forms import AbuseForm
from olympia.amo.utils import randslice, render
from olympia.amo.models import manual_order
from olympia.amo import urlresolvers
from olympia.amo.urlresolvers import reverse
from olympia.abuse.models import send_abuse_report
from olympia.bandwagon.models import Collection
from olympia import paypal
from olympia.api.paginator import ESPageNumberPagination
from olympia.api.permissions import (
    AllowAddonAuthor, AllowReadOnlyIfReviewedAndListed,
    AllowRelatedObjectPermissions, AllowReviewer, AllowReviewerUnlisted, AnyOf)
from olympia.reviews.forms import ReviewForm
from olympia.reviews.models import Review, GroupedRating
from olympia.search.filters import (
    AddonAppFilterParam, AddonCategoryFilterParam, AddonTypeFilterParam,
    ReviewedContentFilter, SearchParameterFilter, SearchQueryFilter,
    SortingFilter)
from olympia.stats.models import Contribution
from olympia.translations.query import order_by_translation
from olympia.versions.models import Version

from .decorators import addon_view_factory
from .forms import ContributionForm
from .indexers import AddonIndexer
from .models import Addon, Persona, FrozenAddon
from .serializers import (
    AddonEulaPolicySerializer, AddonFeatureCompatibilitySerializer,
    AddonSerializer, ESAddonSerializer, VersionSerializer)
from .utils import get_creatured_ids, get_featured_ids


log = commonware.log.getLogger('z.addons')
paypal_log = commonware.log.getLogger('z.paypal')
addon_view = addon_view_factory(qs=Addon.objects.valid)
addon_unreviewed_view = addon_view_factory(qs=Addon.objects.unreviewed)
addon_valid_disabled_pending_view = addon_view_factory(
    qs=Addon.objects.valid_and_disabled_and_pending)


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


@addon_valid_disabled_pending_view
@non_atomic_requests
def addon_detail(request, addon):
    """Add-ons details page dispatcher."""
    if addon.is_deleted or (addon.is_pending() and not addon.is_persona()):
        # Allow pending themes to be listed.
        raise http.Http404
    if addon.is_disabled:
        return render(request, 'addons/impala/disabled.html',
                      {'addon': addon}, status=404)

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
@non_atomic_requests
def extension_detail(request, addon):
    """Extensions details page."""
    # If current version is incompatible with this app, redirect.
    comp_apps = addon.compatible_apps
    if comp_apps and request.APP not in comp_apps:
        prefixer = urlresolvers.get_url_prefix()
        prefixer.app = comp_apps.keys()[0].short
        return redirect('addons.detail', addon.slug, permanent=True)

    # Popular collections this addon is part of.
    collections = Collection.objects.listed().filter(
        addons=addon, application=request.APP.id)

    ctx = {
        'addon': addon,
        'src': request.GET.get('src', 'dp-btn-primary'),
        'version_src': request.GET.get('src', 'dp-btn-version'),
        'tags': addon.tags.not_blacklisted(),
        'grouped_ratings': GroupedRating.get(addon.id),
        'review_form': ReviewForm(),
        'reviews': Review.without_replies.all().filter(
            addon=addon, is_latest=True),
        'get_replies': Review.get_replies,
        'collections': collections.order_by('-subscribers')[:3],
        'abuse_form': AbuseForm(request=request),
    }

    # details.html just returns the top half of the page for speed. The bottom
    # does a lot more queries we don't want on the initial page load.
    if request.is_ajax():
        # Other add-ons/apps from the same author(s).
        ctx['author_addons'] = addon.authors_other_addons(app=request.APP)[:6]
        return render(request, 'addons/impala/details-more.html', ctx)
    else:
        return render(request, 'addons/impala/details.html', ctx)


@mobilized(extension_detail)
@non_atomic_requests
def extension_detail(request, addon):
    if not request.META.get('HTTP_USER_AGENT'):
        ios_user = False
    else:
        ios_user = 'FxiOS' in request.META.get('HTTP_USER_AGENT')
    return render(request, 'addons/mobile/details.html',
                  {'addon': addon, 'ios_user': ios_user})


def _category_personas(qs, limit):
    def f():
        return randslice(qs, limit=limit)
    key = 'cat-personas:' + qs.query_key()
    return caching.cached(f, key)


@mobile_template('addons/{mobile/}persona_detail.html')
@non_atomic_requests
def persona_detail(request, addon, template=None):
    """Details page for Personas."""
    if not (addon.is_public() or addon.is_pending()):
        raise http.Http404

    persona = addon.persona

    # This persona's categories.
    categories = addon.categories.all()
    category_personas = None
    if categories.exists():
        qs = Addon.objects.public().filter(categories=categories[0])
        category_personas = _category_personas(qs, limit=6)

    data = {
        'addon': addon,
        'persona': persona,
        'categories': categories,
        'author_personas': persona.authors_other_addons()[:3],
        'category_personas': category_personas,
    }

    try:
        author = addon.authors.all()[0]
    except IndexError:
        author = None
    else:
        author = author.get_url_path(src='addon-detail')
    data['author_gallery'] = author

    if not request.MOBILE:
        # tags
        dev_tags, user_tags = addon.tags_partitioned_by_developer
        data.update({
            'dev_tags': dev_tags,
            'user_tags': user_tags,
            'review_form': ReviewForm(),
            'reviews': Review.without_replies.all().filter(
                addon=addon, is_latest=True),
            'get_replies': Review.get_replies,
            'search_cat': 'themes',
            'abuse_form': AbuseForm(request=request),
        })

    return render(request, template, data)


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
        return getattr(self, 'filter_{0}'.format(field))()

    def filter_featured(self):
        ids = self.model.featured_random(self.request.APP, self.request.LANG)
        return manual_order(self.base_queryset, ids, 'addons.id')

    def filter_free(self):
        if self.model == Addon:
            return self.base_queryset.top_free(self.request.APP, listed=False)
        else:
            return self.base_queryset.top_free(listed=False)

    def filter_paid(self):
        if self.model == Addon:
            return self.base_queryset.top_paid(self.request.APP, listed=False)
        else:
            return self.base_queryset.top_paid(listed=False)

    def filter_popular(self):
        return self.base_queryset.order_by('-weekly_downloads')

    def filter_downloads(self):
        return self.filter_popular()

    def filter_users(self):
        return self.base_queryset.order_by('-average_daily_users')

    def filter_created(self):
        return self.base_queryset.order_by('-created')

    def filter_updated(self):
        return self.base_queryset.order_by('-last_updated')

    def filter_rating(self):
        return self.base_queryset.order_by('-bayesian_rating')

    def filter_hotness(self):
        return self.base_queryset.order_by('-hotness')

    def filter_name(self):
        return order_by_translation(self.base_queryset.all(), 'name')


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


@non_atomic_requests
def home(request):
    # Add-ons.
    base = Addon.objects.listed(request.APP).filter(type=amo.ADDON_EXTENSION)
    # This is lame for performance. Kill it with ES.
    frozen = list(FrozenAddon.objects.values_list('addon', flat=True))

    # We want to display 6 Featured Extensions, Up & Coming Extensions and
    # Featured Themes.
    featured = Addon.objects.featured(request.APP, request.LANG,
                                      amo.ADDON_EXTENSION)[:6]
    hotness = base.exclude(id__in=frozen).order_by('-hotness')[:6]
    personas = Addon.objects.featured(request.APP, request.LANG,
                                      amo.ADDON_PERSONA)[:6]

    # Most Popular extensions is a simple links list, we display slightly more.
    popular = base.exclude(id__in=frozen).order_by('-average_daily_users')[:10]

    # We want a maximum of 6 Featured Collections as well (though we may get
    # fewer than that).
    collections = Collection.objects.filter(listed=True,
                                            application=request.APP.id,
                                            type=amo.COLLECTION_FEATURED)[:6]

    return render(request, 'addons/home.html',
                  {'popular': popular, 'featured': featured,
                   'hotness': hotness, 'personas': personas,
                   'src': 'homepage', 'collections': collections})


@mobilized(home)
@non_atomic_requests
def home(request):
    # Shuffle the list and get 3 items.
    def rand(xs):
        return random.shuffle(xs) or xs[:3]

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

    if not request.META.get('HTTP_USER_AGENT'):
        ios_user = False
    else:
        ios_user = 'FxiOS' in request.META.get('HTTP_USER_AGENT')
    return render(request, 'addons/mobile/home.html',
                  {'featured': featured, 'popular': popular,
                   'ios_user': ios_user})


@non_atomic_requests
def homepage_promos(request):
    from olympia.legacy_discovery.views import promos
    version, platform = request.GET.get('version'), request.GET.get('platform')
    if not (platform or version):
        raise http.Http404
    return promos(request, 'home', version, platform)


@addon_view
@non_atomic_requests
def eula(request, addon, file_id=None):
    if not addon.eula:
        return http.HttpResponseRedirect(addon.get_url_path())
    if file_id:
        version = get_object_or_404(addon.versions, files__id=file_id)
    else:
        version = addon.current_version
    return render(request, 'addons/eula.html',
                  {'addon': addon, 'version': version})


@addon_view
@non_atomic_requests
def privacy(request, addon):
    if not addon.privacy_policy:
        return http.HttpResponseRedirect(addon.get_url_path())

    return render(request, 'addons/privacy.html', {'addon': addon})


@addon_view
@non_atomic_requests
def developers(request, addon, page):
    if addon.is_persona():
        raise http.Http404()
    if 'version' in request.GET:
        qs = addon.versions.filter(files__status__in=amo.VALID_ADDON_STATUSES)
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
    return render(request, 'addons/impala/developers.html',
                  {'addon': addon, 'page': page, 'src': src,
                   'contribution_src': contribution_src,
                   'version': version})


@addon_view
@anonymous_csrf_exempt
@post_required
@non_atomic_requests
def contribute(request, addon):
    commentlimit = 255  # Enforce paypal-imposed comment length limit

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

    form = ContributionForm({'amount': amount})
    if len(comment) > commentlimit or not form.is_valid():
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

    paykey, error, status = '', '', ''
    try:
        paykey, status = paypal.get_paykey(
            dict(amount=amount,
                 email=paypal_id,
                 ip=request.META.get('REMOTE_ADDR'),
                 memo=contrib_for,
                 pattern='addons.paypal',
                 slug=addon.slug,
                 uuid=contribution_uuid))
    except paypal.PaypalError as error:
        log.error(
            'Error getting paykey, contribution for addon '
            '(addon: %s, contribution: %s)'
            % (addon.pk, contribution_uuid), exc_info=True)

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
@non_atomic_requests
def paypal_result(request, addon, status):
    uuid = request.GET.get('uuid')
    if not uuid:
        raise http.Http404()
    if status == 'cancel':
        log.info('User cancelled contribution: %s' % uuid)
    else:
        log.info('User completed contribution: %s' % uuid)
    response = render(request, 'addons/paypal_result.html',
                      {'addon': addon, 'status': status})
    response['x-frame-options'] = 'allow'
    return response


@addon_view
@non_atomic_requests
def license(request, addon, version=None):
    if version is not None:
        qs = addon.versions.filter(files__status__in=amo.VALID_FILE_STATUSES)
        version = get_list_or_404(qs, version=version)[0]
    else:
        version = addon.current_version
    if not (version and version.license):
        raise http.Http404
    return render(request, 'addons/impala/license.html',
                  dict(addon=addon, version=version))


@non_atomic_requests
def license_redirect(request, version):
    version = get_object_or_404(Version.objects, pk=version)
    return redirect(version.license_url(), permanent=True)


@session_csrf.anonymous_csrf_exempt
@addon_view
@non_atomic_requests
def report_abuse(request, addon):
    form = AbuseForm(request.POST or None, request=request)
    if request.method == "POST" and form.is_valid():
        send_abuse_report(request, addon, form.cleaned_data['text'])
        messages.success(request, _('Abuse reported.'))
        return http.HttpResponseRedirect(addon.get_url_path())
    else:
        return render(request, 'addons/report_abuse_full.html',
                      {'addon': addon, 'abuse_form': form})


@cache_control(max_age=60 * 60 * 24)
@non_atomic_requests
def persona_redirect(request, persona_id):
    if persona_id == 0:
        # Newer themes have persona_id == 0, doesn't mean anything.
        return http.HttpResponseNotFound()

    persona = get_object_or_404(Persona.objects, persona_id=persona_id)
    try:
        to = reverse('addons.detail', args=[persona.addon.slug])
    except Addon.DoesNotExist:
        # Would otherwise throw 500. Something funky happened during GP
        # migration which caused some Personas to be without Addons (problem
        # with cascading deletes?). Tell GoogleBot these are dead with a 404.
        return http.HttpResponseNotFound()
    return http.HttpResponsePermanentRedirect(to)


@non_atomic_requests
def icloud_bookmarks_redirect(request):
    if (waffle.switch_is_active('icloud_bookmarks_redirect')):
        return redirect('/blocked/i1214/', permanent=False)
    else:
        return addon_detail(request, 'icloud-bookmarks')


class AddonViewSet(RetrieveModelMixin, GenericViewSet):
    permission_classes = [
        AnyOf(AllowReadOnlyIfReviewedAndListed, AllowAddonAuthor,
              AllowReviewer, AllowReviewerUnlisted),
    ]
    serializer_class = AddonSerializer
    addon_id_pattern = re.compile(
        # Match {uuid} or something@host.tld ("something" being optional)
        # guids. Copied from mozilla-central XPIProvider.jsm.
        r'^(\{[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\}'
        r'|[a-z0-9-\._]*\@[a-z0-9-\._]+)$', re.IGNORECASE)
    # Permission classes disallow access to non-public/unlisted add-ons unless
    # logged in as a reviewer/addon owner/admin, so the unfiltered queryset
    # is fine here.
    queryset = Addon.with_unlisted.all()
    lookup_value_regex = '[^/]+'  # Allow '.' for email-like guids.

    def get_queryset(self):
        # Special case: admins - and only admins - can see deleted add-ons.
        # This is handled outside a permission class because that condition
        # would pollute all other classes otherwise.
        if self.request.user.is_authenticated() and self.request.user.is_staff:
            return Addon.unfiltered.all()
        return super(AddonViewSet, self).get_queryset()

    def get_lookup_field(self, identifier):
        lookup_field = 'pk'
        if identifier and not identifier.isdigit():
            # If the identifier contains anything other than a digit, it's
            # either a slug or a guid. guids need to contain either {} or @,
            # which are invalid in a slug.
            if self.addon_id_pattern.match(identifier):
                lookup_field = 'guid'
            else:
                lookup_field = 'slug'
        return lookup_field

    def get_object(self):
        identifier = self.kwargs.get('pk')
        self.lookup_field = self.get_lookup_field(identifier)
        self.kwargs[self.lookup_field] = identifier
        return super(AddonViewSet, self).get_object()

    @detail_route()
    def feature_compatibility(self, request, pk=None):
        obj = self.get_object()
        serializer = AddonFeatureCompatibilitySerializer(
            obj.feature_compatibility,
            context=self.get_serializer_context())
        return Response(serializer.data)

    @detail_route()
    def eula_policy(self, request, pk=None):
        obj = self.get_object()
        serializer = AddonEulaPolicySerializer(
            obj, context=self.get_serializer_context())
        return Response(serializer.data)


class AddonChildMixin(object):
    """Mixin containing method to retrive the parent add-on object."""

    def get_addon_object(self, permission_classes=None):
        """Return the parent Addon object using the URL parameter passed
        to the view.

        `permission_classes` can be use passed to change which permission
        classes the parent viewset will be used when loading the Addon object,
        otherwise AddonViewSet.permission_classes will be used."""
        if hasattr(self, 'addon_object'):
            return self.addon_object

        if permission_classes is None:
            permission_classes = AddonViewSet.permission_classes

        self.addon_object = AddonViewSet(
            request=self.request, permission_classes=permission_classes,
            kwargs={'pk': self.kwargs['addon_pk']}).get_object()
        return self.addon_object


class AddonVersionViewSet(AddonChildMixin, RetrieveModelMixin,
                          ListModelMixin, GenericViewSet):
    # Permissions are checked against the parent add-on.
    permission_classes = [
        AllowRelatedObjectPermissions('addon', AddonViewSet.permission_classes)
    ]
    serializer_class = VersionSerializer
    # Since permission checks are done on the parent add-on, we rely on
    # queryset filtering to hide non-valid versions. get_queryset() might
    # override this if we are asked to see non-valid versions explicitly.
    queryset = Version.objects.filter(
        files__status__in=amo.VALID_FILE_STATUSES).distinct()

    def get_queryset(self):
        """Return the right base queryset depending on the situation. Note that
        permissions checks still apply on top of that, against the add-on
        as per check_object_permissions() above."""
        requested = self.request.GET.get('filter')

        # By default we restrict to valid versions. However:
        #
        # When accessing a single version or if requesting it explicitly when
        # listing, admins can access all versions, including deleted ones.
        should_access_all_versions_included_deleted = (
            (requested == 'all_with_deleted' or self.action != 'list') and
            self.request.user.is_authenticated() and
            self.request.user.is_staff)

        # When accessing a single version or if requesting it explicitly when
        # listing, reviewers and add-on authors can access all non-deleted
        # versions.
        should_access_all_versions = (
            (requested == 'all' or self.action != 'list') and
            (AllowReviewer().has_permission(self.request, self) or
                AllowAddonAuthor().has_object_permission(
                    self.request, self, self.get_addon_object())))

        # Everyone can see (non deleted) beta version when they request it
        # explicitly.
        should_access_only_beta_versions = (requested == 'beta_only')

        if should_access_all_versions_included_deleted:
            self.queryset = Version.unfiltered.all()
        elif should_access_all_versions:
            self.queryset = Version.objects.all()
        elif should_access_only_beta_versions:
            self.queryset = Version.objects.filter(
                files__status=amo.STATUS_BETA).distinct()

        # Now that the base queryset has been altered, call super() to use it.
        qs = super(AddonVersionViewSet, self).get_queryset()
        # Filter with the add-on.
        return qs.filter(addon=self.get_addon_object())


class AddonSearchView(ListAPIView):
    authentication_classes = []
    filter_backends = [
        ReviewedContentFilter, SearchQueryFilter, SearchParameterFilter,
        SortingFilter,
    ]
    pagination_class = ESPageNumberPagination
    permission_classes = []
    serializer_class = ESAddonSerializer

    def get_queryset(self):
        return Search(using=amo.search.get_es(),
                      index=AddonIndexer.get_index_alias(),
                      doc_type=AddonIndexer.get_doctype_name())

    @classmethod
    def as_view(cls, **kwargs):
        view = super(AddonSearchView, cls).as_view(**kwargs)
        return non_atomic_requests(view)


class AddonFeaturedView(GenericAPIView):
    authentication_classes = []
    permission_classes = []
    serializer_class = AddonSerializer
    # We accept the 'page_size' parameter but we do not allow pagination for
    # this endpoint since the order is random.
    pagination_class = None
    queryset = Addon.objects.valid()

    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)

        # Simulate pagination-like results, without actual pagination.
        return Response({'results': serializer.data})

    @classmethod
    def as_view(cls, **kwargs):
        view = super(AddonFeaturedView, cls).as_view(**kwargs)
        return non_atomic_requests(view)

    def filter_queryset(self, queryset):
        # We can pass the optional lang parameter to either get_creatured_ids()
        # or get_featured_ids() below to get locale-specific results in
        # addition to the generic ones.
        lang = self.request.GET.get('lang')
        if 'category' in self.request.GET:
            # If a category is passed then the app and type parameters are
            # mandatory because we need to find a category in the constants to
            # pass to get_creatured_ids(), and category slugs are not unique.
            # AddonCategoryFilterParam parses the request parameters for us to
            # determine the category.
            try:
                category = AddonCategoryFilterParam(self.request).get_value()
            except ValueError:
                raise ParseError(
                    'Invalid app, category and/or type parameter(s).')
            ids = get_creatured_ids(category, lang)
        else:
            # If no category is passed, only the app parameter is mandatory,
            # because get_featured_ids() needs it to find the right collection
            # to pick addons from. It can optionally filter by type, so we
            # parse request for that as well.
            try:
                app = AddonAppFilterParam(
                    self.request).get_object_from_reverse_dict()
                type_ = None
                if 'type' in self.request.GET:
                    type_ = AddonTypeFilterParam(self.request).get_value()
            except ValueError:
                raise ParseError(
                    'Invalid app, category and/or type parameter(s).')
            ids = get_featured_ids(app, lang=lang, type=type_)
        # ids is going to be a random list of ids, we just slice it to get
        # the number of add-ons that was requested. We do it before calling
        # manual_order(), since it'll use the ids as part of a id__in filter.
        try:
            page_size = int(
                self.request.GET.get('page_size', api_settings.PAGE_SIZE))
        except ValueError:
            raise ParseError('Invalid page_size parameter')
        ids = ids[:page_size]
        return manual_order(queryset, ids, 'addons.id')
