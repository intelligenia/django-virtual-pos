# coding=utf-8
from django.utils.translation import ugettext_lazy as _


def get_delegated_class(virtualpos_type):
    """
    Obtiene la clase delegada a partir del tipo de TPV. La clase delegada ha de estar definida en el
    diccionario TPV_CLASSES en vpos.models.
    :param virtualpos_type:
    :return:
    """
    try:
        # carga el módulo "models"
        module = __import__('.'.join(__name__.split('.')[:-1]), globals(), locals(), ["models"])

        # getattr obtiene un atributo de un objeto, luego sacamos el
        # objeto clase a partir de su nombre y del objeto módulo "vpos.models"
        cls = getattr(module, VPOS_CLASSES[virtualpos_type])
        return cls
    except KeyError:
        raise ValueError(_(u"The virtual point of sale {0} does not exist").format(virtualpos_type))


VPOS_CLASSES = {
    "ceca": "VPOSCeca",
    "redsys": "VPOSRedsys",
    "paypal": "VPOSPaypal",
    "santanderelavon": "VPOSSantanderElavon",
    "bitpay": "VPOSBitpay",
}