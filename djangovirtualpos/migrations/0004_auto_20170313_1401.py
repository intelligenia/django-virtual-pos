# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('djangovirtualpos', '0003_auto_20170310_1829'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='virtualpointofsale',
            options={'ordering': ['name'], 'verbose_name': 'virtual point of sale', 'verbose_name_plural': 'virtual points of sale', 'permissions': (('view_virtualpointofsale', 'Can view Virtual Points of Sale'),)},
        ),
    ]
