from django.contrib import admin
from django.utils.translation import ugettext

from .models import Collection, CollectionUser


class ContributorInline(admin.TabularInline):
    model = CollectionUser
    raw_id_fields = ('user',)
    fields = ('user',)
    verbose_name_plural = ugettext(u'Contributors')


class CollectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'addon_count', 'downloads')
    list_filter = ('type', 'listed')
    fields = ('name', 'slug', 'uuid', 'listed', 'type', 'default_locale',
              'author')
    raw_id_fields = ('author',)
    readonly_fields = ('name', 'slug', 'uuid')
    inlines = [ContributorInline]


admin.site.register(Collection, CollectionAdmin)
