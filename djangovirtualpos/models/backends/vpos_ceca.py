# coding=utf-8
import hashlib
import random
import re
import time

from django.core.validators import MinLengthValidator, MaxLengthValidator, RegexValidator
from django.db import models
from django.http import HttpResponse
from django.utils import translation

from djangovirtualpos.debug import dlprint
from djangovirtualpos.models.exceptions import VPOSOperationNotImplemented
from djangovirtualpos.models.virtualpointofsale import VirtualPointOfSale
from djangovirtualpos.models.vpos_payment_operation import VPOSPaymentOperation


class VPOSCeca(VirtualPointOfSale):
    """Información de configuración del TPV Virtual CECA"""

    regex_number = re.compile("^\d*$")
    regex_operation_number_prefix = re.compile("^[A-Za-z0-9]*$")

    # Relación con el padre (TPV).
    # Al poner el signo "+" como "related_name" evitamos que desde el padre
    # se pueda seguir la relación hasta aquí (ya que cada uno de las clases
    # que heredan de ella estará en una tabla y sería un lío).
    parent = models.OneToOneField(VirtualPointOfSale, parent_link=True, related_name="+", null=False,
                                  db_column="vpos_id")

    # Identifica al comercio, será facilitado por la caja en el proceso de alta
    merchant_id = models.CharField(max_length=9, null=False, blank=False, verbose_name="MerchantID",
                                   validators=[MinLengthValidator(9), MaxLengthValidator(9),
                                               RegexValidator(regex=regex_number,
                                                              message="Asegúrese de que todos los caracteres son números")])
    # Identifica la caja, será facilitado por la caja en el proceso de alta
    acquirer_bin = models.CharField(max_length=10, null=False, blank=False, verbose_name="AcquirerBIN",
                                    validators=[MinLengthValidator(10), MaxLengthValidator(10),
                                                RegexValidator(regex=regex_number,
                                                               message="Asegúrese de que todos los caracteres son números")])
    # Identifica el terminal, será facilitado por la caja en el proceso de alta
    terminal_id = models.CharField(max_length=8, null=False, blank=False, verbose_name="TerminalID",
                                   validators=[MinLengthValidator(8), MaxLengthValidator(8),
                                               RegexValidator(regex=regex_number,
                                                              message="Asegúrese de que todos los caracteres son números")])
    # Clave de cifrado para el entorno de pruebas
    encryption_key_testing = models.CharField(max_length=10, null=False, blank=False,
                                              verbose_name="Encryption Key para el entorno de pruebas",
                                              validators=[MinLengthValidator(8), MaxLengthValidator(10)])
    # Clave de cifrado para el entorno de producción
    encryption_key_production = models.CharField(max_length=10, null=False, blank=True,
                                                 verbose_name="Encryption Key para el entorno de producción",
                                                 validators=[MinLengthValidator(8), MaxLengthValidator(10)])

    # Prefijo del número de operación usado para identicar al servidor desde el que se realiza la petición
    operation_number_prefix = models.CharField(max_length=20, null=False, blank=True,
                                               verbose_name="Prefijo del número de operación",
                                               validators=[MinLengthValidator(0), MaxLengthValidator(20),
                                                           RegexValidator(regex=regex_operation_number_prefix,
                                                                          message="Asegúrese de sólo use caracteres alfanuméricos")])

    # Clave de cifrado según el entorno
    encryption_key = None

    # El TPV de CECA consta de dos entornos en funcionamiento, uno para pruebas y otro para producción
    CECA_URL = {
        "production": "https://pgw.ceca.es/cgi-bin/tpv",
        "testing": "http://tpv.ceca.es:8000/cgi-bin/tpv"
    }

    # Los códigos de idioma a utilizar son los siguientes
    IDIOMAS = {"es": "1", "en": "6", "fr": "7", "de": "8", "pt": "9", "it": "10"}

    # URL de pago que variará según el entorno
    url = None
    # Identifica el importe de la venta, siempre será un número entero y donde los dos últimos dígitos representan los decimales
    importe = None
    # Tipo de pago que soporta
    pago_soportado = "SSL"
    # Cifrado que será usado en la generación de la firma
    cifrado = "SHA1"
    # Campo específico para realizar el pago, actualmente será 2
    exponente = "2"
    # Identifica el tipo de moneda
    tipo_moneda = "978"
    # Idioma por defecto a usar. Español
    idioma = "1"

    # marca de tiempo de recepción de la notificación de pago OK. Nuestro sistema debe dar una respuesta de
    # OK o NOK antes de 30 segundos. Transcurrido este periodo, CECA anula la operación de forma automática
    # y no notifica de nada (!)
    confirmation_timestamp = None

    ####################################################################
    ## Inicia el valor de la clave de cifrado en función del entorno
    def __init_encryption_key__(self):
        # Clave de cifrado según el entorno
        if self.parent.environment == "testing":
            self.encryption_key = self.encryption_key_testing
        elif self.parent.environment == "production":
            self.encryption_key = self.encryption_key_production
        else:
            raise ValueError(u"Entorno {0} no válido")

    ####################################################################
    ## Constructor del TPV CECA
    def __init__(self, *args, **kwargs):
        super(VPOSCeca, self).__init__(*args, **kwargs)

    def __unicode__(self):
        return self.name

    @classmethod
    def form(cls):
        from forms import VPOSCecaForm
        return VPOSCecaForm

    ####################################################################
    ## Paso 1.1. Configuración del pago
    def configurePayment(self, **kwargs):
        # URL de pago según el entorno
        self.url = self.CECA_URL[self.parent.environment]

        # Formato para Importe: según ceca, ha de tener un formato de entero positivo
        self.importe = "{0:.2f}".format(float(self.parent.operation.amount)).replace(".", "")

        # Idioma de la pasarela, por defecto es español, tomamos
        # el idioma actual y le asignamos éste
        self.idioma = self.IDIOMAS["es"]
        lang = translation.get_language()
        if lang in self.IDIOMAS:
            self.idioma = self.IDIOMAS[lang]

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
            # Identifica al comercio, será facilitado por la caja
            "MerchantID": self.merchant_id,
            # Identifica a la caja, será facilitado por la caja
            "AcquirerBIN": self.acquirer_bin,
            # Identifica al terminal, será facilitado por la caja
            "TerminalID": self.terminal_id,
            # URL determinada por el comercio a la que CECA devolverá el control en caso de que la operación finalice correctamente
            "URL_OK": self.parent.operation.url_ok,
            # URL determinada por el comercio a la que CECA devolverá el control en caso de que la operación NO finalice correctamente
            "URL_NOK": self.parent.operation.url_nok,
            # Cadena de caracteres calculada por el comercio
            "Firma": self._sending_signature(),
            # Tipo de cifrado que se usará para el cifrado de la firma
            "Cifrado": self.cifrado,
            # Identifica el número de pedido, factura, albarán, etc
            "Num_operacion": self.parent.operation.operation_number,
            # Importe de la operación sin formatear. Siempre será entero con los dos últimos dígitos usados para los centimos
            "Importe": self.importe,
            # Codigo ISO-4217 correspondiente a la moneda en la que se efectúa el pago
            "TipoMoneda": self.tipo_moneda,
            # Actualmente siempre será 2
            "Exponente": self.exponente,
            # Valor fijo: SSL
            "Pago_soportado": self.pago_soportado,
            # Código de idioma
            "Idioma": self.idioma,
            # Opcional. Campo reservado para mostrar información en la página de pago
            "Descripcion": self.parent.operation.description
        }
        form_data = {
            "data": data,
            "action": self.url,
            "enctype": "application/x-www-form-urlencoded",
            "method": "post"
        }
        return form_data

    ####################################################################
    ## Paso 3.1. Obtiene el número de operación y los datos que nos
    ## envíe la pasarela de pago.
    @staticmethod
    def receiveConfirmation(request, **kwargs):

        # Almacén de operaciones
        try:
            operation = VPOSPaymentOperation.objects.get(operation_number=request.POST.get("Num_operacion"))
            operation.confirmation_data = {"GET": request.GET.dict(), "POST": request.POST.dict()}
            operation.confirmation_code = request.POST.get("Referencia")
            operation.save()
            dlprint("Operation {0} actualizada en receiveConfirmation()".format(operation.operation_number))
            vpos = operation.virtual_point_of_sale
        except VPOSPaymentOperation.DoesNotExist:
            # Si no existe la operación, están intentando
            # cargar una operación inexistente
            return False

        # Iniciamos el delegado y la operación, esto es fundamental
        # para luego calcular la firma
        vpos._init_delegated()
        vpos.operation = operation

        # Marca de tiempo de recepción de notificación. Debemos completar todo el proceso (es decir,
        # invocar charge()) antes de 30  segundos o CECA anula la operación. Como margen de seguridad,
        # intentaremos hacerlo todo en menos de 20 segundos. Si se supera esa cota de tiempo, se
        # devuelve una exepción y se anula la operacion.
        vpos.delegated.confirmation_timestamp = time.time()

        # Iniciamos los valores recibidos en el delegado

        # Identifica al comercio
        vpos.delegated.merchant_id = request.POST.get("MerchantID")
        # Identifica a la caja
        vpos.delegated.acquirer_bin = request.POST.get("AcquirerBIN")
        # Identifica al terminal
        vpos.delegated.terminal_id = request.POST.get("TerminalID")
        # Identifica el número de pedido, factura, albarán, etc
        vpos.delegated.num_operacion = request.POST.get("Num_operacion")
        # Importe de la operación sin formatear
        vpos.delegated.importe = request.POST.get("Importe")
        # Corresponde a la moneda en la que se efectúa el pago
        vpos.delegated.tipo_moneda = request.POST.get("TipoMoneda")
        # Actualmente siempre será 2
        vpos.delegated.exponente = request.POST.get("Exponente")
        # Idioma de la operación
        vpos.delegated.idioma = request.POST.get("Idioma")
        # Código ISO del país de la tarjeta que ha realizado la operación
        vpos.delegated.pais = request.POST.get("Pais")
        # Los 200 primeros caracteres de la operación
        vpos.delegated.descripcion = request.POST.get("Descripcion")
        # Valor único devuelto por la pasarela. Imprescindible para realizar cualquier tipo de reclamación y/o anulación
        vpos.delegated.referencia = request.POST.get("Referencia")
        # Valor asignado por la entidad emisora a la hora de autorizar una operación
        vpos.delegated.num_aut = request.POST.get("Num_aut")
        # Es una cadena de caracteres calculada por CECA firmada por SHA1
        vpos.delegated.firma = request.POST.get("Firma")

        dlprint(u"Lo que recibimos de CECA: ")
        dlprint(request.POST)
        return vpos.delegated

    ####################################################################
    ## Paso 3.2. Verifica que los datos enviados desde
    ## la pasarela de pago identifiquen a una operación de compra.
    def verifyConfirmation(self):
        # Comprueba si el envío es correcto
        firma_calculada = self._verification_signature()
        dlprint("Firma recibida " + self.firma)
        dlprint("Firma calculada " + firma_calculada)
        verified = (self.firma == firma_calculada)
        return verified

    ####################################################################
    ## Paso 3.3a. Realiza el cobro y genera la respuesta a la pasarela y
    ## comunicamos con la pasarela de pago para que marque la operación
    ## como pagada. Sólo se usa en CECA. Para que el programa sea capaz de discernir a partir
    ## de la respuesta recibida desde el Comercio si todo ha funcionado correctamente
    def charge(self):
        dlprint("responseOk")

        # Si han transcurrido más de 20 segundos anulamos la operación debido
        # a que CECA la anulará si pasan más de 30 sin dar la respuesta. Nosotros
        # nos quedamos en 20 como margen de seguridad por el overhead de otras
        # operaciones.
        elapsed = time.time() - self.confirmation_timestamp
        if elapsed > 12:
            dlprint(
                u"AVISO: se ha superado el margen de tiempo para devolver la respuesta: {0}s. Lanzando excepción.".format(
                    elapsed))
            raise Exception(u"Se ha superado el margen de tiempo en generar la respuesta.")

        operation = self.parent.operation

        dlprint(u"antes de save")
        operation.confirmation_data = u"{0}\n\n{1}".format(operation.confirmation_data, u"XXXXXXXXXXXXXXXXXXXXXXXXXX")
        operation.save()
        dlprint(u"después de save")

        return HttpResponse("$*$OKY$*$")

    ####################################################################
    ## Paso 3.3b. Si ha habido un error en el pago, se ha de dar una
    ## respuesta negativa a la pasarela bancaria.
    def responseNok(self, **kwargs):
        dlprint("responseNok")
        return HttpResponse("")

    ####################################################################
    ## Paso R1. (Refund) Configura el TPV en modo devolución
    ## TODO: No implementado
    def refund(self, operation_sale_code, refund_amount, description):
        raise VPOSOperationNotImplemented(u"No se ha implementado la operación de devolución particular para CECA.")

    ####################################################################
    ## Paso R2.a. Respuesta positiva a confirmación asíncrona de refund
    def refund_response_ok(self, extended_status=""):
        raise VPOSOperationNotImplemented(u"No se ha implementado la operación de devolución particular para CECA.")

    ####################################################################
    ## Paso R2.b. Respuesta negativa a confirmación asíncrona de refund
    def refund_response_nok(self, extended_status=""):
        raise VPOSOperationNotImplemented(u"No se ha implementado la operación de devolución particular para CECA.")

    ####################################################################
    ## Generador de firma para el envío
    def _sending_signature(self):
        """Calcula la firma a incorporar en el formulario de pago"""
        self.__init_encryption_key__()
        dlprint("Clave de cifrado es {0}".format(self.encryption_key))
        signature = "{encryption_key}{merchant_id}{acquirer_bin}{terminal_id}{num_operacion}{importe}{tipo_moneda}{exponente}SHA1{url_ok}{url_nok}".format(
            encryption_key=self.encryption_key,
            merchant_id=self.merchant_id,
            acquirer_bin=self.acquirer_bin,
            terminal_id=self.terminal_id,
            num_operacion=self.parent.operation.operation_number,
            importe=self.importe,
            tipo_moneda=self.tipo_moneda,
            exponente=self.exponente,
            url_ok=self.parent.operation.url_ok,
            url_nok=self.parent.operation.url_nok
        )
        dlprint("\tencryption_key {0}".format(self.encryption_key))
        dlprint("\tmerchant_id {0}".format(self.merchant_id))
        dlprint("\tacquirer_bin {0}".format(self.acquirer_bin))
        dlprint("\tterminal_id {0}".format(self.terminal_id))
        dlprint("\tnum_operacion {0}".format(self.parent.operation.operation_number))
        dlprint("\timporte {0}".format(self.importe))
        dlprint("\ttipo_moneda {0}".format(self.tipo_moneda))
        dlprint("\texponente {0}".format(self.exponente))
        dlprint("\turl_ok {0}".format(self.parent.operation.url_ok))
        dlprint("\turl_nok {0}".format(self.parent.operation.url_nok))
        dlprint("FIRMA {0}".format(signature))
        return hashlib.sha1(signature).hexdigest()

    ####################################################################
    ## Generador de firma para la verificación
    def _verification_signature(self):
        self.__init_encryption_key__()
        """Calcula la firma de verificación"""
        dlprint("Clave de cifrado es ".format(self.encryption_key))
        signature = "{encryption_key}{merchant_id}{acquirer_bin}{terminal_id}{num_operacion}{importe}{tipo_moneda}{exponente}{referencia}".format(
            encryption_key=self.encryption_key,
            merchant_id=self.merchant_id,
            acquirer_bin=self.acquirer_bin,
            terminal_id=self.terminal_id,
            num_operacion=self.parent.operation.operation_number,
            importe=self.importe,
            tipo_moneda=self.tipo_moneda,
            exponente=self.exponente,
            referencia=self.parent.operation.confirmation_code,
        )
        dlprint("\tencryption_key {0}".format(self.encryption_key))
        dlprint("\tmerchant_id {0}".format(self.merchant_id))
        dlprint("\tacquirer_bin {0}".format(self.acquirer_bin))
        dlprint("\tterminal_id {0}".format(self.terminal_id))
        dlprint("\tnum_operacion {0}".format(self.parent.operation.operation_number))
        dlprint("\timporte {0}".format(self.importe))
        dlprint("\ttipo_moneda {0}".format(self.tipo_moneda))
        dlprint("\texponente {0}".format(self.exponente))
        dlprint("\treferencia {0}".format(self.parent.operation.confirmation_code))
        dlprint("FIRMA {0}".format(signature))
        return hashlib.sha1(signature).hexdigest()