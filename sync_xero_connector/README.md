Xero connector with OAuth 2.

Payment Journal Configuration
------------------------------

Import Invoice Case:
    -While importing invoice from xero to odoo, for account(chart of account or Bank account) you used in xero payment you have to create payment journal in odoo. In payment journal form default debit account and credit account set your xero payment account. Otherwise it raise error 'Please Create Payment Journal for Account 'account name' of Company 'company name''.

Export Invoice Case:
    -While exporting invoice from odoo to xero, The payment journal used in payment of odoo , you have to select the xero payment account in field Xero Account of respected payment journal. Otherwise it raise error 'Please select your xero account on payment Journal'.

Notes:
For multi company All journal and accounts(chart of accounts and Bank account) are difference per company.
Xero Account of payment journal select account which is available for payment on xero side.
In case of multi company select accounts based on configured company.

Customer Invoice Journal
-------------------------

The Journal which used in all customer invoice.

Vendor Bill Journal
--------------------

The Journal which used in all vendor bill.

Multi Company
--------------

In case of multi company create separate xero Account for each child company.
set your chart of accounts for each company.
Create Payment journal company wise.

Note:
If you get warning like "can't create move for different company". It means the operation you performed have data of other company. For Ex. User get these warning while export invoice from odoo to xero of 'Company X' but in the invoice customer configured of 'Comapany Y'.

Multi Currencies
----------------

In odoo some entries are created at the time of invoice validate. so those entries are based on odoo currency rates. Then you export that invoice on xero side and make payment on xero side and then import invoice on odoo side with it's payment at that time payment entries are created as par xero currency rate.

Duplicate Records
-----------------

(In case of export records from odoo to xero)

In product if default code of odoo product and item code of xero product id same then it direct store item id(xero id) in product(make sure price and accounts of products are same).

In chart of account if same account name found then it check for code, if code is also same then it consider as a single account.
(In invoice and payments we used unique code of account therefor we also check for code in account.)

In customer if same customer name found the it consider as a single customer.

Import Currencies
-----------------

Xero does not provide any currency rates information with currency in API (Refer 'https://developer.xero.com/documentation/api/currencies').
Right now we only import currencies.


Taxes
-----
Taxes repartition line is 100% of Tax, it will Export(Odoo to Xero).


Bank Account
------------

As listed in features list (https://www.odoo.com/apps/modules/12.0/xero_connector/)it will only import and export bank accounts not bank transaction and other details.


Product Configuration
---------------------

(Export product from odoo to xero)
- name of product is allow less then 50 char in xero, Therefor we export first 50 char of name to xero product.


Credit Notes Allocation:
------------------------
When Credit Note goes in paid stage on Xero, then allocation will applied in Odoo.
When Credit Note and Invoice currency are different, then allocation is not possible in Xero.


General Notes:
--------------

While export Taxes, Chart of Account and Bank Account from Odoo to Xero record will not update as it's an configuration part.
While import Chart of Account from Xero to Odoo record will not update as it's an configuration part.