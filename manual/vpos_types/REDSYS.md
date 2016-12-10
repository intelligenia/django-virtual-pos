# REDSYS

##### Generación del número de operación

```python
	def setupPayment(self, code_len=12):
```

> El número de operación para REDSYS se genera anteponiendole un prefijo (el usuario lo podrá editar desde la administración) 
> A continuación un código aleatorio de 4 números (entre 2 y 9) y una cadena alfanumerica (en mayúsculas) con una longitud de 8 caracteres
> Un ejemplo seria: 2645S5A8D88W

---

##### Generador de firma para el envío

```python
	def _sent_signature(self):
```

> Este método calcula la firma a incorporar en el formulario de pago
> Se encriptarán a través de una clave de cifrado la siguiente cadena:

	{importe}{num_pedido}{merchant_code}{tipo_moneda}{transaction_type}{merchant_url}{encryption_key}
	
---

##### Generación de los datos de pago que se enviarán a la pasarela

```python
	def getPaymentFormData(self):
```

> Este formulario enviará los campos siguientes:
	
 **Ds_Merchant_Amount:** Indica el importe de la venta	
 **Ds_Merchant_Currency:** Indica el tipo de moneda a usar
 **Ds_Merchant_Order:** Indica el número de operacion
 **Ds_Merchant_ProductDescription:** Se mostrará al titular en la pantalla de confirmación de la compra	
 **Ds_Merchant_MerchantCode:** Código FUC asignado al comercio	
 **Ds_Merchant_UrlOK:** URL a la que se redirige al usuario en caso de que la venta haya sido satisfactoria
 **Ds_Merchant_UrlKO:** URL a la que se redirige al usuario en caso de que la venta NO haya sido satisfactoria	 
 **Ds_Merchant_MerchantURL:** Obligatorio si se tiene confirmación online. 
 **Ds_Merchant_ConsumerLanguage:** Indica el valor del idioma	
 **Ds_Merchant_MerchantSignature:** Indica la firma generada por el comercio
 **Ds_Merchant_Terminal:** Indica el terminal
 **Ds_Merchant_SumTotal:** Representa la suma total de los importes de las cuotas	
 **Ds_Merchant_TransactionType:** Indica que tipo de transacción se utiliza
 
---

##### Obtención de los datos de pago enviados por la pasarela

```python
	def receiveConfirmation(request):
```

> Estos serán los valores que nos devuelve la pasarela de pago

 **Ds_Date:** Fecha de la transacción
 **Ds_Hour:** Hora de la transacción
 **Ds_Amount:** Importe de la venta, mismo valor que en la petición
 **Ds_Currency:** Tipo de moneda
 **Ds_Order:** Número de operación, mismo valor que en la petición 
 **Ds_MerchantCode:** Indica el código FUC del comercio, mismo valor que en la petición
 **Ds_Terminal:** Indica la terminal, , mismo valor que en la petición
 **Ds_Signature:** Firma enviada por RedSys, que más tarde compararemos con la generada por el comercio
 **Ds_Response:** Código que indica el tipo de transacción
 **Ds_MerchantData:** Información opcional enviada por el comercio en el formulario de pago
 **Ds_SecurePayment:** Indica: 0, si el pago es NO seguro; 1, si el pago es seguro
 **Ds_TransactionType:** Tipo de operación que se envió en el formulario de pago
 **Card_Country:** País de emisión de la tarjeta con la que se ha intentado realizar el pago
 **AuthorisationCode:** Código alfanumerico de autorización  asignado a la aprobación de la transacción
 **ConsumerLanguage:** El valor 0 indicará que no se ha determinado el idioma
 **Card_type:** Valores posibles: C - Crédito; D - Débito
 
---

##### Verificación de la operación

```python
	def _verification_signature(self):
```

> Este método calcula la firma que más tarde se comparará con la enviada por la pasarela
> Se encriptarán a través de una clave de cifrado la siguiente cadena:

	{importe}{merchant_order}{merchant_code}{tipo_moneda}{ds_response}{encription_key}
	
> El campo 'ds_response' será un valor que devolvió la pasarela

---

##### Confirmación de la operación

```python
	def charge(self):
```

> En el TPV de REDSYS no habrá que enviar una respuesta como en CECA, de todas maneras nosotros enviamos una cadena vacia
