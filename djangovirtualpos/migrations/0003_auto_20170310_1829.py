# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('djangovirtualpos', '0002_vpospaymentoperation_response_code'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='vposredsys',
            name='encryption_key_production',
        ),
        migrations.RemoveField(
            model_name='vposredsys',
            name='encryption_key_testing',
        ),
    ]
