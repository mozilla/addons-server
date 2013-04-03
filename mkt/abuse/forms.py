from django import forms

from users.models import UserProfile

from mkt.site.forms import AbuseForm
from mkt.webapps.models import Webapp


class UserAbuseForm(AbuseForm):
    user = forms.ModelChoiceField(queryset=UserProfile.objects.all())


class AppAbuseForm(AbuseForm):
    app = forms.ModelChoiceField(queryset=Webapp.objects.all())
