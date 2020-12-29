# coding=utf-8
import hashlib
import random
import re
import urllib2

from bs4 import BeautifulSoup
from django.core.validators import MinLengthValidator, MaxLengthValidator, RegexValidator
from django.db import models
from django.http import HttpResponse
from django.utils import timezone

from djangovirtualpos.debug import dlprint
from djangovirtualpos.models.exceptions import VPOSCantCharge, VPOSOperationNotImplemented
from djangovirtualpos.models.virtualpointofsale import VirtualPointOfSale
from djangovirtualpos.models.vpos_payment_operation import VPOSPaymentOperation


class VPOSSantanderElavon(VirtualPointOfSale):
    """Información de configuración del TPV Virtual Santander Elavon"""

    regex_clientid = re.compile("^[a-zA-Z0-9]*$")
    regex_account = re.compile("^[a-zA-Z0-9.]*$")
    regex_number = re.compile("^\d*$")
    regex_operation_number_prefix = re.compile("^[A-Za-z0-9]*$")

    # Relación con el padre (TPV).
    # Al poner el signo "+" como "related_name" evitamos que desde el padre
    # se pueda seguir la relación hasta aquí (ya que cada uno de las clases
    # que heredan de ella estará en una tabla y sería un lío).
    parent = models.OneToOneField(VirtualPointOfSale, parent_link=True, related_name="+", null=False,
                                  db_column="vpos_id")

    # Identifica al comercio, será facilitado por la caja en el proceso de alta
    merchant_id = models.CharField(max_length=50, null=False, blank=False, verbose_name="MerchantID",
                                   validators=[MinLengthValidator(1), MaxLengthValidator(50),
                                               RegexValidator(regex=regex_clientid,
                                                              message="Asegúrese de que todos los caracteres son alfanuméricos")])
    # Confirmation URL that will be used by the virtual POS
    merchant_response_url = models.URLField(max_length=64, null=False, blank=False, verbose_name="MerchantURL",
                                            help_text=u"Confirmation URL that will be used by the virtual POS")

    # Identifica la caja, será facilitado por la caja en el proceso de alta
    account = models.CharField(max_length=30, null=False, blank=False, verbose_name="Account",
                               validators=[MinLengthValidator(0), MaxLengthValidator(30),
                                           RegexValidator(regex=regex_account,
                                                          message="Asegúrese de que todos los caracteres son alfanuméricos")])
    # Clave de cifrado
    encryption_key = models.CharField(max_length=64, null=False, blank=False, verbose_name="Clave secreta de cifrado",
                                      validators=[MinLengthValidator(8), MaxLengthValidator(10)])

    # Prefijo del número de operación usado para identicar al servidor desde el que se realiza la petición
    operation_number_prefix = models.CharField(max_length=20, null=False, blank=True,
                                               verbose_name="Prefijo del número de operación",
                                               validators=[MinLengthValidator(0), MaxLengthValidator(20),
                                                           RegexValidator(regex=regex_operation_number_prefix,
                                                                          message="Asegúrese de sólo use caracteres alfanuméricos")])

    # El TPV de Santander Elavon utiliza dos protocolos, "Redirect" y "Remote". Cada uno de ellos tiene dos entornos,
    # uno para pruebas y otro para producción
    REDIRECT_SERVICE_URL = {
        "production": "https://hpp.santanderelavontpvvirtual.es/pay",
        "testing": "https://hpp.prueba.santanderelavontpvvirtual.es/pay"
    }

    REMOTE_SERVICE_URL = {
        "production": "https://remote.santanderelavontpvvirtual.es/remote",
        "testing": "https://remote.prueba.santanderelavontpvvirtual.es/remote"
    }

    # URL de pago que variará según el entorno
    url = None

    # Identifica el importe de la venta, siempre será un número entero y donde los dos últimos dígitos representan los decimales
    amount = None

    # Tipo de moneda (forzado a Euro (EUR))
    currency = "EUR"

    # Timestamp requerido entre los datos POST enviados al servidor
    timestamp = None

    ####################################################################
    ## Inicia el valor de la clave de cifrado en función del entorno
    def __init_encryption_key__(self):
        # Este modelo de TPV utiliza una única clave de cifrado tanto para el entorno de pruebas como para el de
        # producción, por lo que no es necesario hacer nada especial
        pass

    ####################################################################
    ## Constructor del TPV Santader Elavon
    def __init__(self, *args, **kwargs):
        super(VPOSSantanderElavon, self).__init__(*args, **kwargs)

    def __unicode__(self):
        return self.name

    @classmethod
    def form(cls):
        from ..forms import VPOSSantanderElavonForm
        return VPOSSantanderElavonForm

    ####################################################################
    ## Paso 1.1. Configuración del pago
    def configurePayment(self, **kwargs):
        # URL de pago según el entorno
        self.url = {
            "redirect": self.REDIRECT_SERVICE_URL[self.parent.environment],
            "remote": self.REMOTE_SERVICE_URL[self.parent.environment]
        }

        # Formato para Importe: según las especificaciones, ha de tener un formato de entero positivo
        self.amount = "{0:.2f}".format(float(self.parent.operation.amount)).replace(".", "")

        # Timestamp con la hora local requerido por el servidor en formato AAAAMMDDHHMMSS
        self.timestamp = timezone.now().strftime("%Y%m%d%H%M%S")

    ####################################################################
    ## Paso 1.2. Preparación del TPV y Generación del número de operación
    def setupPayment(self, operation_number=None, code_len=40):
        """
        Inicializa el número de operación si no se indica uno
        explícitamente en los argumentos.
        """

        if operation_number:
            return operation_number

        operation_number = ''
        for i in range(code_len):
            operation_number += random.choice('ABCDEFGHJKLMNPQRSTUWXYZ23456789')
        # Si en settings tenemos un prefijo del número de operación
        # se lo añadimos delante, con carácter "-" entre medias
        if self.operation_number_prefix:
            operation_number = self.operation_number_prefix + "-" + operation_number
            return operation_number[0:code_len]
        return operation_number

    ####################################################################
    ## Paso 1.3. Obtiene los datos de pago
    ## Este método será el que genere los campos del formulario de pago
    ## que se rellenarán desde el cliente (por Javascript)
    def getPaymentFormData(self):
        data = {
            # Identifica al comercio, será facilitado por la entidad
            "MERCHANT_ID": self.merchant_id,
            # Identifica al terminal, será facilitado por la entidad
            "ACCOUNT": self.account,
            # Identifica el número de pedido, factura, albarán, etc
            "ORDER_ID": self.parent.operation.operation_number,
            # Importe de la operación sin formatear. Siempre será entero con los dos últimos dígitos usados para los centimos
            "AMOUNT": self.amount,
            "CURRENCY": self.currency,
            # Marca de tiempo de la transacción
            "TIMESTAMP": self.timestamp,
            # Cadena de caracteres calculada por el comercio
            "SHA1HASH": self._post_signature(),
            # No cargar el importe de forma automática (AUTO_SETTLE_FLAG=0). En el método charge() hay que hacer una
            # llamada a un webservice XML con los datos apropiados para que el pago se haga efectivo.
            "AUTO_SETTLE_FLAG": "0",
            # URL de confirmación. Si se indica una, se sobrescribe el valor que tenga configurada la cuenta del TPV
            "MERCHANT_RESPONSE_URL": self.merchant_response_url
        }

        form_data = {
            "data": data,
            "action": self.url['redirect'],
            "enctype": "application/x-www-form-urlencoded",
            "method": "post"
        }

        dlprint(u"Datos para formulario Santander Elavon: {0}".format(form_data))
        return form_data

    ####################################################################
    ## Paso 3.1. Obtiene el número de operación y los datos que nos
    ## envíe la pasarela de pago.
    @staticmethod
    def receiveConfirmation(request, **kwargs):
        dlprint(u"receiveConfirmation. Encoding:{0}".format(request.encoding))

        # Almacén de operaciones
        try:
            operation = VPOSPaymentOperation.objects.get(operation_number=request.POST.get("ORDER_ID"))
            operation.confirmation_data = {"GET": request.GET.dict(), "POST": request.POST.dict()}

            # en charge() nos harán falta tanto el AUTHCODE PASREF, por eso se meten los dos en el campo
            # operation.confirmation_code, separados por el carácter ":"
            operation.confirmation_code = "{pasref}:{authcode}".format(
                pasref=request.POST.get("PASREF"),
                authcode=request.POST.get("AUTHCODE")
            )

            operation.save()
            dlprint(u"Operation {0} actualizada en receiveConfirmation()".format(operation.operation_number))
            vpos = operation.virtual_point_of_sale
        except VPOSPaymentOperation.DoesNotExist:
            # Si no existe la operación, están intentando
            # cargar una operación inexistente
            return False

        # Iniciamos el delegado y la operación, esto es fundamental
        # para luego calcular la firma
        vpos._init_delegated()
        vpos.operation = operation

        # Iniciamos los valores recibidos en el delegado, para el cálculo de la firma

        # Marca de tiempo de la solicitud enviada a la pasarela
        vpos.delegated.timestamp = request.POST.get("TIMESTAMP")
        # Identifica al comercio
        vpos.delegated.merchant_id = request.POST.get("MERCHANT_ID")
        # Identifica el número de pedido, factura, albarán, etc
        vpos.delegated.order_id = request.POST.get("ORDER_ID")
        # Resultado de la operación
        vpos.delegated.result = request.POST.get("RESULT")
        # Mensaje textual del resultado de la operación
        vpos.delegated.message = request.POST.get("MESSAGE", "")
        dlprint("type(message): {0}".format(type(vpos.delegated.message)))
        # Referencia asignada por el TPV
        vpos.delegated.pasref = request.POST.get("PASREF")
        # Código de autorización de la operación
        vpos.delegated.authcode = request.POST.get("AUTHCODE")
        # Firma enviada por la pasarela de pagos
        vpos.delegated.sha1hash = request.POST.get("SHA1HASH")

        # URLs para charge()
        vpos.delegated.url = {
            "redirect": VPOSSantanderElavon.REDIRECT_SERVICE_URL[vpos.environment],
            "remote": VPOSSantanderElavon.REMOTE_SERVICE_URL[vpos.environment]
        }

        dlprint(u"Response Santander Elavon redirect: ")
        dlprint(request.POST)
        return vpos.delegated

    ####################################################################
    ## Paso 3.2. Verifica que los datos enviados desde
    ## la pasarela de pago identifiquen a una operación de compra.
    def verifyConfirmation(self):
        # Comprobar firma de la respuesta
        firma_calculada = self._verification_signature()
        dlprint(u"Firma recibida " + self.sha1hash)
        dlprint(u"Firma calculada " + firma_calculada)
        if self.sha1hash != firma_calculada:
            return False

        # Comprobar código de la respuesta. Tódos los códigos que sean diferentes de 00
        # indican que la pasarela no ha aceptado la operación.
        #
        # A continuación se detallan todos los códigos posibles de la respuesta
        #
        # Código Descripción
        # ------ --------------------------------------------------------------------------------------------------
        # 00     Operación realizada correctamente: La transacción se ha procesado y puedes continuar con la
        #        venta.
        #
        # 1xx    Una transacción denegada. Puedes tratar cualquier código 1xx como una transacción denegada e
        #        informar al cliente de que deberá intentar de nuevo el pago o probar con otro método distinto.
        #        Si lo deseas, puedes proporcionar flujos alternativos basados en códigos específicos como los
        #        que se indican a continuación:
        #        101 Denegada por el banco: Normalmente, suele producirse por la falta de fondos o por una
        #        fecha de caducidad incorrecta.
        #        102 Referencia del banco (tratar como denegada en el sistema automático, por ejemplo, en
        #        Internet)
        #        103 Tarjeta perdida o robada
        #        107 Las comprobaciones antifraude han bloqueado la transacción.
        #        1xx Otro motivo poco frecuente. Tratar como denegada igual que el código 101.
        #
        # 2xx    Error con los sistemas bancarios: Normalmente, puedes pedirle al cliente que vuelva a intentarlo
        #        de nuevo más tarde. El tiempo de resolución depende del problema.
        #
        # 3xx    Error con el sistema TPV Virtual de Santander Elavon: Normal mente, puedes pedirle al cliente
        #        que vuelva a intentarlo de nuevo más tarde. El tiempo de resolución depende del problema.
        #
        # 5xx    Contenido o formación incorrectos de los mensajes XML. Se trata de errores de desarrollo,
        #        errores de configuración o errores del cliente. A continuación, se incluye una lista completa, pero
        #        a grandes rasgos:
        #        508 Problema de desarrollo: Comprueba el mensaje y corrige tu integración.
        #        509 Problema del cliente: Comprueba el mensaje y pide al cliente que confirme los detalles de
        #        pago y que lo intente de nuevo.
        #        5xx Problema de configuración: Comprueba el mensaje. Ponte en contacto con el equipo de soporte
        #        de TPV Virtual de Santander Elavon para solucionar estos problemas.
        #
        # 666    Cliente desactivado: Tu cuenta de TPV Virtual de Santander Elavon se ha suspendido. Ponte en
        #        contacto con el equipo de soporte de TPV Virtual de Santander Elavon para obtener más
        #        información.

        if self.result != u"00":
            return False

        return True

    ####################################################################
    ## Paso 3.3a. Realiza el cobro y genera la respuesta a la pasarela y
    ## comunicamos con la pasarela de pago para que marque la operación
    ## como pagada.
    def charge(self):
        dlprint(u"responseOk")

        # Enviar operación "settle" al TPV, mediante protocolo Santander Elavon "Remote"
        dlprint(u"confirmation_code almacenado: {0}".format(self.parent.operation.confirmation_code))
        self.pasref, self.authcode = self.parent.operation.confirmation_code.split(":", 1)

        xml_string = u'<request timestamp="{timestamp}" type="settle"><merchantid>{merchant_id}</merchantid><account>{account}</account><orderid>{order_id}</orderid><pasref>{pasref}</pasref><authcode>{authcode}</authcode><sha1hash>{sha1hash}</sha1hash></request>'.format(
            timestamp=self.timestamp,
            merchant_id=self.merchant_id,
            account=self.account,
            order_id=self.parent.operation.operation_number,
            pasref=self.pasref,
            authcode=self.authcode,
            sha1hash=self._settle_signature()
        )

        # Enviamos la petición HTTP POST
        dlprint(u"Request SETTLE: {0}".format(xml_string))
        request = urllib2.Request(self.url['remote'], xml_string, headers={"Content-Type": "application/xml"})

        # Recogemos la respuesta dada, que vendrá en texto plano
        response = urllib2.urlopen(request)
        response_string = response.read().decode("utf8")
        dlprint(u"Response SETTLE: {0}".format(response_string))

        # Almacenar respuesta en datos de operación
        extended_confirmation_data = u"{0}\n\nRespuesta settle:\n{1}".format(self.parent.operation.confirmation_data,
                                                                             response_string)
        self.parent.operation.confirmation_data = extended_confirmation_data
        self.parent.operation.save()
        dlprint(u"Operation {0} actualizada en charge()".format(self.parent.operation.operation_number))

        # Comprobar que se ha hecho el cargo de forma correcta parseando el XML de la respuesta
        try:
            dlprint(u"Antes de parser BeautifulSoup")
            soup = BeautifulSoup(response_string, "html.parser")
            dlprint(u"Después de parser BeautifulSoup")
            if soup.response.result.string != u"00":
                dlprint(u"Response SETTLE operación no autorizada")
                raise VPOSCantCharge(u"Cargo denegado (código TPV {0})".format(soup.response.result.string))
            else:
                dlprint(u"Response SETTLE operación autorizada")
        except Exception as e:
            dlprint(u"EXCEPCIÓN: {0}".format(e))
            raise

        # La pasarela de pagos Santander Elavon "Redirect" espera recibir una plantilla HTML que se le mostrará al
        # cliente.
        # Ya que dicho TPV no redirige al navegador del cliente a ninguna URL, se hace la redirección a la "url_ok"
        # mediante Javascript.
        return HttpResponse(u"""
            <html>
                <head>
                    <title>Operación realizada</title>
                    <script type="text/javascript">
                        window.location.assign("{0}");
                    </script>
                </head>
                <body>
                    <p><strong>Operación realizada con éxito</strong></p>
                    <p>Pulse <a href="{0}">este enlace</a> si su navegador no le redirige automáticamente</p>
                </body>
            </html>
        """.format(self.parent.operation.url_ok))

    ####################################################################
    ## Paso 3.3b. Si ha habido un error en el pago, se ha de dar una
    ## respuesta negativa a la pasarela bancaria.
    def responseNok(self, **kwargs):
        # Enviar operación "void" mediante protocolo Santander Elavon "Remote"
        dlprint(u"confirmation_code almacenado: {0}".format(self.parent.operation.confirmation_code))
        self.pasref, self.authcode = self.parent.operation.confirmation_code.split(":", 1)

        xml_string = u'<request timestamp="{timestamp}" type="void"><merchantid>{merchant_id}</merchantid><account>{account}</account><orderid>{order_id}</orderid><pasref>{pasref}</pasref><authcode>{authcode}</authcode><sha1hash>{sha1hash}</sha1hash></request>'.format(
            timestamp=self.timestamp,
            merchant_id=self.merchant_id,
            account=self.account,
            order_id=self.parent.operation.operation_number,
            pasref=self.pasref,
            authcode=self.authcode,
            sha1hash=self._void_signature()
        )

        # Enviamos la petición HTTP POST
        dlprint(u"Request VOID: {0}".format(xml_string))
        request = urllib2.Request(self.url['remote'], xml_string, headers={"Content-Type": "application/xml"})

        # Recogemos la respuesta dada, que vendrá en texto plano
        response = urllib2.urlopen(request)
        response_string = response.read().decode("utf8")
        dlprint(u"Response VOID: {0}".format(response_string))

        # Almacenar respuesta en datos de operación
        extended_confirmation_data = u"{0}\n\nRespuesta void:\n{1}".format(self.parent.operation.confirmation_data,
                                                                           response_string)
        self.parent.operation.confirmation_data = extended_confirmation_data
        self.parent.operation.save()
        dlprint(u"Operation {0} actualizada en responseNok()".format(self.parent.operation.operation_number))

        # La pasarela de pagos Santander Elavon "Redirect" no espera recibir ningún valor especial.
        dlprint(u"responseNok")

        # La pasarela de pagos Santander Elavon "Redirect" espera recibir una plantilla HTML que se le mostrará al
        # cliente.
        # Ya que dicho TPV no redirige al navegador del cliente a ninguna URL, se hace la redirección a la "url_ok"
        # mediante Javascript.
        return HttpResponse(u"""
            <html>
                <head>
                    <title>Operación cancelada</title>
                    <script type="text/javascript">
                        window.location.assign("{0}");
                    </script>
                </head>
                <body>
                    <p><strong>Operación cancelada</strong></p>
                    <p>Pulse <a href="{0}">este enlace</a> si su navegador no le redirige automáticamente</p>
                </body>
            </html>
        """.format(self.parent.operation.url_nok))

    ####################################################################
    ## Paso R. (Refund) Configura el TPV en modo devolución
    ## TODO: No implementado
    def refund(self, operation_sale_code, refund_amount, description):
        raise VPOSOperationNotImplemented(
            u"No se ha implementado la operación de devolución particular para Santander-Elavon.")

    ####################################################################
    ## Paso R2.a. Respuesta positiva a confirmación asíncrona de refund
    def refund_response_ok(self, extended_status=""):
        raise VPOSOperationNotImplemented(
            u"No se ha implementado la operación de devolución particular para Santader-Elavon.")

    ####################################################################
    ## Paso R2.b. Respuesta negativa a confirmación asíncrona de refund
    def refund_response_nok(self, extended_status=""):
        raise VPOSOperationNotImplemented(
            u"No se ha implementado la operación de devolución particular para Santender-Elavon.")

    ####################################################################
    ## Generador de firma para el envío POST al servicio "Redirect"
    def _post_signature(self):
        """Calcula la firma a incorporar en el formulario de pago"""
        self.__init_encryption_key__()
        dlprint(u"Clave de cifrado es " + self.encryption_key)

        amount = "{0:.2f}".format(float(self.parent.operation.amount)).replace(".", "")

        signature1 = u"{timestamp}.{merchant_id}.{order_id}.{amount}.{currency}".format(
            merchant_id=self.merchant_id,
            order_id=self.parent.operation.operation_number,
            amount=amount,
            currency=self.currency,
            timestamp=self.timestamp
        )

        firma1 = hashlib.sha1(signature1).hexdigest()
        dlprint(u"FIRMA1 datos: {0}".format(signature1))
        dlprint(u"FIRMA1 hash:  {0}".format(firma1))

        signature2 = u"{firma1}.{secret}".format(firma1=firma1, secret=self.encryption_key)
        firma2 = hashlib.sha1(signature2).hexdigest()
        dlprint(u"FIRMA2 datos: {0}".format(signature2))
        dlprint(u"FIRMA2 hash:  {0}".format(firma2))

        return firma2

    ####################################################################
    ## Generador de firma para el envío XML POST al servicio "settle"/"void" (Protocolo "Remote")
    def _settle_void_signature(self, label=None):
        """Calcula la firma a incorporar en el en la petición XML 'settle' o 'void'"""
        self.__init_encryption_key__()
        dlprint(u"Calcular firma para {0}. La clave de cifrado es {1}".format(label, self.encryption_key))

        signature1 = u"{timestamp}.{merchant_id}.{order_id}...".format(
            merchant_id=self.merchant_id,
            order_id=self.parent.operation.operation_number,
            timestamp=self.timestamp
        )

        firma1 = hashlib.sha1(signature1).hexdigest()
        dlprint(u"FIRMA1 datos: {0}".format(signature1))
        dlprint(u"FIRMA1 hash:  {0}".format(firma1))

        signature2 = u"{firma1}.{secret}".format(firma1=firma1, secret=self.encryption_key)
        firma2 = hashlib.sha1(signature2).hexdigest()
        dlprint(u"FIRMA2 datos: {0}".format(signature2))
        dlprint(u"FIRMA2 hash:  {0}".format(firma2))

        return firma2

    ####################################################################
    ## Generador de firma para el envío XML POST al servicio "settle" (Protocolo "Remote")
    def _settle_signature(self):
        """Calcula la firma a incorporar en el en la petición XML 'void'"""
        return self._settle_void_signature(label="SETTLE")

    ####################################################################
    ## Generador de firma para el envío XML POST al servicio "void" (Protocolo "Remote")
    def _void_signature(self):
        """Calcula la firma a incorporar en el en la petición XML 'void'"""
        return self._settle_void_signature(label="VOID")

    ####################################################################
    ## Generador de firma para la verificación
    def _verification_signature(self):
        """ Calcula la firma de verificación de una respuesta de la pasarela de pagos """
        self.__init_encryption_key__()
        dlprint(u"Clave de cifrado es " + self.encryption_key)

        signature1 = u"{timestamp}.{merchant_id}.{order_id}.{result}.{message}.{pasref}.{authcode}".format(
            timestamp=self.timestamp,
            merchant_id=self.merchant_id,
            order_id=self.parent.operation.operation_number,
            result=self.result,
            message=self.message,
            pasref=self.pasref,
            authcode=self.authcode
        )

        firma1 = hashlib.sha1(signature1.encode("utf-8")).hexdigest()
        dlprint(u"FIRMA1 datos: {0}".format(signature1))
        dlprint(u"FIRMA1 hash:  {0}".format(firma1))

        signature2 = "{firma1}.{secret}".format(firma1=firma1, secret=self.encryption_key)
        firma2 = hashlib.sha1(signature2).hexdigest()
        dlprint(u"FIRMA2 datos: {0}".format(signature2))
        dlprint(u"FIRMA2 hash:  {0}".format(firma2))

        return firma2