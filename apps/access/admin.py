from django.contrib import admin

from .models import AccessWhitelist, Group, GroupUser


class GroupUserInline(admin.TabularInline):
    model = GroupUser
    raw_id_fields = ('user',)


class GroupAdmin(admin.ModelAdmin):
    raw_id_fields = ('users',)
    ordering = ('name',)
    list_display = ('name', 'rules', 'notes')
    inlines = (GroupUserInline,)


admin.site.register(AccessWhitelist)
admin.site.register(Group, GroupAdmin)
