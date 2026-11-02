from django.urls import re_path

from olympia.devhub import views as devhub_views

from .urls import base_urlpatterns


urlpatterns = [
    *base_urlpatterns,
    # (New, lit-based) Developer Hub
    # Client-side router handles all urls under /developers/ so regex is open-ended
    re_path(r'^developers/', devhub_views.serve_pinguino, name='devhub.index'),
]
