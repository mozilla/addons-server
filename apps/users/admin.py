from django.contrib import admin

from .models import User


class UserAdmin(admin.ModelAdmin):
    list_display = ('__unicode__', 'email')
    search_fields = ('^email',)


admin.site.register(User, UserAdmin)
