from django.http import HttpResponse
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

from rest_framework import serializers
from rest_framework.viewsets import ModelViewSet

from olympia import amo
from olympia.accounts.views import AccountViewSet
from olympia.addons.models import Addon, attach_tags
from olympia.amo.utils import attach_trans_dict
from olympia.api.filters import OrderingAliasFilter
from olympia.api.permissions import (
    AllOf,
    AllowReadOnlyIfPublic,
    AnyOf,
    PreventActionPermission,
)
from olympia.versions.models import License, Version
from olympia.translations.query import order_by_translation

from .models import Collection, CollectionAddon
from .permissions import (
    AllowCollectionAuthor,
    AllowCollectionContributor,
    AllowContentCurators,
)
from .serializers import (
    CollectionAddonSerializer,
    CollectionSerializer,
    CollectionWithAddonsSerializer,
)


class CollectionViewSet(ModelViewSet):
    # Note: CollectionAddonViewSet will call CollectionViewSet().get_object(),
    # causing the has_object_permission() method of these permissions to be
    # called. It will do so without setting an action however, bypassing the
    # PreventActionPermission() parts.
    permission_classes = [
        AnyOf(
            # Collection authors can do everything.
            AllowCollectionAuthor,
            # Collection contributors can access the featured themes collection
            # (it's community-managed) and change it's addons, but can't delete
            # or edit it's details.
            AllOf(
                AllowCollectionContributor,
                PreventActionPermission(
                    ('create', 'list', 'update', 'destroy', 'partial_update')
                ),
            ),
            # Content curators can modify existing mozilla collections as they
            # see fit, but can't list or delete them.
            AllOf(
                AllowContentCurators,
                PreventActionPermission(('create', 'destroy', 'list')),
            ),
            # Everyone else can do read-only stuff, except list.
            AllOf(AllowReadOnlyIfPublic, PreventActionPermission('list')),
        ),
    ]
    lookup_field = 'slug'

    def get_account_viewset(self):
        if not hasattr(self, 'account_viewset'):
            self.account_viewset = AccountViewSet(
                request=self.request,
                permission_classes=[],  # We handled permissions already.
                kwargs={'pk': self.kwargs['user_pk']},
            )
        return self.account_viewset

    def get_serializer_class(self):
        with_addons = 'with_addons' in self.request.GET and self.action == 'retrieve'
        return (
            CollectionSerializer if not with_addons else CollectionWithAddonsSerializer
        )

    def get_queryset(self):
        return Collection.objects.filter(
            author=self.get_account_viewset().get_object()
        ).order_by('-modified')

    def get_addons_queryset(self):
        collection_addons_viewset = CollectionAddonViewSet(request=self.request)
        # Set this to avoid a pointless lookup loop.
        collection_addons_viewset.collection = self.get_object()
        # This needs to be list to make the filtering work.
        collection_addons_viewset.action = 'list'
        qs = collection_addons_viewset.get_queryset()
        # Now limit and sort
        limit = settings.REST_FRAMEWORK['PAGE_SIZE']
        sort = collection_addons_viewset.ordering[0]
        return qs.order_by(sort)[:limit]


class TranslationAwareOrderingAliasFilter(OrderingAliasFilter):
    def filter_queryset(self, request, queryset, view):
        ordering = self.get_ordering(request, queryset, view)

        if len(ordering) > 1:
            # We can't support multiple orderings easily because of
            # how order_by_translation works.
            raise serializers.ValidationError(
                'You can only specify one "sort" argument. Multiple '
                'orderings are not supported'
            )

        order_by = ordering[0]

        if order_by in ('name', '-name'):
            return order_by_translation(queryset, order_by, Addon)

        sup = super(TranslationAwareOrderingAliasFilter, self)
        return sup.filter_queryset(request, queryset, view)


