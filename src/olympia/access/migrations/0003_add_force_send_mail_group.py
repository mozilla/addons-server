from django.db import migrations

from olympia.amo.mail import DevEmailBackend

def create_group(apps, schema_editor):
    Group = apps.get_model('access', 'Group')

    Group.objects.create(
        name=DevEmailBackend.force_send_mail_group,
        notes=(
            'UserProfiles belonging to this group will have real emails sent'
            ' to them in dev/stage environments. This is useful for testing email flows.'
        )
    )

def delete_group(apps, schema_editor):
    Group = apps.get_model('access', 'Group')

    Group.objects.filter(name=DevEmailBackend.force_send_mail_group).delete()

class Migration(migrations.Migration):

    dependencies = [
        ('access', '0002_give_api_bypass_throttling_permission'),
    ]

    operations = [
        migrations.RunPython(create_group, delete_group)
    ]
