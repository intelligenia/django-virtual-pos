# CECA

##### Generación del número de operación

```python
	def setupPayment(self, code_len=40):
```

> El número de operación para CECA se genera anteponiendole un prefijo (el usuario lo podrá editar desde la administración) 
> A continuación un código aleatorio alfanumerico con una longitud de 40 caracteres

---

##### Generador de firma para el envío

```python
	def _sent_signature(self):
```

> Este método calcula la firma a incorporar en el formulario de pago
> Se encriptarán a través de una clave de cifrado la siguiente cadena:

	{encryption_key}{merchant_id}{acquirer_bin}{terminal_id}{num_operacion}{importe}{tipo_moneda}{exponente}SHA1{url_ok}{url_nok}

---

##### Generación de los datos de pago que se enviarán a la pasarela

```python
	def getPaymentFormData(self):
```

> Este formulario enviará los campos siguientes:

 **MerchantID:** Identifica al comercio, será facilitado por la caja
 **AcquirerID:** Identifica a la caja, será facilitado por la caja
 **TerminalID:** Identifica al terminal, será facilitado por la caja
 **Num_operacion:** Identifica el número de pedido, factura, albarán, etc
 **Importe:** Importe de la operación sin formatear. Siempre será entero con los dos últimos dígitos usados para los centimos
 **TipoMoneda:** Codigo ISO-4217 correspondiente a la moneda en la que se efectúa el pago
 **Exponente:** Actualmente siempre será 2
 **URL_OK:** URL determinada por el comercio a la que CECA devolverá el control en caso de que la operación finalice correctamente
 **URL_NOK:** URL determinada por el comercio a la que CECA devolverá el control en caso de que la operación NO finalice correctamente
 **Firma:** Cadena de caracteres calculada por el comercio
 **Cifrado:** Tipo de cifrado que se usará para el cifrado de la firma
 **Idioma:** Código de idioma
 **Pago_soportado:** Valor fijo: SSL
 **Descripcion:** Opcional. Campo reservado para mostrar información en la página de pago

---

##### Obtención de los datos de pago enviados por la pasarela

```python
	def receiveConfirmation(request):
```

> Estos serán los valores que nos devuelve la pasarela de pago

 **MerchantID:** Identifica al comercio
 **AcquirerBIN:** Identifica a la caja
 **TerminalID:** Identifica al terminal
 **Num_operacion:** Identifica el número de pedido, factura, albarán, etc	
 **Importe:** Importe de la operación sin formatear	
 **TipoMoneda:** Corresponde a la moneda en la que se efectúa el pago
 **Exponente:** Actualmente siempre será 2
 **Idioma:** Idioma de la operación
 **Pais:** Código ISO del país de la tarjeta que ha realizado la operación
 **Descripcion:** Los 200 primeros caracteres de la operación	
 **Referencia:** Valor único devuelto por la pasarela. Imprescinfible para realizar cualquier tipo de reclamanción y/o anulación	
 **Num_aut:** Valor asignado por la entidad emisora a la hora de autorizar una operación
 **Firma:** Es una cadena de caracteres calculada por CECA firmada por SHA1
 
---


##### Verificación de la operación

```python
	def _verification_signature(self):
```

> Este método calcula la firma que más tarde se comparará con la enviada por la pasarela
> Se encriptarán a través de una clave de cifrado la siguiente cadena:

	{encryption_key}{merchant_id}{acquirer_bin}{terminal_id}{num_operacion}{importe}{tipo_moneda}{exponente}{referencia}
	
> La 'Referencia' será un valor que devolvió la pasarela

---

##### Confirmación de la operación

```python
	def charge(self):
```

> En el TPV de CECA habrá que enviar una respuesta, para que la pasarela proceda a enviar la confirmación al cliente
> El valor que habrá que enviar es "$*$OKY$*$"
	
