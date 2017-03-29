# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('djangovirtualpos', '0007_auto_20170320_1757'),
    ]

    operations = [
        migrations.AlterField(
            model_name='vpospaymentoperation',
            name='sale_code',
            field=models.CharField(help_text='C\xf3digo de la venta seg\xfan la aplicaci\xf3n.', max_length=512, verbose_name='C\xf3digo de la venta'),
        ),
    ]
