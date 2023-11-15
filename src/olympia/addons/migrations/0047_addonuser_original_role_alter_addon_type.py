# Generated by Django 4.2.6 on 2023-11-15 14:41

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("addons", "0046_auto_20230612_1057"),
    ]

    operations = [
        migrations.AddField(
            model_name="addonuser",
            name="original_role",
            field=models.SmallIntegerField(
                choices=[(5, "Owner"), (4, "Developer")],
                default=4,
                help_text="Role to assign if user is unbanned",
            ),
        ),
        migrations.AlterField(
            model_name="addon",
            name="type",
            field=models.PositiveIntegerField(
                choices=[
                    (1, "Extension"),
                    (2, "Deprecated Complete Theme"),
                    (3, "Dictionary"),
                    (4, "Deprecated Search Engine"),
                    (5, "Language Pack"),
                    (6, "Deprecated Language Pack (Add-on)"),
                    (7, "Deprecated Plugin"),
                    (9, "Deprecated LWT"),
                    (10, "Theme (Static)"),
                    (12, "Deprecated Site Permission"),
                ],
                db_column="addontype_id",
                default=1,
            ),
        ),
    ]
