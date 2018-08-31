from django.conf import settings
from django.contrib import admin

from olympia import amo
from olympia.access import acl

from .models import Collection, CollectionAddon


class CollectionAddonInline(admin.TabularInline):
    model = CollectionAddon
    raw_id_fields = ('addon',)
    exclude = ('user', )
    view_on_site = False
    # FIXME: leaving 'comments' editable seems to break uniqueness checks for
    # some reason, even though it's picked up as a translated fields correctly.
    readonly_fields = ('comments',)


class CollectionAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'addon_count',)
    list_filter = ('type', 'listed')
    fields = ('name', 'slug', 'uuid', 'listed', 'type', 'application',
              'default_locale', 'author')
    raw_id_fields = ('author',)
    readonly_fields = ('uuid',)
    inlines = (CollectionAddonInline,)

    # Permission checks:
    # A big part of the curation job for the homepage etc is done through
    # collections, so users with Admin:Curation can also edit mozilla's
    # collections as well as their own (allowing them to transfer them to
    # the mozilla user) through the admin, as well as create new ones.
    def has_module_permission(self, request):
        return (
            acl.action_allowed(request, amo.permissions.ADMIN_CURATION) or
            super(CollectionAdmin, self).has_module_permission(request))

    def has_change_permission(self, request, obj=None):
        user = request.user
        should_allow_curators = (
            # Changelist, allowed for convenience, should be harmless.
            obj is None or
            # Mozilla collection or their own.
            obj.author and obj.author.pk in (settings.TASK_USER_ID, user.pk))

        return (
            should_allow_curators and acl.action_allowed(
                request, amo.permissions.ADMIN_CURATION) or
            super(CollectionAdmin, self).has_change_permission(
                request, obj=obj))

    def has_add_permission(self, request):
        return (
            acl.action_allowed(request, amo.permissions.ADMIN_CURATION) or
            super(CollectionAdmin, self).has_add_permission(request))


admin.site.register(Collection, CollectionAdmin)
