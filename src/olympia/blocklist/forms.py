import datetime

from django import forms

from olympia.addons.models import Addon

from .models import Block


class MultiBlockForm(forms.Form):
    input_guids = forms.CharField(widget=forms.HiddenInput())
    min_version = forms.ChoiceField(choices=(('0', '0'),))
    max_version = forms.ChoiceField(choices=(('*', '*'),))
    url = forms.CharField(required=False)
    reason = forms.CharField(widget=forms.Textarea(), required=False)
    include_in_legacy = forms.BooleanField(
        required=False,
        help_text='Include in legacy xml blocklist too, as well as new v3')

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')
        super().__init__(*args, **kwargs)

    def process_input_guids(self, guids):
        all_guids = set(guids.splitlines())

        existing = list(Block.objects.filter(guid__in=all_guids))
        remaining = all_guids - {block.guid for block in existing}

        addon_qs = Addon.unfiltered.filter(guid__in=remaining).order_by(
            '-average_daily_users')
        new = [
            Block(addon=addon) for addon in addon_qs.only_translations()]

        invalid = remaining - {block.guid for block in new}

        return {
            'invalid': list(invalid),
            'existing': list(existing),
            'new': list(new),
        }

    def save(self):
        common_args = dict(self.cleaned_data)
        common_args.update(updated_by=self.request.user)
        processed_guids = self.process_input_guids(
            common_args.pop('input_guids'))

        objects_to_add = processed_guids['new']
        for obj in objects_to_add:
            for field, val in common_args.items():
                setattr(obj, field, val)
            obj.save()
        objects_to_update = processed_guids['existing']
        common_args.update(modified=datetime.datetime.now())
        for obj in objects_to_update:
            obj.update(**common_args)

        return (objects_to_add, objects_to_update)
