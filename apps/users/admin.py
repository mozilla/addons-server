from django.contrib import admin

from access.admin import GroupUserInline
from .models import UserProfile


class UserAdmin(admin.ModelAdmin):
    list_display = ('__unicode__', 'email')
    search_fields = ('^email',)
    inlines = (GroupUserInline,)


admin.site.register(UserProfile, UserAdmin)
