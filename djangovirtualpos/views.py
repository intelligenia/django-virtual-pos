# -*- coding: utf-8 -*-

from __future__ import unicode_literals

from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from djangovirtualpos.models import VirtualPointOfSale, VPOSCantCharge


from django.http import JsonResponse

# Confirm sale
def confirm_payment(request, virtualpos_type, sale_model):
    """
    This view will be called by the bank.
    """

    # Checking if the Point of Sale exists
    virtual_pos = VirtualPointOfSale.receiveConfirmation(request, virtualpos_type=virtualpos_type)

    if not virtual_pos:
        # The VPOS does not exist, inform the bank with a cancel
        # response if needed
        return VirtualPointOfSale.staticResponseNok(virtualpos_type)

    # Verify if bank confirmation is indeed from the bank
    verified = virtual_pos.verifyConfirmation()
    operation_number = virtual_pos.operation.operation_number

    with transaction.atomic():
        try:
            # Getting your payment object from operation number
            payment = sale_model.objects.get(operation_number=operation_number, status="pending")
        except ObjectDoesNotExist:
            return virtual_pos.responseNok("not_exists")

        if verified:
            # Charge the money and answer the bank confirmation
            try:
                response = virtual_pos.charge()
                # Implement the online_confirm method in your payment
                # this method will mark this payment as paid and will
                # store the payment date and time.
                payment.online_confirm()
            except VPOSCantCharge as e:
                return virtual_pos.responseNok(extended_status=e)
            except Exception as e:
                return virtual_pos.responseNok("cant_charge")

        else:
            # Payment could not be verified
            # signature is not right
            response = virtual_pos.responseNok("verification_error")

        return response