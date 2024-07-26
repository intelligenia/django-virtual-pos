# -*- coding: utf-8 -*-
# Generated by Django 1.10.6 on 2017-03-28 16:08
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('djangovirtualpos', '0008_auto_20170321_1437'),
    ]

    operations = [
        migrations.CreateModel(
            name='VPOSRefundOperation',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=6, verbose_name='Cantidad de la devoluci\xf3n')),
                ('description', models.CharField(max_length=512, verbose_name='Descripci\xf3n de la devoluci\xf3n')),
                ('operation_number', models.CharField(max_length=255, verbose_name='N\xfamero de operaci\xf3n')),
                ('confirmation_code', models.CharField(max_length=255, null=True, verbose_name='C\xf3digo de confirmaci\xf3n enviado por el banco.')),
                ('status', models.CharField(choices=[('completed', 'Completed'), ('failed', 'Failed')], max_length=64, verbose_name='Estado de la devoluci\xf3n')),
                ('creation_datetime', models.DateTimeField(verbose_name='Fecha de creaci\xf3n del objeto')),
                ('last_update_datetime', models.DateTimeField(verbose_name='Fecha de \xfaltima actualizaci\xf3n del objeto')),
            ],
        ),
        migrations.AlterField(
            model_name='vpospaymentoperation',
            name='status',
            field=models.CharField(choices=[('pending', 'Pending'), ('completed', 'Completed'), ('failed', 'Failed'), ('partially_refunded', 'Partially Refunded'), ('completely_refunded', 'Completely Refunded')], max_length=64, verbose_name='Estado del pago'),
        ),
        migrations.AddField(
            model_name='vposrefundoperation',
            name='payment',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='refund_operation', to='djangovirtualpos.VPOSPaymentOperation'),
        ),
    ]
