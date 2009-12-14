from django.contrib import admin

from .models import UserProfile


class UserAdmin(admin.ModelAdmin):
    list_display = ('__unicode__', 'email')
    search_fields = ('^email',)


admin.site.register(UserProfile, UserAdmin)
