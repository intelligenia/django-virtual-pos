# -*- coding: utf-8 -*-

from __future__ import unicode_literals, print_function
import base64
import json
import re
import cgi

###########################################
# Sistema de depuración
from bs4 import BeautifulSoup
from debug import dlprint

from django.db import models

from django.conf import settings
from django.core.validators import MinLengthValidator, MaxLengthValidator, RegexValidator
from django.http import HttpResponse
from django.utils import timezone

from django.shortcuts import redirect
from django.core.urlresolvers import reverse
import random
import urllib2, urllib
import urlparse
import hashlib
from django.utils import translation
from Crypto.Cipher import DES3
from Crypto.Hash import SHA256, HMAC
from lxml import etree
import datetime
import time
from decimal import Decimal
from djangovirtualpos.util import dictlist, localize_datetime
from django.utils.translation import ugettext_lazy as _

VPOS_TYPES = (
    ("ceca", _("TPV Virtual - Confederación Española de Cajas de Ahorros (CECA)")),
    ("paypal", _("Paypal")),
    ("redsys", _("TPV Redsys")),
    ("santanderelavon", _("TPV Santander Elavon")),
)

## Relación entre tipos de TPVs y clases delegadas
VPOS_CLASSES = {
    "ceca": "VPOSCeca",
    "redsys": "VPOSRedsys",
    "paypal": "VPOSPaypal",
    "santanderelavon": "VPOSSantanderElavon",
}


########################################################################
## Obtiene la clase delegada a partir del tipo de TPV.
## La clase delegada ha de estar definida en el
## diccionario TPV_CLASSES en vpos.models.
def get_delegated_class(virtualpos_type):
    try:
        # __name__ Es el nombre del módulo actual, esto es,
        # un str con el contenido "vpos.models"

        # __import__(__name__) es el objeto módulo "vpos".

        # __import__(__name__, globals(), locals(), ["models"])
        # carga el objeto módulo "vpos.models"
        mdl = __import__(__name__, globals(), locals(), ["models"])

        # getattr obtiene un atributo de un objeto, luego sacamos el
        # objeto clase a partir de su nombre y del objeto módulo "vpos.models"
        cls = getattr(mdl, VPOS_CLASSES[virtualpos_type])
        return cls
    except KeyError:
        raise ValueError(_(u"The virtual point of sale {0} does not exist").format(virtualpos_type))


####################################################################
## Opciones del campo STATUS
## STATUS: estado en el que se encuentra la operación de pago
VPOS_STATUS_CHOICES = (
    ("pending", _(u"Pending")),
    ("completed", _(u"Completed")),
    ("failed", _(u"Failed")),
)

####################################################################
## Tipos de estado del TPV
VIRTUALPOS_STATE_TYPES = (
    ("testing", "Pruebas"),
    ("production", "Producción")
)

####################################################################
## Operación de pago de TPV
class VPOSPaymentOperation(models.Model):
    """
    Configuratión del pago para un TPV
    """
    amount = models.DecimalField(max_digits=6, decimal_places=2, null=False, blank=False,
                                 verbose_name=u"Coste de la operación")
    description = models.CharField(max_length=512, null=False, blank=False, verbose_name=u"Descripción de la venta")
    url_ok = models.CharField(max_length=255, null=False, blank=False, verbose_name=u"URL de OK",
                              help_text=u"URL a la que redirige la pasarela bancaria cuando la compra ha sido un éxito")
    url_nok = models.CharField(max_length=255, null=False, blank=False, verbose_name=u"URL de NOK",
                               help_text=u"URL a la que redirige la pasarela bancaria cuando la compra ha fallado")
    operation_number = models.CharField(max_length=255, null=False, blank=False, verbose_name=u"Número de operación")
    confirmation_code = models.CharField(max_length=255, null=True, blank=False,
                                         verbose_name="Código de confirmación enviado por el banco.")
    confirmation_data = models.TextField(null=True, blank=False,
                                         verbose_name="POST enviado por la pasarela bancaria al confirmar la compra.")
    sale_code = models.CharField(max_length=512, null=False, blank=False, verbose_name=u"Código de la venta",
                                 help_text=u"Código de la venta según la aplicación.")
    status = models.CharField(max_length=64, choices=VPOS_STATUS_CHOICES, null=False, blank=False,
                              verbose_name=u"Estado del pago")

    response_code = models.CharField(max_length=255, null=True, blank=False,
                                     verbose_name=u"Código de respuesta con estado de aceptación o denegación de la operación.")

    creation_datetime = models.DateTimeField(verbose_name="Fecha de creación del objeto")
    last_update_datetime = models.DateTimeField(verbose_name="Fecha de última actualización del objeto")

    type = models.CharField(max_length=16, choices=VPOS_TYPES, default="", verbose_name="Tipo de TPV")
    virtual_point_of_sale = models.ForeignKey("VirtualPointOfSale", parent_link=True, related_name="payment_operations", null=False)
    environment = models.CharField(max_length=255, choices=VIRTUALPOS_STATE_TYPES, default="", blank=True, verbose_name="Entorno del TPV")

    @property
    def vpos(self):
        return self.virtual_point_of_sale

    ## Guarda el objeto en BD, en realidad lo único que hace es actualizar los datetimes
    def save(self, *args, **kwargs):
        """
        Guarda el objeto en BD, en realidad lo único que hace es actualizar los datetimes.
        El datetime de actualización se actualiza siempre, el de creación sólo al guardar de nuevas.
        """
        # Datetime con el momento actual en UTC
        now_datetime = datetime.datetime.now()
        # Si no se ha guardado aún, el datetime de creación es la fecha actual
        if not self.id:
            self.creation_datetime = localize_datetime(now_datetime)
        # El datetime de actualización es la fecha actual
        self.last_update_datetime = localize_datetime(now_datetime)
        # Llamada al constructor del padre
        super(VPOSPaymentOperation, self).save(*args, **kwargs)


