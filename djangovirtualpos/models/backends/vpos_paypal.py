# coding=utf-8
import urllib
import urllib2
import urlparse

from django.conf import settings
from django.db import models
from django.shortcuts import redirect
from django.urls import reverse

from djangovirtualpos.debug import dlprint
from djangovirtualpos.models.exceptions import VPOSOperationNotImplemented
from djangovirtualpos.models.virtualpointofsale import VirtualPointOfSale
from djangovirtualpos.models.vpos_payment_operation import VPOSPaymentOperation


class VPOSPaypal(VirtualPointOfSale):
    """Información de configuración del TPV Virtual PayPal """
    ## Todo TPV tiene una relación con los datos generales del TPV
    parent = models.OneToOneField(VirtualPointOfSale, parent_link=True, related_name="+", null=False,
                                  db_column="vpos_id")

    # nombre de usuario para la API de Paypal
    API_username = models.CharField(max_length=60, null=False, blank=False, verbose_name="API_username")
    # contraseña para la API de Paypal
    API_password = models.CharField(max_length=60, null=False, blank=False, verbose_name="API_password")
    # firma para la API de Paypal
    API_signature = models.CharField(max_length=60, null=False, blank=False, verbose_name="API_signature")
    # versión de la API de Paypal
    Version = models.CharField(max_length=3, null=False, blank=False, verbose_name="Version")

    Return_url = {
        "production": "http://" + settings.ALLOWED_HOSTS[0] + "/payment/confirm/paypal",
        "testing": "http://" + settings.ALLOWED_HOSTS[0] + "/payment/confirm/paypal"
    }
    Cancel_url = {
        "production": "http://" + settings.ALLOWED_HOSTS[0] + "/es/payment/cancel/",
        "testing": "http://" + settings.ALLOWED_HOSTS[0] + "/es/payment/cancel/"
    }
    paypal_url = {
        "production": {
            "api": "https://api-3t.paypal.com/nvp",
            "payment": "https://www.paypal.com/cgi-bin/webscr",
        },
        "testing": {
            "api": "https://api-3t.sandbox.paypal.com/nvp",
            "payment": "https://www.sandbox.paypal.com/cgi-bin/webscr",
        }
    }

    # URL de pago que variará según el entorno
    url = None
    # Importe de la venta
    importe = None
    # Indica el número de operación
    operation_number = None
    # estado que indica si estamos en api o payment
    endpoint = "api"
    # Tipo de moneda usada en la operación, en este caso sera Euros
    tipo_moneda = "978"
    # Método de envío de formulario
    method = "SetExpressCheckout"
    # Versión de API de PayPal
    version = "95"
    # ID de la moneda
    PaymentRequest_0_CurrencyCode = "EUR"
    # Será siempre este valor fijo
    PaymentRequest_0_PaymentAction = "Sale"
    # Controla si se ha recibido la confirmación de pago del TPV y si esta es correcta.
    is_verified = False
    # Token devuelto por Paypal
    valor_token = None
    # ID del comprador devuelta por Paypal
    valor_payerID = None

    ## Constructor del TPV PayPal
    def __init__(self, *args, **kwargs):
        super(VPOSPaypal, self).__init__(*args, **kwargs)

    def __unicode__(self):
        return u"API_username: {0}".format(self.API_username)

    @classmethod
    def form(cls):
        from ...forms import VPOSPaypalForm
        return VPOSPaypalForm

    ####################################################################
    ## Paso 1.1. Configuración del pago
    def configurePayment(self, **kwargs):
        # URL de pago según el entorno
        self.url = self.paypal_url[self.parent.environment]

        # Formato para Importe: según paypal, ha de tener un formato con un punto decimal con exactamente
        # dos dígitos a la derecha que representa los céntimos
        self.importe = "{0:.2f}".format(float(self.parent.operation.amount))

    ####################################################################
    ## Paso 1.2. Preparación del TPV y Generación del número de operación (token)
    def setupPayment(self, operation_number=None, code_len=12):
        """
        Inicializa el
        Obtiene el número de operación, que para el caso de Paypal será el token
        """
        dlprint("Paypal.setupPayment")
        if operation_number:
            self.token = operation_number
            dlprint("Rescato el operation number para esta venta {0}".format(self.token))
            return self.token

        dlprint("El operation number no existía")
        token_url = self.paypal_url[self.parent.environment][self.endpoint]
        dlprint("Attribute paypal_url " + unicode(self.paypal_url))
        dlprint("Endpoint {0}".format(self.endpoint))
        dlprint("Enviroment {0}".format(self.parent.environment))
        dlprint("URL de envío {0}".format(token_url))

        # Preparamos los campos del formulario
        query_args = {
            # Indica el método a usar
            "METHOD": self.method,
            # Indica la versión
            "VERSION": self.version,
            # Indica el usuario registrado como buyer en paypal
            "USER": self.API_username,
            # Indica la contraseña del usuario registrado como buyer en paypal
            "PWD": self.API_password,
            # Indica la firma del usuario registrado como buyer en paypal
            "SIGNATURE": self.API_signature,
            # Importe de la venta
            "PAYMENTREQUEST_0_AMT": self.importe,
            # ID de la moneda a utilizar
            "PAYMENTREQUEST_0_CURRENCYCODE": self.PaymentRequest_0_CurrencyCode,
            # URL donde Paypal redirige al usuario comprador después de logearse en Paypal
            "RETURNURL": self.Return_url[self.parent.environment],
            # URL a la que Paypal redirige al comprador si el comprador no aprueba el pago
            "CANCELURL": self.parent.operation.url_nok,
            # Especifíca la acción
            "PAYMENTREQUEST_0_PAYMENTACTION": self.PaymentRequest_0_PaymentAction,
            # Especifica la descripción de la venta
            "L_PAYMENTREQUEST_0_NAME0": unicode(self.parent.operation.description).encode('utf-8'),
            # Especifica el importe final de la venta
            "L_PAYMENTREQUEST_0_AMT0": self.parent.operation.amount
        }
        dlprint(u"Petición por POST")
        dlprint(query_args)

        # Recogemos los datos
        data = urllib.urlencode(query_args)
        dlprint("Recogemos los datos")
        dlprint(data)
        # Enviamos la petición HTTP POST
        request = urllib2.Request(token_url, data)
        # Recogemos la respuesta dada, que vendrá en texto plano
        response = urllib2.urlopen(request)
        res_string = response.read()

        dlprint("Paypal responde")
        dlprint("Respuesta PayPal: " + res_string)

        res = urlparse.parse_qs(res_string)

        # Comprobamos que exista un ACK y que este no contenga el valor "Failure"
        if "ACK" in res and res["ACK"][0] == "Failure":
            raise ValueError(u"ERROR. La respuesta ha sido incorrecta.")

        # Si no devuelve un Token, habrá un error en la venta
        if not "TOKEN" in res:
            raise ValueError(u"ERROR. La respuesta no contiene token.")

        # Si hay más de un token, habrá un error
        if len(res["TOKEN"]) != 1:
            raise ValueError(u"ERROR. El token no tiene un único elemento.")

        self.token = res["TOKEN"][0]
        dlprint("Todo OK el token es: " + self.token)

        return self.token

    ####################################################################
    ## Paso 1.3. Obtiene los datos de pago
    ## Este método enviará un formulario por GET con el token dado anteriormente
    def getPaymentFormData(self):
        data = {
            "cmd": "_express-checkout",
            "token": self.token
        }
        form_data = {
            "data": data,
            "action": self.paypal_url[self.parent.environment]["payment"],
            "method": "get"
        }
        return form_data

    ####################################################################
    ## Paso 3.1. Obtiene el número de operación(token) y los datos que nos
    ## envíe la pasarela de pago.
    @staticmethod
    def receiveConfirmation(request, **kwargs):

        # Almacén de operaciones
        try:
            operation = VPOSPaymentOperation.objects.get(operation_number=request.GET.get("token"))
            operation.confirmation_data = {"GET": request.GET.dict(), "POST": request.POST.dict()}
            operation.confirmation_code = request.POST.get("token")
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

        # Iniciamos los valores recibidos en el delegado

        # ID del comprador
        vpos.delegated.payer_id = request.GET.get("PayerID")
        # Token
        vpos.delegated.token = request.GET.get("token")

        dlprint(u"Lo que recibimos de Paypal: ")
        dlprint(request.GET)
        return vpos.delegated

    ####################################################################
    ## Paso 3.2. Verifica que los datos enviados desde
    ## la pasarela de pago identifiquen a una operación de compra.
    def verifyConfirmation(self):
        # Comprueba si el envío es correcto
        # Para esto, comprobamos si hay alguna operación que tenga el mismo
        # número de operación
        self.valor_token = self.token
        self.operation_number = self.token
        # Almacenamos el valor del ID del comprador, para más tarde usarlo
        self.valor_payerID = self.payer_id
        operation = VPOSPaymentOperation.objects.filter(operation_number=self.valor_token)
        if len(operation):
            return True

        return False

    ####################################################################
    ## Paso 3.3. Realiza el cobro y genera un formulario, para comunicarnos
    ## con PayPal
    def charge(self):

        # Prepara los campos del formulario
        query_args = {
            'METHOD': "DoExpressCheckoutPayment",
            'USER': self.API_username,
            'PWD': self.API_password,
            'SIGNATURE': self.API_signature,
            'VERSION': self.Version,
            'TOKEN': self.operation_number,
            'PAYERID': self.valor_payerID,
            'PAYMENTREQUEST_0_CURRENCYCODE': self.PaymentRequest_0_CurrencyCode,
            'PAYMENTREQUEST_0_PAYMENTACTION': self.PaymentRequest_0_PaymentAction,
            'PAYMENTREQUEST_0_AMT': self.parent.operation.amount,
        }

        data = urllib.urlencode(query_args)
        # Realizamos una petición HTTP POST
        api_url = self.paypal_url[self.parent.environment]["api"]
        request = urllib2.Request(api_url, data)

        # Almacenamos la respuesta dada por PayPal
        response = urllib2.urlopen(request)
        res_string = response.read()
        res = urlparse.parse_qs(res_string)

        # Comprobamos que haya un ACK y que no tenga el valor de "Failure"
        if "ACK" in res and res["ACK"][0] == "Failure":
            raise ValueError(u"ERROR. La respuesta ha sido incorrecta.")

        # Si no hay un token, entonces habrá un error
        if not "TOKEN" in res:
            raise ValueError(u"ERROR. La respuesta no contiene token.")

        # Si hay más de un token, habrá un error
        if len(res["TOKEN"]) != 1:
            raise ValueError(u"ERROR. El token no tiene un único elemento.")

        token = res["TOKEN"][0]

        dlprint(u"El token es {0} y el número de operación era ".format(token, self.parent.operation.sale_code))

        # Si llegamos aquí, es que ha ido bien la operación, asi que redireccionamos a la url de payment_ok
        return redirect(reverse("payment_ok_url", kwargs={"sale_code": self.parent.operation.sale_code}))

    ####################################################################
    ## Paso 3.3b. Si ha habido un error en el pago, redirigimos a la url correcta
    def responseNok(self, **kwargs):
        dlprint("responseNok")
        # En Paypal no se exige una respuesta, por parte del comercio, para verificar
        # que la operación ha sido negativa, redireccionamos a la url de cancelación
        return redirect(reverse("payment_cancel_url", kwargs={"sale_code": self.parent.operation.sale_code}))

    ####################################################################
    ## Paso R. (Refund) Configura el TPV en modo devolución
    ## TODO: No implementado
    def refund(self, operation_sale_code, refund_amount, description):
        raise VPOSOperationNotImplemented(u"No se ha implementado la operación de devolución particular para Paypal.")

    ####################################################################
    ## Paso R2.a. Respuesta positiva a confirmación asíncrona de refund
    def refund_response_ok(self, extended_status=""):
        raise VPOSOperationNotImplemented(u"No se ha implementado la operación de devolución particular para Paypal.")

    ####################################################################
    ## Paso R2.b. Respuesta negativa a confirmación asíncrona de refund
    def refund_response_nok(self, extended_status=""):
        raise VPOSOperationNotImplemented(u"No se ha implementado la operación de devolución particular para Paypal.")