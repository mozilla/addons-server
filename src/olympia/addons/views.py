import hashlib
import json
import uuid

from django import http
from django.conf import settings
from django.db.transaction import non_atomic_requests
from django.shortcuts import get_list_or_404, get_object_or_404, redirect
from django.utils.translation import ugettext
from django.utils.cache import patch_cache_control
from django.views.decorators.cache import cache_control
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.vary import vary_on_headers

import caching.base as caching
import jinja2
import session_csrf
import waffle
from elasticsearch_dsl import Search
from rest_framework import serializers
from rest_framework.decorators import detail_route
from rest_framework.exceptions import ParseError
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.viewsets import GenericViewSet
from session_csrf import anonymous_csrf_exempt

import olympia.core.logger
from olympia import amo
from olympia.access import acl
from olympia.amo import messages
from olympia.amo.decorators import post_required
from olympia.amo.forms import AbuseForm
from olympia.amo.utils import randslice, render
from olympia.amo.models import manual_order
from olympia.amo import urlresolvers
from olympia.amo.urlresolvers import reverse
from olympia.abuse.models import send_abuse_report
from olympia.bandwagon.models import Collection
from olympia.constants.payments import PAYPAL_MAX_COMMENT_LENGTH
from olympia.constants.categories import CATEGORIES_BY_ID
from olympia import paypal
from olympia.api.pagination import ESPageNumberPagination
from olympia.api.permissions import (
    AllowAddonAuthor, AllowReadOnlyIfPublic, AllowRelatedObjectPermissions,
    AllowReviewer, AllowReviewerUnlisted, AnyOf, GroupPermission)
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
from .models import Addon, Persona, FrozenAddon, ReplacementAddon
from .serializers import (
    AddonEulaPolicySerializer, AddonFeatureCompatibilitySerializer,
    AddonSerializer, AddonSerializerWithUnlistedData,
    ESAddonAutoCompleteSerializer, ESAddonSerializer, LanguageToolsSerializer,
    VersionSerializer, StaticCategorySerializer)
from .utils import get_creatured_ids, get_featured_ids


log = olympia.core.logger.getLogger('z.addons')
paypal_log = olympia.core.logger.getLogger('z.paypal')
addon_view = addon_view_factory(qs=Addon.objects.valid)
addon_valid_disabled_pending_view = addon_view_factory(
    qs=Addon.objects.valid_and_disabled_and_pending)


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
        'tags': addon.tags.not_denied(),
        'grouped_ratings': GroupedRating.get(addon.id),
        'review_form': ReviewForm(),
        'reviews': Review.without_replies.all().filter(
            addon=addon, is_latest=True).exclude(body=None),
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


def _category_personas(qs, limit):
    def f():
        return randslice(qs, limit=limit)
    key = 'cat-personas:' + qs.query_key()
    return caching.cached(f, key)


@non_atomic_requests
def persona_detail(request, addon):
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

    return render(request, 'addons/persona_detail.html', data)


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
                   'contribution_src': contribution_src})


@addon_view
@anonymous_csrf_exempt
@post_required
@non_atomic_requests
def contribute(request, addon):

    # Enforce paypal-imposed comment length limit
    commentlimit = PAYPAL_MAX_COMMENT_LENGTH

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

    contribution_uuid = hashlib.sha256(str(uuid.uuid4())).hexdigest()

    if addon.charity:
        # TODO(andym): Figure out how to get this in the addon authors
        # locale, rather than the contributors locale.
        name, paypal_id = (u'%s: %s' % (addon.name, addon.charity.name),
                           addon.charity.paypal)
    else:
        name, paypal_id = addon.name, addon.paypal_id
    # l10n: {0} is the addon name
    contrib_for = ugettext(u'Contribution for {0}').format(jinja2.escape(name))

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
        qs = addon.versions.filter(channel=amo.RELEASE_CHANNEL_LISTED,
                                   files__status__in=amo.VALID_FILE_STATUSES)
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
        messages.success(request, ugettext('Abuse reported.'))
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


DEFAULT_FIND_REPLACEMENT_PATH = '/collections/mozilla/featured-add-ons/'
FIND_REPLACEMENT_SRC = 'find-replacement'


def find_replacement_addon(request):
    guid = request.GET.get('guid')
    if not guid:
        raise http.Http404
    try:
        path = ReplacementAddon.objects.get(guid=guid).path
    except ReplacementAddon.DoesNotExist:
        path = DEFAULT_FIND_REPLACEMENT_PATH
    replace_url = '%s%s?src=%s' % (
        ('/' if not path.startswith('/') else ''), path, FIND_REPLACEMENT_SRC)
    return redirect(replace_url, permanent=False)


