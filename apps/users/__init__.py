from apps.admin import jinja_for_django
from django.contrib.auth import views as auth_views

# So we can use the contrib logic for password resets, etc.
auth_views.render_to_response = jinja_for_django
