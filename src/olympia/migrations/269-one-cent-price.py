# from decimal import Decimal
# from django.conf import settings
# from market.models import Price


# def run():
#     if not settings.APP_PREVIEW:
#         return

#     Price.objects.all().delete()
#     Price.objects.create(price=Decimal('0.01'), name='Tier 1')