####################################################################
####################################################################

# Excepción para indicar que la operación charge ha devuelto una respuesta incorrecta o de fallo
class VPOSCantCharge(Exception): pass


####################################################################
## Clase que contiene las operaciones de pago de forma genérica
## actúa de fachada de forma que el resto del software no conozca
## 
class VirtualPointOfSale(models.Model):
    """
    Clases que actúa como clase base para la relación de especialización.

    Cada clase especializada estará relacionada con ésta en una relación
    uno a uno.

    Esta clase no podrá tener un campo para mantener las relaciones con
    las clases especializadas ya que cada una estará en tablas diferentes.

    Para este modelo se crea la tabla de forma automática con syncdb.
    """

    ## Nombre único del TPV
    name = models.CharField(max_length=128, null=False, blank=False, verbose_name="Nombre")

    ## Nombre único del banco que tiene asociado el TPV
    bank_name = models.CharField(max_length=128, null=False, blank=False, verbose_name="Nombre de la entidad bancaria")

    ## Tipo de TPV. Indica la naturaleza del TPV.
    type = models.CharField(max_length=16, choices=VPOS_TYPES, default="", verbose_name="Tipo de TPV")

    ## Nombre del distribuidor del plan
    distributor_name = models.CharField(null=False, blank=True, max_length=512,
                                        verbose_name="Razón social del distribuidor",
                                        help_text="Razón social del distribuidor.")

    ## CIF del organizador del plan
    distributor_cif = models.CharField(null=False, blank=True, max_length=150,
                                       verbose_name="CIF del distribuidor",
                                       help_text="C.I.F. del distribuidor.")

    ## Estado del TPV: por si es de pruebas o de producción
    environment = models.CharField(max_length=16, null=False, blank=False, choices=VIRTUALPOS_STATE_TYPES,
                                   default="testing",
                                   verbose_name="Entorno de ejecución del TPV",
                                   help_text="Entorno de ejecución en el que se encuentra el TPV. Una vez que el TPV esté en entorno de 'producción' no cambie a entorno de 'pruebas' a no ser que esté seguro de lo que hace.")

    ## Permite realizar devoluciones parciales
    has_partial_refunds = models.BooleanField(default=False, verbose_name="Indica si tiene devoluciones parciales.",
                                              help_text="Indica si se pueden realizar devoluciones por un importe menor que el total de la venta (por ejemplo, para devolver tickets individuales).")

    ## Permite realizar devoluciones totales
    has_total_refunds = models.BooleanField(default=False, verbose_name="Indica si tiene devoluciones totales.",
                                            help_text="Indica si se pueden realizar devoluciones por un importe igual al total de la venta.")

    ## Borrados lógicos
    is_erased = models.BooleanField(default=False, verbose_name="Indica si el TPV está eliminado.",
                                    help_text="Indica si el TPV está eliminado de forma lógica.")

    ## Configuración de la operación de pago (actúa también como registro de la operación de pago)
    operation = None

    ## Objeto en el que se delegan las llamadas específicas de la pasarela de pagos dependiente del tipo de TPV
    delegated = None

    class Meta:
        ordering = ['name']
        verbose_name = "virtual point of sale"
        verbose_name_plural = "virtual points of sale"
        permissions = (
            ("view_virtualpointofsale", "View Virtual Points of Sale"),
        )

    def __unicode__(self):
        return self.name

    def meta(self):
        """Obtiene la metainformación de objetos de este modelo."""
        return self._meta

    @property
    def operation_prefix(self):
        """
        Prefijo de operación asociado a este TPV.
        Se consulta al delegado para obtenerlo.
        :return: string | None
        """
        self._init_delegated()
        # Algunos tipos de TPV no tienen este atributo (PayPal)
        if hasattr(self.delegated, "operation_number_prefix"):
            prefix = getattr(self.delegated, "operation_number_prefix")
        else:
            prefix = "n/a"

        return prefix

    ####################################################################
    ## Elimina de forma lógica el objeto
    def erase(self):
        self.is_erased = True
        self.save()

    ####################################################################
    ## Obtiene el texto de ayuda del tipo del TPV
    def get_type_help(self):
        return dict(VPOS_TYPES)[self.type]

    ####################################################################
    ## Devuelve el TPV específico
    @property
    def specific_vpos(self):
        delegated_class = get_delegated_class(self.type)
        try:
            return delegated_class.objects.get(parent_id=self.id)
        except delegated_class.DoesNotExist as e:
            raise ValueError(u" No existe ningún vpos del tipo {0} con el identificador {1}".format(self.type, self.id))

    ####################################################################
    ## Constructor: Inicializa el objeto TPV
    def _init_delegated(self):
        """
        Devuelve la configuración del TPV como una instancia del
        modelo hijo asociado.

        Como, en función del TPV, la configuración se almacena en tablas
        diferentes y, por lo tanto, cada una tiene su propio modelo,
        el resultado devuelto por esta función será una instancia del
        modelo correspondiente.

        Este método habrá que actualizarlo cada vez que se añada un
        TPV nuevo.
        """

        self.delegated = None
        delegated_class = get_delegated_class(self.type)

        try:
            self.delegated = delegated_class.objects.get(parent_id=self.id)
        except delegated_class.DoesNotExist as e:
            raise ValueError(
                unicode(e) + u" No existe ningún vpos del tipo {0} con el identificador {1}".format(self.type, self.id))

        # Necesito los datos dinámicos de mi padre, que es un objeto de
        # la clase Tpv, si usásemos directamente desde el delegated
        # self.parent, se traería de la BD los datos de ese objeto
        # y nosotros queremos sus datos y además, sus atributos dinámicos
        self.delegated.parent = self

        return self.delegated

    ####################################################################
    ## Obtiene un objeto TPV a partir de una serie de filtros
    @staticmethod
    def get(**kwargs):
        vpos = VirtualPointOfSale.objects.get(**kwargs)
        vpos._init_delegated()
        return vpos

    ####################################################################
    ## Paso 1.1. Configuración del pago
    def configurePayment(self, amount, description, url_ok, url_nok, sale_code):
        """
        Configura el pago por TPV.
        Prepara el objeto TPV para
        - Pagar una cantidad concreta
        - Establecera una descripción al pago
        - Establecer las URLs de OK y NOK
        - Alamacenar el código de venta de la operación
        """
        if type(amount) == int or type(amount) == Decimal:
            amount = float(amount)
        if type(amount) != float or amount <= 0.0:
            raise ValueError(u"La cantidad debe ser un flotante positivo")
        if sale_code is None or sale_code == "":
            raise ValueError(u"El código de venta no puede estar vacío")
        if description is None or description == "":
            raise ValueError(u"La descripción de la venta no puede estar vacía")
        # Estas dos condiciones se han de eliminar
        # si algún TPV no utiliza url_ok y url_nok
        if url_ok is None or type(url_ok) != str or url_ok == "":
            raise ValueError(u"La url_ok no puede estar vacía. Ha de ser un str.")
        if url_nok is None or type(url_nok) != str or url_nok == "":
            raise ValueError(u"La url_nok no puede estar vacía. Ha de ser un str.")

        # Creación de la operación
        # (se guarda cuando se tenga el número de operación)
        self.operation = VPOSPaymentOperation(
            amount=amount, description=description, url_ok=url_ok, url_nok=url_nok,
            sale_code=sale_code, status="pending",
            virtual_point_of_sale=self, type=self.type, environment=self.environment
        )

        # Configuración específica (requiere que exista self.operation)
        self.delegated.configurePayment()

    ####################################################################
    ## Paso 1.2. Preparación del TPV y Generación del número de operación
    def setupPayment(self):
        """
        Prepara el TPV.
        Genera el número de operación y prepara el proceso de pago.
        """
        if self.operation is None:
            raise Exception(u"No se ha configurado la operación, ¿ha llamado a vpos.configurePayment antes?")

        # Comprobamos que no se tenga ya un segundo código de operación
        # de TPV para el mismo código de venta
        # Si existe, devolvemos el número de operación existente
        stored_operations = VPOSPaymentOperation.objects.filter(
            sale_code=self.operation.sale_code,
            status="pending",
            virtual_point_of_sale_id=self.operation.virtual_point_of_sale_id
        )
        if stored_operations.count() >= 1:
            self.operation = stored_operations[0]
            return self.delegated.setupPayment(operation_number=self.operation.operation_number)

        # No existe un código de operación de TPV anterior para
        # este código de venta, por lo que generamos un número de operación nuevo
        # Comprobamos que el número de operación generado por el delegado
        # es único en la tabla de TpvPaymentOperation
        operation_number = None
        while operation_number is None or VPOSPaymentOperation.objects.filter(
                operation_number=operation_number).count() > 0:
            operation_number = self.delegated.setupPayment()
            dlprint("entra al delegado para configurar el operation number:{0}".format(operation_number))

        # Asignamos el número de operación único
        self.operation.operation_number = operation_number
        self.operation.save()
        dlprint("Operation {0} creada en BD".format(operation_number))
        return self.operation.operation_number

    ####################################################################
    ## Paso 1.3. Obtiene los datos de pago
    ## Este método será el que genere los campos del formulario de pago
    ## que se rellenarán desde el cliente (por Javascript)
    def getPaymentFormData(self):
        if self.operation.operation_number is None:
            raise Exception(u"No se ha generado el número de operación, ¿ha llamado a vpos.setupPayment antes?")
        data = self.delegated.getPaymentFormData()
        data["type"] = self.type
        return data

    ####################################################################
    ## Paso 2. Envío de los datos de la transacción (incluyendo "amount")
    ## a la pasarela bancaria, a partir del número de operación.
    ## TODO: no se implementa hasta que sea necesario.
    def getPaymentDetails(self):
        pass

    ####################################################################
    ## Paso 3.1. Obtiene el número de operación y los datos que nos
    ## envíe la pasarela de pago para luego realizar la verificación.
    @staticmethod
    def receiveConfirmation(request, virtualpos_type):

        delegated_class = get_delegated_class(virtualpos_type)
        delegated = delegated_class.receiveConfirmation(request)

        if delegated:
            vpos = delegated.parent
            return vpos

        return False

    ####################################################################
    ## Paso 3.2. Realiza la verificación de los datos enviados por
    ## la pasarela de pago, para comprobar si el pago ha de marcarse
    ## como pagado
    def verifyConfirmation(self):
        dlprint("vpos.verifyConfirmation")
        return self.delegated.verifyConfirmation()

    ####################################################################
    ## Paso 3.3 Enviar respuesta al TPV,
    ## la respuesta pueden ser la siguientes:

    ####################################################################
    ## Paso 3.3a Completar el pago.
    ## Última comunicación con el TPV.
    ## La comunicación real sólo se realiza en PayPal y Santander Elavon, dado que en CECA
    ## y otros tienen una verificación y una respuesta con "OK".
    ## En cualquier caso, es necesario que la aplicación llame a este
    ## método para terminar correctamente el proceso.
    def charge(self):
        # Bloquear otras transacciones
        VPOSPaymentOperation.objects.select_for_update().filter(id=self.operation.id)

        # Realizamos el cargo
        response = self.delegated.charge()
        # Cambiamos el estado de la operación
        self.operation.status = "completed"
        self.operation.save()
        dlprint("Operation {0} actualizada en charge()".format(self.operation.operation_number))

        # Devolvemos el cargo
        return response

    ####################################################################
    ## Paso 3.3b1. Error en verificación.
    ## No se ha podido recuperar la instancia de TPV de la respuesta del
    ## banco. Se devuelve una respuesta de Nok específica por tipo de TPV.
    @staticmethod
    def staticResponseNok(vpos_type):
        dlprint("vpos.staticResponseNok")

        delegated_class = get_delegated_class(vpos_type)
        dummy_delegated = delegated_class()

        return dummy_delegated.responseNok()

    ####################################################################
    ## Paso 3.3b2. Error en verificación.
    ## Si ha habido un error en la veritificación, se ha de dar una
    ## respuesta negativa a la pasarela bancaria.
    def responseNok(self, extended_status=""):
        dlprint("vpos.responseNok")
        self.operation.status = "failed"

        if extended_status:
            self.operation.status = u"{0}. {1}".format(self.operation.status, extended_status)

        self.operation.save()

        return self.delegated.responseNok()


