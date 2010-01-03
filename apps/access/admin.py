from django.contrib import admin

from .models import Group


# XXX: needs Django 1.2
# class UserInline(admin.TabularInline):
#     Group.users.through
#     raw_id_fields = ('user_id',)


class GroupAdmin(admin.ModelAdmin):
    raw_id_fields = ('users',)

admin.site.register(Group, GroupAdmin)
