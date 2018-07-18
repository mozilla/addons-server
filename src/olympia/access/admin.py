from django.urls import reverse
from django.contrib import admin
from django.utils.html import format_html

from .models import Group, GroupUser


class GroupUserInline(admin.TabularInline):
    model = GroupUser
    raw_id_fields = ('user',)
    readonly_fields = ('user_profile_link',)

    def user_profile_link(self, obj):
        if obj.pk:
            return format_html(
                '<a href="{}">Admin User Profile</a>',
                reverse('admin:users_userprofile_change', args=(obj.user.pk,)),
            )
        else:
            return ''

    user_profile_link.short_description = 'User Profile'


class GroupAdmin(admin.ModelAdmin):
    raw_id_fields = ('users',)
    ordering = ('name',)
    list_display = ('name', 'rules', 'notes')
    inlines = (GroupUserInline,)


admin.site.register(Group, GroupAdmin)
