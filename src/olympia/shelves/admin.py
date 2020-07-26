from django.contrib import admin, messages

from .forms import ShelfForm


class ShelfAdmin(admin.ModelAdmin):
    list_display = ('title', 'shelf_type')
    actions = ['delete_selected']
    form = ShelfForm

    # Disables automated Django success message
    def message_user(self, request, message, level=messages.INFO,
                     extra_tags='', fail_silently=False):
        pass

    def save_model(self, request, obj, form, change):
        if obj.results:
            if 'count' in obj.results:
                total = obj.results['count']
            else:
                total = len(obj.results)

            messages.success(
                request,
                'The shelf "%s" was changed successfully. Add-ons count: %s' %
                (obj.title, total))
        else:
            messages.success(
                request,
                'The shelf "%s" was changed successfully.' % obj.title)
        super().save_model(request, obj, form, change)
