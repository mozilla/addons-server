# Generated by Django 3.2.15 on 2022-08-26 10:55

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('activity', '0015_auto_20220826_0956'),
    ]

    operations = [
        migrations.RunSQL(
            'UPDATE `log_activity_ip` '
            'SET `ip_address_binary` = INET6_ATON(`ip_address`) '
            'WHERE `ip_address_binary` IS NULL;')
    ]
