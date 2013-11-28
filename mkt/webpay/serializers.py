from rest_framework import serializers

from constants.payments import PROVIDER_LOOKUP
from market.models import Price, price_locale

from mkt.webpay.models import ProductIcon


class PriceSerializer(serializers.ModelSerializer):
    prices = serializers.SerializerMethodField('get_prices')
    localized = serializers.SerializerMethodField('get_localized_prices')
    pricePoint = serializers.CharField(source='name')
    name = serializers.CharField(source='tier_name')

    class Meta:
        model = Price

    def get_prices(self, obj):
        provider = self.context['request'].GET.get('provider', None)
        if provider:
            provider = PROVIDER_LOOKUP[provider]
        return obj.prices(provider=provider)

    def get_localized_prices(self, obj):
        region = self.context['request'].REGION

        for price in self.get_prices(obj):
            if price['region'] == region.id:
                result = price.copy()
                result.update({
                    'locale': price_locale(price['price'], price['currency']),
                    'region': region.name,
                })
                return result
        return {}


class ProductIconSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField('get_url')

    def get_url(self, obj):
        if not obj.pk:
            return ''
        return obj.url()

    class Meta:
        model = ProductIcon
        exclude = ('format',)
