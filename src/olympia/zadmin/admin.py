from django.contrib import admin

from olympia import amo
from olympia.access import acl

from . import models


class StaffAdminSite(admin.AdminSite):
    site_header = 'AMO Staff model administration'

    def has_permission(self, request):
        return acl.action_allowed(request, amo.permissions.ADDONS_EDIT)


staff_admin_site = StaffAdminSite(name='staffadmin')

admin.site.register(models.Config)
admin.site.disable_action('delete_selected')

admin.site.register(models.DownloadSource)
