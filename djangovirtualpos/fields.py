# -*- coding: utf-8 -*-

from django.forms import forms
from django.forms.models import ModelMultipleChoiceField
from django.contrib.admin.widgets import FilteredSelectMultiple
from django.db.models import Count

from djangovirtualpos import models


class VPOSField(ModelMultipleChoiceField):
    """ Campo personalizado para la selección de TPVs """

    def __init__(self, queryset=None, required=True,
                 widget=None, label="VPOSs", initial=None,
                 help_text="TPVs que se podrán utilizar para realizar el pago online.", *args, **kwargs):

        if queryset is None:
            queryset = models.VPOS.objects.filter(is_deleted=False)

        if widget is None:
            widget = FilteredSelectMultiple("", False)

        super(VPOSField, self).__init__(
            queryset=queryset,
            required=required,
            widget=widget,
            label=label,
            initial=initial,
            help_text=help_text,
            *args, **kwargs)

    def clean(self, value):
        if value:
            # Si se reciben valores (id's de Tpvs), cargarlos para comprobar si son todos del mismo tipo.
            # Construimos un ValuesQuerySet con sólo el campo "type", hacemos la cuenta y ordenamos en orden descendente para comprobar el primero (esto es como hacer un "group_by" y un count)
            # Si el primero es mayor que 1 mostramos el error oportuno.
            count = models.VPOS.objects.filter(id__in=value).values("type").annotate(Count("type")).order_by(
                "-type__count")
            if count[0]["type__count"] > 1:
                raise forms.ValidationError("Asegúrese de no seleccionar más de un TPV del tipo '{0}'".format(
                    dict(models.VPOS_TYPES)[count[0]["type"]]))
        return super(VPOSField, self).clean(value)
