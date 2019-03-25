from django.conf import settings

import six

from rest_framework import serializers
from rest_framework.viewsets import ModelViewSet


from olympia import amo
from olympia.accounts.views import AccountViewSet
from olympia.addons.models import Addon
from olympia.api.filters import OrderingAliasFilter
from olympia.api.permissions import (
    AllOf, AllowReadOnlyIfPublic, AnyOf, PreventActionPermission)
from olympia.translations.query import order_by_translation

from .models import Collection, CollectionAddon
from .permissions import (
    AllowCollectionAuthor, AllowCollectionContributor, AllowContentCurators)
from .serializers import (
    CollectionAddonSerializer, CollectionSerializer,
    CollectionWithAddonsSerializer)


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
            AllOf(AllowCollectionContributor,
                  PreventActionPermission(('create', 'list', 'update',
                                           'destroy', 'partial_update'))),
            # Content curators can modify existing mozilla collections as they
            # see fit, but can't list or delete them.
            AllOf(AllowContentCurators,
                  PreventActionPermission(('create', 'destroy', 'list'))),
            # Everyone else can do read-only stuff, except list.
            AllOf(AllowReadOnlyIfPublic,
                  PreventActionPermission('list'))),
    ]
    lookup_field = 'slug'

    def get_account_viewset(self):
        if not hasattr(self, 'account_viewset'):
            self.account_viewset = AccountViewSet(
                request=self.request,
                permission_classes=[],  # We handled permissions already.
                kwargs={'pk': self.kwargs['user_pk']})
        return self.account_viewset

    def get_serializer_class(self):
        with_addons = ('with_addons' in self.request.GET and
                       self.action == 'retrieve')
        return (CollectionSerializer if not with_addons
                else CollectionWithAddonsSerializer)

    def get_queryset(self):
        return Collection.objects.filter(
            author=self.get_account_viewset().get_object()).order_by(
            '-modified')

    def get_addons_queryset(self):
        collection_addons_viewset = CollectionAddonViewSet(
            request=self.request
        )
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
                'orderings are not supported')

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
    ordering_field_aliases = {'popularity': 'addon__weekly_downloads',
                              'name': 'name',
                              'added': 'created'}
    ordering = ('-addon__weekly_downloads',)

    def get_collection(self):
        if not hasattr(self, 'collection'):
            # We're re-using CollectionViewSet and making sure its get_object()
            # method is called, which triggers the permission checks for that
            # class so we don't need our own.
            # Note that we don't pass `action`, so the PreventActionPermission
            # part of the permission checks won't do anything.
            self.collection = CollectionViewSet(
                request=self.request,
                kwargs={'user_pk': self.kwargs['user_pk'],
                        'slug': self.kwargs['collection_slug']}).get_object()
        return self.collection

    def get_object(self):
        self.lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_value = self.kwargs.get(self.lookup_url_kwarg)
        # if the lookup is not a number, its probably the slug instead.
        if lookup_value and not six.text_type(lookup_value).isdigit():
            self.lookup_field = '%s__slug' % self.lookup_field
        return super(CollectionAddonViewSet, self).get_object()

    def get_queryset(self):
        qs = (
            CollectionAddon.objects
            .filter(collection=self.get_collection())
            .prefetch_related('addon'))

        filter_param = self.request.GET.get('filter')
        # We only filter list action.
        include_all_with_deleted = (filter_param == 'all_with_deleted' or
                                    self.action != 'list')
        # If deleted addons are requested, that implies all addons.
        include_all = filter_param == 'all' or include_all_with_deleted

        if not include_all:
            qs = qs.filter(
                addon__status=amo.STATUS_PUBLIC, addon__disabled_by_user=False)
        elif not include_all_with_deleted:
            qs = qs.exclude(addon__status=amo.STATUS_DELETED)
        return qs