class AddonViewSet(RetrieveModelMixin, GenericViewSet):
    permission_classes = [
        AnyOf(AllowReadOnlyIfPublic, AllowAddonAuthor,
              AllowReviewer, AllowReviewerUnlisted),
    ]
    serializer_class = AddonSerializer
    serializer_class_with_unlisted_data = AddonSerializerWithUnlistedData
    lookup_value_regex = '[^/]+'  # Allow '.' for email-like guids.

    def get_queryset(self):
        """Return queryset to be used for the view. We implement our own that
        does not depend on self.queryset to avoid cache-machine caching the
        queryset too agressively (mozilla/addons-frontend#2497)."""
        # Special case: admins - and only admins - can see deleted add-ons.
        # This is handled outside a permission class because that condition
        # would pollute all other classes otherwise.
        if (self.request.user.is_authenticated() and
                acl.action_allowed(self.request,
                                   amo.permissions.ADDONS_VIEW_DELETED)):
            return Addon.unfiltered.all()
        # Permission classes disallow access to non-public/unlisted add-ons
        # unless logged in as a reviewer/addon owner/admin, so we don't have to
        # filter the base queryset here.
        return Addon.objects.all()

    def get_serializer_class(self):
        # Override serializer to use serializer_class_with_unlisted_data if
        # we are allowed to access unlisted data.
        obj = getattr(self, 'instance')
        request = self.request
        if (acl.check_unlisted_addons_reviewer(request) or
                (obj and request.user.is_authenticated() and
                 obj.authors.filter(pk=request.user.pk).exists())):
            return self.serializer_class_with_unlisted_data
        return self.serializer_class

    def get_lookup_field(self, identifier):
        lookup_field = 'pk'
        if identifier and not identifier.isdigit():
            # If the identifier contains anything other than a digit, it's
            # either a slug or a guid. guids need to contain either {} or @,
            # which are invalid in a slug.
            if amo.ADDON_GUID_PATTERN.match(identifier):
                lookup_field = 'guid'
            else:
                lookup_field = 'slug'
        return lookup_field

    def get_object(self):
        identifier = self.kwargs.get('pk')
        self.lookup_field = self.get_lookup_field(identifier)
        self.kwargs[self.lookup_field] = identifier
        self.instance = super(AddonViewSet, self).get_object()
        return self.instance

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
    """Mixin containing method to retrieve the parent add-on object."""

    def get_addon_object(self, permission_classes=None, lookup='addon_pk'):
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
            kwargs={'pk': self.kwargs[lookup]}).get_object()
        return self.addon_object


class AddonVersionViewSet(AddonChildMixin, RetrieveModelMixin,
                          ListModelMixin, GenericViewSet):
    # Permissions are always checked against the parent add-on in
    # get_addon_object() using AddonViewSet.permission_classes so we don't need
    # to set any here. Some extra permission classes are added dynamically
    # below in check_permissions() and check_object_permissions() depending on
    # what the client is requesting to see.
    permission_classes = []
    serializer_class = VersionSerializer

    def check_permissions(self, request):
        requested = self.request.GET.get('filter')
        if self.action == 'list':
            if requested == 'all_with_deleted':
                # To see deleted versions, you need Addons:ViewDeleted.
                self.permission_classes = [
                    GroupPermission(amo.permissions.ADDONS_VIEW_DELETED)]
            elif requested == 'all_with_unlisted':
                # To see unlisted versions, you need to be add-on author or
                # unlisted reviewer.
                self.permission_classes = [AnyOf(
                    AllowReviewerUnlisted, AllowAddonAuthor)]
            elif requested == 'all_without_unlisted':
                # To see all listed versions (not just public ones) you need to
                # be add-on author or reviewer.
                self.permission_classes = [AnyOf(
                    AllowReviewer, AllowAddonAuthor)]
            # When listing, we can't use AllowRelatedObjectPermissions() with
            # check_permissions(), because AllowAddonAuthor needs an author to
            # do the actual permission check. To work around that, we call
            # super + check_object_permission() ourselves, passing down the
            # addon object directly.
            return super(AddonVersionViewSet, self).check_object_permissions(
                request, self.get_addon_object())
        super(AddonVersionViewSet, self).check_permissions(request)

    def check_object_permissions(self, request, obj):
        # If the instance is marked as deleted and the client is not allowed to
        # see deleted instances, we want to return a 404, behaving as if it
        # does not exist.
        if (obj.deleted and
                not GroupPermission(amo.permissions.ADDONS_VIEW_DELETED).
                has_object_permission(request, self, obj)):
            raise http.Http404

        if obj.channel == amo.RELEASE_CHANNEL_UNLISTED:
            # If the instance is unlisted, only allow unlisted reviewers and
            # authors..
            self.permission_classes = [
                AllowRelatedObjectPermissions(
                    'addon', [AnyOf(AllowReviewerUnlisted, AllowAddonAuthor)])
            ]
        elif not obj.is_public():
            # If the instance is disabled, only allow reviewers and authors.
            self.permission_classes = [
                AllowRelatedObjectPermissions(
                    'addon', [AnyOf(AllowReviewer, AllowAddonAuthor)])
            ]
        super(AddonVersionViewSet, self).check_object_permissions(request, obj)

    def get_queryset(self):
        """Return the right base queryset depending on the situation."""
        requested = self.request.GET.get('filter')
        valid_filters = (
            'all_with_deleted',
            'all_with_unlisted',
            'all_without_unlisted',
            'only_beta'
        )
        if requested is not None:
            if self.action != 'list':
                raise serializers.ValidationError(
                    'The "filter" parameter is not valid in this context.')
            elif requested not in valid_filters:
                raise serializers.ValidationError(
                    'Invalid "filter" parameter specified.')
        # By default we restrict to valid, listed versions. Some filtering
        # options are available when listing, and in addition, when returning
        # a single instance, we don't filter at all.
        if requested == 'all_with_deleted' or self.action != 'list':
            queryset = Version.unfiltered.all()
        elif requested == 'all_with_unlisted':
            queryset = Version.objects.all()
        elif requested == 'all_without_unlisted':
            queryset = Version.objects.filter(
                channel=amo.RELEASE_CHANNEL_LISTED)
        elif requested == 'only_beta':
            queryset = Version.objects.filter(
                channel=amo.RELEASE_CHANNEL_LISTED,
                files__status=amo.STATUS_BETA).distinct()
        else:
            # By default, we rely on queryset filtering to hide
            # non-public/unlisted versions. get_queryset() might override this
            # if we are asked to see non-valid, deleted and/or unlisted
            # versions explicitly.
            queryset = Version.objects.filter(
                files__status=amo.STATUS_PUBLIC,
                channel=amo.RELEASE_CHANNEL_LISTED).distinct()

        # Filter with the add-on.
        return queryset.filter(addon=self.get_addon_object())


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
        return Search(
            using=amo.search.get_es(),
            index=AddonIndexer.get_index_alias(),
            doc_type=AddonIndexer.get_doctype_name()).extra(
                _source={'excludes': AddonIndexer.hidden_fields})

    @classmethod
    def as_view(cls, **kwargs):
        view = super(AddonSearchView, cls).as_view(**kwargs)
        return non_atomic_requests(view)


