# coding=utf-8
from decimal import Decimal

from django.core.exceptions import ObjectDoesNotExist
from django.db import models

from .defs import VPOS_TYPES, VIRTUALPOS_STATE_TYPES
from ..debug import dlprint
from .util import get_delegated_class
from .vpos_refund_operation import VPOSRefundOperation
from .vpos_payment_operation import VPOSPaymentOperation


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
        if type(amount) != float or amount < 0.0:
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
    def getPaymentFormData(self, *args, **kwargs):
        if self.operation.operation_number is None:
            raise Exception(u"No se ha generado el número de operación, ¿ha llamado a vpos.setupPayment antes?")
        data = self.delegated.getPaymentFormData(*args, **kwargs)
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

    ####################################################################
    ## Paso R1 (Refund) Configura el TPV en modo devolución y ejecuta la operación
    ## TODO: Se implementa solo para Redsys
    def refund(self, operation_sale_code, refund_amount, description):
        """
        1. Realiza las comprobaciones necesarias, para determinar si la operación es permitida,
           (en caso contrario se lanzan las correspondientes excepciones).
        2. Crea un objeto VPOSRefundOperation (con estado pendiente).
        3. Llama al delegado, que implementa las particularidades para la comunicación con el TPV concreto.
        4. Actualiza el estado del pago, según se encuentra 'parcialmente devuelto' o 'totalmente devuelto'.
        5. Actualiza el estado de la devolución a 'completada' o 'fallada'.

        @param operation_sale_code: Código del pago que pretendemos reembolsar.
        @param refund_amount: Cantidad del pago que reembolsamos
        @param description: Descripción del motivo por el cual se realiza la devolución.
        """

        try:
            # Cargamos la operación sobre la que vamos a realizar la devolución.
            payment_operation = VPOSPaymentOperation.objects.get(sale_code=operation_sale_code, status='completed')
        except ObjectDoesNotExist:
            raise Exception(u"No se puede cargar una operación anterior completada con el código"
                            u" {0}".format(operation_sale_code))

        if (not self.has_total_refunds) and (not self.has_partial_refunds):
            raise Exception(u"El TPV no admite devoluciones, ni totales, ni parciales")

        if refund_amount > payment_operation.amount:
            raise Exception(u"Imposible reembolsar una cantidad superior a la del pago")

        if (refund_amount < payment_operation.amount) and (not self.has_partial_refunds):
            raise Exception(u"Configuración del TPV no permite realizar devoluciones parciales")

        if (refund_amount == payment_operation.amount) and (not self.has_total_refunds):
            raise Exception(u"Configuración del TPV no permite realizar devoluciones totales")

        # Creamos la operación, marcandola como pendiente.
        self.operation = VPOSRefundOperation(amount=refund_amount,
                                             description=description,
                                             operation_number=payment_operation.operation_number,
                                             status='pending',
                                             payment=payment_operation)

        self.operation.save()

        # Llamamos al delegado que implementa la funcionalidad en particular.
        refund_response = self.delegated.refund(operation_sale_code, refund_amount, description)

        if refund_response:
            refund_status = 'completed'
        else:
            refund_status = 'failed'

        self.operation.status = refund_status
        self.operation.save()

        # Calcula el nuevo estado del pago, en función de la suma de las devoluciones,
        # (pudiendolo marcas como "completely_refunded" o "partially_refunded").
        payment_operation.compute_payment_refunded_status()

        return refund_response

    ####################################################################
    ## Paso R2.a. Respuesta positiva a confirmación asíncrona de refund
    def refund_response_ok(self, extended_status=""):
        dlprint("vpos.refund_response_ok")
        return self.delegated.refund_response_ok()

    ####################################################################
    ## Paso R2.b. Respuesta negativa a confirmación asíncrona de refund
    def refund_response_nok(self, extended_status=""):
        dlprint("vpos.refund_response_nok")
        return self.delegated.refund_response_nok()


