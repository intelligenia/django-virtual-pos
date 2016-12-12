# coding=utf-8

from django.contrib import admin
from djangovirtualpos.models import VirtualPointOfSale, VPOSCeca, VPOSRedsys, VPOSSantanderElavon, VPOSPaypal

admin.site.register(VirtualPointOfSale)
admin.site.register(VPOSCeca)
admin.site.register(VPOSRedsys)
admin.site.register(VPOSPaypal)
admin.site.register(VPOSSantanderElavon)


