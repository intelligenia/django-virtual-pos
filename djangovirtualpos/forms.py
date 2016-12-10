# -*- coding: utf-8 -*-

from django import forms
from models import VPOSCeca, VPOSRedsys, VPOSPaypal, VPOSSantanderElavon

from django.conf import settings
from models import VPOS_TYPES


class TrimForm(forms.ModelForm):
    """Django no hace trim por defecto, así que tenemos que crear esta clase
	para hacerlo nosotros de forma explícita a la hora de realizar la
	validación del formulario."""

    def clean(self):
        cleaned_data = super(TrimForm, self).clean()

        for field in self.cleaned_data:
            if isinstance(self.cleaned_data[field], basestring):
                self.cleaned_data[field] = self.cleaned_data[field].strip()

        # Hay que devolver siempre el array "cleaned_data"
        return cleaned_data


# Habrá que añadir un formulario nuevo como este para cada uno de los distintos
# TPVs que se añadan
class VPOSCecaForm(TrimForm):
    """Formulario para el modelo TpvCeca."""

    class Meta:
        model = VPOSCeca
        exclude = ("type", "is_erased")


class VPOSRedsysForm(TrimForm):
    """Formulario para el modelo TpvRedsys."""

    class Meta:
        model = VPOSRedsys
        exclude = ("type", "is_erased")


class VPOSPaypalForm(TrimForm):
    """Formulario para el modelo TpvPaypal."""

    class Meta:
        model = VPOSPaypal
        exclude = ("type", "is_erased")


class VPOSSantanderElavonForm(TrimForm):
    """Formulario para el modelo TpvSantanderElavon."""

    class Meta:
        model = VPOSSantanderElavon
        exclude = ("type", "is_erased")


# Esta variable habrá que actualizarla cada vez que se añada un formulario
# para un TPV
VPOS_FORMS = {
    "ceca": VPOSCecaForm,
    "redsys": VPOSRedsysForm,
    "paypal": VPOSPaypalForm,
    "santanderelavon": VPOSSantanderElavonForm
}


class VPOSTypeForm(forms.Form):
    """Formulario para la selección de tipo de TPV a crear en un paso
	posterior.

	Esta formado por un campo "select" en el que los valores son aquellos
	contenidos en la variable settings.TPVS o todos los disponibles en
	TPV_TYPES en models.py
	"""

    def __init__(self, *args, **kwargs):
        super(VPOSTypeForm, self).__init__(*args, **kwargs)

        if hasattr(settings, "ENABLED_VPOS_LIST") and settings.ENABLED_VPOS_LIST:
            vpos_types = settings.ENABLED_VPOS_LIST
        else:
            vpos_types = VPOS_TYPES

        self.fields["type"] = forms.ChoiceField(choices=vpos_types, required=True, label="Tipo de TPV",
                                                help_text="Tipo de pasarela de pago a crear.")


class DeleteForm(forms.Form):
    """Formulario para confirmación de borrado de elementos"""
    erase = forms.BooleanField(required=False, label="Borrar")
