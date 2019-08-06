import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.forms.widgets import RadioSelect

from olympia.amo.models import ModelBase
from olympia.discovery.models import DiscoveryItem


GRADIENT_START_COLOR = '#20123A'
GRADIENT_CHOICES = (
    ('#054096', 'BLUE70'),
    ('#068989', 'GREEN70'),
    ('#C60184', 'PINK70'),
    ('#712290', 'PURPLE70'),
    ('#582ACB', 'VIOLET70'),
)


class GradientChoiceWidget(RadioSelect):
    option_template_name = 'hero/gradient_option.html'
    option_inherits_attrs = True

    def create_option(self, name, value, label, selected, index,
                      subindex=None, attrs=None):
        attrs['gradient_end_color'] = value
        attrs['gradient_start_color'] = GRADIENT_START_COLOR
        return super().create_option(
            name=name, value=value, label=label, selected=selected,
            index=index, subindex=subindex, attrs=attrs)


class ImageChoiceWidget(RadioSelect):
    option_template_name = 'hero/image_option.html'
    option_inherits_attrs = True

    def create_option(self, name, value, label, selected, index,
                      subindex=None, attrs=None):
        attrs['image_url'] = f'{settings.STATIC_URL}img/hero/featured/{value}'
        return super().create_option(
            name=name, value=value, label=label, selected=selected,
            index=index, subindex=subindex, attrs=attrs)


class FeaturedImageChoices:
    def __iter__(self):
        path = os.path.join(settings.ROOT, 'static', 'img', 'hero', 'featured')
        self.os_iter = os.scandir(path)
        return self

    def __next__(self):
        entry = self.os_iter.__next__()
        return (entry.name, entry.name)


class WidgetCharField(models.CharField):
    def __init__(self, *args, **kwargs):
        self.widget = kwargs.pop('widget', None)
        super().__init__(*args, **kwargs)

    def formfield(self, **kwargs):
        defaults = {'widget': self.widget}
        defaults.update(kwargs)
        return super().formfield(**defaults)


class PrimaryHero(ModelBase):
    image = WidgetCharField(
        choices=FeaturedImageChoices(),
        max_length=255, widget=ImageChoiceWidget)
    gradient_color = WidgetCharField(
        choices=GRADIENT_CHOICES, max_length=7, widget=GradientChoiceWidget)
    enabled = models.BooleanField(db_index=True, null=False, default=False,)
    disco_addon = models.OneToOneField(
        DiscoveryItem, on_delete=models.CASCADE, null=False)
    is_external = models.BooleanField(null=False, default=False)

    def __str__(self):
        return str(self.disco_addon)

    @property
    def image_path(self):
        return f'{settings.STATIC_URL}img/hero/featured/{self.image}'

    @property
    def gradient(self):
        return {'start': GRADIENT_START_COLOR, 'end': self.gradient_color}

    def clean(self):
        if self.is_external:
            if self.enabled and not self.disco_addon.addon.homepage:
                raise ValidationError(
                    'External primary shelves need a homepage defined in '
                    'addon details.')
        else:
            recommended = (self.disco_addon.recommended_status ==
                           self.disco_addon.RECOMMENDED)
            if self.enabled and not recommended:
                raise ValidationError(
                    'Only recommended add-ons can be enabled for non-external '
                    'primary shelves.')


class SecondaryHero(ModelBase):
    headline = models.CharField(max_length=50, blank=False)
    description = models.CharField(max_length=100, blank=False)
    cta_url = models.CharField(max_length=255, blank=True)
    cta_text = models.CharField(max_length=20, blank=True)
    enabled = models.BooleanField(db_index=True, null=False, default=False)

    def __str__(self):
        return str(self.headline)

    def clean(self):
        both_or_neither = not (bool(self.cta_text) ^ bool(self.cta_url))
        if self.enabled and not both_or_neither:
            raise ValidationError(
                'Both the call to action URL and text must be defined, or '
                'neither, for enabled shelves.')