class AddonAutoCompleteSearchView(AddonSearchView):
    pagination_class = None
    serializer_class = ESAddonAutoCompleteSerializer

    def get_queryset(self):
        # Minimal set of fields from ES that we need to build our results.
        # It's the opposite tactic used by the regular search endpoint, which
        # excludes a specific set of fields - because we know that autocomplete
        # only needs to return very few things.
        included_fields = (
            'icon_type',  # Needed for icon_url.
            'id',  # Needed for... id.
            'modified',  # Needed for icon_url.
            'name_translations',  # Needed for... name.
            'persona',  # Needed for icon_url (sadly).
            'slug',  # Needed for url.
            'type',  # Needed to attach the Persona for icon_url (sadly).
        )

        return Search(
            using=amo.search.get_es(),
            index=AddonIndexer.get_index_alias(),
            doc_type=AddonIndexer.get_doctype_name()).extra(
                _source={'includes': included_fields})

    def list(self, request, *args, **kwargs):
        # Ignore pagination (slice directly) but do wrap the data in a
        # 'results' property to mimic what the search API does.
        queryset = self.filter_queryset(self.get_queryset())[:10]
        serializer = self.get_serializer(queryset, many=True)
        return Response({'results': serializer.data})


class AddonFeaturedView(GenericAPIView):
    authentication_classes = []
    permission_classes = []
    serializer_class = AddonSerializer
    # We accept the 'page_size' parameter but we do not allow pagination for
    # this endpoint since the order is random.
    pagination_class = None

    def get(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)

        # Simulate pagination-like results, without actual pagination.
        return Response({'results': serializer.data})

    @classmethod
    def as_view(cls, **kwargs):
        view = super(AddonFeaturedView, cls).as_view(**kwargs)
        return non_atomic_requests(view)

    def get_queryset(self):
        return Addon.objects.valid()

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


class StaticCategoryView(ListAPIView):
    authentication_classes = []
    pagination_class = None
    permission_classes = []
    serializer_class = StaticCategorySerializer

    def get_queryset(self):
        return sorted(CATEGORIES_BY_ID.values(), key=lambda x: x.id)

    @classmethod
    def as_view(cls, **kwargs):
        view = super(StaticCategoryView, cls).as_view(**kwargs)
        return non_atomic_requests(view)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super(StaticCategoryView, self).finalize_response(
            request, response, *args, **kwargs)
        patch_cache_control(response, max_age=60 * 60 * 6)
        return response


class LanguageToolsView(ListAPIView):
    authentication_classes = []
    pagination_class = None
    permission_classes = []
    serializer_class = LanguageToolsSerializer

    def get_queryset(self):
        try:
            application_id = AddonAppFilterParam(self.request).get_value()
        except ValueError:
            raise ParseError('Invalid app parameter.')

        types = (amo.ADDON_DICT, amo.ADDON_LPAPP)
        return Addon.objects.public().filter(
            appsupport__app=application_id, type__in=types,
            target_locale__isnull=False).exclude(target_locale='')

    def list(self, request, *args, **kwargs):
        # Ignore pagination (return everything) but do wrap the data in a
        # 'results' property to mimic what the default implementation of list()
        # does in DRF.
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        return Response({'results': serializer.data})
