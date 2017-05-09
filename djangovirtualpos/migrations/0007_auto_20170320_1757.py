# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('djangovirtualpos', '0006_vpospaymentoperation_environment'),
    ]

    operations = [
        migrations.AlterField(
            model_name='vpospaymentoperation',
            name='sale_code',
            field=models.CharField(help_text='C\xf3digo de la venta seg\xfan la aplicaci\xf3n.', unique=True, max_length=255, verbose_name='C\xf3digo de la venta'),
        ),
        migrations.AlterField(
            model_name='vpospaymentoperation',
            name='virtual_point_of_sale',
            field=models.ForeignKey(parent_link=True, related_name='payment_operations', to='djangovirtualpos.VirtualPointOfSale'),
        ),
    ]