class CollectionAddonViewSet(ModelViewSet):
    permission_classes = []  # We don't need extra permissions.
    serializer_class = CollectionAddonSerializer
    lookup_field = 'addon'
    filter_backends = (TranslationAwareOrderingAliasFilter,)
    ordering_fields = ()
    ordering_field_aliases = {
        'popularity': 'addon__weekly_downloads',
        'name': 'name',
        'added': 'created',
    }
    ordering = ('-addon__weekly_downloads',)

    @method_decorator(cache_page(60 * 60 * 1))
    def _cached_list(self, request, *args, **kwargs):
        # Swap DRF's Response with a HttpResponse so that it's smaller in size
        # when pickling (data attribute is lost, we only keep the rendered
        # content), which matters because by default, memcached doesn't
        # accept values over 1 MB.
        # Note that this needs to happen inside the method that is decorated
        # by cache_page(), because cache_page() attaches the callback that does
        # the caching to the response returned by the function/method it
        # decorates. That's why we manually call finalize_response() and
        # render() here.
        response = super().list(*args, *kwargs)
        response = self.finalize_response(request, response, *args, **kwargs)
        response.render()
        return HttpResponse(
            response.content,
            status=response.status_code,
            content_type='application/json',
        )

    def list(self, request, *args, **kwargs):
        # This endpoint can be quite slow so we cache the most popular
        # collections - those from mozilla - for all anonymous users for one
        # hour.
        if (
            self.kwargs['user_pk'] in ('mozilla', str(settings.TASK_USER_ID))
            and not request.user.is_authenticated
        ):
            return self._cached_list(request, *args, **kwargs)
        else:
            return super().list(request, *args, *kwargs)

    def get_collection(self):
        if not hasattr(self, 'collection'):
            # We're re-using CollectionViewSet and making sure its get_object()
            # method is called, which triggers the permission checks for that
            # class so we don't need our own.
            # Note that we don't pass `action`, so the PreventActionPermission
            # part of the permission checks won't do anything.
            self.collection = CollectionViewSet(
                request=self.request,
                kwargs={
                    'user_pk': self.kwargs['user_pk'],
                    'slug': self.kwargs['collection_slug'],
                },
            ).get_object()
        return self.collection

    def get_object(self):
        self.lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_value = self.kwargs.get(self.lookup_url_kwarg)
        # if the lookup is not a number, its probably the slug instead.
        if lookup_value and not str(lookup_value).isdigit():
            self.lookup_field = '%s__slug' % self.lookup_field
        return super().get_object()

    @classmethod
    def _transformer(self, objs):
        current_versions = [
            obj.addon._current_version for obj in objs if obj.addon._current_version
        ]
        addons = [obj.addon for obj in objs]
        Version.transformer_promoted(current_versions)
        Version.transformer_license(current_versions)
        attach_tags(addons)

    @classmethod
    def _locales_transformer(self, objs):
        current_versions = [
            obj.addon._current_version for obj in objs if obj.addon._current_version
        ]
        addons = [obj.addon for obj in objs]
        attach_trans_dict(CollectionAddon, objs)
        attach_trans_dict(Addon, addons)
        attach_trans_dict(License, [ver.license for ver in current_versions])

    def get_queryset(self):
        qs = (
            CollectionAddon.objects.filter(collection=self.get_collection())
            .prefetch_related('addon__promotedaddon')
            .transform(self._transformer)
        )

        if 'lang' not in self.request.GET:
            qs = qs.transform(self._locales_transformer)

        filter_param = self.request.GET.get('filter')
        # We only filter list action.
        include_all_with_deleted = (
            filter_param == 'all_with_deleted' or self.action != 'list'
        )
        # If deleted addons are requested, that implies all addons.
        include_all = filter_param == 'all' or include_all_with_deleted

        if not include_all:
            qs = qs.filter(
                addon__status=amo.STATUS_APPROVED, addon__disabled_by_user=False
            )
        elif not include_all_with_deleted:
            qs = qs.exclude(addon__status=amo.STATUS_DELETED)
        return qs

    def get_data(self, count=None):
        self.initial(self.request)
        queryset = self.filter_queryset(self.get_queryset())
        if count:
            queryset = queryset[0:count]
        serializer = self.get_serializer(queryset, many=True)
        return serializer.data