########################################################################################################################
########################################################################################################################
####################################################### TPV Ceca #######################################################
########################################################################################################################
########################################################################################################################

class VPOSCeca(VirtualPointOfSale):
    """Información de configuración del TPV Virtual CECA"""

    regex_number = re.compile("^\d*$")
    regex_operation_number_prefix = re.compile("^[A-Za-z0-9]*$")

    # Relación con el padre (TPV).
    # Al poner el signo "+" como "related_name" evitamos que desde el padre
    # se pueda seguir la relación hasta aquí (ya que cada uno de las clases
    # que heredan de ella estará en una tabla y sería un lío).
    parent = models.OneToOneField(VirtualPointOfSale, parent_link=True, related_name="+", null=False, db_column="vpos_id")

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


########################################################################################################################
########################################################################################################################
###################################################### TPV Redsys ######################################################
########################################################################################################################
########################################################################################################################

class VPOSRedsys(VirtualPointOfSale):
    """Información de configuración del TPV Virtual Redsys"""
    ## Todo TPV tiene una relación con los datos generales del TPV
    parent = models.OneToOneField(VirtualPointOfSale, parent_link=True, related_name="+", null=False, db_column="vpos_id")

    # Expresión regular usada en la identificación del servidor
    regex_number = re.compile("^\d*$")
    regex_operation_number_prefix = re.compile("^\d+$")

    # Código FUC asignado al comercio
    merchant_code = models.CharField(max_length=9, null=False, blank=False, verbose_name="MerchantCode")

    # Confirmation URL that will be used by the virtual POS
    merchant_response_url = models.URLField(max_length=64, null=False, blank=False, verbose_name="MerchantURL",
                                            help_text=u"Confirmation URL that will be used by the virtual POS")

    # Número de terminal que le asignará su banco
    terminal_id = models.CharField(max_length=3, null=False, blank=False, verbose_name="TerminalID")

    # Clave de cifrado SHA-256 para el entorno de prueba
    encryption_key_testing_sha256 = models.CharField(max_length=64, null=True, default=None,
                                                     verbose_name="Encryption Key SHA-256 para el entorno de pruebas")
    # Clave de cifrado SHA-256 para el entorno de producción
    encryption_key_production_sha256 = models.CharField(max_length=64, null=True, default=None,
                                                        verbose_name="Encryption Key SHA-256 para el entorno de producción")

    # Prefijo del número de operación usado para identicar al servidor desde el que se realiza la petición, el tamaño máximo sera de 3 caracteres numéricos
    operation_number_prefix = models.CharField(max_length=3, null=False, blank=True,
                                               verbose_name="Prefijo del número de operación",
                                               validators=[MinLengthValidator(0), MaxLengthValidator(3),
                                                           RegexValidator(regex=regex_operation_number_prefix,
                                                                          message="Asegúrese de sólo use caracteres numéricos")])

    # Clave que se va usar para esta operación
    encryption_key = None

    # Códigos de respuesta
    DS_RESPONSE_CODES = {
        "0101": u"Tarjeta Caducada.",
        "0102": u"Tarjeta en excepción transitoria o bajo sospecha de fraude.",
        "0104": u"Operación no permitida para esa tarjeta o terminal.",
        "0106": u"Intentos de PIN excedidos.",
        "0116": u"Disponible Insuficiente.",
        "0118": u"Tarjeta no Registrada.",
        "0125": u"Tarjeta no efectiva.",
        "0129": u"Código de seguridad (CVV2/CVC2) incorrecto.",
        "0180": u"Tarjeta ajena al servicio.",
        "0184": u"Error en la autenticación del titular.",
        "0190": u"Denegación sin especificar motivo.",
        "0191": u"Fecha de caducidad errónea.",
        "0202": u"Tarjeta en excepción transitoria o bajo sospecha de fraude con retirada de tarjeta.",
        "0904": u"Comercio no registrado en FUC.",
        "0909": u"Error de sistema.",
        "0912": u"Emisor no disponible.",
        "0913": u"Pedido repetido.",
        "0944": u"Sesión Incorrecta.",
        "0950": u"Operación de devolución no permitida.",
        "9064": u"Número de posiciones de la tarjeta incorrecto.",
        "9078": u"No existe método de pago válido para esa tarjeta.",
        "9093": u"Tarjeta no existente.",
        "9094": u"Rechazo servidores internacionales.",
        "9104": u"Comercio con “titular seguro” y titular sin clave de compra segura.",
        "9218": u"El comercio no permite op. seguras por entrada /operaciones.",
        "9253": u"Tarjeta no cumple el check-digit.",
        "9256": u"El comercio no puede realizar preautorizaciones.",
        "9257": u"Esta tarjeta no permite operativa de preautorizaciones.",
        "9261": u"Operación detenida por superar el control de restricciones en la entrada al SIS.",
        "9912": u"Emisor no disponible.",
        "9913": u"Error en la confirmación que el comercio envía al TPV Virtual (solo aplicable en la opción de sincronización SOAP).",
        "9914": u"Confirmación “KO” del comercio (solo aplicable en la opción de sincronización SOAP).",
        "9915": u"A petición del usuario se ha cancelado el pago.",
        "9928": u"Anulación de autorización en diferido realizada por el SIS (proceso batch).",
        "9929": u"Anulación de autorización en diferido realizada por el comercio.",
        "9997": u"Se está procesando otra transacción en SIS con la misma tarjeta.",
        "9998": u"Operación en proceso de solicitud de datos de tarjeta.",
        "9999": u"Operación que ha sido redirigida al emisor a autenticar.",
    }

    # El TPV de RedSys consta de dos entornos en funcionamiento, uno para pruebas y otro para producción
    REDSYS_URL = {
        "production": "https://sis.redsys.es/sis/realizarPago",
        "testing": "https://sis-t.redsys.es:25443/sis/realizarPago"
    }

    # Idiomas soportados por RedSys
    IDIOMAS = {"es": "001", "en": "002", "ca": "003", "fr": "004", "de": "005", "pt": "009", "it": "007"}

    # URL de pago que variará según el entorno
    url = None
    # Importe de la venta
    importe = None
    # Tipo de cifrado usado en la generación de la firma
    cifrado = "SHA1"
    # Tipo de moneda usada en la operación, en este caso sera Euros
    tipo_moneda = "978"
    # Indica qué tipo de transacción se utiliza, en este caso usamos 0-Autorización
    transaction_type = "0"
    # Idioma por defecto a usar. Español
    idioma = "001"

    # En modo SOAP, string con "<Request>...</Request>" completo. Es necesario para calcular la firma
    soap_request = None

    ## Inicia el valor de la clave de cifrado en función del entorno
    def __init_encryption_key__(self):
        # Clave de cifrado según el entorno
        if self.parent.environment == "testing":
            self.encryption_key = self.encryption_key_testing_sha256
        elif self.parent.environment == "production":
            self.encryption_key = self.encryption_key_production_sha256
        else:
            raise ValueError(u"Entorno {0} no válido".format(self.parent.environment))

        if not self.encryption_key:
            raise ValueError(u"La clave de cifrado para {0} no es válida".format(self.parent.environment))

        # Algunos métodos utilizados más adelante necesitan que sea un str
        self.encryption_key = str(self.encryption_key)

    ####################################################################

    ## Constructor del TPV REDSYS
    def __init__(self, *args, **kwargs):
        super(VPOSRedsys, self).__init__(*args, **kwargs)

    def __unicode__(self):
        return self.name

    @classmethod
    def form(cls):
        from forms import VPOSRedsysForm
        return VPOSRedsysForm

    ####################################################################
    ## Paso 1.1. Configuración del pago
    def configurePayment(self, **kwargs):
        # URL de pago según el entorno
        self.url = self.REDSYS_URL[self.parent.environment]

        # Formato para Importe: según redsys, ha de tener un formato de entero positivo, con las dos últimas posiciones
        # ocupadas por los decimales
        self.importe = "{0:.2f}".format(float(self.parent.operation.amount)).replace(".", "")

        # Idioma de la pasarela, por defecto es español, tomamos
        # el idioma actual y le asignamos éste
        self.idioma = self.IDIOMAS["es"]
        lang = translation.get_language()
        if lang in self.IDIOMAS:
            self.idioma = self.IDIOMAS[lang]

    ####################################################################
    ## Paso 1.2. Preparación del TPV y Generación del número de operación
    def setupPayment(self, operation_number=None, code_len=12):
        """
        Devuelve un número de operación para los pagos al TPV Redsys.
        Nótese que los 4 primeros carateres son dígitos, el resto
        pueden ser dígitos o carecteres alfabéticos.
        """

        operation_number = ''

        if operation_number:
            return operation_number

        if self.operation_number_prefix:
            operation_number = self.operation_number_prefix

        # Los 4 primeros dígitos deben ser numéricos, forzosamente
        for i in range(4 - len(operation_number)):
            operation_number += random.choice('23456789')

        # El resto de los dígitos pueden ser alfanuméricos
        for i in range(code_len - 4):
            operation_number += random.choice('ABCDEFGHJKLMNPQRSTUWXYZ23456789')

        return operation_number

    ####################################################################
    ## Paso 1.3. Obtiene los datos de pago
    ## Este método será el que genere los campos del formulario de pago
    ## que se rellenarán desde el cliente (por Javascript)
    def getPaymentFormData(self):
        order_data = {
            # Indica el importe de la venta
            "DS_MERCHANT_AMOUNT": self.importe,

            # Indica el número de operacion
            "DS_MERCHANT_ORDER": self.parent.operation.operation_number,

            # Código FUC asignado al comercio
            "DS_MERCHANT_MERCHANTCODE": self.merchant_code,

            # Indica el tipo de moneda a usar
            "DS_MERCHANT_CURRENCY": self.tipo_moneda,

            # Indica que tipo de transacción se utiliza
            "DS_MERCHANT_TRANSACTIONTYPE": self.transaction_type,

            # Indica el terminal
            "DS_MERCHANT_TERMINAL": self.terminal_id,

            # Obligatorio si se tiene confirmación online.
            "DS_MERCHANT_MERCHANTURL": self.merchant_response_url,

            # URL a la que se redirige al usuario en caso de que la venta haya sido satisfactoria
            "DS_MERCHANT_URLOK": self.parent.operation.url_ok,

            # URL a la que se redirige al usuario en caso de que la venta NO haya sido satisfactoria
            "DS_MERCHANT_URLKO": self.parent.operation.url_nok,

            # Se mostrará al titular en la pantalla de confirmación de la compra
            "DS_MERCHANT_PRODUCTDESCRIPTION": self.parent.operation.description,

            # Indica el valor del idioma
            "DS_MERCHANT_CONSUMERLANGUAGE": self.idioma,

            # Representa la suma total de los importes de las cuotas
            "DS_MERCHANT_SUMTOTAL": self.importe,
        }

        json_order_data = json.dumps(order_data)
        packed_order_data = base64.b64encode(json_order_data)

        data = {
            "Ds_SignatureVersion": "HMAC_SHA256_V1",
            "Ds_MerchantParameters": packed_order_data,
            "Ds_Signature": self._redsys_hmac_sha256_signature(packed_order_data)
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
    @classmethod
    def receiveConfirmation(cls, request):
        # Es una respuesta HTTP POST "normal"
        if 'Ds_MerchantParameters' in request.POST:
            return cls._receiveConfirmationHTTPPOST(request)

        # Es una respuesta SOAP
        body = request.body
        if "procesaNotificacionSIS" in body and "SOAP" in body:
            return cls._receiveConfirmationSOAP(request)

        raise Exception(u"No se reconoce la petición ni como HTTP POST ni como SOAP")

    ####################################################################
    ## Paso 3.1.a  Procesar notificación HTTP POST
    @staticmethod
    def _receiveConfirmationHTTPPOST(request):
        dlprint(u"Notificación Redsys HTTP POST:")
        dlprint(request.POST)

        # Almacén de operaciones
        try:
            operation_data = json.loads(base64.b64decode(request.POST.get("Ds_MerchantParameters")))
            operation_number = operation_data.get("Ds_Order")
            operation = VPOSPaymentOperation.objects.get(operation_number=operation_number)
            operation.confirmation_data = {"GET": request.GET.dict(), "POST": request.POST.dict()}
            operation.confirmation_code = operation_number
            operation.save()
            dlprint("Operation {0} actualizada en _receiveConfirmationHTTPPOST()".format(operation.operation_number))

            vpos = operation.virtual_point_of_sale
        except VPOSPaymentOperation.DoesNotExist:
            # Si no existe la operación, están intentando
            # cargar una operación inexistente
            return False

        # Iniciamos el delegado y la operación, esto es fundamental para luego calcular la firma
        vpos._init_delegated()
        vpos.operation = operation

        # Iniciamos los valores recibidos en el delegado

        ## Datos que llegan por POST
        # Firma enviada por RedSys, que más tarde compararemos con la generada por el comercio
        vpos.delegated.firma = request.POST.get("Ds_Signature")

        # Versión del método de firma utilizado
        vpos.delegated.signature_version = request.POST.get("Ds_SignatureVersion")

        # Parámetros de la operación (en base64 + JSON)
        vpos.delegated.merchant_parameters = request.POST.get("Ds_MerchantParameters")

        ## Datos decodificados de Ds_MerchantParameters
        # Respuesta de la pasarela de pagos. Indica si la operación se autoriza o no
        vpos.delegated.ds_response = operation_data.get("Ds_Response")

        return vpos.delegated

    ####################################################################
    ## Paso 3.1.b  Procesar notificación SOAP
    @staticmethod
    def _receiveConfirmationSOAP(request):
        dlprint(u"Notificación Redsys SOAP:")
        body = request.body
        dlprint(body)

        root = etree.fromstring(body)
        tree = etree.ElementTree(root)

        soapdict = dictlist(tree.getroot())

        # Aquí tendremos toda la cadena <Message>...</Message>
        xml_content = soapdict['{http://schemas.xmlsoap.org/soap/envelope/}Envelope']['value'][0][
            '{http://schemas.xmlsoap.org/soap/envelope/}Body']['value'][0]['{InotificacionSIS}procesaNotificacionSIS'][
            'value'][0]['XML']['value']

        # procesar <Message>...</Message>
        dlprint(u"Mensaje XML completo:" + xml_content)
        root = etree.fromstring(xml_content)

        # Almacén de operaciones
        try:
            ds_order = root.xpath("//Message/Request/Ds_Order/text()")[0]
            operation = VPOSPaymentOperation.objects.get(operation_number=ds_order)
            operation.confirmation_data = {"GET": "", "POST": xml_content}
            operation.confirmation_code = ds_order
            operation.response_code = TpvRedsys._format_ds_response_code(ds_response)
            operation.save()
            dlprint("Operation {0} actualizada en _receiveConfirmationSOAP()".format(operation.operation_number))
            vpos = operation.virtual_point_of_sale
        except VPOSPaymentOperation.DoesNotExist:
            # Si no existe la operación, están intentando
            # cargar una operación inexistente
            return False

        # Iniciamos el delegado y la operación, esto es fundamental
        # para luego calcular la firma
        vpos._init_delegated()
        vpos.operation = operation

        ## Iniciamos los valores recibidos en el delegado

        # Contenido completo de <Request>...</Request>, necesario posteriormente para cálculo de firma
        soap_request = etree.tostring(root.xpath("//Message/Request")[0])
        # corrige autocierre de etuqueta y entrecomillado de atributos. Para la comprobación de la firma,
        # la etiqueta debe tener apertura y cierre y el atributo va entre comilla simple
        soap_request = soap_request.replace("<Ds_MerchantData/>", "<Ds_MerchantData></Ds_MerchantData>", 1).replace('"',
                                                                                                                    "'")
        vpos.delegated.soap_request = soap_request
        dlprint(u"Request:" + vpos.delegated.soap_request)

        # Firma enviada por RedSys, que más tarde compararemos con la generada por el comercio
        vpos.delegated.firma = root.xpath("//Message/Signature/text()")[0]
        dlprint(u"Signature:" + vpos.delegated.firma)

        # Código que indica el tipo de transacción
        vpos.delegated.ds_response = root.xpath("//Message/Request/Ds_Response/text()")[0]

        return vpos.delegated

    ####################################################################
    ## Paso 3.2. Verifica que los datos enviados desde
    ## la pasarela de pago identifiquen a una operación de compra y un
    ## pago autorizado.
    def verifyConfirmation(self):
        firma_calculada = self._verification_signature()
        dlprint("Firma calculada " + firma_calculada)

        dlprint("Firma recibida " + self.firma)

        # Traducir caracteres de la firma recibida '-' y '_' al alfabeto base64
        firma_traducida = self.firma.replace("-", "+").replace("_", "/")
        if self.firma != firma_traducida:
            dlprint("Firma traducida " + firma_traducida)

        # Comprueba si el envío es correcto
        if firma_traducida != firma_calculada:
            dlprint("Las firmas no coinciden")
            return False
        else:
            dlprint("Firma verificada correctamente")

        # Comprobar que el resultado se corresponde a un pago autorizado
        # por RedSys. Los pagos autorizados son todos los Ds_Response entre
        # 0000 y 0099 [manual TPV Virtual SIS v1.0, pág. 31]
        if len(self.ds_response) != 4 or self.ds_response.isdigit() == False or self.ds_response[:2] != "00":
            dlprint(u"Transacción no autorizada por RedSys. Ds_Response es {0} (no está entre 0000-0099)".format(
                self.ds_response))
            return False

        # Todo OK
        return True

    ####################################################################
    ## Paso 3.3a. Realiza el cobro y genera la respuesta a la pasarela y
    ## comunicamos con la pasarela de pago para que marque la operación
    ## como pagada. Sólo se usa en CECA
    def charge(self):
        if self.soap_request:
            dlprint("responseOk SOAP")
            # Respuesta a notificación HTTP SOAP
            response = '<Response Ds_Version="0.0"><Ds_Response_Merchant>OK</Ds_Response_Merchant></Response>'

            dlprint("FIRMAR RESPUESTA {response} CON CLAVE DE CIFRADO {key}".format(response=response,
                                                                                    key=self.encryption_key))
            signature = self._redsys_hmac_sha256_signature(response)

            message = "<Message>{response}<Signature>{signature}</Signature></Message>".format(response=response,
                                                                                               signature=signature)
            dlprint("MENSAJE RESPUESTA CON FIRMA {0}".format(message))

            # El siguiente mensaje NO debe tener espacios en blanco ni saltos de línea entre las marcas XML
            out = "<?xml version='1.0' encoding='UTF-8'?><SOAP-ENV:Envelope xmlns:SOAP-ENV=\"http://schemas.xmlsoap.org/soap/envelope/\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xmlns:xsd=\"http://www.w3.org/2001/XMLSchema\"><SOAP-ENV:Body><ns1:procesaNotificacionSISResponse xmlns:ns1=\"InotificacionSIS\" SOAP-ENV:encodingStyle=\"http://schemas.xmlsoap.org/soap/encoding/\"><result xsi:type=\"xsd:string\">{0}</result></ns1:procesaNotificacionSISResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>"
            out = out.format(cgi.escape(message))
            dlprint("RESPUESTA SOAP:" + out)

            return HttpResponse(out, "text/xml")
        else:
            dlprint(u"responseOk HTTP POST (respuesta vacía)")
            # Respuesta a notificación HTTP POST
            # En RedSys no se exige una respuesta, por parte del comercio, para verificar
            # la operación, pasamos una respuesta vacia
            return HttpResponse("")

    ####################################################################
    ## Paso 3.3b. Si ha habido un error en el pago, se ha de dar una
    ## respuesta negativa a la pasarela bancaria.
    def responseNok(self, **kwargs):
        if self.soap_request:
            dlprint("responseOk SOAP")
            # Respuesta a notificación HTTP SOAP
            response = '<Response Ds_Version="0.0"><Ds_Response_Merchant>KO</Ds_Response_Merchant></Response>'

            dlprint("FIRMAR RESPUESTA {response} CON CLAVE DE CIFRADO {key}".format(response=response,
                                                                                    key=self.encryption_key))
            signature = self._redsys_hmac_sha256_signature(response)

            message = "<Message>{response}<Signature>{signature}</Signature></Message>".format(response=response,
                                                                                               signature=signature)
            dlprint("MENSAJE RESPUESTA CON FIRMA {0}".format(message))

            # El siguiente mensaje NO debe tener espacios en blanco ni saltos de línea entre las marcas XML
            out = "<?xml version='1.0' encoding='UTF-8'?><SOAP-ENV:Envelope xmlns:SOAP-ENV=\"http://schemas.xmlsoap.org/soap/envelope/\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xmlns:xsd=\"http://www.w3.org/2001/XMLSchema\"><SOAP-ENV:Body><ns1:procesaNotificacionSISResponse xmlns:ns1=\"InotificacionSIS\" SOAP-ENV:encodingStyle=\"http://schemas.xmlsoap.org/soap/encoding/\"><result xsi:type=\"xsd:string\">{0}</result></ns1:procesaNotificacionSISResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>"
            out = out.format(cgi.escape(message))
            dlprint("RESPUESTA SOAP:" + out)

            return HttpResponse(out, "text/xml")
        else:
            dlprint(u"responseNok HTTP POST (respuesta vacía)")
            # Respuesta a notificación HTTP POST
            # En RedSys no se exige una respuesta, por parte del comercio, para verificar
            # que la operación ha sido negativa, pasamos una respuesta vacia
            return HttpResponse("")

    ####################################################################
    ## Generador de firma de mensajes
    def _redsys_hmac_sha256_signature(self, data):
        """
        Firma la cadena de texto recibida usando 3DES y HMAC SHA-256

        Calcula la firma a incorporar en el formulario de pago
        :type data: str  cadena de texto que se va a firmar
        :return: str     cadena de texto con la firma
        """

        # Obtener encryption key para el entorno actual (almacenada en self.encryption_key)
        self.__init_encryption_key__()
        dlprint("_redsys_hmac_sha256_signature: encryption key {0}".format(self.encryption_key))

        # Decodificar firma
        encryption_key = base64.b64decode(self.encryption_key)

        # operation_number = bytes(self.parent.operation.operation_number)
        operation_number = bytes(self.parent.operation.operation_number)
        dlprint("_redsys_hmac_sha256_signature: operation_number {0}".format(operation_number))

        # Rellenar cadena hasta múltiplo de 8 bytes
        if len(operation_number) % 8 != 0:
            dlprint(
                "_redsys_hmac_sha256_signature: la longitud del operation number es {0} y necesita relleno para 3DES".format(
                    len(operation_number)))
            operation_number += bytes("\x00") * (8 - len(self.parent.operation.operation_number) % 8)
            dlprint("_redsys_hmac_sha256_signature: la longitud de la cadena rellenada para 3DES es de {0}".format(
                len(operation_number)))

        # Generar clave de firma con 3DES y IV igual a ocho bytes con cero
        des3_obj = DES3.new(encryption_key, DES3.MODE_CBC, b"\x00" * 8)
        signature_key = des3_obj.encrypt(operation_number)

        # Generar firma HMAC SHA-256 del mensaje.
        hash_obj = HMAC.new(key=signature_key, msg=data, digestmod=SHA256)
        digest = hash_obj.digest()

        # Devolver firma codificada en Base64
        signature = base64.b64encode(digest)
        dlprint("Firma: {0}".format(signature))
        return signature

    ####################################################################
    ## Generador de firma para la verificación
    def _verification_signature(self):
        """
        Calcula la firma de verificación, tanto para peticiones SOAP como para peticiones HTTP POST
        :rtype : str
        :return: str  firma calculada
        """
        self.__init_encryption_key__()

        # El método de comprobación de firma difiere según se esté procesando una notificación
        # SOAP o HTTP POST

        if self.soap_request:
            ## Cálculo de firma para confirmación SOAP:
            dlprint(u"Comprobación de firma para SOAP con clave de cifrado " + self.encryption_key)
            signature = self._redsys_hmac_sha256_signature(self.soap_request)
        else:
            ## Cálculo de firma para confirmación HTTP POST:
            dlprint(u"Comprobación de firma para HTTP POST con clave de cifrado " + self.encryption_key)
            signature = self._redsys_hmac_sha256_signature(self.merchant_parameters)

        dlprint("FIRMA {0}".format(signature))
        return signature

    @staticmethod
    def _format_ds_response_code(ds_response):
        """
        Formatea el mensaje asociado a un Ds_Response
        :param ds_response: str  código Ds_Response
        :return: unicode  mensaje formateado
        """
        if not ds_response:
            return None

        if len(ds_response) == 4 and ds_response.isdigit() and ds_response[:2] == "00":
            message = u"Transacción autorizada para pagos y preautorizaciones."
        else:
            message = TpvRedsys.DS_RESPONSE_CODES.get(ds_response)

        out = u"{0}. {1}".format(ds_response, message)

        return out


########################################################################################################################
########################################################################################################################
###################################################### TPV PayPal ######################################################
########################################################################################################################
########################################################################################################################

class VPOSPaypal(VirtualPointOfSale):
    """Información de configuración del TPV Virtual PayPal """
    ## Todo TPV tiene una relación con los datos generales del TPV
    parent = models.OneToOneField(VirtualPointOfSale, parent_link=True, related_name="+", null=False, db_column="vpos_id")

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
        from forms import VPOSPaypalForm
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


########################################################################################################################
########################################################################################################################
################################################# TPV Santander Elavon #################################################
########################################################################################################################
########################################################################################################################

class VPOSSantanderElavon(VirtualPointOfSale):
    """Información de configuración del TPV Virtual CECA"""

    regex_clientid = re.compile("^[a-zA-Z0-9]*$")
    regex_account = re.compile("^[a-zA-Z0-9.]*$")
    regex_number = re.compile("^\d*$")
    regex_operation_number_prefix = re.compile("^[A-Za-z0-9]*$")

    # Relación con el padre (TPV).
    # Al poner el signo "+" como "related_name" evitamos que desde el padre
    # se pueda seguir la relación hasta aquí (ya que cada uno de las clases
    # que heredan de ella estará en una tabla y sería un lío).
    parent = models.OneToOneField(VirtualPointOfSale, parent_link=True, related_name="+", null=False, db_column="vpos_id")

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
        from forms import VPOSSantanderElavonForm
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
