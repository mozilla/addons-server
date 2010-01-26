from django.contrib import admin
from .models import BlocklistApp, BlocklistItem, BlocklistPlugin

admin.site.register(BlocklistApp)
admin.site.register(BlocklistItem)
admin.site.register(BlocklistPlugin)
