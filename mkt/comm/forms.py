import happyforms

from mkt.api.forms import SluggableModelChoiceField
from mkt.webapps.models import Webapp


class AppSlugForm(happyforms.Form):
    app = SluggableModelChoiceField(queryset=Webapp.objects.all(),
                                    sluggable_to_field_name='app_slug')
