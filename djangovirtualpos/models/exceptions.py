# coding=utf-8
class VPOSCantCharge(Exception):
    """
    Excepción para indicar que la operación charge ha devuelto una respuesta incorrecta o de fallo
    """
    pass


class VPOSOperationNotImplemented(Exception):
    """
    Excepción para indicar que no se ha implementado una operación para un tipo de TPV en particular.
    """
    pass


class VPOSOperationException(Exception):
    """
    Cuando se produce un error al realizar una operación en concreto.
    """
    pass


class VPOSOperationAlreadyConfirmed(Exception):
    """
    La operacióm ya fue confirmada anteriormente mediante otra notificación recibida
    """
    pass