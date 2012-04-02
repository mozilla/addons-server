import happyforms

from stats.models import Contribution

from .models import InappPayment


class PaymentForm(happyforms.ModelForm):
    class Meta:
        model = InappPayment
        fields = ('name', 'description', 'app_data')


class ContributionForm(happyforms.ModelForm):
    class Meta:
        model = Contribution
        fields = ('currency', 'amount')
