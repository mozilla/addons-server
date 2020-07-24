import requests

from rest_framework.reverse import reverse as drf_reverse

from django.contrib import admin, messages

from .forms import ShelfForm


class ShelfAdmin(admin.ModelAdmin):
    list_display = ('title', 'shelf_type')
    actions = ['delete_selected']
    form = ShelfForm

    def save_model(self, request, obj, form, change):
        baseUrl = "https://addons.mozilla.org"

        if obj.shelf_type in ('extension', 'search', 'theme'):
            api = drf_reverse('v4:addon-search')
        elif obj.shelf_type == 'categories':
            api = drf_reverse('v4:category-list')
        elif obj.shelf_type == 'collections':
            api = drf_reverse('v4:collection-list')
        elif obj.shelf_type == 'recommendations':
            api = drf_reverse('v4:addon-recommendations')

        url = baseUrl + api + obj.criteria.lower()
        response = requests.get(url)
        results = response.json()

        if 'count' in results:
            messages.add_message(
                request, messages.INFO, 'Add-ons count for "%s" shelf: %s' % (
                    obj.title, results['count']))
        else:
            messages.add_message(
                request, messages.INFO, 'Add-ons count for "%s" shelf: %s' % (
                    obj.title, len(results)))
        super().save_model(request, obj, form, change)
