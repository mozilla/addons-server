from django.core.paginator import InvalidPage

from rest_framework.exceptions import NotFound

from olympia.api.pagination import CustomPageNumberPagination


class AddonRatingsPagination(CustomPageNumberPagination):
    def paginate_queryset(self, queryset, request, view=None):
        """
        Like DRF's paginate_queryset(), but with the paginator.count set to
        the add-on's total_ratings denormalized field.
        """
        page_size = self.get_page_size(request)
        if not page_size:
            return None

        paginator = self.django_paginator_class(queryset, page_size)
        # Override paginator.count with the total ratings from the add-on,
        # avoiding the expensive count() query.
        paginator.count = view.get_addon_object().total_ratings
        page_number = request.query_params.get(self.page_query_param, 1)
        if page_number in self.last_page_strings:
            page_number = paginator.num_pages

        try:
            self.page = paginator.page(page_number)
        except InvalidPage as exc:
            msg = self.invalid_page_message.format(
                page_number=page_number, message=str(exc)
            )
            raise NotFound(msg)

        if paginator.num_pages > 1 and self.template is not None:
            # The browsable API should display pagination controls.
            self.display_page_controls = True

        self.request = request
        return list(self.page)
