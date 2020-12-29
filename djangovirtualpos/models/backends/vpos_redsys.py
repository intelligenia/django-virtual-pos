# coding=utf-8
import base64
import cgi
import json
import logging
import random
import re
from lxml import etree

import requests
from Crypto.Cipher import DES3
from Crypto.Hash import HMAC, SHA256
from bs4 import BeautifulSoup
from django.core.validators import MinLengthValidator, MaxLengthValidator, RegexValidator
from django.db import models
from django.http import HttpResponse
from django.utils import translation

from djangovirtualpos.models import VirtualPointOfSale, VPOSRefundOperation, VPOSPaymentOperation
from djangovirtualpos.models.exceptions import VPOSOperationAlreadyConfirmed, VPOSOperationException
from djangovirtualpos.util import dictlist

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
formatter = logging.Formatter("[%(filename)s:%(lineno)s - %(funcName)20s() ] %(message)s")
ch.setFormatter(formatter)
logger.addHandler(ch)

AUTHORIZATION_TYPE = "authorization"
PREAUTHORIZATION_TYPE = "pre-authorization"
OPERATIVE_TYPES = (
    (AUTHORIZATION_TYPE, u"Pago normal (\"autorización\")"),
    (PREAUTHORIZATION_TYPE, u"Preautorización"),
)


