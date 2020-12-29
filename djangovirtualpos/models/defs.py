# coding=utf-8
from django.utils.translation import ugettext_lazy as _

VPOS_TYPES = (
    ("ceca", _(u"TPV Virtual - Confederación Española de Cajas de Ahorros (CECA)")),
    ("paypal", _(u"Paypal")),
    ("redsys", _(u"TPV Redsys")),
    ("santanderelavon", _(u"TPV Santander Elavon")),
    ("bitpay", _(u"TPV Bitpay")),
)
VPOS_STATUS_CHOICES = (
    ("pending", _(u"Pending")),
    ("completed", _(u"Completed")),
    ("failed", _(u"Failed")),
    ("partially_refunded", _(u"Partially Refunded")),
    ("completely_refunded", _(u"Completely Refunded")),
)
VIRTUALPOS_STATE_TYPES = (
    ("testing", "Pruebas"),
    ("production", "Producción")
)
VPOS_REFUND_STATUS_CHOICES = (
    ("pending", _(u"Pending")),
    ("completed", _(u"Completed")),
    ("failed", _(u"Failed")),
)