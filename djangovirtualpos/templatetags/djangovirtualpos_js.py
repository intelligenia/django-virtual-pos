# -*- coding: utf-8 -*-

from __future__ import unicode_literals
from django import template
from django.utils import timezone
from django.template import loader, Context

register = template.Library()


@register.simple_tag
def include_djangovirtualpos_set_payment_attributes_js(set_payment_attributes_url, sale_code, url_ok, url_nok):
	t = loader.get_template("djangovirtualpos/templatetags/djangovirtualpos_js/djangovirtualpos_js.html")
	replacements = {
		"url_set_payment_attributes": set_payment_attributes_url,
		"sale_code": sale_code,
		"url_ok": url_ok,
		"url_nok": url_nok
	}
	try:
		return t.render(Context(replacements))
	except TypeError:
		return t.render(replacements)