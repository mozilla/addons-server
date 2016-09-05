from rest_framework import serializers
from rest_framework.relations import PrimaryKeyRelatedField

from olympia.reviews.models import Review
from olympia.users.serializers import BaseUserSerializer
from olympia.versions.models import Version


class BaseReviewSerializer(serializers.ModelSerializer):
    # title and body are TranslatedFields, but there is never more than one
    # translation for each review - it's essentially useless. Because of that
    # we use a simple CharField in the API, hiding the fact that it's a
    # TranslatedField underneath.
    body = serializers.CharField(allow_null=True, required=False)
    title = serializers.CharField(allow_null=True, required=False)
    user = BaseUserSerializer(read_only=True)

    # Version queryset is unfiltered, the version is checked more thoroughly
    # in the validate() method.
    version = PrimaryKeyRelatedField(queryset=Version.unfiltered)

    class Meta:
        model = Review
        fields = ('id', 'body', 'title', 'version', 'user')

    def to_representation(self, obj):
        data = super(BaseReviewSerializer, self).to_representation(obj)
        # For the version, we want to accept PKs for input, but use the version
        # string for output.
        data['version'] = unicode(obj.version.version) if obj.version else None
        return data

    def validate_version(self, version):
        addon = self.context['view'].get_addon_object()
        if (version.addon_id != addon.pk or
                not version.is_public()):
            raise serializers.ValidationError(
                'Version does not exist on this add-on or is not public.')
        return version

    def validate(self, data):
        data = super(BaseReviewSerializer, self).validate(data)
        # Get the add-on pk from the URL, no need to pass it as POST data since
        # the URL is always going to have it.
        data['addon'] = self.context['view'].get_addon_object()

        # Get the user from the request, don't allow clients to pick one
        # themselves.
        data['user'] = self.context['request'].user

        if data['addon'].authors.filter(pk=data['user'].pk).exists():
            raise serializers.ValidationError(
                'An add-on author can not leave a review on its own add-on.')

        if Review.objects.filter(
                addon=data['addon'], user=data['user'],
                version=data['version']).exists():
            raise serializers.ValidationError(
                'The same user can not leave a review on the same version more'
                ' than once.')

        return data


class ReviewSerializer(BaseReviewSerializer):
    reply = BaseReviewSerializer(read_only=True)
    rating = serializers.IntegerField(min_value=1, max_value=5)

    class Meta:
        model = Review
        fields = BaseReviewSerializer.Meta.fields + ('rating', 'reply')
