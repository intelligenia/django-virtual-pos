# django-virtual-pos
Django module that abstracts the flow of several virtual points of sale including PayPal


# What's this?

This module abstracts the use of the most used virtual points of sale in Spain.

# License

[MIT LICENSE](LICENSE).

# Implemented payment methods

## PayPal

Easy integration with PayPal.

## Spanish Virtual Points of Sale

### Ceca
[CECA](http://www.cajasdeahorros.es/) is the Spanish confederation of savings banks.

### RedSyS
[RedSyS](http://www.redsys.es/) gives payment services to several Spanish banks like CaixaBank or Caja Rural.

### Santander Elavon
[Santander Elavon](https://www.santanderelavon.com/) is one of the payment methods of the Spanish bank Santander. 


# Requirements and Installation

## Requirements

- Python 2.7 (Python 3 not tested, contributors wanted!)
- [Django](https://pypi.python.org/pypi/django)
- [BeautifulSoup4](https://pypi.python.org/pypi/beautifulsoup4)
- [lxml](https://pypi.python.org/pypi/lxml)
- [pycrypto](https://pypi.python.org/pypi/pycrypto)
- [Pytz](https://pypi.python.org/pypi/pytz)


Type:
````sh
$ pip install django beautifulsoup4 lxml pycrypto pytz
````

## Installation


### From PyPi

````sh
$ pip install django-virtual-pos
````

### From master branch

Master branch will allways contain a working version of this module. 

````sh
$ pip install git+git://github.com/intelligenia/django-virtual-pos.git
````


### settings.py

Add the application djangovirtualpos to your settings.py:

````python
INSTALLED_APPS = (
	# ...
	"djangovirtualpos",
)
````

# Use

See this [manual](manual/COMMON.md) (currently only in Spanish).

## Needed models

You will need to implement this skeleton view using your own **Payment** model.

This model has must have at least the following attributes:
 - **code**: sale code given by our system.
 - **operation_number**: bank operation number.
 - **status**: status of the payment: "paid", "pending" or "canceled".
 - **amount**: amount to be charged.

And the following methods:
 - **online_confirm**: mark the payment as paid.


## Needed views
### Sale summary view

````python
def payment_summary(request, payment_id):
	"""
	Load a Payment object and show a summary of its contents to the user.
	"""

	payment = get_object_or_404(Payment, id=payment_id, status="pending")
	replacements = {
		"payment": payment,
		# ...
	}
	return render(request, '<sale summary template path>', replacements)

````

Note that this payment summary view should load a JS file called **set_payment_attributes.js**.

This file is needed to set initial payment attributes according to which bank have the user selected.


### Payment_confirm view

````python
@csrf_exempt
def payment_confirmation(request, virtualpos_type):
	"""
	This view will be called by the bank.
	"""

	# Checking if the Point of Sale exists
	virtual_pos = VirtualPointOfSale.receiveConfirmation(request, virtualpos_type=virtualpos_type)

	if not virtual_pos:
		# The VPOS does not exist, inform the bank with a cancel
		# response if needed
		return VirtualPointOfSale.staticResponseNok(virtualpos_type)

	# Verify if bank confirmation is indeed from the bank
	verified = virtual_pos.verifyConfirmation()
	operation_number = virtual_pos.operation.operation_number

	with transaction.atomic():
		try:
			# Getting your payment object from operation number
			payment = Payment.objects.get(operation_number=operation_number, status="pending")
		except Payment.DoesNotExist:
			return virtual_pos.responseNok("not_exists")

		if verified:
			# Charge the money and answer the bank confirmation
			try:
				response = virtual_pos.charge()
				# Implement the online_confirm method in your payment
				# this method will mark this payment as paid and will
				# store the payment date and time.
				payment.online_confirm()
			except VPOSCantCharge as e:
				return virtual_pos.responseNok(extended_status=e)
			except Exception as e:
				return virtual_pos.responseNok("cant_charge")

		else:
			# Payment could not be verified
			# signature is not right
			response = virtual_pos.responseNok("verification_error")

		return response
````

### Payment ok view

````python
def payment_ok(request, sale_code):
	"""
	Informs the user that the payment has been made successfully
	:param payment_code: Payment code.
	:param request: request.
	"""

	# Load your Payment model given its code
	payment =  get_object_or_404(Payment, code=sale_code, status="paid")

	context = {'pay_status': "Done", "request": request}
	return render(request, '<payment_ok template>', {'context': context, 'payment': payment})
````

### Payment cancel view

````python
def payment_cancel(request, sale_code):
	"""
	Informs the user that the payment has been canceled
	:param payment_code: Payment code.
	:param request: request.
	"""

	# Load your Payment model given its code
	payment =  get_object_or_404(Payment, code=sale_code, status="pending")
	# Mark this payment as canceled
	payment.cancel()

	context = {'pay_status': "Done", "request": request}
	return render(request, '<payment_canceled template>', {'context': context, 'payment': payment})
````


# Authors
- Mario Barchéin marioREMOVETHIS@REMOVETHISintelligenia.com
- Diego J. Romero diegoREMOVETHIS@REMOVETHISintelligenia.com

Remove REMOVETHIS to contact the authors.
