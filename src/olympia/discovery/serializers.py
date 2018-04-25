from django.utils.translation import ugettext

from rest_framework import serializers

from olympia import amo
from olympia.addons.models import Addon
from olympia.addons.serializers import AddonSerializer, VersionSerializer
from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.versions.models import Version


class DiscoveryVersionSerializer(VersionSerializer):
    class Meta:
        fields = ('compatibility', 'files',)
        model = Version


class DiscoveryAddonSerializer(AddonSerializer):
    current_version = DiscoveryVersionSerializer()

    class Meta:
        fields = ('id', 'current_version', 'guid', 'icon_url', 'name',
                  'slug', 'theme_data', 'type', 'url',)
        model = Addon


class DiscoverySerializer(serializers.Serializer):
    heading = serializers.CharField()
    description = serializers.CharField()
    addon = DiscoveryAddonSerializer()
    is_recommendation = serializers.BooleanField()

    def to_representation(self, instance):
        data = super(DiscoverySerializer, self).to_representation(instance)
        authors = u', '.join(
            author.name for author in instance.addon.listed_authors)
        addon_name = unicode(instance.addon_name or instance.addon.name)
        url = absolutify(instance.addon.get_url_path())

        if data['heading'] is None:
            data['heading'] = (
                u'{0} <span>{1} <a href="{2}">{3}</a></span>'.format(
                    addon_name, ugettext(u'by'), url, authors))
        else:
            # Note: target and rel attrs are added in addons-frontend.
            addon_link = u'<a href="{0}">{1} {2} {3}</a>'.format(
                url, addon_name, ugettext(u'by'), authors)

            data['heading'] = data['heading'].replace(
                '{start_sub_heading}', '<span>').replace(
                '{end_sub_heading}', '</span>').replace(
                '{addon_name}', addon_link)

        if data['description'] is None:
            if (instance.addon.type == amo.ADDON_EXTENSION and
                    instance.addon.summary):
                data['description'] = (
                    u'<blockquote>%s</blockquote>' % instance.addon.summary)
            elif (instance.addon.type == amo.ADDON_PERSONA and
                    instance.addon.description):
                data['description'] = (
                    u'<blockquote>%s</blockquote>' %
                    instance.addon.description)
        return data
