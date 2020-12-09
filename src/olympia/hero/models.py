import os

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage as storage
from django.db import models
from django.db.models.fields import BLANK_CHOICE_DASH
from django.forms.widgets import RadioSelect
from django.utils.safestring import mark_safe

from olympia.amo.models import LongNameIndex, ModelBase
from olympia.constants.promoted import PROMOTED_GROUPS
from olympia.promoted.models import PromotedAddon


GRADIENT_START_COLOR = ('#20123A', 'color-ink-80')
# Before changing these colors think about existing shelves.  We either need a
# db migration to update them or define a default end color if they're invalid.
GRADIENT_COLORS = {
    '#054096': 'color-blue-70',
    '#008787': 'color-green-70',
    '#C60084': 'color-pink-70',
    '#722291': 'color-purple-70',
    '#592ACB': 'color-violet-70',
}
MODULE_ICON_PATH = os.path.join(settings.ROOT, 'static', 'img', 'hero', 'icons')
MODULE_ICON_URL = f'{settings.STATIC_URL}img/hero/icons/'
HERO_PREVIEW_URL = f'{settings.MEDIA_URL}hero-featured-image/thumbs/'


class GradientChoiceWidget(RadioSelect):
    option_template_name = 'hero/gradient_option.html'
    option_inherits_attrs = True

    def create_option(
        self, name, value, label, selected, index, subindex=None, attrs=None
    ):
        attrs['gradient_end_color'] = value
        attrs['gradient_start_color'] = GRADIENT_START_COLOR[0]
        return super().create_option(
            name=name,
            value=value,
            label=label,
            selected=selected,
            index=index,
            subindex=subindex,
            attrs=attrs,
        )


class IconChoiceWidget(RadioSelect):
    option_template_name = 'hero/image_option.html'
    option_inherits_attrs = True
    image_url_base = MODULE_ICON_URL

    def create_option(
        self, name, value, label, selected, index, subindex=None, attrs=None
    ):
        attrs['image_url'] = f'{self.image_url_base}{value}'
        return super().create_option(
            name=name,
            value=value,
            label=label,
            selected=selected,
            index=index,
            subindex=subindex,
            attrs=attrs,
        )


class DirImageChoices:
    def __init__(self, path):
        self.path = path

    def __iter__(self):
        self.os_iter = os.scandir(self.path)
        return self

    def __next__(self):
        entry = self.os_iter.__next__()
        return (entry.name, entry.name)


class WidgetCharField(models.CharField):
    def __init__(self, *args, **kwargs):
        self.widget = kwargs.pop('widget', None)
        self.blank_text = kwargs.pop('blank_text', 'No image selected')
        super().__init__(*args, **kwargs)

    def formfield(self, **kwargs):
        defaults = {'widget': self.widget}
        defaults.update(kwargs)
        return super().formfield(**defaults)

    def get_choices(self, *args, **kwargs):
        if kwargs.get('blank_choice', BLANK_CHOICE_DASH) == BLANK_CHOICE_DASH:
            kwargs['blank_choice'] = [('', self.blank_text)]
        return super().get_choices(*args, **kwargs)


def hero_image_directory(instance, filename):
    prefix = os.path.splitext(filename)[0]
    return f'hero-featured-image/{prefix}.jpg'


class PrimaryHeroImage(ModelBase):
    custom_image = models.ImageField(
        upload_to=hero_image_directory, blank=False, verbose_name='custom image path'
    )

    def __str__(self):
        return f'{self.custom_image}'

    @property
    def thumbnail_path(self):
        (path, fn) = os.path.split(self.custom_image.path)
        return path + b'/thumbs/' + fn

    @property
    def preview_url(self):
        fn = os.path.basename(self.custom_image.path).decode('utf-8')
        return f'{HERO_PREVIEW_URL}{fn}'

    def preview_image(self):
        if self.custom_image:
            return mark_safe(
                '<img class="prmhero-preview" src="{}" />'.format(self.preview_url)
            )
        else:
            return None

    preview_image.short_description = "Image"
    preview_image.allow_tags = True

    def delete(self, *args, **kwargs):
        if storage.exists(self.thumbnail_path):
            storage.delete(self.thumbnail_path)

        if storage.exists(self.custom_image.path):
            storage.delete(self.custom_image.path)

        super().delete(*args, **kwargs)


