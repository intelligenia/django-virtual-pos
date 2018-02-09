# coding=utf-8

from django.contrib import admin
from djangovirtualpos.models import VirtualPointOfSale, VPOSRefundOperation, VPOSCeca, VPOSRedsys, VPOSSantanderElavon, VPOSPaypal, VPOSBitpay

admin.site.register(VirtualPointOfSale)
admin.site.register(VPOSRefundOperation)
admin.site.register(VPOSCeca)
admin.site.register(VPOSRedsys)
admin.site.register(VPOSPaypal)
admin.site.register(VPOSSantanderElavon)
admin.site.register(VPOSBitpay)


