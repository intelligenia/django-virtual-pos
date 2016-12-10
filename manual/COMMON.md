TPVs
====

Manual de implantación de TPV Virtual para comercios
----------------------------------------------------

# Módulo genérico de TPVs

El proceso de compra tendrá tres pasos (el paso 2 es opcional):

---

## Diagrama de flujo (PASO 1)


                          PASO a)
    +-----------+ ---------------------->  +------------+
    | CLIENTE   |                          |  SERVIDOR  |
    |-----------|                          |------------|
    |           |         PASO b)          |            |
    |           | <----------------------- |            |
    +-----------+                          +------------+
         |
         |
         |
         | PASO c)
         |           +-------------+
         |           |  PASARELA   |
         +---------> +-------------+
                      

---                     

### Paso 1. Envío a la pasarela de datos


#### Paso a). Configuración del pago
	a.1. Se prepara la URL del pago según el entorno, el importe y el idioma.
```python
def configurePayment(self, amount, description, url_ok, url_nok, sale_code):
	"""
	Configura el pago por TPV.
	Prepara el objeto TPV para:
	- Pagar una cantidad concreta
	- Establecera una descripción al pago
	- Establecer las URLs de OK y NOK
	- Almacenar el código de venta de la operación
	"""	
```
> Después de realizar la configuración del método general, se llamará a las configuraciones específicas, a través de los delegados.

	a.2. Se prepara el importe con el formato que solicite la entidad bancaria.
```python
	def setupPayment(self):
		"""
		Prepara el TPV.
		Genera el número de operación y prepara el proceso de pago.
		"""
```
> Comprobamos que el número de operación generado por el delegado es único en la tabla de TpvPaymentOperation
	
	a.3. Se obtienen los datos del pago rellenando el formulario con los datos rellenados por el cliente. Luego se enviará el formulario por POST a través de Javascript.
```python
	def getPaymentFormData(self):
		"""
		Este método será el que genere los campos del formulario de pago
		que se rellenarán desde el cliente (por Javascript)
		"""
```
> La generación de los campos de los formularios será específica de cada TPV a través de una llamada de su delegado 

#### Paso b). El servidor renderiza el formulario y lo devuelve al cliente para que lo envíe a la pasarela de pago.

#### Paso c). El cliente envia mediante un formulario POST a la pasarela de pago los datos que solicita la entidad bancaria para realizar la operación.

---

## Diagrama de flujo (PASO 3)

                          PASO a)
    +-----------+ ---------------------->  +------------+
    | PASARELA  |                          |  SERVIDOR  |
    |-----------|                          |------------|
    |           |         PASO b)          |            |
    |           | <----------------------- |            |
    +-----------+                          +------------+
         |
         |
         |
         | PASO c)
         |           +-------------+
         |           |   CLIENTE   |
         +---------> +-------------+

---         

### Paso 3. Confirmación del pago

> En este paso se encarga de la comunicación con la pasarela de pago y la verificación de los datos

#### Paso a). Obtenemos número de operación y datos 
	Guardamos el número de operación y el diccionario enviado desde la pasarela de pago. Cada pasarela de pago enviará los datos de distinta manera, por lo que hay que hacer recepciones específicas.
```python
	def receiveConfirmation(request, tpv_type):
		"""
		Este método se encargará recibir la información proporcionada por el tpv,
		debido a que cada información recibida variará segun el TPV, directamente llamará a cada delegado, según el tipo de tpv. 
		"""
```
#### Paso b). El servidor verifica que los datos enviados desde la pasarela de pago identifiquen a una operación de compra. Dependiendo si la verificación es correcta o no, se enviará URLOK o URLNOK
	Se calcula la firma y se compara con la que ha generado la pasarela de pago
```python
	def verifyConfirmation(self):
		"""
		Este método también se encargará de llamar a cada método delegado de tpv, se creará la firma y se comprobará que 
		coincida con la enviada por la pasarela de pago
		"""	
```
#### Paso 3. La pasarela de pago redirige al cliente a una URL. Dependiendo si ha ido bien o mal, redirige a una o a otra. Si la firma ha sido verificada el Servidor mandará un correo electrónico al cliente.
> Si la respuesta ha ido bien, se utilizará el siguiente método:

```python
	def charge(self):
		"""
		Última comunicación con el TPV (si hiciera falta).Esta comunicación sólo se realiza en 
		PayPal, dado que en CECA y otros hay una verificación y una respuesta con "OK"
		"""	
```

> Si ha habido un error en el pago, se ha de dar una respuesta negativa a la pasarela bancaria.

```python
	def responseNok(self):
		dlprint("responseNok")
		return HttpResponse("")
```



Especificaciones particulares de cada TPV
-----------------------------------------

> Cada TPV tiene una manera distinta, tanto de enviar los datos como de recibirlos, a continuación detallamos los campos:

- [CECA](manual/vpos_types/CECA.md)
- [PAYPAL](manual/vpos_types/PAYPAL.md)
- [REDSYS](manual/vpos_types/REDSYS.md)
- Santander Enlavon está pendiente.
