# coding=utf-8

from django.contrib import admin
from djangovirtualpos.models import VirtualPointOfSale, VPOSRefundOperation
from djangovirtualpos.models.backends.vpos_bitpay import VPOSBitpay
from djangovirtualpos.models.backends.vpos_ceca import VPOSCeca
from djangovirtualpos.models.backends.vpos_paypal import VPOSPaypal
from djangovirtualpos.models.backends.vpos_redsys import VPOSRedsys
from djangovirtualpos.models.backends.vpos_santanderelavon import VPOSSantanderElavon

admin.site.register(VirtualPointOfSale)
admin.site.register(VPOSRefundOperation)
admin.site.register(VPOSCeca)
admin.site.register(VPOSRedsys)
admin.site.register(VPOSPaypal)
admin.site.register(VPOSSantanderElavon)
admin.site.register(VPOSBitpay)


