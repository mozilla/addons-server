from django.forms.models import BaseModelFormSet


class AdminBasePromotedApprovalFormSet(BaseModelFormSet):
    def __init__(self, instance=None, **kwargs):
        self.instance = instance

        if kwargs.pop('save_as_new', False):
            raise NotImplementedError
        super().__init__(**kwargs)
