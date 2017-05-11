from django.core.files.storage import default_storage

from rest_framework import serializers

import olympia.core.logger
from olympia.access.models import Group
from olympia.users.models import UserProfile
from olympia.users.serializers import BaseUserSerializer
from olympia.users.tasks import resize_photo


log = olympia.core.logger.getLogger('accounts')


class PublicUserProfileSerializer(BaseUserSerializer):
    picture_url = serializers.URLField(read_only=True)
    average_addon_rating = serializers.CharField(source='averagerating')

    class Meta(BaseUserSerializer.Meta):
        fields = BaseUserSerializer.Meta.fields + (
            'average_addon_rating', 'created', 'biography', 'homepage',
            'is_addon_developer', 'is_artist', 'location', 'occupation',
            'num_addons_listed', 'picture_type', 'picture_url', 'username',
        )
        # This serializer should never be used for updates but just to be sure.
        read_only_fields = fields


class UserProfileSerializer(PublicUserProfileSerializer):
    picture_upload = serializers.ImageField(use_url=True, write_only=True)

    class Meta(PublicUserProfileSerializer.Meta):
        fields = PublicUserProfileSerializer.Meta.fields + (
            'display_name', 'email', 'deleted', 'last_login', 'picture_upload',
            'last_login_ip', 'read_dev_agreement', 'is_verified',
        )
        writeable_fields = (
            'biography', 'display_name', 'homepage', 'location', 'occupation',
            'picture_upload', 'username',
        )
        read_only_fields = tuple(set(fields) - set(writeable_fields))

    def update(self, instance, validated_data):
        instance = super(UserProfileSerializer, self).update(
            instance, validated_data)

        photo = validated_data.get('picture_upload')
        if photo:
            tmp_destination = instance.picture_path + '__unconverted'

            with default_storage.open(tmp_destination, 'wb') as fh:
                for chunk in photo.chunks():
                    fh.write(chunk)
            instance.update(picture_type='image/png')
            resize_photo.delay(tmp_destination, instance.picture_path,
                               set_modified_on=[instance])
        return instance


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
