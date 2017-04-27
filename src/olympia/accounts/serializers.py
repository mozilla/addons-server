from rest_framework import serializers

import olympia.core.logger
from olympia.access.models import Group
from olympia.addons.serializers import AddonSerializer
from olympia.bandwagon.serializers import SimpleCollectionSerializer
from olympia.reviews.models import Review
from olympia.reviews.serializers import ReviewSerializer
from olympia.users.models import UserProfile
from olympia.users.serializers import BaseUserSerializer


log = olympia.core.logger.getLogger('accounts')


class PublicUserProfileSerializer(BaseUserSerializer):
    picture_url = serializers.URLField(read_only=True)
    addons = AddonSerializer(many=True, source='addons_listed')
    reviews = serializers.SerializerMethodField()

    class Meta(BaseUserSerializer.Meta):
        fields = BaseUserSerializer.Meta.fields + (
            'addons', 'averagerating', 'created', 'biography', 'homepage',
            'is_addon_developer', 'is_artist', 'location', 'addons_listed',
            'occupation', 'picture_type', 'picture_url', 'reviews',
            'username',
        )

    def get_reviews(self, obj):
        q = Review.objects.filter(user=obj, reply_to=None)
        return [ReviewSerializer(r) for r in q]


class UserProfileSerializer(PublicUserProfileSerializer):
    collections = SimpleCollectionSerializer(many=True)

    class Meta(PublicUserProfileSerializer.Meta):
        fields = PublicUserProfileSerializer.Meta.fields + (
            'collections', 'display_name', 'email', 'deleted', 'last_login',
            'last_login_ip', 'read_dev_agreement', 'is_verified',
        )


group_rules = {
    'reviewer': 'Addons:Review',
    'admin': '*:*',
}


class AccountSuperCreateSerializer(serializers.Serializer):
    username = serializers.CharField(required=False)
    email = serializers.EmailField(required=False)
    fxa_id = serializers.CharField(required=False)
    group = serializers.ChoiceField(choices=group_rules.items(),
                                    required=False)

    def validate_email(self, email):
        if email and UserProfile.objects.filter(email=email).exists():
            raise serializers.ValidationError(
                'Someone with this email already exists in the system')
        return email

    def validate_username(self, username):
        if username and UserProfile.objects.filter(username=username).exists():
            raise serializers.ValidationError(
                'Someone with this username already exists in the system')
        return username

    def validate_group(self, group):
        if group:
            rule = group_rules[group]
            # This isn't perfect. It makes an assumption that a single group
            # will exist having a *single* rule for what we want. In the
            # case of reviewers and admins this should always be true.
            qs = Group.objects.filter(rules=rule)
            count = qs.count()
            if count != 1:
                log.info(u'Super creation: looking for group with '
                         u'permissions {} {} (count: {})'
                         .format(group, rule, count))
                raise serializers.ValidationError(
                    'Could not find a permissions group with the exact '
                    'rules needed.')
            group = qs.get()
        return group
