# Generated by Django 2.2.16 on 2020-10-15 17:51

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import olympia.amo.models


class Migration(migrations.Migration):

    dependencies = [
        ("promoted", "0009_promotedtheme"),
    ]

    operations = [
        migrations.CreateModel(
            name="PromotedSubscription",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    models.DateTimeField(
                        blank=True,
                        default=django.utils.timezone.now,
                        editable=False,
                    ),
                ),
                ("modified", models.DateTimeField(auto_now=True)),
                (
                    "link_visited_at",
                    models.DateTimeField(
                        help_text=(
                            "This date is set when the developer has visited"
                            " the onboarding page.",
                        ),
                        null=True,
                    ),
                ),
                (
                    "stripe_session_id",
                    models.CharField(default=None, max_length=100, null=True),
                ),
                (
                    "payment_cancelled_at",
                    models.DateTimeField(
                        help_text=(
                            "This date is set when the developer has cancelled"
                            " the payment process."
                        ),
                        null=True,
                    ),
                ),
                (
                    "paid_at",
                    models.DateTimeField(
                        help_text=(
                            "This date is set when the developer successfully"
                            " completed the Stripe Checkout process."
                        ),
                        null=True,
                    ),
                ),
                (
                    "promoted_addon",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="promoted.PromotedAddon",
                    ),
                ),
            ],
            options={
                "get_latest_by": "created",
                "abstract": False,
                "base_manager_name": "objects",
            },
            bases=(
                olympia.amo.models.SearchMixin,
                olympia.amo.models.SaveUpdateMixin,
                models.Model,
            ),
        ),
    ]
