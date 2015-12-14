from django import forms


class DateForm(forms.Form):
    start = forms.DateField(input_formats=['%Y%m%d'], required=False)
    end = forms.DateField(input_formats=['%Y%m%d'], required=False)
    last = forms.IntegerField(required=False)
