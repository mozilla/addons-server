from django import forms

from .models import ReviewFlag


class ReviewFlagForm(forms.ModelForm):

    class Meta:
        model = ReviewFlag

    def clean(self):
        data = super(ReviewFlagForm, self).clean()
        if 'note' in data and data['note'].strip():
            data['flag'] = 'other'
        return data
