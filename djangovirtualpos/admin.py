# coding=utf-8

from django.contrib import admin
from djangovirtualpos.models import VPOS, VPOSCeca, VPOSRedsys, VPOSSantanderElavon, VPOSPaypal

admin.site.register(VPOS)
admin.site.register(VPOSCeca)
admin.site.register(VPOSRedsys)
admin.site.register(VPOSPaypal)
admin.site.register(VPOSSantanderElavon)


