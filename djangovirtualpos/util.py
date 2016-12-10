# -*- coding: utf-8 -*-

import datetime
from django.conf import settings
from django.utils import timezone
import pytz


########################################################################
########################################################################
# Obtiene la dirección IP del cliente
def get_client_ip(request):
    """
    Obtiene la dirección IP del cliente.
    """
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0]
    else:
        return request.META.get('REMOTE_ADDR')


def as_server_datetime(_datetime):
    """Localiza la marca de tiempo en función de la zona de tiempo del servidor"""
    SERVERT_PYTZ = pytz.timezone(settings.TIME_ZONE)
    return SERVERT_PYTZ.localize(_datetime)


def localize_datetime(_datetime):
    """Localiza la marca de tiempo en función de la zona de tiempo del servidor. Sólo y exclusivamente si no está localizada ya."""
    if timezone.is_naive(_datetime):
        return as_server_datetime(_datetime)
    return _datetime


def localize_datetime_from_format(str_datetime, datetime_format="%Y-%m-%d %H:%M"):
    _datetime = datetime.datetime.strptime(str_datetime, datetime_format)
    return localize_datetime(_datetime)


########################################################################
########################################################################


def dictlist(node):
    res = {}
    res[node.tag] = []
    xmltodict(node, res[node.tag])
    reply = {}
    reply[node.tag] = {'value': res[node.tag], 'attribs': node.attrib, 'tail': node.tail}

    return reply


def xmltodict(node, res):
    rep = {}
    if len(node):
        # n = 0
        for n in list(node):
            rep[node.tag] = []
            value = xmltodict(n, rep[node.tag])
            if len(n):
                value = {'value': rep[node.tag], 'attributes': n.attrib, 'tail': n.tail}
                res.append({n.tag: value})
            else:
                res.append(rep[node.tag][0])
    else:
        value = {}
        value = {'value': node.text, 'attributes': node.attrib, 'tail': node.tail}

        res.append({node.tag: value})

    return
