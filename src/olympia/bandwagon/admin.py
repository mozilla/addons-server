from django.contrib import admin

from .models import Collection, CollectionAddon


class CollectionAddonInline(admin.TabularInline):
    model = CollectionAddon
    raw_id_fields = ('addon',)
    exclude = ('user',)
    view_on_site = False
    # FIXME: leaving 'comments' editable seems to break uniqueness checks for
    # some reason, even though it's picked up as a translated fields correctly.
    readonly_fields = ('comments',)


class CollectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'addon_count', 'downloads')
    list_filter = ('type', 'listed')
    fields = (
        'name',
        'slug',
        'uuid',
        'listed',
        'type',
        'application',
        'default_locale',
        'author',
    )
    raw_id_fields = ('author',)
    readonly_fields = ('uuid',)
    inlines = (CollectionAddonInline,)


admin.site.register(Collection, CollectionAdmin)
