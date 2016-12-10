# PAYPAL

---

> **Importante:** El envío y recepción de datos en PayPal es distinto al del resto de TPVs. Nosotros enviaremos los datos
> desde un formulario a través de POST y recibiremos desde PayPal a través de GET. Al contrario que el resto de TPVs, con 
> PayPal no es el cliente el que envía los formularios, sino que los envía el servidor. 
> El siguiente diagrama muestra el flujo de ejecución de Express Checkout, los cuadros de la izquierda representan
> nuestro website y los de la derecha el servidor de PayPal.

---

## Diagrama de flujo

                          PASO 1
    +-----------+ ---------------------->  +------------+
    | Finalizar |                          |  SERVIDOR  |
    |  Compra   |         PASO 2           |   PAYPAL   |                       
    |           | <----------------------- |            |
    +-----------+                          +------------+
         |
         |
         |
         | PASO 3
         |                                 +-------------+
         |                                 |   Log In    |
         |                                 |   PAYPAL    |
         +-------------------------------> +-------------+
                                                  |
                                                  |
                                                  | Paso 4
                                                  |
                                                  v
    +------------+                          +------------+
    | Recibimos  |        PASO 5            | Continuar  |
    |Confirmacion| <----------------------- |   PAYPAL   |
    |            |                          |            |
    +------------+                          +------------+                                                  
         |
         |
         |
         | PASO 6
         |                                  +-------------+
         |                                  |  SERVIDOR   |
         |                                  |   PAYPAL    |
         +--------------------------------> +-------------+     
                                                  |
                                                  |                                                  
    +------------+                                | 
    |            |        PASO 7                  |
    |Confirmacion| <------------------------------+
    |            |                       
    +------------+
         
---         
 
### Pasos:
 **1.** Peticion al servidor de PayPal: SetExpressCheckout 
  1.1. Se le pasan los datos API_Username, API_Password, API_Signature, importe, PAYMENTREQUEST_0_PAYMENTACTION=SALE,
       la version=95, RETURN URL (url a la que vuelve si va todo bien), CANCELURL (url a la que redirige si hay error)
 **2.** Respuesta de PayPal con el Token
  2.1. Se guarda el token, ya que será usado como el número de operación
 **3.** Redirige a Paypal para logearse
 **4.** Se redirige al usuario a la pagina de Login de Paypal
 **5.** PayPal confirma el token y el PayerID
  5.1. Después de logearse, se redirige a la RETURNURL con el token y el PayerID
 **6.** Enviamos DoExpressCheckoutPayment con el token y PayerID   
 **7.** PayPal confirma el pago, y según falle o no manda a la URL

---

##### Configuración del pago

```python
	def configurePayment(self):
```

> En PayPal solo debemos configurar el importe, no hay idioma.
> El importe debe ser el valor de la operación y dos digitos decimales separador por un punto (.)
> Un ejemplo para una venta de 15€ seria: 15.00

---


##### Generación del número de operación

```python
	def setupPayment(self, code_len=12):
```

> El número de operación para PayPal no se genera como en los demás, sino que será un token devuelto
> por PayPal, por tanto, en este paso preparamos un formulario con los siguientes datos:

 **METHOD:**	Indica el método a usar (SetExpressCheckout)
 **VERSION:** Indica la versión (95 en este caso)
 **USER:** Indica el usuario registrado con cuenta bussiness en paypal
 **PWD:** Indica la contraseña del usuario registrado con cuenta bussiness en paypal
 **SIGNATURE:** Indica la firma del usuario registrado con cuenta bussiness en paypal
 **PAYMENTREQUEST_0_AMT:** Importe de la venta
 **PAYMENTREQUEST_0_CURRENCYCODE:** ID de la moneda a utilizar
 **RETURNURL:** URL donde Paypal redirige al usuario comprador después de logearse en Paypal
 **CANCELURL:** URL a la que Paypal redirige al comprador si el comprador no aprueba el pago
 **PAYMENTREQUEST_0_PAYMENTACTION:** Especifíca la acción
 
> Estos dos últimos valores se pasan a PayPal para que los muestre en el resumen de la venta

 **L_PAYMENTREQUEST_0_NAME0:** Especifica la descripción de la venta
 **L_PAYMENTREQUEST_0_AMT0:** Especifica el importe final de la venta

> Una vez enviado el formulario, comprobamos en este mismo método la respuesta. Ésta debe contener
> un ACK con el valor de Success, y un TOKEN

---

##### Generador de firma para el envío

> En PayPal no es necesaria la firma para el envío, ya que se hace a través de los datos
> de la API proporcionados en el formulario anterior
	
---

##### Generación de los datos de pago que se enviarán a la pasarela


```python
	def getPaymentFormData(self):
```

> Este formulario enviará los campos siguientes:
	
 **cmd:** Indica el tipo de operación que vamos a usar, en este caso "_express-checkout"
 **token:** Indica el token devuelto por PayPal en el paso anterior
 
---

##### Obtención de los datos de pago enviados por la pasarela

```python
	def receiveConfirmation(request):
```

> Estos serán los valores que nos devuelve la pasarela de pago

 **PayerID:** Número de identificación del comprador
 **token:** Número de operación
 
 
---

##### Verificación de la operación

```python
	def _verification_signature(self):
```

> Este método lo único que hará será comprobar que, en la tabla TPVPaymentOperation exista
> un número de operación que coincida con el token devuelto por PayPal

---

##### Confirmación de la operación

```python
	def charge(self):
```

> En el TPV de Paypal, éste método enviará por POST un formulario con solo siguientes campos:

 **METHOD:** Indica el método a usar, en este caso "DoExpressCheckoutPayment"
 **USER:** Indica el nombre del usuario con cuenta bussiness
 **PWD:** Indica la contraseña del usuario con cuenta bussiness
 **SIGNATURE:** Indica la firma  del usuario con cuenta bussiness
 **VERSION:** Indica la versión de PayPal, en este caso la 95
 **TOKEN:** Indica el token (número de operación)
 **PAYERID:** Indica el valor del número de identificación del usuario comprador
 **PAYMENTREQUEST_0_CURRENCYCODE:** Indica el tipo de moneda
 **PAYMENTREQUEST_0_PAYMENTACTION:** Indica el tipo de acción, en este caso es "Sale"
 **PAYMENTREQUEST_0_AMT:** Indica el importe final de la venta

> Este método recibirá mediante GET el token. 
 
> Al enviar este formulario recibiremos una respuesta de PayPal, en la que debemos comprobar 
> si existe ACK y que su valor sea "Success" y si existe un token. 
