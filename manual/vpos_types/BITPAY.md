# Biptay

##### Configuración de la operación

```python
	def setupPayment(self, code_len=40):
```

Realiza una petición a Bitpay, ``Create an Invoice``.

Los parámetros que se deben incorporar pare crear una orden de pago en bitpay son los siguientes (* son obligatórios).


| Name              | Description                                                                                                                                                                                                                                                                                                                                                                                                         |
|-------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| price*            | This is the amount that is required to be collected from the buyer. Note, if this is specified in a currency other than BTC, the price will be converted into BTC at market exchange rates to determine the amount collected from the buyer.                                                                                                                                                                        |
| currency*         | This is the currency code set for the price setting. The pricing currencies currently supported are USD, EUR, BTC, and all of the codes listed on this page: ​https://bitpay.com/bitcoin­exchange­rates                                                                                                                                                                                                              |
| posData           | A passthrough variable provided by the merchant and designed to be used by the merchant to correlate the invoice with an order or other object in their system. Maximum string length is 100 characters.,This passthrough variable can be a JSON­encoded string, for example,posData: ‘ ``{ “ref” : 711454, “affiliate” : “spring112” }`` ‘                                                                             |
| notificationURL   | A URL to send status update messages to your server (this must be an https URL, unencrypted http URLs or any other type of URL is not supported).,Bitpay.com will send a POST request with a JSON encoding of the invoice to this URL when the invoice status changes.                                                                                                                                              |
| transactionSpeed  | default value: set in your ​https://bitpay.com/order­settings​, the default value set in your merchant dashboard is “medium”.  -  **high**: An invoice is considered to be "confirmed" immediately upon receipt of payment., - **medium**: An invoice is considered to be "confirmed" after 1 blockconfirmation (~10 minutes). - **low**: An invoice is considered to be "confirmed" after 6 block confirmations (~1 hour).  |
| fullNotifications | Notifications will be sent on every status change.                                                                                                                                                                                                                                                                                                                                                                  |
| notificationEmail | Bitpay will send an email to this email address when the invoice status changes.                                                                                                                                                                                                                                                                                                                                    |
| redirectURL       | This is the URL for a return link that is displayed on the receipt, to return the shopper back to your website after a successful purchase. This could be a page specific to the order, or to their account.                                                                                                                                                                                                        |

> En nuetra implementación particular incorporamos los siguientes campos:

```python

params = {
    'price': self.importe,
    'currency': self.currency,
    'redirectURL': self.parent.operation.url_ok,
    'itemDesc': self.parent.operation.description,
    'notificationURL': self.notification_url,
    # Campos libres para el programador, puedes introducir cualquier información útil.
    # En nuestro caso el prefijo de la operación, que ayuda a TPV proxy a identificar el servidor
    # desde donde se ha ejecutado la operación.
    'posData': json.dumps({"operation_number_prefix": self.operation_number_prefix})
    'fullNotifications': True
}

```

>Tales parámetros se envían como  ``JSON`` con el verbo http ``POST``. 

>Como resultado de esta petición obtenemos una respuesta JSON como la siguiente:

```json
{  
   "status":"new",
   "btcPaid":"0.000000",
   "invoiceTime":1518093126310,
   "buyerFields":{ },
   "currentTime":1518093126390,
   "url":"https://bitpay.com/invoice?id=X7VytgMABGuv5Vo4xPsRhb",
   "price":5,
   "btcDue":"0.000889",
   "btcPrice":"0.000721",
   "currency":"EUR",
   "rate":6938.79,
   "paymentSubtotals":{  
      "BTC":72100
   },
   "paymentTotals":{  
      "BTC":88900
   },
   "expirationTime":1518094026310,
   "id":"X7VytgMABGuv5Vo4xPsRhb",
   "exceptionStatus": false
}
```

>De esta petición capturamos el ``id`` para almacenarlo como identificador de la operación.

---

##### Generación de los datos de pago que se enviarán a la pasarela

```python
	def getPaymentFormData(self):
```

>Dada la URL principal de bitpay (entorno test o estable) y el identificador de la operación, construimos un formulario ``GET`` con referencia a la url de pago de bitpay.

>Al hacer **submit** de este formulario el usuario es redirigido a la plataforma de Bitpay y cuando termine la operación vuelve a la aplicación, (a la url de vuelta establecida).

---

##### Obtención de los datos de pago enviados por la pasarela

```python
	def receiveConfirmation(request):
```

>Cuando se produce un cambio de estado en la operación de pago realizada anteriormente, el servidor de bitpay hace una petición POST a la url ``confirm/``, indicando el nuevo estado. Este método tiene la responsabilidad de identificar la operación dedo el ``id`` y capturar el ``status``.

---


##### Verificación de la operación

```python
	def verifyConfirmation(self):
```

>Tiene la responsabilidad de verificar que el nuevo estado comunicado en ``receiveConfirmation`` se corresponde con **"confirmed"**, ello quiere decir que el pago ha sido escrito correctamente en blockchain.
---

##### Confirmación de la operación

```python
	def charge(self):
```

En Bitpay no es importante la respuesta de la url ``confirm/``, siempre y cuando sea un 200, por tanto nosotros enviamos el string **"OK"**
	
