from django.contrib import admin

from olympia import amo
from olympia.access import acl

from . import models


class StaffAdminSite(admin.AdminSite):
    site_header = 'AMO Staff model administration'

    def has_permission(self, request):
        return acl.action_allowed(request, amo.permissions.ADDONS_EDIT)


class StaffModelAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return self.admin_site.has_permission(request)

    def has_change_permission(self, request, obj=None):
        return self.admin_site.has_permission(request)

    def has_delete_permission(self, request, obj=None):
        return self.admin_site.has_permission(request)

    def has_module_permission(self, request):
        return self.admin_site.has_permission(request)


staff_admin_site = StaffAdminSite(name='staffadmin')

admin.site.register(models.Config)
admin.site.disable_action('delete_selected')

admin.site.register(models.DownloadSource)
