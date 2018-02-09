# django-virtual-pos
Django module that abstracts the flow of several virtual points of sale.

# Releases

## 1.6.8
- Integration with [BitPay](https://bitpay.com/)

## 1.6.7
- Add DS_ERROR_CODE logging default message for unknown Ds_Response, allow SOAP responses with empty Ds_AuthorisationCode

## 1.6.6
- Simplify integration.
- Add example integration.

## 1.6.5
- Add method to allow partial refund and full refund, specific to Redsys TPV Platform. 
- New model to register refund operations.
- Add refund view example.
 
 
## 1.6.4
- Include migrations.


## 1.6.4
- Include migrations.


## 1.6.1
- Allow reverse relation VPOSPaymentOperation -> VirtualPointOfSale


## 1.5
- Adding environment to VPOSPaymentOperation
- Changing labels in models


## 1.3
- Fixing get_type_help_bug


## 1.2
- Add new permission view_virtualpointofsale to ease management.
- Add method specificit_vpos in VirtualPointOfSale that returns the specific model object according to the VPOS type.


## 1.1
Minor changes in README.md.


## 1.0 Features 
- Integration with PayPal Checkout.
- Integration with the following Spanish bank virtual POS:
  - [RedSyS](http://www.redsys.es/)
  - [Santander Elavon](https://www.santanderelavon.com/)
  - [CECA](http://www.cajasdeahorros.es/).










