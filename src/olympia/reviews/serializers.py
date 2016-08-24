from rest_framework import serializers

from olympia.reviews.models import Review
from olympia.users.serializers import BaseUserSerializer


class BaseReviewSerializer(serializers.ModelSerializer):
    # title and body are TranslatedFields, but there is never more than one
    # translation for each review - it's essentially useless. Because of that
    # we use a simple CharField in the API, hiding the fact that it's a
    # TranslatedField underneath.
    body = serializers.CharField()
    title = serializers.CharField()
    user = BaseUserSerializer()

    class Meta:
        model = Review
        fields = ('id', 'body', 'title', 'version', 'user')

    def to_representation(self, obj):
        data = super(BaseReviewSerializer, self).to_representation(obj)
        # For the version, we want to accept PKs for input, but use the version
        # string for output.
        data['version'] = unicode(obj.version.version) if obj.version else None
        return data


class ReviewSerializer(BaseReviewSerializer):
    reply = BaseReviewSerializer(read_only=True)

    class Meta:
        model = Review
        fields = BaseReviewSerializer.Meta.fields + ('rating', 'reply')
