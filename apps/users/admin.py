from django.contrib import admin

from access.admin import GroupUserInline
from .models import UserProfile


class UserAdmin(admin.ModelAdmin):
    list_display = ('__unicode__', 'email')
    search_fields = ('^email',)
    inlines = (GroupUserInline,)

    # XXX TODO: Ability to edit the picture
    # XXX TODO: Ability to change the password (use AdminPasswordChangeForm)
    fieldsets = (
        (None, {
            'fields': ('nickname', 'firstname', 'lastname', 'email',
                       'password', 'bio', 'homepage', 'location',
                       'occupation',),
        }),
        ('Registration', {
            'fields': ('confirmationcode', 'resetcode',
                       'resetcode_expires'),
        }),
        ('Flags', {
            'fields': ('deleted', 'display_collections',
                       'display_collections_fav', 'emailhidden',
                       'notifycompat', 'notifyevents', 'sandboxshown'),
        }),
        ('Admin', {
            'fields': ('notes', 'picture_type'),
        }),
    )


admin.site.register(UserProfile, UserAdmin)
