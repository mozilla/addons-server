# Generated by Django 2.2.14 on 2020-07-17 11:37

from django.db import migrations, models



class Migration(migrations.Migration):

    dependencies = [
        ('versions', '0008_auto_20200625_1114'),
    ]

    operations = [
        migrations.AlterField(
            model_name='version',
            name='recommendation_approved',
            field=models.BooleanField(null=True),
        ),
    ]
