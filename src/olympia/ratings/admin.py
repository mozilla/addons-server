from django.contrib import admin

from .models import Rating


class RatingAdmin(admin.ModelAdmin):
    raw_id_fields = ('addon', 'version', 'user', 'reply_to')
    readonly_fields = (
        'addon',
        'version',
        'user',
        'reply_to',
        'ip_address',
        'body',
        'rating',
    )
    fields = ('addon', 'version', 'body', 'rating', 'ip_address', 'user')
    list_display = ('addon', 'body', 'rating', 'user')


admin.site.register(Rating, RatingAdmin)
