# coding=utf-8
import datetime

from django.db import models

from .defs import VPOS_REFUND_STATUS_CHOICES
from .vpos_payment_operation import VPOSPaymentOperation
from ..util import localize_datetime


class VPOSRefundOperation(models.Model):
    """
    Entidad que gestiona las devoluciones de pagos realizados.
    Las devoluciones pueden ser totales o parciales, por tanto un "pago" tiene una relación uno a muchos con "devoluciones".
    """
    amount = models.DecimalField(max_digits=6, decimal_places=2, null=False, blank=False,
                                 verbose_name=u"Cantidad de la devolución")
    description = models.CharField(max_length=512, null=False, blank=False,
                                   verbose_name=u"Descripción de la devolución")

    operation_number = models.CharField(max_length=255, null=False, blank=False, verbose_name=u"Número de operación")
    status = models.CharField(max_length=64, choices=VPOS_REFUND_STATUS_CHOICES, null=False, blank=False,
                              verbose_name=u"Estado de la devolución")
    creation_datetime = models.DateTimeField(verbose_name="Fecha de creación del objeto")
    last_update_datetime = models.DateTimeField(verbose_name="Fecha de última actualización del objeto")
    payment = models.ForeignKey(VPOSPaymentOperation, on_delete=models.PROTECT, related_name="refund_operations")

    @property
    def virtual_point_of_sale(self):
        return self.payment.virtual_point_of_sale

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
        super(VPOSRefundOperation, self).save(*args, **kwargs)


