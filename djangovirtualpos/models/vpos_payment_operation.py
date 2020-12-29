# coding=utf-8
import datetime

from django.db import models
from django.db.models import Sum

from ..debug import dlprint
from .defs import VPOS_TYPES, VPOS_STATUS_CHOICES, VIRTUALPOS_STATE_TYPES
from ..util import localize_datetime


class VPOSPaymentOperation(models.Model):
    """
    Operación de pago de TPV
    """
    amount = models.DecimalField(max_digits=6, decimal_places=2, null=False, blank=False,
                                 verbose_name=u"Coste de la operación")
    description = models.CharField(max_length=512, null=False, blank=False, verbose_name=u"Descripción de la venta")
    url_ok = models.CharField(max_length=255, null=False, blank=False, verbose_name=u"URL de OK",
                              help_text=u"URL a la que redirige la pasarela bancaria cuando la compra ha sido un éxito")
    url_nok = models.CharField(max_length=255, null=False, blank=False, verbose_name=u"URL de NOK",
                               help_text=u"URL a la que redirige la pasarela bancaria cuando la compra ha fallado")
    operation_number = models.CharField(max_length=255, null=False, blank=False, verbose_name=u"Número de operación")
    confirmation_code = models.CharField(max_length=255, null=True, blank=False,
                                         verbose_name="Código de confirmación enviado por el banco.")
    confirmation_data = models.TextField(null=True, blank=False,
                                         verbose_name="POST enviado por la pasarela bancaria al confirmar la compra.")
    sale_code = models.CharField(max_length=512, null=False, blank=False, verbose_name=u"Código de la venta",
                                 help_text=u"Código de la venta según la aplicación.")
    status = models.CharField(max_length=64, choices=VPOS_STATUS_CHOICES, null=False, blank=False,
                              verbose_name=u"Estado del pago")

    response_code = models.CharField(max_length=255, null=True, blank=False,
                                     verbose_name=u"Código de respuesta con estado de aceptación o denegación de la operación.")

    creation_datetime = models.DateTimeField(verbose_name="Fecha de creación del objeto")
    last_update_datetime = models.DateTimeField(verbose_name="Fecha de última actualización del objeto")

    type = models.CharField(max_length=16, choices=VPOS_TYPES, default="", verbose_name="Tipo de TPV")
    virtual_point_of_sale = models.ForeignKey("VirtualPointOfSale", parent_link=True, related_name="payment_operations",
                                              null=False)
    environment = models.CharField(max_length=255, choices=VIRTUALPOS_STATE_TYPES, default="", blank=True,
                                   verbose_name="Entorno del TPV")

    @property
    def vpos(self):
        return self.virtual_point_of_sale

    @property
    def total_amount_refunded(self):
        return self.refund_operations.filter(status='completed').aggregate(Sum('amount'))['amount__sum']

    # Comprueba si un pago ha sido totalmente debuelto y cambia el estado en coherencias.
    def compute_payment_refunded_status(self):

        if self.total_amount_refunded == self.amount:
            self.status = "completely_refunded"

        elif self.total_amount_refunded < self.amount:
            dlprint('Devolución parcial de pago.')
            self.status = "partially_refunded"

        elif self.total_amount_refunded > self.amount:
            raise ValueError(u'ERROR. Este caso es imposible, no se puede reembolsar una cantidad superior al pago.')

        self.save()

    ## Guarda el objeto en BD, en realidad lo único que hace es actualizar los datetimes
    def save(self, *args, **kwargs):
        """
        Guarda el objeto en BD, en realidad lo único que hace es actualizar los datetimes.
        El datetime de actualización se actualiza siempre, el de creación sólo al guardar de nuevas.
        """
        # Datetime con el momento actual en UTC
        now_datetime = datetime.datetime.now()
        # Si no se ha guardado aún, el datetime de creación es la fecha actual
        if not self.id:
            self.creation_datetime = localize_datetime(now_datetime)
        # El datetime de actualización es la fecha actual
        self.last_update_datetime = localize_datetime(now_datetime)
        # Llamada al constructor del padre
        super(VPOSPaymentOperation, self).save(*args, **kwargs)