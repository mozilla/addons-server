from django.contrib import admin

from .models import Group, GroupUser


class GroupUserInline(admin.TabularInline):
    model = GroupUser
    raw_id_fields = ('user',)


class GroupAdmin(admin.ModelAdmin):
    raw_id_fields = ('users',)
    ordering = ('name',)
    list_display = ('name', 'rules')
    inlines = (GroupUserInline,)

admin.site.register(Group, GroupAdmin)
