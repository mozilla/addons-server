from django.db.models import Prefetch, Q
from django.utils.encoding import force_text

from rest_framework import serializers
from rest_framework.decorators import action
from rest_framework.exceptions import (
    NotAuthenticated, ParseError, PermissionDenied)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import HTTP_202_ACCEPTED
from rest_framework.viewsets import ModelViewSet

from olympia import amo
from olympia.access import acl
from olympia.addons.views import AddonChildMixin
from olympia.api.pagination import OneOrZeroPageNumberPagination
from olympia.api.permissions import (
    AllowAddonAuthor, AllowIfPublic, AllowNotOwner, AllowOwner,
    AllowRelatedObjectPermissions, AnyOf, ByHttpMethod, GroupPermission)
from olympia.api.throttling import GranularUserRateThrottle
from olympia.api.utils import is_gate_active

from .models import GroupedRating, Rating, RatingFlag, RatingVote
from .permissions import CanDeleteRatingPermission, CanVoteRatingPermission
from .serializers import (
    RatingFlagSerializer, RatingSerializer,
    RatingSerializerReply, RatingVoteSerializer)


class RatingThrottle(GranularUserRateThrottle):
    rate = '1/minute'
    scope = 'user_rating'

    def allow_request(self, request, view):
        if request.method.lower() == 'post':
            return super(RatingThrottle, self).allow_request(request, view)
        else:
            return True


class RatingReplyThrottle(RatingThrottle):
    rate = '1/5second'


