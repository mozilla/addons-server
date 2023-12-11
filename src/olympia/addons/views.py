from collections import OrderedDict

from django import http
from django.db.models import F, Max, Prefetch
from django.db.transaction import non_atomic_requests
from django.shortcuts import redirect
from django.utils.cache import patch_cache_control
from django.utils.translation import gettext

from drf_yasg.utils import swagger_auto_schema
from elasticsearch_dsl import Q, Search, query
from rest_framework import exceptions, serializers, status
from rest_framework.decorators import action
from rest_framework.generics import ListAPIView
from rest_framework.mixins import (
    CreateModelMixin,
    DestroyModelMixin,
    ListModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

import olympia.core.logger
from olympia import amo
from olympia.access import acl
from olympia.activity.models import ActivityLog
from olympia.amo.urlresolvers import get_outgoing_url
from olympia.amo.utils import StopWatch
from olympia.api.authentication import (
    JWTKeyAuthentication,
    SessionIDAuthentication,
)
from olympia.api.exceptions import UnavailableForLegalReasons
from olympia.api.pagination import ESPageNumberPagination, LargePageNumberPagination
from olympia.api.permissions import (
    AllowAddonAuthor,
    AllowAddonOwner,
    AllowIfNotMozillaDisabled,
    AllowListedViewerOrReviewer,
    AllowReadOnlyIfPublic,
    AllowRelatedObjectPermissions,
    AllowUnlistedViewerOrReviewer,
    AnyOf,
    APIGatePermission,
    GroupPermission,
    RegionalRestriction,
)
from olympia.api.throttling import addon_submission_throttles
from olympia.api.utils import is_gate_active
from olympia.constants.browsers import BROWSERS
from olympia.constants.categories import CATEGORIES_BY_ID
from olympia.devhub.permissions import IsSubmissionAllowedFor
from olympia.search.filters import (
    AddonAppQueryParam,
    AddonAppVersionQueryParam,
    AddonAuthorQueryParam,
    AddonTypeQueryParam,
    AutoCompleteSortFilter,
    ReviewedContentFilter,
    SearchParameterFilter,
    SearchQueryFilter,
    SortingFilter,
)
from olympia.search.utils import get_es
from olympia.translations.query import order_by_translation
from olympia.users.utils import (
    send_addon_author_add_mail,
    send_addon_author_change_mail,
    send_addon_author_remove_mail,
)
from olympia.versions.models import Version

from .decorators import addon_view_factory
from .indexers import AddonIndexer
from .models import (
    Addon,
    AddonBrowserMapping,
    AddonUser,
    AddonUserPendingConfirmation,
    ReplacementAddon,
)
from .serializers import (
    AddonAuthorSerializer,
    AddonBrowserMappingSerializer,
    AddonEulaPolicySerializer,
    AddonPendingAuthorSerializer,
    AddonSerializer,
    DeveloperAddonSerializer,
    DeveloperListVersionSerializer,
    DeveloperVersionSerializer,
    ESAddonAutoCompleteSerializer,
    ESAddonSerializer,
    LanguageToolsSerializer,
    ListVersionSerializer,
    PreviewSerializer,
    ReplacementAddonSerializer,
    StaticCategorySerializer,
    VersionSerializer,
)
from .utils import (
    DeleteTokenSigner,
    get_addon_recommendations,
    get_addon_recommendations_invalid,
    is_outcome_recommended,
    webext_version_stats,
)


log = olympia.core.logger.getLogger('z.addons')
addon_view = addon_view_factory(qs=Addon.objects.valid)


class BaseFilter:
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
        if key in request.GET and (
            request.GET[key] in self.opts_dict or request.GET[key] in self.extras_dict
        ):
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
        return {field: self.filter(field) for field in dict(self.opts)}

    def filter(self, field):
        """Get the queryset for the given field."""
        return getattr(self, f'filter_{field}')()

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


DEFAULT_FIND_REPLACEMENT_PATH = '/collections/mozilla/featured-add-ons/'
FIND_REPLACEMENT_SRC = 'find-replacement'


def find_replacement_addon(request):
    guid = request.GET.get('guid')
    if not guid:
        raise http.Http404
    try:
        replacement = ReplacementAddon.objects.get(guid=guid)
        path = replacement.path
    except ReplacementAddon.DoesNotExist:
        path = DEFAULT_FIND_REPLACEMENT_PATH
    else:
        if replacement.has_external_url():
            # It's an external URL:
            return redirect(get_outgoing_url(path))
    replace_url = (
        '%s%s?utm_source=addons.mozilla.org&utm_medium=referral&utm_content=%s'
    ) % (
        ('/' if not path.startswith('/') else ''),
        path,
        FIND_REPLACEMENT_SRC,
    )
    return redirect(replace_url, permanent=False)


class AddonViewSet(
    CreateModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
    DestroyModelMixin,
    GenericViewSet,
):
    write_permission_classes = [
        APIGatePermission('addon-submission-api'),
        AllowAddonAuthor,
        AllowIfNotMozillaDisabled,
        IsSubmissionAllowedFor,
    ]
    delete_permission_classes = [
        APIGatePermission('addon-submission-api'),
        AllowAddonOwner,
        AllowIfNotMozillaDisabled,
    ]
    permission_classes = [
        AnyOf(
            AllowReadOnlyIfPublic,
            AllowAddonAuthor,
            AllowListedViewerOrReviewer,
            AllowUnlistedViewerOrReviewer,
        )
    ]
    authentication_classes = [
        JWTKeyAuthentication,
        SessionIDAuthentication,
    ]
    georestriction_classes = [
        RegionalRestriction | GroupPermission(amo.permissions.ADDONS_EDIT)
    ]
    serializer_class = AddonSerializer
    serializer_class_for_developers = DeveloperAddonSerializer
    lookup_value_regex = r'[^/]+'  # Allow '.' for email-like guids.
    throttle_classes = addon_submission_throttles

    def get_queryset(self):
        """Return queryset to be used for the view."""
        # Special case: admins - and only admins - can see deleted add-ons.
        # This is handled outside a permission class because that condition
        # would pollute all other classes otherwise.
        if self.request.user.is_authenticated and acl.action_allowed_for(
            self.request.user, amo.permissions.ADDONS_VIEW_DELETED
        ):
            qs = Addon.unfiltered.all()
        else:
            # Permission classes disallow access to non-public/unlisted add-ons
            # unless logged in as a reviewer/addon owner/admin, so we don't
            # have to filter the base queryset here.
            qs = Addon.objects.all()
        if self.action == 'retrieve_from_related':
            # Avoid default transformers if we're fetching a single instance
            # from a related view: We're unlikely to need the preloading they
            # bring, this would only cause extra useless queries. Still include
            # translations because at least the addon name is likely to be
            # needed in most cases.
            qs = qs.only_translations()
        return qs

    def get_serializer_class(self):
        # Override serializer to use serializer_class_for_developers if the author or
        # we are allowed to access unlisted data.
        obj = getattr(self, 'instance', None)
        request = self.request
        if request.user.is_authenticated and (
            self.action in ('create', 'update', 'partial_update')
            or acl.is_unlisted_addons_viewer_or_reviewer(request.user)
            or (obj and obj.authors.filter(pk=request.user.pk).exists())
        ):
            return self.serializer_class_for_developers
        return self.serializer_class

    def get_lookup_field(self, identifier):
        return Addon.get_lookup_field(identifier)

    def get_object(self):
        if not hasattr(self, 'instance'):
            identifier = self.kwargs.get('pk')
            self.lookup_field = self.get_lookup_field(identifier)
            self.kwargs[self.lookup_field] = identifier
            self.instance = super().get_object()
        return self.instance

    def check_permissions(self, request):
        for restriction in self.get_georestrictions():
            if not restriction.has_permission(request, self):
                raise UnavailableForLegalReasons()
        if self.action in ('create', 'update', 'partial_update'):
            self.permission_classes = self.write_permission_classes
        elif self.action in ('destroy', 'delete_confirm'):
            self.permission_classes = self.delete_permission_classes
        super().check_permissions(request)

    def check_object_permissions(self, request, obj):
        """
        Check if the request should be permitted for a given object.
        Raises an appropriate exception if the request is not permitted.

        Calls DRF implementation, but adds `is_disabled_by_developer` and
        `is_disabled_by_mozilla` to the exception being thrown so that clients
        can tell the difference between a 401/403 returned because an add-on
        has been disabled by their developer or something else.
        """
        for restriction in self.get_georestrictions():
            if not restriction.has_object_permission(request, self, obj):
                raise UnavailableForLegalReasons()

        if self.action in ('update', 'partial_update'):
            self.permission_classes = self.write_permission_classes
        elif self.action in ('destroy', 'delete_confirm'):
            self.permission_classes = self.delete_permission_classes
        try:
            super().check_object_permissions(request, obj)
        except exceptions.APIException as exc:
            # Override exc.detail with a dict so that it's returned as-is in
            # the response. The base implementation for exc.get_codes() does
            # not expect dicts in that format, so override it as well with a
            # lambda that returns what would have been returned before our
            # changes.
            codes = exc.get_codes()
            exc.get_codes = lambda: codes
            exc.detail = {
                'detail': exc.detail,
                'is_disabled_by_developer': obj.disabled_by_user,
                'is_disabled_by_mozilla': obj.status == amo.STATUS_DISABLED,
            }
            raise exc

    def get_georestrictions(self):
        return [perm() for perm in self.georestriction_classes]

    @action(detail=True)
    def eula_policy(self, request, pk=None):
        obj = self.get_object()
        serializer = AddonEulaPolicySerializer(
            obj, context=self.get_serializer_context()
        )
        return Response(serializer.data)

    @action(detail=True)
    def delete_confirm(self, request, *args, **kwargs):
        token = DeleteTokenSigner().generate(self.get_object().id)
        return Response({'delete_confirm': token})

    def destroy(self, request, *args, **kwargs):
        # check token
        token = request.GET.get('delete_confirm')
        if not token:
            raise exceptions.ValidationError(
                '"delete_confirm" token must be supplied for add-on delete.'
            )
        if not DeleteTokenSigner().validate(token, self.get_object().id):
            raise exceptions.ValidationError('"delete_confirm" token is invalid.')

        return super().destroy(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if kwargs.get('partial'):
            # PATCH uses the standard update always
            return super().update(request, *args, **kwargs)

        # for PUT we check if the object exists first
        try:
            instance = self.get_object()
        except http.Http404:
            instance = None

        # We only support guid style ids for PUT requests
        if self.lookup_field != 'guid':
            raise http.Http404

        if instance:
            # if the add-on exists we can use the standard update
            return super().update(request, *args, **kwargs)
        else:
            # otherwise we create a new add-on
            self.action = 'create'
            return self.create(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_description="""
            This endpoint allows a submission of an upload to create a new add-on
            and setting other AMO metadata.

            To create an add-on with a listed version from an upload
            (an upload that has channel == listed) certain metadata must be defined
            - version license
            - add-on name
            - add-on summary
            - add-on categories for each app the version is compatible with.
        """
    )
    def create(self, request, *args, **kwargs):
        response = super().create(request, *args, **kwargs)
        webext_version_stats(request, 'addons.submission')
        return response


class AddonChildMixin:
    """Mixin containing method to retrieve the parent add-on object."""

    def get_addon_object(
        self, permission_classes=None, georestriction_classes=None, lookup='addon_pk'
    ):
        """Return the parent Addon object using the URL parameter passed
        to the view.

        `permission_classes` can be use passed to change which permission
        classes the parent viewset will be used when loading the Addon object,
        otherwise AddonViewSet.permission_classes will be used for safe actions and
        AddonViewSet.write_permission_classes for unsafe actions.

        `georestriction_classes` can be use passed to change which regional
        restriction classes the parent viewset will be used when loading the
        Addon object, otherwise AddonViewSet.georestriction_classes will be
        used."""
        if hasattr(self, 'addon_object'):
            return self.addon_object
        if permission_classes is None:
            permission_classes = (
                AddonViewSet.write_permission_classes
                if self.action in ('create', 'update', 'partial_update', 'destroy')
                else AddonViewSet.permission_classes
            )
        if georestriction_classes is None:
            georestriction_classes = AddonViewSet.georestriction_classes

        self.addon_object = AddonViewSet(
            request=self.request,
            permission_classes=permission_classes,
            georestriction_classes=georestriction_classes,
            kwargs={'pk': self.kwargs[lookup]},
            action='retrieve_from_related',
        ).get_object()
        return self.addon_object


class AddonVersionViewSet(
    AddonChildMixin,
    CreateModelMixin,
    DestroyModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
    ListModelMixin,
    GenericViewSet,
):
    # Permissions are always checked against the parent add-on in
    # get_addon_object() using AddonViewSet's permissions so we don't need
    # to set any here. Some extra permission classes are added dynamically
    # below in check_permissions() and check_object_permissions() depending on
    # what the client is requesting to see.
    permission_classes = []
    authentication_classes = [
        JWTKeyAuthentication,
        SessionIDAuthentication,
    ]
    throttle_classes = addon_submission_throttles

    lookup_value_regex = r'[^/]+'  # Allow '.' for version number lookups.

    def get_object(self):
        if identifier := self.kwargs.get('pk'):
            if identifier.startswith('v'):
                identifier = identifier[1:]
                self.lookup_field = 'version'
            elif '.' in identifier:
                self.lookup_field = 'version'
            self.kwargs[self.lookup_field] = identifier
        return super().get_object()

    def get_serializer_class(self):
        use_developer_serializer = getattr(
            self.request, 'user', None
        ) and acl.author_or_unlisted_viewer_or_reviewer(
            self.request.user, self.get_addon_object()
        )

        if (
            self.action == 'list'
            and self.request
            and not is_gate_active(self.request, 'keep-license-text-in-version-list')
        ):
            serializer_class = (
                ListVersionSerializer
                if not use_developer_serializer
                else DeveloperListVersionSerializer
            )
        else:
            serializer_class = (
                VersionSerializer
                if not use_developer_serializer
                else DeveloperVersionSerializer
            )
        return serializer_class

    def get_serializer(self, *args, **kwargs):
        return super().get_serializer(
            *args, **{**kwargs, 'addon': self.get_addon_object()}
        )

    def check_permissions(self, request):
        requested = self.request.GET.get('filter')
        if requested == 'all_with_deleted':
            # To see deleted versions, you need Addons:ViewDeleted.
            self.permission_classes = [
                GroupPermission(amo.permissions.ADDONS_VIEW_DELETED)
            ]
        elif requested == 'all_with_unlisted':
            # To see unlisted versions, you need to be add-on author or
            # unlisted reviewer.
            self.permission_classes = [
                AnyOf(
                    GroupPermission(amo.permissions.ADDONS_REVIEW_UNLISTED),
                    GroupPermission(amo.permissions.REVIEWER_TOOLS_UNLISTED_VIEW),
                    AllowAddonAuthor,
                )
            ]
        elif requested == 'all_without_unlisted':
            # To see all listed versions (not just public ones) you need to
            # be add-on author or reviewer.
            self.permission_classes = [
                AnyOf(
                    AllowListedViewerOrReviewer,
                    AllowUnlistedViewerOrReviewer,
                    AllowAddonAuthor,
                )
            ]
        # When listing, we can't use AllowRelatedObjectPermissions() with
        # check_permissions(), because AllowAddonAuthor needs an author to
        # do the actual permission check. To work around that, we call
        # super + check_object_permission() ourselves, passing down the
        # addon object directly.
        # Note that just calling get_addon_object() will trigger permission
        # checks on its own using AddonViewSet permission classes, regardless
        # of what permission classes are set on self.
        return super().check_object_permissions(request, self.get_addon_object())

    def check_object_permissions(self, request, obj):
        # If the instance is marked as deleted and the client is not allowed to
        # see deleted instances, we want to return a 404, behaving as if it
        # does not exist.
        if obj.deleted and not GroupPermission(
            amo.permissions.ADDONS_VIEW_DELETED
        ).has_object_permission(request, self, obj):
            raise http.Http404

        if obj.channel == amo.CHANNEL_UNLISTED:
            # If the instance is unlisted, only allow unlisted reviewers and
            # authors..
            self.permission_classes = [
                AllowRelatedObjectPermissions(
                    'addon', [AnyOf(AllowUnlistedViewerOrReviewer, AllowAddonAuthor)]
                )
            ]
        elif not obj.is_public():
            # If the instance is disabled, only allow reviewers and authors.
            self.permission_classes = [
                AllowRelatedObjectPermissions(
                    'addon', [AnyOf(AllowListedViewerOrReviewer, AllowAddonAuthor)]
                )
            ]

        super().check_object_permissions(request, obj)

    def get_queryset(self):
        """Return the right base queryset depending on the situation."""
        requested = self.request.GET.get('filter')
        valid_filters = (
            'all_with_deleted',
            'all_with_unlisted',
            'all_without_unlisted',
        )
        if requested is not None:
            if self.action != 'list':
                raise serializers.ValidationError(
                    'The "filter" parameter is not valid in this context.'
                )
            elif requested not in valid_filters:
                raise serializers.ValidationError(
                    'Invalid "filter" parameter specified.'
                )
        # When listing, by default we only want to return listed, approved
        # versions, matching frontend needs - this can be overridden by the
        # filter in use. When fetching a single instance however, we use the
        # same queryset as the less restrictive filter, that allows us to see
        # all versions, even deleted ones. In any case permission checks will
        # prevent access if necessary (meaning regular users will never see
        # deleted or unlisted versions regardless of the queryset being used).
        # We start with the <Addon>.versions manager in order to have the
        # `addon` property preloaded on each version we return.
        addon = self.get_addon_object()
        if requested == 'all_with_deleted' or self.action != 'list':
            queryset = addon.versions(manager='unfiltered_for_relations').all()
        elif requested == 'all_with_unlisted':
            queryset = addon.versions.all()
        elif requested == 'all_without_unlisted':
            queryset = addon.versions.filter(channel=amo.CHANNEL_LISTED)
        else:
            queryset = addon.versions.filter(
                file__status=amo.STATUS_APPROVED, channel=amo.CHANNEL_LISTED
            )
        queryset = queryset.select_related('file___webext_permissions')
        if (
            self.action == 'list'
            and self.request
            and not is_gate_active(self.request, 'keep-license-text-in-version-list')
        ):
            # When listing, we use the transformer_license (it's not active by default)
            # to fetch licenses & their translations in one (two with translations)
            # query regardless of the number of versions.
            # Note that this transformer defers text, which we don't need when listing.
            # This means we can't use it in API versions where the
            # 'keep-license-text-in-version-list' gate is active, so that endpoint
            # doesn't scale as nicely in those versions.
            queryset = queryset.transform(Version.transformer_license)
        return queryset

    def create(self, request, *args, **kwargs):
        addon = self.get_addon_object()
        has_source = request.data.get('source')
        if has_source:
            timer = StopWatch('addons.views.AddonVersionViewSet.create.')
            timer.start()
            log.info(
                'create, source upload received, addon.slug: %s',
                addon.slug,
            )
            timer.log_interval('1.source_received')

        serializer = self.get_serializer(data=request.data)
        if has_source:
            log.info(
                'create, serializer loaded, addon.slug: %s',
                addon.slug,
            )
            timer.log_interval('2.serializer_loaded')

        serializer.is_valid(raise_exception=True)
        if has_source:
            log.info(
                'create, serializer validated, addon.slug: %s',
                addon.slug,
            )
            timer.log_interval('3.serializer_validated')

        self.perform_create(serializer)
        if has_source:
            log.info(
                'create, data saved, addon.slug: %s',
                addon.slug,
            )
            timer.log_interval('4.data_saved')

        headers = self.get_success_headers(serializer.data)
        webext_version_stats(request, 'addons.submission')
        return Response(
            serializer.data, status=status.HTTP_201_CREATED, headers=headers
        )

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        addon = self.get_addon_object()
        has_source = request.data.get('source')
        if has_source:
            timer = StopWatch('addons.views.AddonVersionViewSet.update.')
            timer.start()
            log.info(
                'update, source upload received, addon.slug: %s, version.id: %s',
                addon.slug,
                instance.id,
            )
            timer.log_interval('1.source_received')

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        if has_source:
            log.info(
                'update, serializer loaded, addon.slug: %s, version.id: %s',
                addon.slug,
                instance.id,
            )
            timer.log_interval('2.serializer_loaded')

        serializer.is_valid(raise_exception=True)
        if has_source:
            log.info(
                'update, serializer validated, addon.slug: %s, version.id: %s',
                addon.slug,
                instance.id,
            )
            timer.log_interval('3.serializer_validated')

        self.perform_update(serializer)
        if has_source:
            log.info(
                'update, data saved, addon.slug: %s, version.id: %s',
                addon.slug,
                instance.id,
            )
            timer.log_interval('4.data_saved')

        if getattr(instance, '_prefetched_objects_cache', None):
            # If 'prefetch_related' has been applied to a queryset, we need to
            # forcibly invalidate the prefetch cache on the instance.
            instance._prefetched_objects_cache = {}

        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if not instance.can_be_disabled_and_deleted():
            group = self.get_addon_object().promoted_group()
            msg = gettext(
                'The latest approved version of this %s add-on cannot be deleted '
                'because the previous version was not approved for %s promotion. '
                'Please contact AMO Admins if you need help with this.'
            ) % (group.name, group.name)
            raise exceptions.ValidationError(msg)

        return super().destroy(request, *args, **kwargs)


class AddonPreviewViewSet(
    AddonChildMixin,
    CreateModelMixin,
    DestroyModelMixin,
    UpdateModelMixin,
    GenericViewSet,
):
    # Permissions are always checked against the parent add-on in
    # get_addon_object() using AddonViewSet's permissions so we don't need
    # to set any here.
    permission_classes = []
    authentication_classes = [
        JWTKeyAuthentication,
        SessionIDAuthentication,
    ]
    throttle_classes = addon_submission_throttles
    serializer_class = PreviewSerializer

    def check_permissions(self, request):
        # When listing, we can't use AllowRelatedObjectPermissions() with
        # check_permissions(), because AllowAddonAuthor needs an author to
        # do the actual permission check. To work around that, we call
        # super + check_object_permission() ourselves, passing down the
        # addon object directly.
        # Note that just calling get_addon_object() will trigger permission
        # checks on its own using AddonViewSet permission classes, regardless
        # of what permission classes are set on self.
        return super().check_object_permissions(request, self.get_addon_object())

    def get_queryset(self):
        return self.get_addon_object().previews.all()

    def perform_destroy(self, instance):
        super().perform_destroy(instance)
        ActivityLog.objects.create(
            amo.LOG.CHANGE_MEDIA, instance.addon, user=self.request.user
        )


class AddonAuthorViewSet(
    AddonChildMixin,
    ListModelMixin,
    RetrieveModelMixin,
    UpdateModelMixin,
    DestroyModelMixin,
    GenericViewSet,
):
    # We can't define permissions here because we need slightly different permissions
    # for list and get - see check_permissions and check_object_permissions. Permissions
    # are also always checked against the parent add-on in get_addon_object() using
    # AddonViewSet's permissions.
    permission_classes = [APIGatePermission('addon-submission-api'), IsAuthenticated]
    authentication_classes = [
        JWTKeyAuthentication,
        SessionIDAuthentication,
    ]
    throttle_classes = addon_submission_throttles
    serializer_class = AddonAuthorSerializer
    lookup_field = 'user__id'
    lookup_url_kwarg = 'user_id'
    pagination_class = None  # Add-ons don't have huge numbers of authors
    # We want unsafe actions to be restricted to owner role authors
    owner_actions = ('create', 'update', 'partial_update', 'destroy')

    def check_permissions(self, request):
        # When listing, we can't use AllowRelatedObjectPermissions() with
        # check_permissions(), because AllowAddonAuthor needs an author to do the actual
        # permission check. To work around that, we call super +
        # check_object_permission() ourselves, passing down the addon object directly.
        # We're overriding the permission_classes to restrict access to add-on authors.
        addon = self.get_addon_object(
            permission_classes=[
                AnyOf(
                    AllowAddonOwner
                    if self.action in self.owner_actions
                    else AllowAddonAuthor,
                    AllowListedViewerOrReviewer,
                    AllowUnlistedViewerOrReviewer,
                ),
            ]
        )
        return super().check_permissions(request) and super().check_object_permissions(
            request, addon
        )

    def get_queryset(self):
        return self.get_addon_object().addonuser_set.all().order_by('position')

    def _get_existing_author_emails(self):
        return self.get_addon_object().authors.values_list('email', flat=True)

    def perform_update(self, serializer):
        old_role = serializer.instance.role
        instance = serializer.save()
        if old_role != instance.role:
            send_addon_author_change_mail(instance, self._get_existing_author_emails())

    def perform_destroy(self, instance):
        if isinstance(instance, AddonUser):
            serializer = self.get_serializer(instance)
            serializer.validate_role(value=None)
            serializer.validate_listed(value=None)

        send_addon_author_remove_mail(instance, self._get_existing_author_emails())
        return super().perform_destroy(instance)


class AddonPendingAuthorViewSet(CreateModelMixin, AddonAuthorViewSet):
    serializer_class = AddonPendingAuthorSerializer

    def check_permissions(self, request):
        # confirm/decline needs to be actionable without being an addon author already
        if self.action in ('confirm', 'decline'):
            # .get_addon_object is cached so we just need to call without restricted
            # permission_classes first and it'll be used for subsequent calls too.
            self.get_addon_object(permission_classes=())

        return super().check_permissions(request)

    def get_queryset(self):
        return self.get_addon_object().addonuserpendingconfirmation_set.all()

    def get_object_for_request(self, request):
        try:
            return self.get_queryset().get(user=request.user)
        except AddonUserPendingConfirmation.DoesNotExist:
            raise exceptions.PermissionDenied()

    def perform_create(self, serializer):
        instance = serializer.save()
        send_addon_author_add_mail(instance, self._get_existing_author_emails())

    @action(detail=False, methods=('post',))
    def confirm(self, request, *args, **kwargs):
        pending = self.get_object_for_request(request)

        max_position = super().get_queryset().aggregate(max=Max('position'))['max'] or 0
        AddonUser.unfiltered.update_or_create(
            addon=pending.addon,
            user=pending.user,
            defaults={
                'role': pending.role,
                'listed': pending.listed,
                'position': max_position + 1,
            },
        )
        # The invitation is now obsolete.
        pending.delete()

        return Response()

    @action(detail=False, methods=('post',))
    def decline(self, request, *args, **kwargs):
        self.get_object_for_request(request).delete()
        return Response()


class AddonSearchView(ListAPIView):
    authentication_classes = []
    filter_backends = [
        ReviewedContentFilter,
        SearchQueryFilter,
        SearchParameterFilter,
        SortingFilter,
    ]
    pagination_class = ESPageNumberPagination
    permission_classes = []
    serializer_class = ESAddonSerializer

    def get_queryset(self):
        qset = (
            Search(
                using=get_es(),
                index=AddonIndexer.get_index_alias(),
            )
            .extra(
                _source={'excludes': AddonIndexer.hidden_fields}, track_total_hits=True
            )
            .params(search_type='dfs_query_then_fetch')
        )

        return qset

    @classmethod
    def as_view(cls, **kwargs):
        view = super().as_view(**kwargs)
        return non_atomic_requests(view)

    def get_data(self, count=None):
        self.initial(self.request)
        queryset = self.filter_queryset(self.get_queryset())
        if count:
            queryset = queryset[0:count]
        serializer = self.get_serializer(queryset, many=True)
        return serializer.data


class AddonAutoCompleteSearchView(AddonSearchView):
    pagination_class = None
    serializer_class = ESAddonAutoCompleteSerializer
    filter_backends = [
        ReviewedContentFilter,
        SearchQueryFilter,
        SearchParameterFilter,
        AutoCompleteSortFilter,
    ]

    def get_queryset(self):
        # Minimal set of fields from ES that we need to build our results.
        # It's the opposite tactic used by the regular search endpoint, which
        # excludes a specific set of fields - because we know that autocomplete
        # only needs to return very few things.
        included_fields = (
            'current_version',
            'icon_type',  # Needed for icon_url.
            'id',  # Needed for... id
            'modified',  # Needed for icon_url.
            'name_translations',  # Needed for... name.
            'promoted',  # Needed for promted badging.
            'default_locale',  # Needed for translations to work.
            'slug',  # Needed for url.
            'type',  # Needed to attach the Persona for icon_url (sadly).
        )

        qset = Search(
            using=get_es(),
            index=AddonIndexer.get_index_alias(),
        ).extra(_source={'includes': included_fields})

        return qset

    def list(self, request, *args, **kwargs):
        # Ignore pagination (slice directly) but do wrap the data in a
        # 'results' property to mimic what the search API does.
        queryset = self.filter_queryset(self.get_queryset())[:10]
        serializer = self.get_serializer(queryset, many=True)
        return Response({'results': serializer.data})


class AddonFeaturedView(AddonSearchView):
    """Featuring is gone, so this view is a hollowed out shim that returns
    recommended addons for api/v3."""

    # We accept the 'page_size' parameter but we do not allow pagination for
    # this endpoint since the order is random.
    pagination_class = None

    filter_backends = [
        ReviewedContentFilter,
        SearchParameterFilter,
    ]

    def get(self, request, *args, **kwargs):
        try:
            page_size = int(self.request.GET.get('page_size', api_settings.PAGE_SIZE))
        except ValueError:
            raise exceptions.ParseError('Invalid page_size parameter')

        # Simulate pagination-like results, without actual pagination.
        queryset = self.filter_queryset(self.get_queryset()[:page_size])
        serializer = self.get_serializer(queryset, many=True)
        return Response({'results': serializer.data})

    def filter_queryset(self, qs):
        qs = super().filter_queryset(qs)
        qs = qs.query(query.Bool(filter=[Q('term', is_recommended=True)]))
        return qs.query('function_score', functions=[query.SF('random_score')]).sort(
            '_score'
        )


class StaticCategoryView(ListAPIView):
    authentication_classes = []
    pagination_class = None
    permission_classes = []
    serializer_class = StaticCategorySerializer

    def get_queryset(self):
        return sorted(CATEGORIES_BY_ID.values(), key=lambda x: x.id)

    @classmethod
    def as_view(cls, **kwargs):
        view = super().as_view(**kwargs)
        return non_atomic_requests(view)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        patch_cache_control(response, max_age=60 * 60 * 6)
        return response


class LanguageToolsView(ListAPIView):
    authentication_classes = []
    pagination_class = None
    permission_classes = []
    serializer_class = LanguageToolsSerializer

    @classmethod
    def as_view(cls, **initkwargs):
        """The API is read-only so we can turn off atomic requests."""
        return non_atomic_requests(super().as_view(**initkwargs))

    def get_query_params(self):
        """
        Parse query parameters that this API supports:
        - app (ignored unless appversion, then mandatory)
        - type (optional)
        - appversion (optional, makes type mandatory)
        - author (optional)

        Can raise ParseError() in case a mandatory parameter is missing or a
        parameter is invalid.

        Returns a dict containing application (int), types (tuple or None),
        appversions (dict or None) and author (string or None).
        """
        # appversion parameter is optional.
        if AddonAppVersionQueryParam.query_param in self.request.GET:
            # app parameter is mandatory with appversion
            try:
                application = AddonAppQueryParam(self.request.GET).get_value()
            except ValueError:
                raise exceptions.ParseError(
                    'Invalid or missing app parameter while appversion parameter is '
                    'set.'
                )
            try:
                value = AddonAppVersionQueryParam(self.request.GET).get_values()
                appversions = {'min': value[1], 'max': value[2]}
            except ValueError:
                raise exceptions.ParseError('Invalid appversion parameter.')
        else:
            appversions = None
            application = None

        # type is optional, unless appversion is set. That's because the way
        # dicts and language packs have their compatibility info set in the
        # database differs, so to make things simpler for us we force clients
        # to filter by type if they want appversion filtering.
        if AddonTypeQueryParam.query_param in self.request.GET or appversions:
            try:
                addon_types = tuple(AddonTypeQueryParam(self.request.GET).get_values())
            except ValueError:
                raise exceptions.ParseError(
                    'Invalid or missing type parameter while appversion '
                    'parameter is set.'
                )
        else:
            addon_types = (amo.ADDON_LPAPP, amo.ADDON_DICT)

        # author is optional. It's a string representing the username(s) we're
        # filtering on.
        if AddonAuthorQueryParam.query_param in self.request.GET:
            authors = AddonAuthorQueryParam(self.request.GET).get_values()
        else:
            authors = None

        return {
            'application': application,
            'types': addon_types,
            'appversions': appversions,
            'authors': authors,
        }

    def get_queryset(self):
        """
        Return queryset to use for this view, depending on query parameters.
        """
        # application, addon_types, appversions
        params = self.get_query_params()
        if params['types'] == (amo.ADDON_LPAPP,) and params['appversions']:
            qs = self.get_language_packs_queryset_with_appversions(
                params['application'], params['appversions']
            )
        else:
            qs = self.get_queryset_base(params['types'])

        if params['authors']:
            qs = qs.filter(
                addonuser__user__username__in=params['authors'], addonuser__listed=True
            ).distinct()
        return qs

    def get_queryset_base(self, addon_types):
        """
        Return base queryset to be used as the starting point in both
        get_queryset() and get_language_packs_queryset_with_appversions().
        """
        return (
            Addon.objects.public()
            .filter(
                type__in=addon_types,
                target_locale__isnull=False,
            )
            .exclude(target_locale='')
            # Deactivate default transforms which fetch a ton of stuff we
            # don't need here like authors, previews or current version.
            # It would be nice to avoid translations entirely, because the
            # translations transformer is going to fetch a lot of translations
            # we don't need, but some language packs or dictionaries have
            # custom names, so we can't use a generic one for them...
            .only_translations()
            # FIXME: we want to prefetch file.webext_permission instances in here
            # Since we're fetching everything with no pagination, might as well
            # not order it.
            .order_by()
        )

    def get_language_packs_queryset_with_appversions(self, application, appversions):
        """
        Return queryset to use specifically when requesting language packs
        compatible with a given app + versions.

        application is an application id, and appversions is a dict with min
        and max keys pointing to application versions expressed as ints.
        """
        # Base queryset.
        qs = self.get_queryset_base((amo.ADDON_LPAPP,))
        # Version queryset we'll prefetch once for all results. We need to
        # find the ones compatible with the app+appversion requested, and we
        # can avoid loading translations by removing transforms and then
        # re-applying the default one that takes care of the compat info.
        versions_qs = (
            Version.objects.latest_public_compatible_with(application, appversions)
            .no_transforms()
            .transform(Version.transformer)
        )
        return (
            qs.prefetch_related(
                Prefetch(
                    'versions', to_attr='compatible_versions', queryset=versions_qs
                )
            )
            .filter(
                versions__apps__application=application,
                versions__apps__min__version_int__lte=appversions['min'],
                versions__apps__max__version_int__gte=appversions['max'],
                versions__channel=amo.CHANNEL_LISTED,
                versions__file__status=amo.STATUS_APPROVED,
            )
            .distinct()
        )

    def list(self, request, *args, **kwargs):
        # Ignore pagination (return everything) but do wrap the data in a
        # 'results' property to mimic what the default implementation of list()
        # does in DRF.
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)
        response = Response({'results': serializer.data})
        # Cache on the CDN/clients for 24 hours.
        patch_cache_control(response, max_age=60 * 60 * 24)
        return response


class ReplacementAddonView(ListAPIView):
    authentication_classes = []
    queryset = ReplacementAddon.objects.all()
    serializer_class = ReplacementAddonSerializer


class CompatOverrideView(APIView):
    """This view is used by Firefox but we don't have any more overrides so we
    just return an empty response.  This api is v3 only.
    """

    @classmethod
    def as_view(cls, **initkwargs):
        return non_atomic_requests(super().as_view(**initkwargs))

    def get(self, request, format=None):
        return Response({'results': []})


class AddonRecommendationView(AddonSearchView):
    filter_backends = [ReviewedContentFilter]
    ab_outcome = None
    fallback_reason = None
    pagination_class = None

    def get_paginated_response(self, data):
        data = data[:4]  # taar is only supposed to return 4 anyway.
        return Response(
            OrderedDict(
                [
                    ('outcome', self.ab_outcome),
                    ('fallback_reason', self.fallback_reason),
                    ('page_size', 1),
                    ('page_count', 1),
                    ('count', len(data)),
                    ('next', None),
                    ('previous', None),
                    ('results', data),
                ]
            )
        )

    def get_results_count(self, results):
        try:
            # Elasticsearch 7.x and higher
            total = results.hits.total['value']
        except TypeError:
            # Elasticsearch 6.x and lower
            total = results.hits.total
        return int(total)

    def filter_queryset(self, qs):
        qs = super().filter_queryset(qs)
        guid_param = self.request.GET.get('guid')
        if not guid_param or not amo.ADDON_GUID_PATTERN.match(guid_param):
            raise exceptions.ParseError('Invalid guid parameter')
        taar_enable = self.request.GET.get('recommended', '').lower() == 'true'
        guids, self.ab_outcome, self.fallback_reason = get_addon_recommendations(
            guid_param, taar_enable
        )
        recommended_qs = qs.query(query.Bool(must=[Q('terms', guid=guids)]))
        results = recommended_qs.execute()
        if self.get_results_count(results) != 4 and is_outcome_recommended(
            self.ab_outcome
        ):
            (
                guids,
                self.ab_outcome,
                self.fallback_reason,
            ) = get_addon_recommendations_invalid()
            return qs.query(query.Bool(must=[Q('terms', guid=guids)]))
        return results

    def paginate_queryset(self, queryset):
        # We don't need pagination for the fixed number of results.
        return queryset


class AddonBrowserMappingView(ListAPIView):
    authentication_classes = []
    serializer_class = AddonBrowserMappingSerializer
    pagination_class = LargePageNumberPagination

    def get(self, request, format=None):
        browser = self.request.query_params.get('browser', None)
        if browser not in list(BROWSERS.values()):
            raise exceptions.ParseError('Invalid browser parameter')

        response = super().get(request, format)
        # Cache for 24 hours.
        patch_cache_control(response, max_age=60 * 60 * 24)
        return response

    def get_queryset(self):
        browser = next(
            (
                key
                for key in BROWSERS
                if BROWSERS.get(key) == self.request.query_params.get('browser')
            ),
            None,
        )
        return AddonBrowserMapping.objects.filter(
            browser=browser,
            addon__status__in=amo.APPROVED_STATUSES,
            addon__disabled_by_user=False,
        ).annotate(
            # This is used in `AddonBrowserMappingSerializer` in order to avoid
            # unnecessary queries since we only need the add-on GUID.
            addon__guid=F('addon__guid')
        )

    @classmethod
    def as_view(cls, **initkwargs):
        """The API is read-only so we can turn off atomic requests."""
        return non_atomic_requests(super().as_view(**initkwargs))
