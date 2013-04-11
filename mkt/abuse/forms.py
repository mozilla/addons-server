from django import forms

from users.models import UserProfile

from mkt.api.forms import SluggableModelChoiceField
from mkt.site.forms import AbuseForm
from mkt.webapps.models import Webapp


class UserAbuseForm(AbuseForm):
    user = forms.ModelChoiceField(queryset=UserProfile.objects.all())


class AppAbuseForm(AbuseForm):
    app = SluggableModelChoiceField(queryset=Webapp.objects.all(),
                                    sluggable_to_field_name='app_slug')
