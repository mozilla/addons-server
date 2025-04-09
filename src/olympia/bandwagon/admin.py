from django.conf import settings
from django.contrib import admin

from olympia import amo
from olympia.access import acl
from olympia.activity.models import ActivityLog
from olympia.amo.admin import AMOModelAdmin

from .models import Collection, CollectionAddon


class CollectionAddonInline(admin.TabularInline):
    model = CollectionAddon
    raw_id_fields = ('addon',)
    exclude = ('user',)
    view_on_site = False
    # FIXME: leaving 'comments' editable seems to break uniqueness checks for
    # some reason, even though it's picked up as a translated fields correctly.
    readonly_fields = ('comments',)

    # Permission checks:
    # We use the implementation for CollectionAdmin permission checks: if you
    # can edit a collection, you can edit/remove the add-ons inside it.
    def has_change_permission(self, request, obj=None):
        return CollectionAdmin(Collection, self.admin_site).has_change_permission(
            request, obj=getattr(obj, 'collection', None)
        )

    def has_delete_permission(self, request, obj=None):
        # For deletion we use the *change* permission to allow curators to
        # remove an add-on from a collection (they can't delete a collection).
        return self.has_change_permission(request, obj=obj)

    def has_add_permission(self, request, obj=None):
        return CollectionAdmin(Collection, self.admin_site).has_add_permission(request)


class CollectionAdmin(AMOModelAdmin):
    list_display = (
        'name',
        'slug',
        'addon_count',
        'deleted',
    )
    list_filter = ('listed', 'deleted')
    fields = (
        'name',
        'slug',
        'description',
        'uuid',
        'listed',
        'default_locale',
        'author',
    )
    raw_id_fields = ('author',)
    readonly_fields = ('uuid',)
    inlines = (CollectionAddonInline,)

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj=obj)
        # Only add "deleted" to the fields for something already deleted, for
        # something not yet deleted the admin should use the regular button
        # instead of the checkbox.
        if obj and obj.deleted:
            return fields + ('deleted',)
        return fields

    # Permission checks:
    # A big part of the curation job for the homepage etc is done through
    # collections, so users with Admin:Curation can also edit mozilla's
    # collections as well as their own (allowing them to transfer them to
    # the mozilla user) through the admin, as well as create new ones.
    def has_module_permission(self, request):
        return acl.action_allowed_for(
            request.user, amo.permissions.ADMIN_CURATION
        ) or super().has_module_permission(request)

    def has_change_permission(self, request, obj=None):
        user = request.user
        should_allow_curators = (
            # Changelist, allowed for convenience, should be harmless.
            obj is None
            # Mozilla collection or their own.
            or obj.author
            and obj.author.pk in (settings.TASK_USER_ID, user.pk)
        )

        return (
            should_allow_curators
            and acl.action_allowed_for(request.user, amo.permissions.ADMIN_CURATION)
            or super().has_change_permission(request, obj=obj)
        )

    def has_add_permission(self, request):
        return acl.action_allowed_for(
            request.user, amo.permissions.ADMIN_CURATION
        ) or super().has_add_permission(request)

    def delete_model(self, request, obj):
        ActivityLog.objects.create(amo.LOG.COLLECTION_DELETED, obj)
        obj.delete(clear_slug=False)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if change and 'deleted' in form.changed_data and not obj.deleted:
            ActivityLog.objects.create(amo.LOG.COLLECTION_UNDELETED, obj)


admin.site.register(Collection, CollectionAdmin)
