# coding=utf-8
import base64
import json
import urllib2

from django.db import models
from django.http import HttpResponse

from djangovirtualpos.debug import dlprint
from djangovirtualpos.models.exceptions import VPOSOperationAlreadyConfirmed, VPOSOperationNotImplemented
from djangovirtualpos.models.virtualpointofsale import VirtualPointOfSale
from djangovirtualpos.models.vpos_payment_operation import VPOSPaymentOperation


class VPOSBitpay(VirtualPointOfSale):
    """
    Pago con criptomoneda usando la plataforma bitpay.com
    Siguiendo la documentación: https://bitpay.com/api
    """

    CURRENCIES = (
        ('EUR', 'Euro'),
        ('USD', 'Dolares'),
        ('BTC', 'Bitcoin'),
    )

    # Velocidad de la operación en función de la fortaleza de la confirmación en blockchain.
    TRANSACTION_SPEED = (
        ('high', 'Alta'),  # Se supone confirma en el momento que se ejecuta.
        ('medium', 'Media'),  # Se supone confirmada una vez se verifica 1 bloque. (~10 min)
        ('low', 'Baja'),  # Se supone confirmada una vez se verifican 6 bloques (~1 hora)
    )

    # Relación con el padre (TPV).
    # Al poner el signo "+" como "related_name" evitamos que desde el padre
    # se pueda seguir la relación hasta aquí (ya que cada uno de las clases
    # que heredan de ella estará en una tabla y sería un lío).
    parent = models.OneToOneField(VirtualPointOfSale, parent_link=True, related_name="+", null=False,
                                  db_column="vpos_id")
    testing_api_key = models.CharField(max_length=512, null=True, blank=True,
                                       verbose_name="API Key de Bitpay para entorno de test")
    production_api_key = models.CharField(max_length=512, null=False, blank=False,
                                          verbose_name="API Key de Bitpay para entorno de producción")
    currency = models.CharField(max_length=3, choices=CURRENCIES, default='EUR', null=False, blank=False,
                                verbose_name="Moneda (EUR, USD, BTC)")
    transaction_speed = models.CharField(max_length=10, choices=TRANSACTION_SPEED, default='medium', null=False,
                                         blank=False, verbose_name="Velocidad de la operación")
    notification_url = models.URLField(verbose_name="Url notificaciones actualización estados (https)", null=False,
                                       blank=False)

    # Prefijo usado para identicar al servidor desde el que se realiza la petición, en caso de usar TPV-Proxy.
    operation_number_prefix = models.CharField(max_length=20, null=True, blank=True,
                                               verbose_name="Prefijo del número de operación")

    bitpay_url = {
        "production": {
            "api": "https://bitpay.com/api/",
            "create_invoice": "https://bitpay.com/api/invoice",
            "payment": "https://bitpay.com/invoice/"
        },
        "testing": {
            "api": "https://test.bitpay.com/api/",
            "create_invoice": "https://test.bitpay.com/api/invoice",
            "payment": "https://test.bitpay.com/invoice/"
        }
    }

    def configurePayment(self, **kwargs):

        self.api_key = self.testing_api_key

        if self.parent.environment == "production":
            self.api_key = self.production_api_key

        self.importe = self.parent.operation.amount

    def setupPayment(self, operation_number=None, code_len=40):
        """
        Inicializa el pago
        Obtiene el número de operación, que para el caso de BitPay será el id dado
        :param operation_number:
        :param code_len:
        :return:
        """

        dlprint("BitPay.setupPayment")
        if operation_number:
            self.bitpay_id = operation_number
            dlprint("Rescato el operation number para esta venta {0}".format(self.bitpay_id))
            return self.bitpay_id

        params = {
            'price': self.importe,
            'currency': self.currency,
            'redirectURL': self.parent.operation.url_ok,
            'itemDesc': self.parent.operation.description,
            'notificationURL': self.notification_url,
            # Campos libres para el programador, puedes introducir cualquier información útil.
            # En nuestro caso el prefijo de la operación, que ayuda a TPV proxy a identificar el servidor
            # desde donde se ha ejecutado la operación.
            'posData': '{"operation_number_prefix": "' + str(self.operation_number_prefix) + '"}',
            'fullNotifications': True
        }

        # URL de pago según el entorno
        url = self.bitpay_url[self.parent.environment]["create_invoice"]

        post = json.dumps(params)
        req = urllib2.Request(url)
        base64string = base64.encodestring(self.api_key).replace('\n', '')
        req.add_header("Authorization", "Basic %s" % base64string)
        req.add_header("Content-Type", "application/json")
        req.add_header("Content-Length", len(post))

        json_response = urllib2.urlopen(req, post)
        response = json.load(json_response)

        dlprint(u"Parametros que enviamos a Bitpay para crear la operación")
        dlprint(params)

        dlprint(u"Respuesta de Bitpay")
        dlprint(response)

        if response.get("error"):
            error = response.get("error")
            message = error.get("message")
            error_type = error.get("type")
            raise ValueError(u"ERROR. {0} - {1}".format(message, error_type))

        if not response.get("id"):
            raise ValueError(u"ERROR. La respuesta no contiene id de invoice.")

        self.bitpay_id = response.get("id")

        return self.bitpay_id

    def getPaymentFormData(self):
        """
        Generar formulario (en este caso prepara un submit a la página de bitpay).
        """

        url = self.bitpay_url[self.parent.environment]["payment"]
        data = {"id": self.bitpay_id}

        form_data = {
            "data": data,
            "action": url,
            "method": "get"
        }
        return form_data

    @staticmethod
    def receiveConfirmation(request, **kwargs):

        confirmation_body_param = json.loads(request.body)

        # Almacén de operaciones
        try:
            operation = VPOSPaymentOperation.objects.get(operation_number=confirmation_body_param.get("id"))

            if operation.status != "pending":
                raise VPOSOperationAlreadyConfirmed(u"Operación ya confirmada")

            operation.confirmation_data = {"GET": request.GET.dict(), "POST": request.POST.dict(),
                                           "BODY": confirmation_body_param}
            operation.save()

            dlprint("Operation {0} actualizada en receiveConfirmation()".format(operation.operation_number))
            vpos = operation.virtual_point_of_sale
        except VPOSPaymentOperation.DoesNotExist:
            # Si no existe la operación, están intentando
            # cargar una operación inexistente
            return False

        # Iniciamos el delegado y la operación
        vpos._init_delegated()
        vpos.operation = operation

        vpos.delegated.bitpay_id = operation.confirmation_data["BODY"].get("id")
        vpos.delegated.status = operation.confirmation_data["BODY"].get("status")

        dlprint(u"Lo que recibimos de BitPay: ")
        dlprint(operation.confirmation_data["BODY"])
        return vpos.delegated

    def verifyConfirmation(self):
        # Comprueba si el envío es correcto
        # Para esto, comprobamos si hay alguna operación que tenga el mismo
        # número de operación
        operation = VPOSPaymentOperation.objects.filter(operation_number=self.bitpay_id, status='pending')

        if operation:
            # En caso de recibir, un estado confirmado ()
            # NOTA: Bitpay tiene los siguientes posibles estados:
            # new, paid, confirmed, complete, expired, invalid.
            if self.status == "paid":
                dlprint(u"La operación es confirmada")
                return True

        return False

    def charge(self):
        dlprint(u"Marca la operacion como pagada")
        return HttpResponse("OK")

    def responseNok(self, extended_status=""):
        dlprint("responseNok")
        return HttpResponse("NOK")

    ####################################################################
    ## Paso R1 (Refund) Configura el TPV en modo devolución y ejecuta la operación
    def refund(self, operation_sale_code, refund_amount, description):
        raise VPOSOperationNotImplemented(u"No se ha implementado la operación de devolución particular para Bitpay.")

    ####################################################################
    ## Paso R2.a. Respuesta positiva a confirmación asíncrona de refund
    def refund_response_ok(self, extended_status=""):
        raise VPOSOperationNotImplemented(u"No se ha implementado la operación de devolución particular para Bitpay.")

    ####################################################################
    ## Paso R2.b. Respuesta negativa a confirmación asíncrona de refund
    def refund_response_nok(self, extended_status=""):
        raise VPOSOperationNotImplemented(u"No se ha implementado la operación de devolución particular para Bitpay.")