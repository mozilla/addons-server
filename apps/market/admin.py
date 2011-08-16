from django.contrib import admin

from .models import Price, PriceCurrency

admin.site.register(Price)
admin.site.register(PriceCurrency)
