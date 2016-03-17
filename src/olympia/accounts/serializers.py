import logging

from rest_framework import serializers

from olympia.access.models import Group
from olympia.users.models import UserProfile

log = logging.getLogger('accounts')


class UserProfileSerializer(serializers.ModelSerializer):
    picture_url = serializers.URLField(read_only=True, source='picture_url')

    class Meta:
        model = UserProfile
        fields = (
            'username', 'display_name', 'email',
            'bio', 'deleted', 'display_collections',
            'display_collections_fav', 'homepage',
            'location', 'notes', 'occupation', 'picture_type',
            'read_dev_agreement', 'is_verified',
            'region', 'lang', 'picture_url'
        )


class AccountSourceSerializer(serializers.ModelSerializer):
    source = serializers.CharField(source='source')

    class Meta:
        model = UserProfile
        fields = ['source']


group_rules = {
    'reviewer': 'Addons:Review',
    'admin': '*:*',
}


class AccountSuperCreateSerializer(serializers.Serializer):
    username = serializers.CharField(required=False)
    password = serializers.CharField(required=False)
    email = serializers.EmailField(required=False)
    fxa_id = serializers.CharField(required=False)
    group = serializers.ChoiceField(choices=group_rules.items(),
                                    required=False)

    def validate_email(self, attrs, source):
        email = attrs.get(source)
        if email and UserProfile.objects.filter(email=email).exists():
            raise serializers.ValidationError(
                'Someone with this email already exists in the system')
        return attrs

    def validate_username(self, attrs, source):
        username = attrs.get(source)
        if username and UserProfile.objects.filter(username=username).exists():
            raise serializers.ValidationError(
                'Someone with this username already exists in the system')
        return attrs

    def validate_group(self, attrs, source):
        group = attrs.get(source)
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
            attrs[source] = qs.get()
        return attrs
