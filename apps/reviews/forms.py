from django import forms

from .models import ReviewFlag


class ReviewReplyForm(forms.Form):
    title = forms.CharField(required=False)
    body = forms.CharField(widget=forms.Textarea(attrs={'rows': 3}))


class ReviewForm(ReviewReplyForm):
    rating = forms.ChoiceField(zip(range(1, 6), range(1, 6)))


class ReviewFlagForm(forms.ModelForm):

    class Meta:
        model = ReviewFlag

    def clean(self):
        data = super(ReviewFlagForm, self).clean()
        if 'note' in data and data['note'].strip():
            data['flag'] = ReviewFlag.OTHER
        return data
