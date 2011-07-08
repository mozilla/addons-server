import happyforms

from .models import Performance


class PerformanceForm(happyforms.ModelForm):
    class Meta:
        model = Performance
