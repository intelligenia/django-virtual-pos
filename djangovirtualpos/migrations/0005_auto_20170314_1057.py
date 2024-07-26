# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('djangovirtualpos', '0004_auto_20170313_1401'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='virtualpointofsale',
            options={'ordering': ['name'], 'verbose_name': 'virtual point of sale', 'verbose_name_plural': 'virtual points of sale', 'permissions': (('view_virtualpointofsale', 'View Virtual Points of Sale'),)},
        ),
        migrations.AlterField(
            model_name='virtualpointofsale',
            name='distributor_cif',
            field=models.CharField(help_text='C.I.F. del distribuidor.', max_length=150, verbose_name='CIF del distribuidor', blank=True),
        ),
        migrations.AlterField(
            model_name='virtualpointofsale',
            name='distributor_name',
            field=models.CharField(help_text='Raz\xf3n social del distribuidor.', max_length=512, verbose_name='Raz\xf3n social del distribuidor', blank=True),
        ),
    ]