class PrimaryHero(ModelBase):
    select_image = models.ForeignKey(
        PrimaryHeroImage, null=True, on_delete=models.SET_NULL
    )
    gradient_color = WidgetCharField(
        choices=GRADIENT_COLORS.items(),
        max_length=7,
        widget=GradientChoiceWidget,
        blank=True,
    )
    description = models.TextField(
        blank=True,
        help_text='Text used to describe an add-on. Should not contain any '
        'HTML or special tags. Will be translated.',
    )
    enabled = models.BooleanField(db_index=True, default=False)
    promoted_addon = models.OneToOneField(
        PromotedAddon, on_delete=models.CASCADE, null=False
    )
    is_external = models.BooleanField(default=False)

    def __str__(self):
        return str(self.promoted_addon.addon)

    @property
    def image_url(self):
        return f'{self.select_image.custom_image.url}' if self.select_image else None

    @property
    def gradient(self):
        return {
            'start': GRADIENT_START_COLOR[1],
            'end': GRADIENT_COLORS.get(self.gradient_color),
        }

    def clean(self):
        super().clean()
        error_dict = {}
        if self.enabled:
            if not self.gradient_color:
                error_dict['gradient_color'] = ValidationError(
                    'Gradient color is required for enabled shelves'
                )

            if self.is_external and not self.promoted_addon.addon.homepage:
                error_dict['is_external'] = ValidationError(
                    'External primary shelves need a homepage defined in '
                    'addon details.'
                )
            elif not self.is_external:
                can_add_to_primary = (
                    self.promoted_addon.group.can_primary_hero
                    and self.promoted_addon.approved_applications
                )
                if not can_add_to_primary:
                    can_hero_groups = ', '.join(
                        str(promo.name)
                        for promo in PROMOTED_GROUPS
                        if promo.can_primary_hero
                    )
                    error_dict['enabled'] = ValidationError(
                        'Only add-ons that are %s can be enabled for '
                        'non-external primary shelves.' % can_hero_groups
                    )
        else:
            if list(PrimaryHero.objects.filter(enabled=True)) == [self]:
                error_dict['enabled'] = ValidationError(
                    'You can\'t disable the only enabled primary shelf.'
                )
        if error_dict:
            raise ValidationError(error_dict)


class CTACheckMixin:
    def clean(self):
        super().clean()
        both_or_neither = not (bool(self.cta_text) ^ bool(self.cta_url))
        if getattr(self, 'enabled', True) and not both_or_neither:
            raise ValidationError(
                'Both the call to action URL and text must be defined, or '
                'neither, for enabled shelves.'
            )


class SecondaryHero(CTACheckMixin, ModelBase):
    headline = models.CharField(max_length=50, blank=False)
    description = models.CharField(max_length=100, blank=False)
    cta_url = models.CharField(max_length=255, blank=True)
    cta_text = models.CharField(max_length=20, blank=True)
    enabled = models.BooleanField(null=False, default=False)

    class Meta(ModelBase.Meta):
        indexes = [
            LongNameIndex(
                fields=('enabled',), name='hero_secondaryhero_enabled_1a9ea03c'
            ),
        ]

    def __str__(self):
        return str(self.headline)

    def clean(self):
        super().clean()
        if not self.enabled:
            if list(SecondaryHero.objects.filter(enabled=True)) == [self]:
                raise ValidationError(
                    'You can\'t disable the only enabled secondary shelf.'
                )


class SecondaryHeroModule(CTACheckMixin, ModelBase):
    icon = WidgetCharField(
        choices=DirImageChoices(path=MODULE_ICON_PATH),
        max_length=255,
        widget=IconChoiceWidget,
        blank_text='Not selected',
    )
    description = models.CharField(max_length=50, blank=False)
    cta_url = models.CharField(max_length=255, blank=True)
    cta_text = models.CharField(max_length=20, blank=True)
    shelf = models.ForeignKey(
        SecondaryHero, on_delete=models.CASCADE, related_name='modules'
    )

    def __str__(self):
        return str(self.description)

    @property
    def icon_url(self):
        return f'{MODULE_ICON_URL}{self.icon}'
