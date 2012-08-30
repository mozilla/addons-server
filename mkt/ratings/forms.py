from django import forms

from reviews.forms import (ReviewForm as OldReviewForm,
                           ReviewReplyForm as OldReviewReplyForm)


class ReviewReplyForm(OldReviewReplyForm):
    body = forms.CharField(max_length=150,
                           widget=forms.Textarea(attrs={'rows': 2}))


class ReviewForm(OldReviewForm, ReviewReplyForm):
    pass
