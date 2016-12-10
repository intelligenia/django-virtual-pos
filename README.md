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

- Python 2.7
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
Type:

Master branch will allways contain a working version of this module. 

````sh
$ pip install git+git://github.com/intelligenia/django-virtual-pos.git
````


# Use

See this [manual/COMMON.md](manual) (currently only in Spanish).

# Authors
- Mario Barchéin marioREMOVETHIS@REMOVETHISintelligenia.com
- Diego J. Romero diegoREMOVETHIS@REMOVETHISintelligenia.com

Remove REMOVETHIS to contact the authors.