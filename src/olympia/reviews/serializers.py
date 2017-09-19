import re
from urllib2 import unquote

from django.utils.translation import ugettext

from rest_framework import serializers
from rest_framework.relations import PrimaryKeyRelatedField

from olympia.accounts.serializers import BaseUserSerializer
from olympia.addons.serializers import SimpleVersionSerializer
from olympia.reviews.forms import ReviewForm
from olympia.reviews.models import Review
from olympia.versions.models import Version


class BaseReviewSerializer(serializers.ModelSerializer):
    # title and body are TranslatedFields, but there is never more than one
    # translation for each review - it's essentially useless. Because of that
    # we use a simple CharField in the API, hiding the fact that it's a
    # TranslatedField underneath.
    addon = serializers.SerializerMethodField()
    body = serializers.CharField(allow_null=True, required=False)
    is_latest = serializers.BooleanField(read_only=True)
    previous_count = serializers.IntegerField(read_only=True)
    title = serializers.CharField(allow_null=True, required=False)
    user = BaseUserSerializer(read_only=True)

    class Meta:
        model = Review
        fields = ('id', 'addon', 'body', 'created', 'is_latest',
                  'previous_count', 'title', 'user')

    def get_addon(self, obj):
        # We only return the addon id and slug for convenience, so just return
        # them directly to avoid instantiating a full serializer. Also avoid
        # database queries if possible by re-using the addon object from the
        # view if there is one.
        addon = self.context['view'].get_addon_object() or obj.addon

        return {
            'id': addon.id,
            'slug': addon.slug
        }

    def validate(self, data):
        data = super(BaseReviewSerializer, self).validate(data)
        request = self.context['request']

        data['user_responsible'] = request.user

        # There are a few fields that need to be set at creation time and never
        # modified afterwards:
        if not self.partial:
            # Because we want to avoid extra queries, addon is a
            # SerializerMethodField, which means it needs to be validated
            # manually. Fortunately the view does most of the work for us.
            data['addon'] = self.context['view'].get_addon_object()
            if data['addon'] is None:
                raise serializers.ValidationError(
                    {'addon': ugettext('This field is required.')})

            # Get the user from the request, don't allow clients to pick one
            # themselves.
            data['user'] = request.user

            # Also include the user ip adress.
            data['ip_address'] = request.META.get('REMOTE_ADDR', '')
        else:
            # When editing, you can't change the add-on.
            if self.context['request'].data.get('addon'):
                raise serializers.ValidationError(
                    {'addon': ugettext(
                        u'You can\'t change the add-on of a review once'
                        u' it has been created.')})

        # Clean up body and automatically flag the review if an URL was in it.
        body = data.get('body', '')
        if body:
            if '<br>' in body:
                data['body'] = re.sub('<br>', '\n', body)
            # Unquote the body when searching for links, in case someone tries
            # 'example%2ecom'.
            if ReviewForm.link_pattern.search(unquote(body)) is not None:
                data['flag'] = True
                data['editorreview'] = True

        return data


class ReviewSerializerReply(BaseReviewSerializer):
    """Serializer used for replies only."""
    body = serializers.CharField(
        allow_null=False, required=True, allow_blank=False)

    def to_representation(self, obj):
        should_access_deleted = getattr(
            self.context['view'], 'should_access_deleted_reviews', False)
        if obj.deleted and not should_access_deleted:
            return None
        return super(ReviewSerializerReply, self).to_representation(obj)

    def validate(self, data):
        # review_object is set on the view by the reply() method.
        data['reply_to'] = self.context['view'].review_object

        # When a reply is made on top of an existing deleted reply, we make
        # an edit instead, so we need to make sure `deleted` is reset.
        data['deleted'] = False

        if data['reply_to'].reply_to:
            # Only one level of replying is allowed, so if it's already a
            # reply, we shouldn't allow that.
            msg = ugettext(
                u'You can\'t reply to a review that is already a reply.')
            raise serializers.ValidationError(msg)

        data = super(ReviewSerializerReply, self).validate(data)
        return data


class ReviewVersionSerializer(SimpleVersionSerializer):

    class Meta:
        model = Version
        fields = ('id', 'version')

    def to_internal_value(self, data):
        """Resolve the version only by `id`."""
        # Version queryset is unfiltered, the version is checked more
        # thoroughly in `ReviewSerializer.validate()` method.
        field = PrimaryKeyRelatedField(queryset=Version.unfiltered)
        return field.to_internal_value(data)


class ReviewSerializer(BaseReviewSerializer):
    reply = ReviewSerializerReply(read_only=True)
    rating = serializers.IntegerField(min_value=1, max_value=5)
    version = ReviewVersionSerializer()

    class Meta:
        model = Review
        fields = BaseReviewSerializer.Meta.fields + (
            'rating', 'reply', 'version')

    def validate_version(self, version):
        if self.partial:
            raise serializers.ValidationError(
                ugettext(u'You can\'t change the version of the add-on '
                         u'reviewed once the review has been created.'))

        addon = self.context['view'].get_addon_object()
        if not addon:
            # BaseReviewSerializer.validate() should complain about that, not
            # this method.
            return None
        if version.addon_id != addon.pk or not version.is_public():
            raise serializers.ValidationError(
                ugettext(u'This version of the add-on doesn\'t exist or '
                         u'isn\'t public.'))
        return version

    def validate(self, data):
        data = super(ReviewSerializer, self).validate(data)
        if not self.partial:
            if data['addon'].authors.filter(pk=data['user'].pk).exists():
                raise serializers.ValidationError(
                    ugettext(u'You can\'t leave a review on your own add-on.'))

            review_exists_on_this_version = Review.objects.filter(
                addon=data['addon'], user=data['user'],
                version=data['version']).exists()
            if review_exists_on_this_version:
                raise serializers.ValidationError(
                    ugettext(u'You can\'t leave more than one review for the '
                             u'same version of an add-on.'))
        return data
