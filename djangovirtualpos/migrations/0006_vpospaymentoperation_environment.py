# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('djangovirtualpos', '0005_auto_20170314_1057'),
    ]

    operations = [
        migrations.AddField(
            model_name='vpospaymentoperation',
            name='environment',
            field=models.CharField(default='', max_length=255, verbose_name='Entorno del TPV', blank=True, choices=[('testing', 'Pruebas'), ('production', 'Producci\xf3n')]),
        ),
    ]
