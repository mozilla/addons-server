from django.urls import re_path

from . import views


urlpatterns = [
    re_path(
        r'^stripe-webhook$',
        views.stripe_webhook,
        name='promoted.stripe_webhook',
    ),
]
