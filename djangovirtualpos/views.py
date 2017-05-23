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


def set_payment_attributes(request, sale_model, sale_ok_url, sale_nok_url, reference_number=False):
    """
    Set payment attributes for the form that makes the first call to the VPOS.
    :param request: HttpRequest.
    :param sale_model: Sale model. Must have "status" and "operation_number" attributes and "online_confirm" method.
    :param sale_ok_url: Name of the URL used to redirect client when sale is successful.
    :param sale_nok_url: Name of the URL used to redirect client when sale is not successful.
    :return: HttpResponse.
    """
    if request.method == 'GET':
        return JsonResponse({"message":u"Method not valid."})

    # Getting the VPOS and the Sale
    try:
        # Getting the VirtualPointOfSale object
        virtual_point_of_sale = VirtualPointOfSale.get(id=request.POST["vpos_id"], is_erased=False)
        # Getting Sale object
        payment_code = request.POST["payment_code"]
        sale = sale_model.objects.get(code=payment_code, status="pending")
        sale.virtual_point_of_sale = virtual_point_of_sale
        sale.save()

    except ObjectDoesNotExist as e:
        return JsonResponse({"message":u"La orden de pago no ha sido previamente creada."}, status=404)

    except VirtualPointOfSale.DoesNotExist:
        return JsonResponse({"message": u"VirtualPOS does NOT exist"}, status=404)

    virtual_point_of_sale.configurePayment(
        # Payment amount
        amount=sale.amount,
        # Payment description
        description=sale.description,
        # Sale code
        sale_code=sale.code,
        # Return URLs
        url_ok=request.build_absolute_uri(reverse(sale_ok_url, kwargs={"sale_code": sale.code})),
        url_nok=request.build_absolute_uri(reverse(sale_nok_url, kwargs={"sale_code": sale.code})),
    )

    # Operation number assignment. This operation number depends on the
    # Virtual VPOS selected, it can be letters and numbers or numbers
    # or even match with a specific pattern depending on the
    # Virtual VPOS selected, remember.
    try:
        # Operation number generation and assignement
        operation_number = virtual_point_of_sale.setupPayment()
        # Update operation number of sale
        sale.operation_number = operation_number
        sale_model.objects.filter(id=sale.id).update(operation_number=operation_number)
    except Exception as e:
        return JsonResponse({"message": u"Error generating operation number {0}".format(e)}, status=500)

    # Payment form data
    if hasattr(reference_number, "lower") and reference_number.lower() == "request":
        form_data = virtual_point_of_sale.getPaymentFormData(reference_number="request")
    elif reference_number:
        form_data = virtual_point_of_sale.getPaymentFormData(reference_number=reference_number)
    else:
        form_data = virtual_point_of_sale.getPaymentFormData(reference_number=False)

    # Debug message
    form_data["message"] = "Payment {0} updated. Returning payment attributes.".format(payment_code)

    # Return JSON response
    return JsonResponse(form_data)


# Confirm sale
@csrf_exempt
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
                payment.virtual_pos = virtual_pos
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