class VPOSRedsys(VirtualPointOfSale):
    """Información de configuración del TPV Virtual Redsys"""
    # Todo TPV tiene una relación con los datos generales del TPV
    parent = models.OneToOneField(VirtualPointOfSale, parent_link=True, related_name="+", null=False,
                                  db_column="vpos_id")

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

    # Habilita mecanismo de preautorización + confirmación o anulación.

    operative_type = models.CharField(max_length=512, choices=OPERATIVE_TYPES, default=AUTHORIZATION_TYPE,
                                      verbose_name=u"Tipo de operativa")

    # Clave de cifrado SHA-256 para el entorno de prueba
    encryption_key_testing_sha256 = models.CharField(max_length=64, null=True, default=None,
                                                     verbose_name="Encryption Key SHA-256 para el entorno de pruebas")
    # Clave de cifrado SHA-256 para el entorno de producción
    encryption_key_production_sha256 = models.CharField(max_length=64, null=True, default=None,
                                                        verbose_name="Encryption Key SHA-256 para el entorno de producción")

    # Prefijo del número de operación usado para identicar al servidor desde el que se realiza la petición, el tamaño
    # máximo sera de 3 caracteres numéricos
    operation_number_prefix = models.CharField(
        max_length=3, null=False, blank=True, verbose_name="Prefijo del número de operación",
        validators=[MinLengthValidator(0),
                    MaxLengthValidator(3),
                    RegexValidator(
                        regex=regex_operation_number_prefix,
                        message="Asegúrese de sólo use caracteres numéricos")
                    ]
    )

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
        "9913": u"Error en la confirmación que el comercio envía al TPV Virtual (solo aplicable en la opción de "
                u"sincronización SOAP).",
        "9914": u"Confirmación “KO” del comercio (solo aplicable en la opción de sincronización SOAP).",
        "9915": u"A petición del usuario se ha cancelado el pago.",
        "9928": u"Anulación de autorización en diferido realizada por el SIS (proceso batch).",
        "9929": u"Anulación de autorización en diferido realizada por el comercio.",
        "9997": u"Se está procesando otra transacción en SIS con la misma tarjeta.",
        "9998": u"Operación en proceso de solicitud de datos de tarjeta.",
        "9999": u"Operación que ha sido redirigida al emisor a autenticar.",
    }

    # Códigos de error SISxxxx
    DS_ERROR_CODES = {
        'SIS0001': u'Error en la generación de HTML',
        'SIS0002': u'Error al generar el XML de la clase de datos',
        'SIS0003': u'Error al crear el gestor de mensajes price',
        'SIS0004': u'Error al montar el mensaje para pago móvil',
        'SIS0005': u'Error al desmontar la respuesta de un pago móvil',
        'SIS0006': u'Error al provocar un ROLLBACK de una transacción',
        'SIS0007': u'Error al desmontar XML',
        'SIS0008': u'Error falta Ds_Merchant_MerchantCode ',
        'SIS0009': u'Error de formato en Ds_Merchant_MerchantCode',
        'SIS0010': u'Error falta Ds_Merchant_Terminal',
        'SIS0011': u'Error de formato en Ds_Merchant_Terminal',
        'SIS0012': u'Error, no se pudo crear el componente de conexión con Stratus',
        'SIS0013': u'Error, no se pudo cerrar el componente de conexión con Stratus',
        'SIS0014': u'Error de formato en Ds_Merchant_Order',
        'SIS0015': u'Error falta Ds_Merchant_Currency',
        'SIS0016': u'Error de formato en Ds_Merchant_Currency',
        'SIS0017': u'Error no se admiten operaciones en pesetas -- DEPRECATED !!!!',
        'SIS0018': u'Error falta Ds_Merchant_Amount',
        'SIS0019': u'Error de formato en Ds_Merchant_Amount',
        'SIS0020': u'Error falta Ds_Merchant_MerchantSignature',
        'SIS0021': u'Error la Ds_Merchant_MerchantSignature viene vacía',
        'SIS0022': u'Error de formato en Ds_Merchant_TransactionType',
        'SIS0023': u'Error Ds_Merchant_TransactionType desconocido. Pago Adicional: Si no se permite pago Adicional '
                   u'(porque el comercio no es de la Entidad o no hay pago adicional en métodos de pago -> SIS0023 '
                   u'Transation type invalido)',
        'SIS0024': u'Error Ds_Merchant_ConsumerLanguage tiene mas de 3 posiciones',
        'SIS0025': u'Error de formato en Ds_Merchant_ConsumerLanguage',
        'SIS0026': u'Error No existe el comercio / terminal enviado en TZF',
        'SIS0027': u'Error Moneda enviada por el comercio es diferente a la de la TZF',
        'SIS0028': u'Error Comercio / terminal está dado de baja',
        'SIS0029': u'Error al montar el mensaje para pago con tarjeta',
        'SIS0030': u'Error en un pago con tarjeta ha llegado un tipo de operación que no es ni pago ni preautorización',
        'SIS0031': u'Método de pago no definido',
        'SIS0032': u'Error al montar el mensaje para una devolución',
        'SIS0033': u'Error en un pago con móvil ha llegado un tipo de operación que no es ni pago ni preautorización',
        'SIS0034': u'Error de acceso a la base de datos',
        'SIS0035': u'Error al recuperar los datos de la sesión desde un XML',
        'SIS0036': u'Error al tomar los datos para Pago Móvil desde el XML',
        'SIS0037': u'El número de teléfono no es válido',
        'SIS0038': u'Error en java (errores varios)',
        'SIS0039': u'Error al tomar los datos para Pago Tarjeta desde el XML',
        'SIS0040': u'Error el comercio / terminal no tiene ningún método de pago asignado',
        'SIS0041': u'Error en el cálculo de la HASH de datos del comercio.',
        'SIS0042': u'La firma enviada no es correcta',
        'SIS0043': u'Error al realizar la notificación on-line',
        'SIS0044': u'Error al tomar los datos para Pago Finanet desde el XML',
        'SIS0045': u'Error al montar el mensaje para pago Finanet',
        'SIS0046': u'El bin de la tarjeta no está dado de alta en FINANET',
        'SIS0047': u'Error al montar el mensaje para preautorización móvil',
        'SIS0048': u'Error al montar el mensaje para preautorización tarjeta',
        'SIS0049': u'Error al montar un mensaje de anulación',
        'SIS0050': u'Error al montar un mensaje de repetición de anulación',
        'SIS0051': u'Error número de pedido repetido',
        'SIS0052': u'Error al montar el mensaje para una confirmación',
        'SIS0053': u'Error al montar el mensaje para una preautenticación por referencia',
        'SIS0054': u'Error no existe operación sobre la que realizar la devolución',
        'SIS0055': u'Error existe más de un pago con el mismo número de pedido',
        'SIS0056': u'La operación sobre la que se desea devolver no está autorizada',
        'SIS0057': u'El importe a devolver supera el permitido',
        'SIS0058': u'Inconsistencia de datos, en la validación de una confirmación ',
        'SIS0059': u'Error no existe operación sobre la que realizar la confirmación',
        'SIS0060': u'Ya existe una confirmación asociada a la preautorización',
        'SIS0061': u'La preautorización sobre la que se desea confirmar no está autorizada',
        'SIS0062': u'El importe a confirmar supera el permitido',
        'SIS0063': u'Error. Número de tarjeta no disponible',
        'SIS0064': u'Error. Número de posiciones de la tarjeta incorrecto',
        'SIS0065': u'Error. El número de tarjeta no es numérico',
        'SIS0066': u'Error. Mes de caducidad no disponible',
        'SIS0067': u'Error. El mes de la caducidad no es numérico',
        'SIS0068': u'Error. El mes de la caducidad no es válido',
        'SIS0069': u'Error. Año de caducidad no disponible',
        'SIS0070': u'Error. El Año de la caducidad no es numérico',
        'SIS0071': u'Tarjeta caducada',
        'SIS0072': u'Operación no anulable',
        'SIS0073': u'Error al analizar la respuesta de una anulación',
        'SIS0074': u'Error falta Ds_Merchant_Order',
        'SIS0075': u'Error el Ds_Merchant_Order tiene menos de 4 posiciones o más de 12 (Para algunas operativas el '
                   u'límite es 10 en lugar de 12)',
        'SIS0076': u'Error el Ds_Merchant_Order no tiene las cuatro primeras posiciones numéricas',
        'SIS0077': u'Error de formato en Ds_Merchant_Order',
        'SIS0078': u'Método de pago no disponible',
        'SIS0079': u'Error en realizar pago tarjeta',
        'SIS0080': u'Error al tomar los datos para Pago tarjeta desde el XML',
        'SIS0081': u'La sesión es nueva, se han perdido los datos almacenados',
        'SIS0082': u'Error procesando operaciones pendientes en el arranque',
        'SIS0083': u'El sistema no está arrancado (Se está arrancado)',
        'SIS0084': u'El valor de Ds_Merchant_Conciliation es nulo',
        'SIS0085': u'El valor de Ds_Merchant_Conciliation no es numérico',
        'SIS0086': u'El valor de Ds_Merchant_Conciliation no ocupa 6 posiciones',
        'SIS0087': u'El valor de Ds_Merchant_Session es nulo',
        'SIS0088': u'El valor de Ds_Merchant_Session no es numérico',
        'SIS0089': u'El valor de caducidad no ocupa 4 posiciones',
        'SIS0090': u'El valor del ciers representado de BBVA es nulo',
        'SIS0091': u'El valor del ciers representado de BBVA no es numérico',
        'SIS0092': u'El valor de caducidad es nulo',
        'SIS0093': u'Tarjeta no encontrada en la tabla de rangos',
        'SIS0094': u'La tarjeta no fue autenticada como 3D Secure',
        'SIS0095': u'Error al intentar validar la tarjeta como 3DSecure',
        'SIS0096': u'El formato utilizado para los datos 3DSecure es incorrecto',
        'SIS0097': u'Valor del campo Ds_Merchant_CComercio no válido',
        'SIS0098': u'Valor del campo Ds_Merchant_CVentana no válido',
        'SIS0099': u'Error al desmontar los datos para Pago 3D Secure desde el XML',
        'SIS0100': u'Error al desmontar los datos para PagoPIN desde el XML',
        'SIS0101': u'Error al desmontar los datos para PantallaPIN desde el XML',
        'SIS0102': u'Error No se recibió el resultado de la autenticación',
        'SIS0103': u'Error Mandando SisMpiTransactionRequestMessage al Merchant Plugin',
        'SIS0104': u'Error calculando el bloque de PIN',
        'SIS0105': u'Error, la referencia es nula o vacía',
        'SIS0106': u'Error al montar los datos para RSisPantallaSPAUCAF.xsl',
        'SIS0107': u'Error al desmontar los datos para PantallaSPAUCAF desde el XML',
        'SIS0108': u'Error al desmontar los datos para pagoSPAUCAF desde el XML',
        'SIS0109': u'Error El número de tarjeta no se corresponde con el seleccionado originalmente ',
        'SIS0110': u'Error La fecha de caducidad de la tarjeta no se corresponde con el seleccionado originalmente',
        'SIS0111': u'Error El campo Ucaf_Authentication_Data no tiene la longitud requerida',
        'SIS0112': u'Error El tipo de transacción especificado en Ds_Merchant_Transaction_Type no está permitido',
        'SIS0113': u'Excepción producida en el servlet de operaciones',
        'SIS0114': u'Error, se ha llamado con un GET al servlet de operaciones',
        'SIS0115': u'Error no existe operación sobre la que realizar el pago de la cuota',
        'SIS0116': u'La operación sobre la que se desea pagar una cuota no es una operación válida',
        'SIS0117': u'La operación sobre la que se desea pagar una cuota no está autorizada',
        'SIS0118': u'Se ha excedido el importe total de las cuotas',
        'SIS0119': u'Valor del campo Ds_Merchant_DateFrecuency no válido',
        'SIS0120': u'Valor del campo Ds_Merchant_ChargeExpiryDate no válido',
        'SIS0121': u'Valor del campo Ds_Merchant_SumTotal no válido',
        'SIS0122': u'Error en formato numérico. Antiguo Valor del campo Ds_Merchant_DateFrecuency o no '
                   u'Ds_Merchant_SumTotal tiene formato incorrecto',
        'SIS0123': u'Se ha excedido la fecha tope para realizar transacciones',
        'SIS0124': u'No ha transcurrido la frecuencia mínima en un pago recurrente sucesivo',
        'SIS0125': u'Error en código java validando cuota',
        'SIS0126': u'Error la operación no se puede marcar como pendiente',
        'SIS0127': u'Error la generando datos Url OK CANCEL',
        'SIS0128': u'Error se quiere generar una anulación sin p2',
        'SIS0129': u'Error, se ha detectado un intento masivo de peticiones desde la ip',
        'SIS0130': u'Error al regenerar el mensaje',
        'SIS0131': u'Error en la firma de los datos del SAS',
        'SIS0132': u'La fecha de Confirmación de Autorización no puede superar en más de 7 días a la de '
                   u'Preautorización.',
        'SIS0133': u'La fecha de Confirmación de Autenticación no puede superar en más de 45 días a la de '
                   u'Autenticación Previa.',
        'SIS0134': u'El valor del Ds_MerchantCiers enviado por BBVA no es válido',
        'SIS0135': u'Error generando un nuevo valor para el IDETRA',
        'SIS0136': u'Error al montar el mensaje de notificación',
        'SIS0137': u'Error al intentar validar la tarjeta como 3DSecure NACIONAL',
        'SIS0138': u'Error debido a que existe una Regla del ficheros de reglas que evita que se produzca la '
                   u'Autorización',
        'SIS0139': u'Error el pago recurrente inicial está duplicado',
        'SIS0140': u'Error al interpretar la respuesta de Stratus para una preautenticación por referencia',
        'SIS0141': u'Error formato no correcto para 3DSecure',
        'SIS0142': u'Tiempo excedido para el pago',
        'SIS0143': u'No viene el campo laOpcion en el formulario enviado',
        'SIS0144': u'El campo laOpcion recibido del formulario tiene un valor desconocido para el servlet',
        'SIS0145': u'Error al montar el mensaje para P2P',
        'SIS0146': u'Transacción P2P no reconocida',
        'SIS0147': u'Error al tomar los datos para Pago P2P desde el XML',
        'SIS0148': u'Método de pago no disponible o no válido para P2P',
        'SIS0149': u'Error al obtener la referencia para operación P2P',
        'SIS0150': u'Error al obtener la clave para operación P2P',
        'SIS0151': u'Error al generar un objeto desde el XML',
        'SIS0152': u'Error en operación P2P. Se carece de datos',
        'SIS0153': u'Error, el número de días de operación P2P no es correcto',
        'SIS0154': u'Error el mail o el teléfono de T2 son obligatorios (operación P2P)',
        'SIS0155': u'Error obteniendo datos de operación P2P',
        'SIS0156': u'Error la operación no es P2P Tipo 3',
        'SIS0157': u'Error no se encuentra la operación P2P original',
        'SIS0158': u'Error, la operación P2P original no está en el estado correcto',
        'SIS0159': u'Error, la clave de control de operación P2P no es válida ',
        'SIS0160': u'Error al tomar los datos para una operación P2P tipo 3',
        'SIS0161': u'Error en el envío de notificación P2P',
        'SIS0162': u'Error tarjeta de carga micropago no tiene pool asociado',
        'SIS0163': u'Error tarjeta de carga micropago no autenticable',
        'SIS0164': u'Error la recarga para micropagos sólo permite euros',
        'SIS0165': u'Error la T1 de la consulta no coincide con la de la operación P2P original',
        'SIS0166': u'Error el nombre del titular de T1 es obligatorio',
        'SIS0167': u'Error la operación está bloqueada por superar el número de intentos fallidosde introducción del '
                   u'código por parte de T2',
        'SIS0168': u'No existe terminal AMEX asociada',
        'SIS0169': u'Valor PUCE Ds_Merchant_MatchingData no válido',
        'SIS0170': u'Valor PUCE Ds_Acquirer_Identifier no válido',
        'SIS0171': u'Valor PUCE Ds_Merchant_Csb no válido',
        'SIS0172': u'Valor PUCE Ds_Merchant_MerchantCode no válido',
        'SIS0173': u'Valor PUCE Ds_Merchant_UrlOK no válido',
        'SIS0174': u'Error calculando el resultado PUCE',
        'SIS0175': u'Error al montar el mensaje PUCE',
        'SIS0176': u'Error al tratar el mensaje de petición P2P procedente de Stratus.',
        'SIS0177': u'Error al descomponer el mensaje de Envío de fondos en una operación P2P iniciada por Stratus.',
        'SIS0178': u'Error al montar el XML con los datos de envío para una operación P2P',
        'SIS0179': u'Error P2P Móvil, el teléfono no tiene asociada tarjeta',
        'SIS0180': u'El telecode es nulo o vacía para operación P2P',
        'SIS0181': u'Error al montar el XML con los datos recibidos',
        'SIS0182': u'Error al montar el mensaje PRICE / Error al tratar el mensaje de petición Cobro de Recibo',
        'SIS0183': u'Error al montar el XML de respuesta',
        'SIS0184': u'Error al tratar el XML de Recibo',
        'SIS0186': u'Error en entrada Banco Sabadell. Faltan datos',
        'SIS0187': u'Error al montar el mensaje de respuesta a Stratus (Error Formato)',
        'SIS0188': u'Error al desmontar el mensaje price en una petición P2P procedente de Stratus',
        'SIS0190': u'Error al intentar mandar el mensaje SMS',
        'SIS0191': u'Error, El mail del beneficiario no coincide con el indicado en la recepción P2P',
        'SIS0192': u'Error, La clave de mail del beneficiario no es correcta en la recepción P2P',
        'SIS0193': u'Error comprobando monedas para DCC',
        'SIS0194': u'Error problemas con la aplicación del cambio y el mostrado al titular',
        'SIS0195': u'Error en pago PIN. No llegan los datos',
        'SIS0196': u'Error las tarjetas de operación P2P no son del mismo procesador',
        'SIS0197': u'Error al obtener los datos de cesta de la compra en operación tipo pasarela',
        'SIS0198': u'Error el importe supera el límite permitido para el comercio',
        'SIS0199': u'Error el número de operaciones supera el límite permitido para el comercio',
        'SIS0200': u'Error el importe acumulado supera el límite permitido para el comercio',
        'SIS0201': u'Se ha producido un error inesperado al realizar la conexión con el VDS',
        'SIS0202': u'Se ha producido un error en el envío del mensaje',
        'SIS0203': u'No existe ningún método definido para el envío del mensaje',
        'SIS0204': u'No se ha definido una URL válida para el envío de mensajes',
        'SIS0205': u'Error al generar la firma, es posible que el mensaje no sea válido o esté incompleto',
        'SIS0206': u'No existe una clave asociada al BID especificado',
        'SIS0207': u'La consulta no ha devuelto ningún resultado',
        'SIS0208': u'La operación devuelta por el SIS no coincide con la petición',
        'SIS0209': u'No se han definido parámetros para realizar la consulta',
        'SIS0210': u'Error al validar el mensaje, faltan datos: BID',
        'SIS0211': u'Error en la validación de la firma ',
        'SIS0212': u'La respuesta recibida no se corresponde con la petición. Referencias de mensaje distintas',
        'SIS0213': u'Errores devueltos por el VDS',
        'SIS0214': u'El comercio no permite devoluciones. Se requiere usar firma ampliada.',
        'SIS0215': u'Operación no permitida para TPV’s virtuales de esta entidad.',
        'SIS0216': u'Error Ds_Merchant_CVV2 tiene más de 3 posiciones',
        'SIS0217': u'Error de formato en Ds_Merchant_CVV2',
        'SIS0218': u'El comercio no permite operaciones seguras por entrada XML',
        'SIS0219': u'Error el número de operaciones de la tarjeta supera el límite permitido para el comercio',
        'SIS0220': u'Error el importe acumulado de la tarjeta supera el límite permitido para el comercio',
        'SIS0221': u'Error el CVV2 es obligatorio',
        'SIS0222': u'Ya existe una anulación asociada a la preautorización',
        'SIS0223': u'La preautorización que se desea anular no está autorizada',
        'SIS0224': u'El comercio no permite anulaciones por no tener firma ampliada',
        'SIS0225': u'Error no existe operación sobre la que realizar la anulación',
        'SIS0226': u'Inconsistencia de datos, en la validación de una anulación',
        'SIS0227': u'Valor del campo Ds_Merchant_TransactionDate no válido',
        'SIS0228': u'Sólo se puede hacer pago aplazado con tarjeta de crédito On-us',
        'SIS0229': u'No existe el código de pago aplazado solicitado',
        'SIS0230': u'El comercio no permite pago fraccionado',
        'SIS0231': u'No hay forma de pago aplicable para el cliente',
        'SIS0232': u'Error. Forma de pago no disponible',
        'SIS0233': u'Error. Forma de pago desconocida',
        'SIS0234': u'Error. Nombre del titular de la cuenta no disponible',
        'SIS0235': u'Error. Campo Sis_Numero_Entidad no disponible',
        'SIS0236': u'Error. El campo Sis_Numero_Entidad no tiene la longitud requerida',
        'SIS0237': u'Error. El campo Sis_Numero_Entidad no es numérico',
        'SIS0238': u'Error. Campo Sis_Numero_Oficina no disponible',
        'SIS0239': u'Error. El campo Sis_Numero_Oficina no tiene la longitud requerida',
        'SIS0240': u'Error. El campo Sis_Numero_Oficina no es numérico',
        'SIS0241': u'Error. Campo Sis_Numero_DC no disponible',
        'SIS0242': u'Error. El campo Sis_Numero_DC no tiene la longitud requerida',
        'SIS0243': u'Error. El campo Sis_Numero_DC no es numérico',
        'SIS0244': u'Error. Campo Sis_Numero_Cuenta no disponible',
        'SIS0245': u'Error. El campo Sis_Numero_Cuenta no tiene la longitud requerida',
        'SIS0246': u'Error. El campo Sis_Numero_Cuenta no es numérico',
        'SIS0247': u'Dígito de Control de Cuenta Cliente no válido',
        'SIS0248': u'El comercio no permite pago por domiciliación',
        'SIS0249': u'Error al realizar pago por domiciliación',
        'SIS0250': u'Error al tomar los datos del XML para realizar Pago por Transferencia',
        'SIS0251': u'El comercio no permite pago por transferencia',
        'SIS0252': u'El comercio no permite el envío de tarjeta',
        'SIS0253': u'Tarjeta no cumple check-digit',
        'SIS0254': u'El número de operaciones de la IP supera el límite permitido por el comercio',
        'SIS0255': u'El importe acumulado por la IP supera el límite permitido por el comercio',
        'SIS0256': u'El comercio no puede realizar preautorizaciones',
        'SIS0257': u'Esta tarjeta no permite operativa de preautorizaciones',
        'SIS0258': u'Inconsistencia de datos, en la validación de una confirmación',
        'SIS0259': u'No existe la operación original para notificar o consultar',
        'SIS0260': u'Entrada incorrecta al SIS',
        'SIS0261': u'Operación detenida por superar el control de restricciones en la entrada al SIS',
        'SIS0262': u'Moneda no permitida para operación de transferencia o domiciliación ',
        'SIS0263': u'Error calculando datos para procesar operación en su banca online',
        'SIS0264': u'Error procesando datos de respuesta recibidos desde su banca online',
        'SIS0265': u'Error de firma en los datos recibidos desde su banca online',
        'SIS0266': u'No se pueden recuperar los datos de la operación recibida desde su banca online',
        'SIS0267': u'La operación no se puede procesar por no existir Código Cuenta Cliente',
        'SIS0268': u'La operación no se puede procesar por este canal',
        'SIS0269': u'No se pueden realizar devoluciones de operaciones de domiciliación no descargadas',
        'SIS0270': u'El comercio no puede realizar preautorizaciones en diferido',
        'SIS0271': u'Error realizando pago-autenticación por WebService',
        'SIS0272': u'La operación a autorizar por WebService no se puede encontrar',
        'SIS0273': u'La operación a autorizar por WebService está en un estado incorrecto',
        'SIS0274': u'Tipo de operación desconocida o no permitida por esta entrada al SIS',
        'SIS0275': u'Error Premio: Premio sin IdPremio',
        'SIS0276': u'Error Premio: Unidades del Premio a redimir no numéricas.',
        'SIS0277': u'Error Premio: Error general en el proceso.',
        'SIS0278': u'Error Premio: Error en el proceso de consulta de premios',
        'SIS0279': u'Error Premio: El comercio no tiene activada la operativa de fidelización',
        'SIS0280': u'Reglas V3.0 : excepción por regla con Nivel de gestión usuario Interno.',
        'SIS0281': u'Reglas V3.0 : excepción por regla con Nivel de gestión usuario Entidad.',
        'SIS0282': u'Reglas V3.0 : excepción por regla con Nivel de gestión usuario Comercio/MultiComercio de una '
                   u'entidad.',
        'SIS0283': u'Reglas V3.0 : excepción por regla con Nivel de gestión usuario Comercio-Terminal.',
        'SIS0284': u'Pago Adicional: error no existe operación sobre la que realizar el PagoAdicional',
        'SIS0285': u'Pago Adicional: error tiene más de una operación sobre la que realizar el Pago Adicional',
        'SIS0286': u'Pago Adicional: La operación sobre la que se quiere hacer la operación adicional no está Aceptada',
        'SIS0287': u'Pago Adicional: la Operación ha sobrepasado el importe para el Pago Adicional.',
        'SIS0288': u'Pago Adicional: No se puede realizar otro pago Adicional. Se ha superado el número de pagos '
                   u'adicionales permitidos sobre la operación.',
        'SIS0289': u'Pago Adicional: El importe del pago Adicional supera el máximo días permitido.',
        'SIS0290': u'Control de Fraude: Bloqueo por control de Seguridad',
        'SIS0291': u'Control de Fraude: Bloqueo por lista Negra control de IP',
        'SIS0292': u'Control de Fraude: Bloqueo por lista Negra control de Tarjeta',
        'SIS0293': u'Control de Fraude: Bloqueo por Lista negra evaluación de Regla',
        'SIS0294': u'Tarjetas Privadas BBVA: La tarjeta no es Privada de BBVA (uno-e). No seadmite el envío de '
                   u'DS_MERCHANT_PAY_TYPE.',
        'SIS0295': u'Error de duplicidad de operación. Se puede intentar de nuevo',
        'SIS0296': u'Error al validar los datos de la Operación de Tarjeta en Archivo Inicial',
        'SIS0297': u'Número de operaciones sucesivas de Tarjeta en Archivo superado',
        'SIS0298': u'El comercio no permite realizar operaciones de Tarjeta en Archivo',
        'SIS0299': u'Error en la llamada a PayPal',
        'SIS0300': u'Error en los datos recibidos de PayPal',
        'SIS0301': u'Error en pago con PayPal',
        'SIS0302': u'Moneda no válida para pago con PayPal',
        'SIS0303': u'Esquema de la entidad es 4B',
        'SIS0304': u'No se permite pago fraccionado si la tarjeta no es de FINCONSUM',
        'SIS0305': u'No se permite pago fraccionado FINCONSUM en moneda diferente de euro',
        'SIS0306': u'Valor de Ds_Merchant_PrepaidCard no válido',
        'SIS0307': u'Operativa de tarjeta regalo no permitida',
        'SIS0308': u'Tiempo límite para recarga de tarjeta regalo superado',
        'SIS0309': u'Error faltan datos adicionales para realizar la recarga de tarjeta prepago',
        'SIS0310': u'Valor de Ds_Merchant_Prepaid_Expiry no válido',
        'SIS0311': u'Error al montar el mensaje para consulta de comisión en recarga de tarjeta prepago ',
        'SIS0312': u'Error en petición StartCheckoutSession con V.me',
        'SIS0313': u'Petición de compra mediante V.me no permitida',
        'SIS0314': u'Error en pago V.me',
        'SIS0315': u'Error analizando petición de autorización de V.me',
        'SIS0316': u'Error en petición de autorización de V.me',
        'SIS0317': u'Error montando respuesta a autorización de V.me',
        'SIS0318': u'Error en retorno del pago desde V.me',
        'SIS0319': u'El comercio no pertenece al grupo especificado en Ds_Merchant_Group',
        'SIS0321': u'El identificador indicado en Ds_Merchant_Identifier no está asociado al comercio',
        'SIS0322': u'Error de formato en Ds_Merchant_Group',
        'SIS0323': u'Para tipo de operación F es necesario el campo Ds_Merchant_Customer_Mobile o '
                   u'Ds_Merchant_Customer_Mail',
        'SIS0324': u'Para tipo de operación F. Imposible enviar link al titular',
        'SIS0325': u'Se ha pedido no mostrar pantallas pero no se ha enviado ningún identificador de tarjeta',
        'SIS0326': u'Se han enviado datos de tarjeta en fase primera de un pago con dos fases',
        'SIS0327': u'No se ha enviado ni móvil ni email en fase primera de un pago con dos fases',
        'SIS0328': u'Token de pago en dos fases inválido',
        'SIS0329': u'No se puede recuperar el registro en la tabla temporal de pago en dos fases',
        'SIS0330': u'Fechas incorrectas de pago dos fases',
        'SIS0331': u'La operación no tiene un estado válido o no existe.',
        'SIS0332': u'El importe de la operación original y de la devolución debe ser idéntico',
        'SIS0333': u'Error en una petición a MasterPass Wallet',
        'SIS0334': u'Bloqueo regla operativa grupos definidos por la entidad',
        'SIS0335': u'Ds_Merchant_Recharge_Commission no válido',
        'SIS0336': u'Error realizando petición de redirección a Oasys',
        'SIS0337': u'Error calculando datos de firma para redirección a Oasys',
        'SIS0338': u'No se encuentra la operación Oasys en la BD',
        'SIS0339': u'El comercio no dispone de pago Oasys',
        'SIS0340': u'Respuesta recibida desde Oasys no válida',
        'SIS0341': u'Error en la firma recibida desde Oasys',
        'SIS0342': u'El comercio no permite realizar operaciones de pago de tributos',
        'SIS0343': u'El parámetro Ds_Merchant_Tax_Reference falta o es incorrecto',
        'SIS0344': u'El usuario ha elegido aplazar el pago, pero no ha aceptado las condiciones de las cuotas',
        'SIS0345': u'El usuario ha elegido un número de plazos incorrecto',
        'SIS0346': u'Error de formato en parámetro DS_MERCHANT_PAY_TYPE',
        'SIS0347': u'El comercio no está configurado para realizar la consulta de BIN.',
        'SIS0348': u'El BIN indicado en la consulta no se reconoce',
        'SIS0349': u'Los datos de importe y DCC enviados no coinciden con los registrados en SIS',
        'SIS0350': u'No hay datos DCC registrados en SIS para este número de pedido',
        'SIS0351': u'Autenticación prepago incorrecta',
        'SIS0352': u'El tipo de firma del comercio no permite esta operativa',
        'SIS0353': u'El comercio no tiene definida una clave 3DES válida',
        'SIS0354': u'Error descifrando petición al SIS',
        'SIS0355': u'El comercio-terminal enviado en los datos cifrados no coincide con el enviado en la petición',
        'SIS0356': u'Existen datos de entrada para control de fraude y el comercio no tiene activo control de fraude',
        'SIS0357': u'Error en parametros enviados. El comercio tiene activo control de fraude y no existe campo '
                   u'ds_merchant_merchantscf',
        'SIS0358': u'La entidad no dispone de pago Oasys',
        'SIS0370': u'Error en formato Scf_Merchant_Nif. Longitud máxima 16',
        'SIS0371': u'Error en formato Scf_Merchant_Name. Longitud máxima 30',
        'SIS0372': u'Error en formato Scf_Merchant_First_Name. Longitud máxima 30 ',
        'SIS0373': u'Error en formato Scf_Merchant_Last_Name. Longitud máxima 30',
        'SIS0374': u'Error en formato Scf_Merchant_User. Longitud máxima 45',
        'SIS0375': u'Error en formato Scf_Affinity_Card. Valores posibles \'S\' o \'N\'. Longitud máxima 1',
        'SIS0376': u'Error en formato Scf_Payment_Financed. Valores posibles \'S\' o \'N\'. Longitud máxima 1',
        'SIS0377': u'Error en formato Scf_Ticket_Departure_Point. Longitud máxima 30',
        'SIS0378': u'Error en formato Scf_Ticket_Destination. Longitud máxima 30',
        'SIS0379': u'Error en formato Scf_Ticket_Departure_Date. Debe tener formato yyyyMMddHHmmss.',
        'SIS0380': u'Error en formato Scf_Ticket_Num_Passengers. Longitud máxima 1.',
        'SIS0381': u'Error en formato Scf_Passenger_Dni. Longitud máxima 16.',
        'SIS0382': u'Error en formato Scf_Passenger_Name. Longitud máxima 30.',
        'SIS0383': u'Error en formato Scf_Passenger_First_Name. Longitud máxima 30.',
        'SIS0384': u'Error en formato Scf_Passenger_Last_Name. Longitud máxima 30.',
        'SIS0385': u'Error en formato Scf_Passenger_Check_Luggage. Valores posibles \'S\' o \'N\'. Longitud máxima 1.',
        'SIS0386': u'Error en formato Scf_Passenger_Special_luggage. Valores posibles \'S\' o \'N\'. Longitud máxima '
                   u'1.',
        'SIS0387': u'Error en formato Scf_Passenger_Insurance_Trip. Valores posibles \'S\' o \'N\'. Longitud máxima 1.',
        'SIS0388': u'Error en formato Scf_Passenger_Type_Trip. Valores posibles \'N\' o \'I\'. Longitud máxima 1.',
        'SIS0389': u'Error en formato Scf_Passenger_Pet. Valores posibles \'S\' o \'N\'. Longitud máxima 1.',
        'SIS0390': u'Error en formato Scf_Order_Channel. Valores posibles \'M\'(móvil), \'P\'(PC) o \'T\'(Tablet)',
        'SIS0391': u'Error en formato Scf_Order_Total_Products. Debe tener formato numérico y longitud máxima de 3.',
        'SIS0392': u'Error en formato Scf_Order_Different_Products. Debe tener formato numérico y longitud máxima de '
                   u'3.',
        'SIS0393': u'Error en formato Scf_Order_Amount. Debe tener formato numérico y longitud máxima de 19.',
        'SIS0394': u'Error en formato Scf_Order_Max_Amount. Debe tener formato numérico y longitud máxima de 19.',
        'SIS0395': u'Error en formato Scf_Order_Coupon. Valores posibles \'S\' o \'N\'',
        'SIS0396': u'Error en formato Scf_Order_Show_Type. Debe longitud máxima de 30.',
        'SIS0397': u'Error en formato Scf_Wallet_Identifier',
        'SIS0398': u'Error en formato Scf_Wallet_Client_Identifier',
        'SIS0399': u'Error en formato Scf_Merchant_Ip_Address',
        'SIS0400': u'Error en formato Scf_Merchant_Proxy',
        'SIS0401': u'Error en formato Ds_Merchant_Mail_Phone_Number. Debe ser numérico y de longitud máxima 19',
        'SIS0402': u'Error en llamada a SafetyPay para solicitar token url',
        'SIS0403': u'Error en proceso de solicitud de token url a SafetyPay',
        'SIS0404': u'Error en una petición a SafetyPay',
        'SIS0405': u'Solicitud de token url denegada',
        'SIS0406': u'El sector del comercio no está permitido para realizar un pago de premio de apuesta',
        'SIS0407': u'El importe de la operación supera el máximo permitido para realizar un pago de premio de apuesta',
        'SIS0408': u'La tarjeta debe de haber operado durante el último año para poder realizar un pago de premio de '
                   u'apuesta',
        'SIS0409': u'La tarjeta debe ser una Visa o MasterCard nacional para realizar un pago de premio de apuesta',
        'SIS0410': u'Bloqueo por Operación con Tarjeta Privada del Cajamar, en comercio que no es de Cajamar',
        'SIS0411': u'No existe el comercio en la tabla de datos adicionales de RSI Directo',
        'SIS0412': u'La firma enviada por RSI Directo no es correcta',
        'SIS0413': u'La operación ha sido denegada por Lynx',
        'SIS0414': u'El plan de ventas no es correcto',
        'SIS0415': u'El tipo de producto no es correcto',
        'SIS0416': u'Importe no permitido en devolución ',
        'SIS0417': u'Fecha de devolución no permitida',
        'SIS0418': u'No existe plan de ventas vigente',
        'SIS0419': u'Tipo de cuenta no permitida',
        'SIS0420': u'El comercio no dispone de formas de pago para esta operación',
        'SIS0421': u'Tarjeta no permitida. No es producto Agro',
        'SIS0422': u'Faltan datos para operación Agro',
        'SIS0423': u'CNPJ del comercio incorrecto',
        'SIS0424': u'No se ha encontrado el establecimiento',
        'SIS0425': u'No se ha encontrado la tarjeta',
        'SIS0426': u'Enrutamiento no valido para comercio Corte Ingles.',
        'SIS0427': u'La conexión con CECA no ha sido posible para el comercio Corte Ingles.',
        'SIS0428': u'Operación debito no segura',
        'SIS0429': u'Error en la versión enviada por el comercio (Ds_SignatureVersion)',
        'SIS0430': u'Error al decodificar el parámetro Ds_MerchantParameters',
        'SIS0431': u'Error del objeto JSON que se envía codificado en el parámetro Ds_MerchantParameters',
        'SIS0432': u'Error FUC del comercio erróneo',
        'SIS0433': u'Error Terminal del comercio erróneo',
        'SIS0434': u'Error ausencia de número de pedido en la op. del comercio',
        'SIS0435': u'Error en el cálculo de la firma',
        'SIS0436': u'Error en la construcción del elemento padre <REQUEST>',
        'SIS0437': u'Error en la construcción del elemento <DS_SIGNATUREVERSION>',
        'SIS0438': u'Error en la construcción del elemento <DATOSENTRADA>',
        'SIS0439': u'Error en la construcción del elemento <DS_SIGNATURE>',
        'SIS0440': u'Error al crear pantalla MyBank',
        'SIS0441': u'Error no tenemos bancos para Mybank',
        'SIS0442': u'Error al realizar el pago Mybank',
        'SIS0443': u'No se permite pago en terminales ONEY con tarjetas ajenas',
        'SIS0445': u'Error gestionando referencias con Stratus',
        'SIS0444': u'Se está intentando acceder usando firmas antiguas y el comercio está configurado como HMAC SHA256',
        'SIS0446': u'Para terminales Oney es obligatorio indicar la forma de pago',
        'SIS0447': u'Error, se está utilizando una referencia que se generó con un adquirente distinto al adquirente '
                   u'que la utiliza.',
        'SIS0448': u'Error, la tarjeta de la operación es DINERS y el comercio no tiene el método de pago "Pago '
                   u'DINERS"',
        'SIS0449': u'Error, el tipo de pago de la operación es Tradicional(A), la tarjeta de la operación no es '
                   u'DINERS ni JCB ni AMEX y el comercio tiene el método de pago "Prohibir Pago A"',
        'SIS0450': u'Error, el tipo de pago de la operación es Tradicional(A), la tarjeta de la operación es AMEX y el '
                   u'comercio tiene los métodos de pago "Pago Amex y Prohibir Pago A AMEX"',
        'SIS0451': u'Error, la operación es Host to Host con tipo de pago Tradicional(A), la tarjeta de la operación '
                   u'no es DINERS ni JCB ni AMEX y el comercio tiene el método de pago "Prohibir Pago A"',
        'SIS0452': u'Error, la tarjeta de la operación es 4B y el comercio no tiene el método de pago "Tarjeta 4B"',
        'SIS0453': u'Error, la tarjeta de la operación es JCB y el comercio no tiene el método de pago "Pago JCB"',
        'SIS0454': u'Error, la tarjeta de la operación es AMEX y el comercio no tiene el método de pago "Pago Amex"',
        'SIS0455': u'Error, el comercio no tiene el método de pago "Tarjetas Propias" y la tarjeta no está registrada '
                   u'como propia. ',
        'SIS0456': u'Error, se aplica el método de pago "Verified By Visa" con Respuesta [VEReq, VERes] = U y el '
                   u'comercio no tiene los métodos de pago "Pago U y Pago U Nacional"',
        'SIS0457': u'Error, se aplica el método de pago "MasterCard SecureCode" con Respuesta [VEReq, VERes] = N con '
                   u'tarjeta MasterCard Comercial y el comercio no tiene el método de pago "MasterCard Comercial"',
        'SIS0458': u'Error, se aplica el método de pago "MasterCard SecureCode" con Respuesta [VEReq, VERes] = U con '
                   u'tarjeta MasterCard Comercial y el comercio no tiene el método de pago "MasterCard Comercial"',
        'SIS0459': u'Error, se aplica el método de pago "JCB Secure" con Respuesta [VEReq, VERes]= U y el comercio no '
                   u'tiene el método de pago "Pago JCB"',
        'SIS0460': u'Error, se aplica el método de pago "AMEX SafeKey" con Respuesta [VEReq, VERes] = N y el comercio '
                   u'no tiene el método de pago "Pago AMEX"',
        'SIS0461': u'Error, se aplica el método de pago "AMEX SafeKey" con Respuesta [VEReq, VERes] = U y el comercio '
                   u'no tiene el método de pago "Pago AMEX"',
        'SIS0462': u'Error, se aplica el método de pago "Verified By Visa","MasterCard SecureCode","JCB Secure" o '
                   u'"AMEX SafeKey" y la operación es Host To Host',
        'SIS0463': u'Error, se selecciona un método de pago que no está entre los permitidos por el SIS para ser '
                   u'ejecutado',
        'SIS0464': u'Error, el resultado de la autenticación 3DSecure es "NO_3DSECURE" con tarjeta MasterCard '
                   u'Comercial y el comercio no tiene el método de pago "MasterCard Comercial"',
        'SIS0465': u'Error, el resultado de la autenticación 3DSecure es "NO_3DSECURE", la tarjeta no es Visa, ni '
                   u'Amex, ni JCB, ni Master y el comercio no tiene el método de pago "Tradicional Mundial" ',
    }

    # El TPV de RedSys consta de dos entornos en funcionamiento, uno para pruebas y otro para producción
    REDSYS_URL = {
        'production': 'https://sis.redsys.es/sis/realizarPago',
        'testing': 'https://sis-t.redsys.es:25443/sis/realizarPago'
    }

    # Idiomas soportados por RedSys
    IDIOMAS = {'es': '001', 'en': '002', 'ca': '003', 'fr': '004', 'de': '005', 'pt': '009', 'it': '007'}

    # URL de pago que variará según el entorno
    url = None

    # Importe de la venta
    importe = None

    # Tipo de moneda usada en la operación, en este caso sera Euros
    tipo_moneda = "978"

    # Indica qué tipo de transacción se utiliza. Ver https://pagosonline.redsys.es/tipos-operacion.html
    #  0 - Pago normal ("Autorización")
    #  1 - Preautorización
    #  2 - Confirmación de preautorización
    #  3 - Devolución
    #  9 - Cancelación de preautorización
    transaction_type = None

    # Idioma por defecto a usar. Español
    idioma = IDIOMAS['es']

    # En modo SOAP, string con "<Request>...</Request>" completo. Es necesario para calcular la firma
    soap_request = None

    # Inicia el valor de la clave de cifrado en función del entorno
    def __init_encryption_key__(self):
        # Clave de cifrado según el entorno
        if self.parent.environment == 'testing':
            self.encryption_key = self.encryption_key_testing_sha256
        elif self.parent.environment == 'production':
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
        from ...forms import VPOSRedsysForm
        return VPOSRedsysForm

    ####################################################################
    ## Paso 1.1. Configuración del pago
    def configurePayment(self, **kwargs):
        # URL de pago según el entorno
        self.url = self.REDSYS_URL[self.parent.environment]

        # Configurar el tipo de transacción se utiliza, en función del parámetro enable_preauth-policy.
        if self.operative_type == PREAUTHORIZATION_TYPE:
            logger.info(u"Configuracion TPV en modo Pre-Autorizacion")
            self.transaction_type = '1'
        elif self.operative_type == AUTHORIZATION_TYPE:
            logger.info(u"Configuracion TPV en modo Autorizacion")
            self.transaction_type = '0'

        # Formato para Importe: según redsys, ha de tener un formato de entero positivo, con las dos últimas posiciones
        # ocupadas por los decimales
        self.importe = "{0:.2f}".format(float(self.parent.operation.amount)).replace('.', '')
        if self.importe == "000":
            self.importe = "0"

        # Idioma de la pasarela, por defecto es español, tomamos
        # el idioma actual y le asignamos éste
        self.idioma = self.IDIOMAS['es']
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
    # Paso 1.3. Obtiene los datos de pago
    # Este método será el que genere los campos del formulario de pago
    # que se rellenarán desde el cliente (por Javascript)
    def getPaymentFormData(self, reference_number=""):
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

        # En caso de que tenga referencia
        if reference_number:
            # Puede ser una petición de referencia
            if reference_number.lower() == 'request':
                order_data['DS_MERCHANT_IDENTIFIER'] = 'REQUIRED'
                if '?' in order_data['DS_MERCHANT_MERCHANTURL']:
                    order_data['DS_MERCHANT_MERCHANTURL'] += '&request_reference=1'
                else:
                    order_data['DS_MERCHANT_MERCHANTURL'] += '?request_reference=1'
            # o en cambio puede ser el envío de una referencia obtenida antes
            else:
                order_data['DS_MERCHANT_IDENTIFIER'] = reference_number

        json_order_data = json.dumps(order_data)
        packed_order_data = base64.b64encode(json_order_data)

        data = {
            'Ds_SignatureVersion': 'HMAC_SHA256_V1',
            'Ds_MerchantParameters': packed_order_data,
            'Ds_Signature': self._redsys_hmac_sha256_signature(packed_order_data)
        }

        form_data = {
            'data': data,
            'action': self.url,
            'enctype': 'application/x-www-form-urlencoded',
            'method': 'post'
        }

        return form_data

    ####################################################################
    # Paso 3.1. Obtiene el número de operación y los datos que nos
    # envíe la pasarela de pago.
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
    # Paso 3.1.a  Procesar notificación HTTP POST
    @staticmethod
    def _receiveConfirmationHTTPPOST(request):
        logger.info(u"Notificación Redsys HTTP POST:")
        logger.info(request.POST)

        # Almacén de operaciones
        try:
            operation_data = json.loads(base64.b64decode(request.POST.get('Ds_MerchantParameters')))
            logger.info(operation_data)

            # Operation number
            operation_number = operation_data.get('Ds_Order')

            ds_transactiontype = operation_data.get('Ds_TransactionType')
            if ds_transactiontype == '3':
                # Operación de reembolso
                operation = VPOSRefundOperation.objects.get(operation_number=operation_number)
            elif ds_transactiontype in ('0', '1'):
                # Operación de confirmación autorización / preautorización
                operation = VPOSPaymentOperation.objects.get(operation_number=operation_number)

                # Comprobar que no se trata de una operación de confirmación de compra anteriormente confirmada
                if operation.status != "pending":
                    raise VPOSOperationAlreadyConfirmed(u"Operación ya confirmada")

                operation.confirmation_data = {"GET": request.GET.dict(), "POST": request.POST.dict()}
                operation.confirmation_code = operation_number

                ds_errorcode = operation_data.get("Ds_ErrorCode")
                if ds_errorcode:
                    errormsg = u' // ' + VPOSRedsys._format_ds_error_code(operation_data.get("Ds_ErrorCode"))
                else:
                    errormsg = u''

                operation.response_code = VPOSRedsys._format_ds_response_code(
                    operation_data.get("Ds_Response")) + errormsg
                operation.save()
                logger.info(u"Operation {0} actualizada en _receiveConfirmationHTTPPOST()"
                            .format(operation.operation_number))
                logger.info(u"Ds_Response={0} Ds_ErrorCode={1}"
                            .format(operation_data.get('Ds_Response'), operation_data.get('Ds_ErrorCode')))
            else:
                raise VPOSOperationException(u"Ds_Transactiontype desconocido: {}".format(ds_transactiontype))

        except VPOSPaymentOperation.DoesNotExist:
            # Si no existe la operación, están intentando cargar una operación inexistente
            logger.info(u"No se ha encontrado VPOSPaymentOperation")
            return False

        except VPOSRefundOperation.DoesNotExist:
            # Si no existe la operación, están intentando cargar una operación inexistente
            logger.info(u"No se ha encontrado VPOSRefundOperation")
            return False

        # Iniciamos el delegado y la operación, esto es fundamental para luego calcular la firma
        vpos = operation.virtual_point_of_sale
        vpos._init_delegated()
        vpos.operation = operation

        # Iniciamos los valores recibidos en el delegado

        # Datos de la operación al completo
        # Usado para recuperar los datos la referencia
        vpos.delegated.ds_merchantparameters = operation_data

        ## Datos que llegan por POST
        # Firma enviada por RedSys, que más tarde compararemos con la generada por el comercio
        vpos.delegated.firma = request.POST.get('Ds_Signature')

        # Versión del método de firma utilizado
        vpos.delegated.signature_version = request.POST.get('Ds_SignatureVersion')

        # Parámetros de la operación (en base64 + JSON)
        vpos.delegated.merchant_parameters = request.POST.get('Ds_MerchantParameters')

        ## Datos decodificados de Ds_MerchantParameters
        # Respuesta de la pasarela de pagos. Indica si la operación se autoriza o no
        vpos.delegated.ds_response = operation_data.get('Ds_Response')

        return vpos.delegated

    ####################################################################
    ## Paso 3.1.b  Procesar notificación SOAP
    @staticmethod
    def _receiveConfirmationSOAP(request):
        logger.info(u"Notificación Redsys SOAP:")
        body = request.body
        logger.info(body)

        root = etree.fromstring(body)
        tree = etree.ElementTree(root)

        soapdict = dictlist(tree.getroot())

        # Aquí tendremos toda la cadena <Message>...</Message>
        xml_content = soapdict['{http://schemas.xmlsoap.org/soap/envelope/}Envelope']['value'][0][
            '{http://schemas.xmlsoap.org/soap/envelope/}Body']['value'][0]['{InotificacionSIS}procesaNotificacionSIS'][
            'value'][0]['XML']['value']

        # procesar <Message>...</Message>
        logger.info(u"Mensaje XML completo:" + xml_content)
        root = etree.fromstring(xml_content)

        # Almacén de operaciones
        try:
            ds_order = root.xpath('//Message/Request/Ds_Order/text()')[0]
            ds_response = root.xpath('//Message/Request/Ds_Response/text()')[0]
            ds_transactiontype = root.xpath('//Message/Request/Ds_TransactionType/text()')[0]

            try:
                ds_authorisationcode = root.xpath('//Message/Request/Ds_AuthorisationCode/text()')[0]
            except IndexError:
                logger.info(u"Ds_Order {0} sin Ds_AuthorisationCode (Ds_response={1})".format(ds_order, ds_response))
                ds_authorisationcode = ""

            try:
                ds_errorcode = root.xpath('//Message/Request/Ds_ErrorCode/text()')[0]
                errormsg = u' // ' + VPOSRedsys._format_ds_error_code(ds_errorcode)
            except IndexError:
                ds_errorcode = None
                errormsg = u''

            if ds_transactiontype == '3':
                # Operación de reembolso
                operation = VPOSRefundOperation.objects.get(operation_number=ds_order)
            elif ds_transactiontype in ('0', '1'):
                # Operación de confirmación autorización / preautorización
                operation = VPOSPaymentOperation.objects.get(operation_number=ds_order)

                if operation.status != 'pending':
                    raise VPOSOperationAlreadyConfirmed(u"Operación ya confirmada")

                operation.confirmation_data = {'GET': '', 'POST': xml_content}
                operation.confirmation_code = ds_order
                operation.response_code = VPOSRedsys._format_ds_response_code(ds_response) + errormsg
                operation.save()
                logger.info(u"Operation {0} actualizada en _receiveConfirmationSOAP()"
                            .format(operation.operation_number))
                logger.info(u"Ds_Response={0} Ds_ErrorCode={1}".format(ds_response, ds_errorcode))
            else:
                raise VPOSOperationException(u"Ds_Transactiontype desconocido: {}".format(ds_transactiontype))

        except VPOSPaymentOperation.DoesNotExist:
            # Si no existe la operación, están intentando cargar una operación inexistente
            logger.info(u"No se ha encontrado VPOSPaymentOperation")
            return False

        except VPOSRefundOperation.DoesNotExist:
            # Si no existe la operación, están intentando cargar una operación inexistente
            logger.info(u"No se ha encontrado VPOSRefundOperation")
            return False

        # Iniciamos el delegado y la operación, esto es fundamental
        # para luego calcular la firma
        vpos = operation.virtual_point_of_sale
        vpos._init_delegated()
        vpos.operation = operation

        # Iniciamos los valores recibidos en el delegado

        # Contenido completo de <Request>...</Request>, necesario posteriormente para cálculo de firma
        # soap_request = etree.tostring(root.xpath("//Message/Request")[0])
        # corrige autocierre de etuqueta y entrecomillado de atributos. Para la comprobación de la firma,
        # la etiqueta debe tener apertura y cierre y el atributo va entre comilla simple
        # soap_request = soap_request\
        #     .replace("<Ds_MerchantData/>", "<Ds_MerchantData></Ds_MerchantData>", 1)\
        #     .replace('"',"'")

        regex = r"<Request.+</Request>"
        matches = re.search(regex, xml_content, re.MULTILINE)
        soap_request = matches.group(0)

        vpos.delegated.soap_request = soap_request
        logger.info(u"Request:" + vpos.delegated.soap_request)

        # Firma enviada por RedSys, que más tarde compararemos con la generada por el comercio
        vpos.delegated.firma = root.xpath('//Message/Signature/text()')[0]
        logger.info(u"Signature:" + vpos.delegated.firma)

        # Código que indica el tipo de transacción
        vpos.delegated.ds_response = root.xpath('//Message/Request/Ds_Response/text()')[0]

        # Usado para recuperar los datos la referencia
        vpos.delegated.ds_merchantparameters = {}
        try:
            vpos.delegated.ds_merchantparameters['Ds_Merchant_Identifier'] = \
            root.xpath('//Message/Request/Ds_Merchant_Identifier/text()')[0]
            vpos.delegated.ds_merchantparameters['Ds_ExpiryDate'] = \
            root.xpath('//Message/Request/Ds_ExpiryDate/text()')[0]
            # Aquí la idea es incluir más parámetros que nos puedan servir en el llamador de este módulo
        except IndexError:
            pass

        return vpos.delegated

    ####################################################################
    ## Paso 3.2. Verifica que los datos enviados desde
    ## la pasarela de pago identifiquen a una operación de compra y un
    ## pago autorizado.
    def verifyConfirmation(self):
        firma_calculada = self._verification_signature()
        logger.info("Firma calculada " + firma_calculada)
        logger.info("Firma recibida " + self.firma)

        # Traducir caracteres de la firma recibida '-' y '_' al alfabeto base64
        firma_traducida = self.firma.replace("-", "+").replace("_", "/")
        if self.firma != firma_traducida:
            logger.info("Firma traducida " + firma_traducida)

        # Comprueba si el envío es correcto
        if firma_traducida != firma_calculada:
            logger.info("Las firmas no coinciden")
            return False
        else:
            logger.info("Firma verificada correctamente")

        # Comprobar que el resultado se corresponde a un pago autorizado
        # por RedSys. Los pagos autorizados son todos los Ds_Response entre
        # 0000 y 0099 [manual TPV Virtual SIS v1.0, pág. 31]
        if len(self.ds_response) != 4 or not self.ds_response.isdigit():
            logger.info(u"Transacción no autorizada por RedSys. Ds_Response es {0} (no está entre 0000-0099)".format(
                self.ds_response))
            return False
        elif self.ds_response[:2] != "00":
            logger.info(u"Transacción no autorizada por RedSys. Ds_Response es {0} (no está entre 0000-0099)".format(
                self.ds_response))
            return False

        return True

    ####################################################################
    ## Paso 3.3a. Realiza el cobro y genera la respuesta a la pasarela y
    ## comunicamos con la pasarela de pago para que marque la operación
    ## como pagada. Sólo se usa en CECA
    def charge(self):
        # En caso de tener habilitada la preautorización
        # no nos importa el tipo de confirmación.
        if self.operative_type == PREAUTHORIZATION_TYPE:
            # Cuando se tiene habilitada política de preautorización.
            logger.info("Confirmar mediante política de preautorizacion")
            if self._confirm_preauthorization():
                return HttpResponse("OK")
            else:
                return self.responseNok()

        # En otro caso la confirmación continua haciendose como antes.
        # Sin cambiar nada.
        elif self.soap_request:
            logger.info("responseOk SOAP")
            # Respuesta a notificación HTTP SOAP
            response = '<Response Ds_Version="0.0"><Ds_Response_Merchant>OK</Ds_Response_Merchant></Response>'

            logger.info("FIRMAR RESPUESTA {response} CON CLAVE DE CIFRADO {key}".format(response=response,
                                                                                    key=self.encryption_key))
            signature = self._redsys_hmac_sha256_signature(response)

            message = "<Message>{response}<Signature>{signature}</Signature></Message>".format(response=response,
                                                                                               signature=signature)
            logger.info("MENSAJE RESPUESTA CON FIRMA {0}".format(message))

            # El siguiente mensaje NO debe tener espacios en blanco ni saltos de línea entre las marcas XML
            out = "<?xml version='1.0' encoding='UTF-8'?><SOAP-ENV:Envelope xmlns:SOAP-ENV=\"http://schemas.xmlsoap.org/soap/envelope/\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xmlns:xsd=\"http://www.w3.org/2001/XMLSchema\"><SOAP-ENV:Body><ns1:procesaNotificacionSISResponse xmlns:ns1=\"InotificacionSIS\" SOAP-ENV:encodingStyle=\"http://schemas.xmlsoap.org/soap/encoding/\"><result xsi:type=\"xsd:string\">{0}</result></ns1:procesaNotificacionSISResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>"
            out = out.format(cgi.escape(message))
            logger.info("RESPUESTA SOAP:" + out)

            return HttpResponse(out, "text/xml")

        else:
            logger.info(u"responseOk HTTP POST (respuesta vacía)")
            # Respuesta a notificación HTTP POST
            # En RedSys no se exige una respuesta, por parte del comercio, para verificar
            # la operación, pasamos una respuesta vacia
            return HttpResponse("")

    ####################################################################
    ## Paso 3.3b. Si ha habido un error en el pago, se ha de dar una
    ## respuesta negativa a la pasarela bancaria.
    def responseNok(self, **kwargs):

        if self.operative_type == PREAUTHORIZATION_TYPE:
            # Cuando se tiene habilitada política de preautorización.
            logger.info("Enviar mensaje para cancelar una preautorizacion")
            self._cancel_preauthorization()
            return HttpResponse("")

        elif self.soap_request:
            logger.info("responseNok SOAP")
            # Respuesta a notificación HTTP SOAP
            response = '<Response Ds_Version="0.0"><Ds_Response_Merchant>KO</Ds_Response_Merchant></Response>'

            logger.info("FIRMAR RESPUESTA {response} CON CLAVE DE CIFRADO {key}".format(response=response,
                                                                                    key=self.encryption_key))
            signature = self._redsys_hmac_sha256_signature(response)

            message = "<Message>{response}<Signature>{signature}</Signature></Message>".format(response=response,
                                                                                               signature=signature)
            logger.info("MENSAJE RESPUESTA CON FIRMA {0}".format(message))

            # El siguiente mensaje NO debe tener espacios en blanco ni saltos de línea entre las marcas XML
            out = "<?xml version='1.0' encoding='UTF-8'?><SOAP-ENV:Envelope xmlns:SOAP-ENV=\"http://schemas.xmlsoap.org/soap/envelope/\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xmlns:xsd=\"http://www.w3.org/2001/XMLSchema\"><SOAP-ENV:Body><ns1:procesaNotificacionSISResponse xmlns:ns1=\"InotificacionSIS\" SOAP-ENV:encodingStyle=\"http://schemas.xmlsoap.org/soap/encoding/\"><result xsi:type=\"xsd:string\">{0}</result></ns1:procesaNotificacionSISResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>"
            out = out.format(cgi.escape(message))
            logger.info("RESPUESTA SOAP:" + out)

            return HttpResponse(out, 'text/xml')

        else:
            logger.info(u"responseNok HTTP POST (respuesta vacía)")
            # Respuesta a notificación HTTP POST
            # En RedSys no se exige una respuesta, por parte del comercio, para verificar
            # que la operación ha sido negativa, pasamos una respuesta vacia
            return HttpResponse("")

    ####################################################################
    ## Paso R1 (Refund) Configura el TPV en modo devolución y ejecuta la operación
    def refund(self, operation_sale_code, refund_amount, description):

        """
        Implementación particular del mátodo de devolución para el TPV de Redsys.
        Se ocupa de preparar un mensaje http con los parámetros adecuados.
        Realizar la comunicación con los parámetros dados y la codificación necesaria.
        Interpretar la respuesta HTML, buscando etiquetas DOM que informen si la operación
        se realiza correctamente o con error.

        NOTA IMPORTANTE: La busqueda de etiquetas en el arbol DOM es sensible a posibles cambios en la plataforma Redsys,
        por lo tanto en caso de no encontrar ninguna etiqueta de las posibles esperadas
        (noSePuedeRealizarOperacion o operacionAceptada), se lanza una excepción del tipo 'VPOSOperationException'.

        Es responsibilidad del programador gestionar adecuadamente esta excepción desde la vista
        y en caso que se produzca, avisar a los desarrolladores responsables del módulo 'DjangoVirtualPost'
        para su actualización.

        :param refund_amount: Cantidad de la devolución.
        :param description: Motivo o comentario de la devolución.
        :return: True | False según se complete la operación con éxito.
        """

        # Modificamos el tipo de operación para indicar que la transacción
        # es de tipo devolución automática.
        # URL de pago según el entorno.

        self.url = self.REDSYS_URL[self.parent.environment]

        # IMPORTANTE: Este es el código de operación para hacer devoluciones.
        self.transaction_type = 3

        # Formato para Importe: según redsys, ha de tener un formato de entero positivo, con las dos últimas posiciones
        # ocupadas por los decimales
        self.importe = "{0:.2f}".format(float(refund_amount)).replace(".", "")

        # Idioma de la pasarela, por defecto es español, tomamos
        # el idioma actual y le asignamos éste
        self.idioma = self.IDIOMAS["es"]
        lang = translation.get_language()
        if lang in self.IDIOMAS:
            self.idioma = self.IDIOMAS[lang]

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
            "DS_MERCHANT_URLOK": self.parent.operation.payment.url_ok,

            # URL a la que se redirige al usuario en caso de que la venta NO haya sido satisfactoria
            "DS_MERCHANT_URLKO": self.parent.operation.payment.url_nok,

            # Se mostrará al titular en la pantalla de confirmación de la compra
            "DS_MERCHANT_PRODUCTDESCRIPTION": description,

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

        headers = {'enctype': 'application/x-www-form-urlencoded'}

        # Realizamos petición POST con los datos de la operación y las cabeceras necesarias.
        refund_html_request = requests.post(self.url, data=data, headers=headers)

        # En caso de tener una respuesta 200
        if refund_html_request.status_code == 200:

            # Iniciamos un objeto BeautifulSoup (para poder leer los elementos del DOM del HTML recibido).
            html = BeautifulSoup(refund_html_request.text, "html.parser")

            # Buscamos elementos significativos del DOM que nos indiquen si la operación se ha realizado correctamente o no.
            refund_message_error = html.find('text', {'lngid': 'noSePuedeRealizarOperacion'})
            refund_message_ok = html.find('text', {'lngid': 'operacionAceptada'})

            # Cuando en el DOM del documento HTML aparece un mensaje de error.
            if refund_message_error:
                logger.info(refund_message_error)
                logger.info(u'Error realizando la operación')
                status = False

            # Cuando en el DOM del documento HTML aparece un mensaje de ok.
            elif refund_message_ok:
                logger.info(u'Operación realizada correctamente')
                logger.info(refund_message_error)
                status = True

            # No aparece mensaje de error ni de ok
            else:
                raise VPOSOperationException("La resupuesta HTML con la pantalla de devolución "
                                             "no muestra mensaje informado de forma expícita "
                                             "si la operación se produce con éxito o error. Revisar método 'VPOSRedsys.refund'.")

        # Respuesta HTTP diferente a 200
        else:
            status = False

        return status

    ####################################################################
    ## Paso R2.a. Respuesta positiva a confirmación asíncrona de refund
    def refund_response_ok(self, extended_status=""):
        if self.soap_request:
            logger.info("refund_response_ok SOAP")
            # Respuesta a notificación HTTP SOAP
            response = '<Response Ds_Version="0.0"><Ds_Response_Merchant>OK</Ds_Response_Merchant></Response>'

            logger.info("FIRMAR RESPUESTA {response} CON CLAVE DE CIFRADO {key}".format(response=response,
                                                                                    key=self.encryption_key))
            signature = self._redsys_hmac_sha256_signature(response)

            message = "<Message>{response}<Signature>{signature}</Signature></Message>".format(response=response,
                                                                                               signature=signature)
            logger.info("MENSAJE RESPUESTA CON FIRMA {0}".format(message))

            # El siguiente mensaje NO debe tener espacios en blanco ni saltos de línea entre las marcas XML
            out = "<?xml version='1.0' encoding='UTF-8'?><SOAP-ENV:Envelope xmlns:SOAP-ENV=\"http://schemas.xmlsoap.org/soap/envelope/\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xmlns:xsd=\"http://www.w3.org/2001/XMLSchema\"><SOAP-ENV:Body><ns1:procesaNotificacionSISResponse xmlns:ns1=\"InotificacionSIS\" SOAP-ENV:encodingStyle=\"http://schemas.xmlsoap.org/soap/encoding/\"><result xsi:type=\"xsd:string\">{0}</result></ns1:procesaNotificacionSISResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>"
            out = out.format(cgi.escape(message))
            logger.info("RESPUESTA SOAP:" + out)

            return HttpResponse(out, "text/xml")

        else:
            logger.info(u"refund_response_ok HTTP POST (respuesta vacía)")
            # Respuesta a notificación HTTP POST
            # En RedSys no se exige una respuesta, por parte del comercio, para verificar
            # la operación, pasamos una respuesta vacia
            return HttpResponse("")

    ####################################################################
    ## Paso R2.b. Respuesta negativa a confirmación asíncrona de refund
    def refund_response_nok(self, extended_status=""):

        if self.soap_request:
            logger.info("refund_response_nok SOAP")
            # Respuesta a notificación HTTP SOAP
            response = '<Response Ds_Version="0.0"><Ds_Response_Merchant>KO</Ds_Response_Merchant></Response>'

            logger.info("FIRMAR RESPUESTA {response} CON CLAVE DE CIFRADO {key}".format(response=response,
                                                                                    key=self.encryption_key))
            signature = self._redsys_hmac_sha256_signature(response)

            message = "<Message>{response}<Signature>{signature}</Signature></Message>".format(response=response,
                                                                                               signature=signature)
            logger.info("MENSAJE RESPUESTA CON FIRMA {0}".format(message))

            # El siguiente mensaje NO debe tener espacios en blanco ni saltos de línea entre las marcas XML
            out = "<?xml version='1.0' encoding='UTF-8'?><SOAP-ENV:Envelope xmlns:SOAP-ENV=\"http://schemas.xmlsoap.org/soap/envelope/\" xmlns:xsi=\"http://www.w3.org/2001/XMLSchema-instance\" xmlns:xsd=\"http://www.w3.org/2001/XMLSchema\"><SOAP-ENV:Body><ns1:procesaNotificacionSISResponse xmlns:ns1=\"InotificacionSIS\" SOAP-ENV:encodingStyle=\"http://schemas.xmlsoap.org/soap/encoding/\"><result xsi:type=\"xsd:string\">{0}</result></ns1:procesaNotificacionSISResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>"
            out = out.format(cgi.escape(message))
            logger.info("RESPUESTA SOAP:" + out)

            return HttpResponse(out, "text/xml")

        else:
            logger.info(u"refund_response_nok HTTP POST (respuesta vacía)")
            # Respuesta a notificación HTTP POST
            # En RedSys no se exige una respuesta, por parte del comercio, para verificar
            # que la operación ha sido negativa, pasamos una respuesta vacia
            return HttpResponse("")

    def _confirm_preauthorization(self):

        """
        Realiza petición HTTP POST con los parámetros adecuados para
        confirmar una operación de pre-autorización.
        NOTA: La respuesta de esta petición es un HTML, aplicamos scraping
        para asegurarnos que corresponde a una pantalla de éxito.
        NOTA2: Si el HTML anterior no proporciona información de éxito o error. Lanza una excepción.
        :return: status: Bool
        """

        logger.info("Entra en confirmacion de pre-autorizacion")

        # URL de pago según el entorno
        self.url = self.REDSYS_URL[self.parent.environment]

        # IMPORTANTE: Este es el código de operación para hacer confirmación de preautorización.
        self.transaction_type = 2

        # Idioma de la pasarela, por defecto es español, tomamos
        # el idioma actual y le asignamos éste
        self.idioma = self.IDIOMAS["es"]
        lang = translation.get_language()
        if lang in self.IDIOMAS:
            self.idioma = self.IDIOMAS[lang]

        self.importe = "{0:.2f}".format(float(self.parent.operation.amount)).replace(".", "")
        if self.importe == "000":
            self.importe = "0"

        order_data = {
            # Indica el importe de la venta
            'DS_MERCHANT_AMOUNT': self.importe,

            # Indica el número de operacion
            'DS_MERCHANT_ORDER': self.parent.operation.operation_number,

            # Código FUC asignado al comercio
            'DS_MERCHANT_MERCHANTCODE': self.merchant_code,

            # Indica el tipo de moneda a usar
            'DS_MERCHANT_CURRENCY': self.tipo_moneda,

            # Indica que tipo de transacción se utiliza
            'DS_MERCHANT_TRANSACTIONTYPE': self.transaction_type,

            # Indica el terminal
            'DS_MERCHANT_TERMINAL': self.terminal_id,
        }

        json_order_data = json.dumps(order_data)
        packed_order_data = base64.b64encode(json_order_data)

        logger.info(json_order_data)

        data = {
            'Ds_SignatureVersion': "HMAC_SHA256_V1",
            'Ds_MerchantParameters': packed_order_data,
            'Ds_Signature': self._redsys_hmac_sha256_signature(packed_order_data)
        }

        headers = {'enctype': 'application/x-www-form-urlencoded'}

        # Realizamos petición POST con los datos de la operación y las cabeceras necesarias.
        confirmpreauth_html_request = requests.post(self.url, data=data, headers=headers)

        if confirmpreauth_html_request.status_code == 200:
            logger.info("_confirm_preauthorization status_code 200")

            # Iniciamos un objeto BeautifulSoup (para poder leer los elementos del DOM del HTML recibido).
            request_text = confirmpreauth_html_request.text
            logger.info(request_text)
            html = BeautifulSoup(request_text, "html.parser")

            # Buscamos elementos significativos del DOM que nos indiquen si la operación se ha realizado correctamente
            # o no.
            confirmpreauth_message_error = html.find('text', {'lngid': 'noSePuedeRealizarOperacion'})
            confirmpreauth_message_ok = html.find('text', {'lngid': 'operacionAceptada'})

            # Cuando en el DOM del documento HTML aparece un mensaje de error.
            if confirmpreauth_message_error:
                logger.info(confirmpreauth_message_error)
                logger.info(u'Error realizando la operación')
                status = False

            # Cuando en el DOM del documento HTML aparece un mensaje de ok.
            elif confirmpreauth_message_ok:
                logger.info(u'Operación realizada correctamente')
                logger.info(confirmpreauth_message_ok)
                status = True

            # No aparece mensaje de error ni de ok
            else:
                raise VPOSOperationException(
                    u"La resupuesta HTML con la pantalla de confirmación no muestra mensaje informado de forma "
                    u"explícita indicando si la operación se ha producido con éxito o error, revisar método "
                    u"'VPOSRedsys._confirm_preauthorization'")

        # Respuesta HTTP diferente a 200
        else:
            status = False

        return status

    def _cancel_preauthorization(self):
        """
        Realiza petición HTTP POST con los parámetros adecuados para
        anular una operación de pre-autorización.
        NOTA: La respuesta de esta petición es un HTML, aplicamos scraping
        para asegurarnos que corresponde a una pantalla de éxito.
        NOTA2: Si el HTML anterior no proporciona información de éxito o error. Lanza una excepción.
        :return: status: Bool
        """

        logger.info("Entra en cancelacion de pre-autorizacion")

        # URL de pago según el entorno
        self.url = self.REDSYS_URL[self.parent.environment]

        # IMPORTANTE: Este es el código de operación para hacer cancelación de preautorizacon.
        self.transaction_type = 9

        # Idioma de la pasarela, por defecto es español, tomamos
        # el idioma actual y le asignamos éste
        self.idioma = self.IDIOMAS["es"]
        lang = translation.get_language()
        if lang in self.IDIOMAS:
            self.idioma = self.IDIOMAS[lang]

        self.importe = "{0:.2f}".format(float(self.parent.operation.amount)).replace(".", "")
        if self.importe == "000":
            self.importe = "0"

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
            "DS_MERCHANT_SUMTOTAL": self.importe
        }

        json_order_data = json.dumps(order_data)

        logger.info(json_order_data)

        packed_order_data = base64.b64encode(json_order_data)

        data = {
            "Ds_SignatureVersion": "HMAC_SHA256_V1",
            "Ds_MerchantParameters": packed_order_data,
            "Ds_Signature": self._redsys_hmac_sha256_signature(packed_order_data)
        }

        headers = {'enctype': 'application/x-www-form-urlencoded'}

        # Realizamos petición POST con los datos de la operación y las cabeceras necesarias.
        confirmpreauth_html_request = requests.post(self.url, data=data, headers=headers)

        if confirmpreauth_html_request.status_code == 200:

            # Iniciamos un objeto BeautifulSoup (para poder leer los elementos del DOM del HTML recibido).
            html = BeautifulSoup(confirmpreauth_html_request.text, "html.parser")

            # Buscamos elementos significativos del DOM que nos indiquen si la operación se ha realizado correctamente o no.
            confirmpreauth_message_error = html.find('text', {'lngid': 'noSePuedeRealizarOperacion'})
            confirmpreauth_message_ok = html.find('text', {'lngid': 'operacionAceptada'})

            # Cuando en el DOM del documento HTML aparece un mensaje de error.
            if confirmpreauth_message_error:
                logger.info(confirmpreauth_message_error)
                logger.info(u'Error realizando la operación')
                status = False

            # Cuando en el DOM del documento HTML aparece un mensaje de ok.
            elif confirmpreauth_message_ok:
                logger.info(u'Operación realizada correctamente')
                logger.info(confirmpreauth_message_ok)
                status = True

            # No aparece mensaje de error ni de ok
            else:
                raise VPOSOperationException(
                    "La resupuesta HTML con la pantalla de cancelación no muestra mensaje informado de forma expícita,"
                    " si la operación se produce con éxito/error, (revisar método 'VPOSRedsys._cancel_preauthorization').")

        # Respuesta HTTP diferente a 200
        else:
            status = False

        return status

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
        logger.info("_redsys_hmac_sha256_signature: encryption key {0}".format(self.encryption_key))

        # Decodificar firma
        encryption_key = base64.b64decode(self.encryption_key)

        # operation_number = bytes(self.parent.operation.operation_number)
        operation_number = bytes(self.parent.operation.operation_number)
        logger.info("_redsys_hmac_sha256_signature: operation_number {0}".format(operation_number))

        # Rellenar cadena hasta múltiplo de 8 bytes
        if len(operation_number) % 8 != 0:
            logger.info(u"_redsys_hmac_sha256_signature: la longitud del operation number es {0} y necesita relleno "
                        u"para 3DES".format(len(operation_number)))
            operation_number += bytes("\x00") * (8 - len(self.parent.operation.operation_number) % 8)
            logger.info(u"_redsys_hmac_sha256_signature: la longitud de la cadena rellenada para 3DES es de {0}"
                .format(len(operation_number)))

        # Generar clave de firma con 3DES y IV igual a ocho bytes con cero
        des3_obj = DES3.new(encryption_key, DES3.MODE_CBC, b"\x00" * 8)
        signature_key = des3_obj.encrypt(operation_number)

        # Generar firma HMAC SHA-256 del mensaje.
        hash_obj = HMAC.new(key=signature_key, msg=data, digestmod=SHA256)
        digest = hash_obj.digest()

        # Devolver firma codificada en Base64
        signature = base64.b64encode(digest)
        logger.info("Firma: {0}".format(signature))
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
            logger.info(u"Comprobación de firma para SOAP con clave de cifrado " + self.encryption_key)
            signature = self._redsys_hmac_sha256_signature(self.soap_request)
        else:
            ## Cálculo de firma para confirmación HTTP POST:
            logger.info(u"Comprobación de firma para HTTP POST con clave de cifrado " + self.encryption_key)
            signature = self._redsys_hmac_sha256_signature(self.merchant_parameters)

        logger.info("FIRMA {0}".format(signature))
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
            message = VPOSRedsys.DS_RESPONSE_CODES.get(ds_response, u"código de respuesta Ds_Response desconocido")

        out = u"{0}. {1}".format(ds_response, message)

        return out

    @staticmethod
    def _format_ds_error_code(ds_errorcode):
        """
        Formatea el mensaje asociado a un Ds_ErrorCode
        :param ds_errorcode: str  código Ds_ErrorCode
        :return: unicode  mensaje formateado
        """

        if not ds_errorcode:
            return ''

        message = VPOSRedsys.DS_ERROR_CODES.get(ds_errorcode, u'Código de respuesta Ds_ErrorCode desconocido')
        out = u"{0}. {1}".format(ds_errorcode, message)

        return out
