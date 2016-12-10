# -*- coding: utf-8 -*-

from __future__ import unicode_literals, print_function

import inspect
from django.conf import settings
from django.utils import timezone

import logging


# Prepare debug message
def _prepare_debuglog_message(message, caller_level=2):
    # Por si acaso se le mete una cadena de tipo str,
    # este módulo es capaz de detectar eso y convertirla a UTF8
    if type(message) == str:
        message = unicode(message, "UTF-8")

    # Hora
    now = timezone.now()

    # Contexto desde el que se ha llamado
    curframe = inspect.currentframe()

    # Objeto frame que llamó a dlprint
    calframes = inspect.getouterframes(curframe, caller_level)
    caller_frame = calframes[2][0]
    caller_name = calframes[2][3]

    # Ruta del archivo que llamó a dlprint
    filename_path = caller_frame.f_code.co_filename
    filename = filename_path.split("/")[-1]

    # Obtención del mensaje
    return u"DjangoVirtualPOS: {0} {1} \"{2}\" at {3}:{5} in {6} ({4}:{5})\n".format(
        now.strftime("%Y-%m-%d %H:%M:%S %Z"), settings.DOMAIN, message,
                     filename, filename_path, caller_frame.f_lineno, caller_name
    )


# Prints the debug message
def dlprint(message):
    logger = logging.getLogger("syslog")
    complete_message = _prepare_debuglog_message(message=message, caller_level=3)
    utf8_complete_message = complete_message.encode('UTF-8')
    logger.debug(utf8_complete_message)
    print(utf8_complete_message)
