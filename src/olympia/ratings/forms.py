import re
import six

from six.moves.urllib.parse import unquote

from django import forms
from django.utils.translation import ugettext, ugettext_lazy as _

from bleach.linkifier import TLDS

from olympia.amo.utils import raise_required

from .models import RatingFlag


class RatingReplyForm(forms.Form):
    form_id = 'review-reply-edit'

    body = forms.CharField(
        widget=forms.Textarea(
            attrs={'rows': 3, 'id': 'id_review_reply_body', },
        ),
        label='Review',
    )

    def clean_body(self):
        body = self.cleaned_data.get('body', '')
        # Whitespace is not a review!
        if not body.strip():
            raise_required()
        return body


class RatingForm(RatingReplyForm):
    form_id = 'review-edit'

    body = forms.CharField(
        widget=forms.Textarea(
            attrs={'rows': 3, 'id': 'id_review_body', },
        ),
        label='Review',
    )
    rating = forms.ChoiceField(
        choices=zip(range(1, 6), range(1, 6)), label=_(u'Rating')
    )
    # re.L flag has been removed in py3.6 as Unicode matching is already
    # enabled by default for Unicode (str) patterns.
    flags = (re.I | re.L | re.U | re.M) if six.PY2 else (re.I | re.U | re.M)
    # This matches the following three types of patterns:
    # http://... or https://..., generic domain names, and IPv4
    # octets. It does not match IPv6 addresses or long strings such as
    # "example dot com".
    link_pattern = re.compile(
        r'((://)|'  # Protocols (e.g.: http://)
        r'((\d{1,3}\.){3}(\d{1,3}))|'
        r'([0-9a-z\-%%]+\.(%s)))' % '|'.join(TLDS),
        flags)

    def _post_clean(self):
        # Unquote the body in case someone tries 'example%2ecom'.
        data = unquote(self.cleaned_data.get('body', ''))
        if '<br>' in data:
            self.cleaned_data['body'] = re.sub('<br>', '\n', data)
        if self.link_pattern.search(data) is not None:
            self.cleaned_data['flag'] = True
            self.cleaned_data['editorreview'] = True


class RatingFlagForm(forms.ModelForm):

    class Meta:
        model = RatingFlag
        fields = ('flag', 'note', 'rating', 'user')

    def clean(self):
        data = super(RatingFlagForm, self).clean()
        if 'note' in data and data['note'].strip():
            data['flag'] = RatingFlag.OTHER
        elif data.get('flag') == RatingFlag.OTHER:
            self.add_error(
                'note',
                ugettext(u'A short explanation must be provided when '
                         u'selecting "Other" as a flag reason.'))
        return data
