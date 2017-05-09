# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('djangovirtualpos', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='vpospaymentoperation',
            name='response_code',
            field=models.CharField(max_length=255, null=True, verbose_name='C\xf3digo de respuesta con estado de aceptaci\xf3n o denegaci\xf3n de la operaci\xf3n.'),
        ),
    ]