class RatingViewSet(AddonChildMixin, ModelViewSet):
    serializer_class = RatingSerializer
    permission_classes = [
        ByHttpMethod({
            'get': AllowAny,
            'head': AllowAny,
            'options': AllowAny,  # Needed for CORS.

            # Deletion requires a specific permission check.
            'delete': CanDeleteRatingPermission,

            # To post a rating you just need to be authenticated.
            'post': IsAuthenticated,

            # To edit a rating you need to be the author or be an admin.
            'patch': AnyOf(AllowOwner, GroupPermission(
                amo.permissions.ADDONS_EDIT)),

            # Implementing PUT would be a little incoherent as we don't want to
            # allow users to change `version` but require it at creation time.
            # So only PATCH is allowed for editing.
        }),
    ]
    reply_permission_classes = [AnyOf(
        GroupPermission(amo.permissions.ADDONS_EDIT),
        AllowRelatedObjectPermissions('addon', [AllowAddonAuthor]),
    )]
    reply_serializer_class = RatingSerializerReply
    flag_permission_classes = [AllowNotOwner]
    throttle_classes = (RatingThrottle,)
    vote_permission_classes = [CanVoteRatingPermission]

    def set_addon_object_from_rating(self, rating):
        """Set addon object on the instance from a rating object."""
        # At this point it's likely we didn't have an addon in the request, so
        # if we went through get_addon_object() before it's going to be set
        # to None already. We delete the addon_object property cache and set
        # addon_pk in kwargs to force get_addon_object() to reset
        # self.addon_object.
        del self.addon_object
        self.kwargs['addon_pk'] = str(rating.addon.pk)
        return self.get_addon_object()

    def get_addon_object(self):
        """Return addon object associated with the request, or None if not
        relevant.

        Will also fire permission checks on the addon object when it's loaded.
        """
        if hasattr(self, 'addon_object'):
            return self.addon_object

        if 'addon_pk' not in self.kwargs:
            self.kwargs['addon_pk'] = (
                self.request.data.get('addon') or
                self.request.GET.get('addon'))
        if not self.kwargs['addon_pk']:
            # If we don't have an addon object, set it as None on the instance
            # and return immediately, that's fine.
            self.addon_object = None
            return
        else:
            # AddonViewSet.get_lookup_field() expects a string.
            self.kwargs['addon_pk'] = force_text(self.kwargs['addon_pk'])
        # When loading the add-on, pass a specific permission class - the
        # default from AddonViewSet is too restrictive, we are not modifying
        # the add-on itself so we don't need all the permission checks it does.
        return super(RatingViewSet, self).get_addon_object(
            permission_classes=[AllowIfPublic])

    def should_include_flags(self):
        if not hasattr(self, '_should_include_flags'):
            request = self.request
            self._should_include_flags = (
                'show_flags_for' in request.GET and
                not is_gate_active(request, 'del-ratings-flags')
            )
            if self._should_include_flags:
                # Check the parameter was sent correctly
                try:
                    show_flags_for = (
                        serializers.IntegerField().to_internal_value(
                            request.GET['show_flags_for']))
                    if show_flags_for != request.user.pk:
                        raise serializers.ValidationError
                except serializers.ValidationError:
                    raise ParseError(
                        'show_flags_for parameter value should be equal to '
                        'the user id of the authenticated user')
        return self._should_include_flags

    def check_permissions(self, request):
        """Perform permission checks.

        The regular DRF permissions checks are made, but also, before that, if
        an addon was requested, verify that it exists, is public and listed,
        through AllowIfPublic permission, that get_addon_object() uses."""
        self.get_addon_object()

        # Proceed with the regular permission checks.
        return super(RatingViewSet, self).check_permissions(request)

    def get_serializer(self, *args, **kwargs):
        if self.action in ('partial_update', 'update'):
            instance = args[0]
            if instance.reply_to is not None:
                self.rating_object = instance.reply_to
                self.serializer_class = self.reply_serializer_class
        return super(RatingViewSet, self).get_serializer(*args, **kwargs)

    def filter_queryset(self, qs):
        if self.action == 'list':
            addon_identifier = self.request.GET.get('addon')
            user_identifier = self.request.GET.get('user')
            version_identifier = self.request.GET.get('version')
            score_filter = (
                self.request.GET.get('score')
                if is_gate_active(self.request, 'ratings-score-filter')
                else None)
            exclude_ratings = self.request.GET.get('exclude_ratings')
            if addon_identifier:
                qs = qs.filter(addon=self.get_addon_object())
            if user_identifier:
                try:
                    user_identifier = int(user_identifier)
                except ValueError:
                    raise ParseError('user parameter should be an integer.')
                qs = qs.filter(user=user_identifier)
            if version_identifier:
                try:
                    version_identifier = int(version_identifier)
                except ValueError:
                    raise ParseError('version parameter should be an integer.')
                qs = qs.filter(version=version_identifier)
            elif addon_identifier:
                # When filtering on addon but not on version, only return the
                # latest rating posted by each user.
                qs = qs.filter(is_latest=True)
            if not addon_identifier and not user_identifier:
                # Don't allow listing ratings without filtering by add-on or
                # user.
                raise ParseError('Need an addon or user parameter')
            if user_identifier and addon_identifier and version_identifier:
                # When user, addon and version identifiers are set, we are
                # effectively only looking for one or zero objects. Fake
                # pagination in that case, avoiding all count() calls and
                # therefore related cache-machine invalidation issues. Needed
                # because the frontend wants to call this before and after
                # having posted a new rating, and needs accurate results.
                self.pagination_class = OneOrZeroPageNumberPagination
            if score_filter:
                try:
                    scores = [int(score) for score in score_filter.split(',')]
                except ValueError:
                    raise ParseError(
                        'score parameter should be an integer or a list of '
                        'integers (separated by a comma).')
                qs = qs.filter(rating__in=scores)
            if exclude_ratings:
                try:
                    exclude_ratings = [
                        int(rating) for rating in exclude_ratings.split(',')
                    ]
                except ValueError:
                    raise ParseError('exclude_ratings parameter should be an '
                                     'integer or a list of integers '
                                     '(separated by a comma).')
                qs = qs.exclude(pk__in=exclude_ratings)
        return super(RatingViewSet, self).filter_queryset(qs)

    def get_paginated_response(self, data):
        request = self.request
        extra_data = {}
        if 'show_grouped_ratings' in request.GET:
            try:
                show_grouped_ratings = (
                    serializers.BooleanField().to_internal_value(
                        request.GET['show_grouped_ratings']))
            except serializers.ValidationError:
                raise ParseError(
                    'show_grouped_ratings parameter should be a boolean')
            if show_grouped_ratings and self.get_addon_object():
                extra_data['grouped_ratings'] = dict(GroupedRating.get(
                    self.addon_object.id))
        if ('show_permissions_for' in request.GET and
                is_gate_active(self.request, 'ratings-can_reply')):
            if 'addon' not in request.GET:
                raise ParseError(
                    'show_permissions_for parameter is only valid if the '
                    'addon parameter is also present')
            try:
                show_permissions_for = (
                    serializers.IntegerField().to_internal_value(
                        request.GET['show_permissions_for']))
                if show_permissions_for != request.user.pk:
                    raise serializers.ValidationError
            except serializers.ValidationError:
                raise ParseError(
                    'show_permissions_for parameter value should be equal to '
                    'the user id of the authenticated user')
            extra_data['can_reply'] = (
                self.check_can_reply_permission_for_ratings_list())
        # Call this here so the validation checks on the `show_flags_for` are
        # carried out even when there are no results to serialize.
        self.should_include_flags()
        response = super(RatingViewSet, self).get_paginated_response(data)
        if extra_data:
            response.data.update(extra_data)
        return response

    def check_can_reply_permission_for_ratings_list(self):
        """Check whether or not the current request contains an user that can
        reply to ratings we're about to return.

        Used to populate the `can_reply` property in ratings list, when an
        addon is passed."""
        # Clone the current viewset, but change permission_classes.
        viewset = self.__class__(**self.__dict__)
        viewset.permission_classes = self.reply_permission_classes

        # Create a fake rating with the addon object attached, to be passed to
        # check_object_permissions().
        dummy_rating = Rating(addon=self.get_addon_object())

        try:
            viewset.check_permissions(self.request)
            viewset.check_object_permissions(self.request, dummy_rating)
            return True
        except (PermissionDenied, NotAuthenticated):
            return False

    def check_can_vote_permission_for_ratings_list(self):
        """Check whether or not the current request contains an user that can
        vote to ratings we're about to return.

        Used to populate the `can_vote` property in ratings list, when an
        addon is passed."""
        # Clone the current viewset, but change permission_classes.
        viewset = self.__class__(**self.__dict__)
        viewset.permission_classes = self.vote_permission_classes

        # Create a fake rating with the addon object attached, to be passed to
        # check_object_permissions().
        dummy_rating = Rating(addon=self.get_addon_object())

        try:
            viewset.check_permissions(self.request)
            viewset.check_object_permissions(self.request, dummy_rating)
            return True
        except (PermissionDenied, NotAuthenticated):
            return False

    def get_queryset(self):
        requested = self.request.GET.get('filter', '').split(',')
        has_addons_edit = acl.action_allowed(self.request,
                                             amo.permissions.ADDONS_EDIT)

        # Add this as a property of the view, because we need to pass down the
        # information to the serializer to show/hide delete replies.
        if not hasattr(self, 'should_access_deleted_ratings'):
            self.should_access_deleted_ratings = (
                ('with_deleted' in requested or self.action != 'list') and
                self.request.user.is_authenticated and
                has_addons_edit)

        should_access_only_top_level_ratings = (
            self.action == 'list' and self.get_addon_object())

        if self.should_access_deleted_ratings:
            # For admins or add-on authors replying. When listing, we include
            # deleted ratings but still filter out out replies, because they'll
            # be in the serializer anyway. For other actions, we simply remove
            # any filtering, allowing them to access any rating out of the box
            # with no extra parameter needed.
            if self.action == 'list':
                queryset = Rating.unfiltered.filter(reply_to__isnull=True)
            else:
                queryset = Rating.unfiltered.all()
        elif should_access_only_top_level_ratings:
            # When listing add-on ratings, exclude replies, they'll be
            # included during serialization as children of the relevant
            # ratings instead.
            queryset = Rating.without_replies.all()
        else:
            queryset = Rating.objects.all()

        # Filter out empty ratings if specified.
        # Should the users own empty ratings be filtered back in?
        if 'with_yours' in requested and self.request.user.is_authenticated:
            user_filter = Q(user=self.request.user.pk)
        else:
            user_filter = Q()
        # Apply the filter(s)
        if 'without_empty_body' in requested:
            queryset = queryset.filter(~Q(body=None) | user_filter)

        # The serializer needs reply, version and user. We don't need much
        # for version and user, so we can make joins with select_related(),
        # but for replies additional queries will be made for translations
        # anyway so we're better off using prefetch_related() to make a
        # separate query to fetch them all.
        queryset = queryset.select_related('version', 'user')
        replies_qs = Rating.unfiltered.select_related('user')
        return queryset.prefetch_related(
            Prefetch('reply', queryset=replies_qs))

    @action(
        detail=True, methods=['post'],
        permission_classes=reply_permission_classes,
        serializer_class=reply_serializer_class,
        throttle_classes=[RatingReplyThrottle])
    def reply(self, *args, **kwargs):
        # A reply is just like a regular post, except that we set the reply
        # FK to the current rating object and only allow add-on authors/admins.
        # Call get_object() to trigger 404 if it does not exist.
        self.rating_object = self.get_object()
        self.set_addon_object_from_rating(self.rating_object)
        if Rating.unfiltered.filter(reply_to=self.rating_object).exists():
            # A reply already exists, just edit it.
            # We set should_access_deleted_ratings so that it works even if
            # the reply has been deleted.
            self.kwargs['pk'] = kwargs['pk'] = self.rating_object.reply.pk
            self.should_access_deleted_ratings = True
            return self.partial_update(*args, **kwargs)
        return self.create(*args, **kwargs)

    @action(
        detail=True, methods=['post'],
        permission_classes=vote_permission_classes,
        # serializer_class=reply_serializer_class,
        throttle_classes=[])
    def vote(self, request, *args, **kwargs):
        # We load the add-on object from the rating to trigger permission
        # checks.
        self.rating_object = self.get_object()
        self.set_addon_object_from_rating(self.rating_object)

        try:
            vote_instance = RatingVote.objects.get(
                rating=self.rating_object, user=self.request.user)
        except RatingVote.DoesNotExist:
            vote_instance = None
        if vote_instance is None:
            serializer = RatingVoteSerializer(
                data=request.data, context=self.get_serializer_context())
        else:
            serializer = RatingVoteSerializer(
                vote_instance, data=request.data, partial=False,
                context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        # TODO:
        # "Traceback (most recent call last):\n  File \"/deps/lib/python3.6/site-packages/django/db/backends/mysql/base.py\", line 71, in execute\n    return self.cursor.execute(query, args)\n  File \"/deps/lib/python3.6/site-packages/MySQLdb/cursors.py\", line 209, in execute\n    res = self._query(query)\n  File \"/deps/lib/python3.6/site-packages/MySQLdb/cursors.py\", line 315, in _query\n    db.query(q)\n  File \"/deps/lib/python3.6/site-packages/MySQLdb/connections.py\", line 239, in query\n    _mysql.connection.query(self, query)\nMySQLdb._exceptions.OperationalError: (1048, \"Column 'addon_id' cannot be null\")\n\nDuring handling of the above exception, another exception occurred:\n\nTraceback (most recent call last):\n  File \"/deps/lib/python3.6/site-packages/rest_framework/views.py\", line 502, in dispatch\n    response = handler(request, *args, **kwargs)\n  File \"/code/src/olympia/ratings/views.py\", line 395, in vote\n    serializer.save()\n  File \"/code/src/olympia/ratings/serializers.py\", line 264, in save\n    instance = super().save(**kwargs)\n  File \"/deps/lib/python3.6/site-packages/rest_framework/serializers.py\", line 212, in save\n    self.instance = self.create(validated_data)\n  File \"/deps/lib/python3.6/site-packages/rest_framework/serializers.py\", line 948, in create\n    instance = ModelClass._default_manager.create(**validated_data)\n  File \"/deps/lib/python3.6/site-packages/django/db/models/manager.py\", line 82, in manager_method\n    return getattr(self.get_queryset(), name)(*args, **kwargs)\n  File \"/deps/lib/python3.6/site-packages/django/db/models/query.py\", line 422, in create\n    obj.save(force_insert=True, using=self.db)\n  File \"/code/src/olympia/amo/models.py\", line 346, in save\n    return super(SaveUpdateMixin, self).save(**kwargs)\n  File \"/deps/lib/python3.6/site-packages/django/db/models/base.py\", line 741, in save\n    force_update=force_update, update_fields=update_fields)\n  File \"/deps/lib/python3.6/site-packages/django/db/models/base.py\", line 779, in save_base\n    force_update, using, update_fields,\n  File \"/deps/lib/python3.6/site-packages/django/db/models/base.py\", line 870, in _save_table\n    result = self._do_insert(cls._base_manager, using, fields, update_pk, raw)\n  File \"/deps/lib/python3.6/site-packages/django/db/models/base.py\", line 908, in _do_insert\n    using=using, raw=raw)\n  File \"/deps/lib/python3.6/site-packages/django/db/models/manager.py\", line 82, in manager_method\n    return getattr(self.get_queryset(), name)(*args, **kwargs)\n  File \"/deps/lib/python3.6/site-packages/django/db/models/query.py\", line 1186, in _insert\n    return query.get_compiler(using=using).execute_sql(return_id)\n  File \"/deps/lib/python3.6/site-packages/django/db/models/sql/compiler.py\", line 1375, in execute_sql\n    cursor.execute(sql, params)\n  File \"/deps/lib/python3.6/site-packages/debug_toolbar/panels/sql/tracking.py\", line 198, in execute\n    return self._record(self.cursor.execute, sql, params)\n  File \"/deps/lib/python3.6/site-packages/debug_toolbar/panels/sql/tracking.py\", line 133, in _record\n    return method(sql, params)\n  File \"/deps/lib/python3.6/site-packages/django/db/backends/utils.py\", line 99, in execute\n    return super().execute(sql, params)\n  File \"/deps/lib/python3.6/site-packages/raven/contrib/django/client.py\", line 127, in execute\n    return real_execute(self, sql, params)\n  File \"/deps/lib/python3.6/site-packages/django/db/backends/utils.py\", line 67, in execute\n    return self._execute_with_wrappers(sql, params, many=False, executor=self._execute)\n  File \"/deps/lib/python3.6/site-packages/django/db/backends/utils.py\", line 76, in _execute_with_wrappers\n    return executor(sql, params, many, context)\n  File \"/deps/lib/python3.6/site-packages/django/db/backends/utils.py\", line 84, in _execute\n    return self.cursor.execute(sql, params)\n  File \"/deps/lib/python3.6/site-packages/django/db/backends/mysql/base.py\", line 76, in execute\n    raise utils.IntegrityError(*tuple(e.args))\ndjango.db.utils.IntegrityError: (1048, \"Column 'addon_id' cannot be null\")\n"
        #
        # vote = serializer.is_voted()
        # if vote is None:
        #     create
        # else:
        #     if vote
        serializer.save()
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=HTTP_202_ACCEPTED, headers=headers)

    @action(
        detail=True, methods=['post'],
        permission_classes=flag_permission_classes,
        throttle_classes=[])
    def flag(self, request, *args, **kwargs):
        # We load the add-on object from the rating to trigger permission
        # checks.
        self.rating_object = self.get_object()
        self.set_addon_object_from_rating(self.rating_object)

        try:
            flag_instance = RatingFlag.objects.get(
                rating=self.rating_object, user=self.request.user)
        except RatingFlag.DoesNotExist:
            flag_instance = None
        if flag_instance is None:
            serializer = RatingFlagSerializer(
                data=request.data, context=self.get_serializer_context())
        else:
            serializer = RatingFlagSerializer(
                flag_instance, data=request.data, partial=False,
                context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        serializer.save()
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data, status=HTTP_202_ACCEPTED, headers=headers)

    def perform_destroy(self, instance):
        instance.delete(user_responsible=self.request.user)

