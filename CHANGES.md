# django-virtual-pos
Django module that abstracts the flow of several virtual points of sale including PayPal.

# Releases

## 1.0 Features 
- Integration with PayPal Checkout.
- Integration with the following Spanish bank virtual POS:
  - [RedSyS](http://www.redsys.es/)
  - [Santander Elavon](https://www.santanderelavon.com/)
  - [CECA](http://www.cajasdeahorros.es/).

## 1.1
Minor changes in README.md.

## 1.2
- Add new permission view_virtualpointofsale to ease management.
- Add method specificit_vpos in VirtualPointOfSale that returns the specific model object according to the VPOS type.

## 1.3
- Fixing get_type_help_bug

## 1.5
- Adding environment to VPOSPaymentOperation
- Changing labels in models

## 1.6.1
- Allow reverse relation VPOSPaymentOperation -> VirtualPointOfSale
