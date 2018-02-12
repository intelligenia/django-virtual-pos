django-virtual-pos
==================

Django module that abstracts the flow of several virtual points of sale
including PayPal

What’s this?
============

This module abstracts the use of the most used virtual points of sale in
Spain.

License
=======

`MIT LICENSE`_.

Implemented payment methods
===========================

Paypal
~~~~~~

`Paypal`_ paypal payment available.

Bitpay
~~~~~~

`Bitpay`_ bitcoin payments, from wallet to checkout

Spanish Virtual Points of Sale
------------------------------

Ceca
~~~~

`CECA`_ is the Spanish confederation of savings banks.

RedSyS
~~~~~~

`RedSyS`_ gives payment services to several Spanish banks like CaixaBank
or Caja Rural.

Santander Elavon
~~~~~~~~~~~~~~~~

`Santander Elavon`_ is one of the payment methods of the Spanish bank
Santander.

Requirements and Installation
=============================

Requirements
------------

-  Python 2.7 (Python 3 not tested, contributors wanted!)
-  `Django`_
-  `BeautifulSoup4`_
-  `lxml`_
-  `pycrypto`_
-  `Pytz`_
-  `Requests`_

Type:

.. code:: sh

    $ pip install django beautifulsoup4 lxml pycrypto pytz

Installation
------------

From PyPi
~~~~~~~~~

.. code:: sh

    $ pip install django-virtual-pos

From master branch
~~~~~~~~~~~~~~~~~~

Master branch will allways contain a working version of this module.

.. code:: sh

    $ pip install git+git://github.com/intelligenia/django-virtual-pos.git

settings.py
~~~~~~~~~~~

Add the application djangovirtualpos to your settings.py:

.. code:: python

    INSTALLED_APPS = (
        # ...
        "djangovirtualpos",
    )

Use
===

See this `manual`_ (currently only in Spanish).

Needed models
-------------

You will need to implement this skeleton view using your own **Payment**
model.

This model has must have at least the following attributes: - **code**:
sale code given by our system. - **operation_number**: bank operation
number. - **status**: status of the payment: “paid”, “pending”
(**pending** is mandatory) or “canceled”. - **amount**: amount to be
charged.

And the following methods: - **online_confirm**: mark the payment as
paid.

Integration examples
--------------------

-  `djshop`_

Needed views
------------

Sale summary view
~~~~~~~~~~~~~~~~~

.. code:: python

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

Note that this payment summary view should load a JS file called
**set_payment_attributes.js**.

This file is needed to set initial payment attributes according to which
bank have the user selected.

Payment_confirm view
~~~~~~~~~~~~~~~~~~~~

\````python @csrf_exempt def payment_confirmation(request,
virtualpos_typ

.. _MIT LICENSE: LICENSE
.. _Paypal: https://www.paypal.com/
.. _Bitpay: http://bitpay.com
.. _CECA: http://www.cajasdeahorros.es/
.. _RedSyS: http://www.redsys.es/
.. _Santander Elavon: https://www.santanderelavon.com/
.. _Django: https://pypi.python.org/pypi/django
.. _BeautifulSoup4: https://pypi.python.org/pypi/beautifulsoup4
.. _lxml: https://pypi.python.org/pypi/lxml
.. _pycrypto: https://pypi.python.org/pypi/pycrypto
.. _Pytz: https://pypi.python.org/pypi/pytz
.. _Requests: https://pypi.python.org/pypi/requests
.. _manual: manual/COMMON.md
.. _djshop: https://github.com/diegojromerolopez/djshop