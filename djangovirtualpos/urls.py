
from __future__ import unicode_literals

from django.conf import settings
from django.conf.urls import url, include
from django.conf.urls.static import static
from django.contrib import admin


from views import confirm_payment

urlpatterns = [
    url(r'^confirm/$', confirm_payment, name="confirm_payment")
]
