# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

{
    'name': 'Xero Connector (OAuth 2.0)',
    'version': '1.0',
    'category': 'Accounting',
    'license': 'OPL-1',
    'summary': 'Tool to integrate XERO with ODOO (OAuth 2.0)',
    'description': """

Xero is the QuickBooks alternative accounting software to manage invoicing, bank reconciliation, book keeping & more.

This module does bi-directional integration between Xero and Odoo for Accounts, Taxes, Contacts, Products and Invoices.

Benefits
========

- Raise invoices from Odoo.
- Allow your sales team to view overdue client accounts in Odoo.
- Reduce double data entry between Odoo and Xero.
- Improve cash flow by accelerating payment time.

Import Xero data into Odoo
==========================

- Currency: Complete currency types will be brought over to Odoo.
- Contact Groups: Entire contact groups.
- Contacts: All contacts which are stored in Xero, it could be Supplier or Customer.
- Account: All types of Accounts.
- Tax: All Tax types with its component.
- Bank Account: Accounts with bank type.
- Manual Journal: All type of manual journal, which cannot be recorded directly.
- Product: Products with its details (sale price, cost price, accounts, taxes etc), Also manage tracked and Untracked Products.
- Invoice: Customer Invoices with taxes. Also create payment lines in Odoo if invoice are paid fully or partially in Xero.
- Bills: Bills with taxes. Also create payment lines in Odoo if bills are paid fully or partially in Xero.
- Credit Note (ACCRECCREDIT): An Account Receivable (customer) Credit Note with payment and allocations.
- Credit Note (ACCPAYCREDIT): An Accounts Payable (supplier) Credit Note with payment and allocations.

Export Odoo data to Xero
========================

- Contacts: All contacts which are stored in Odoo, whether Customer or Supplier.
- Contact Groups: Entire contact groups.
- Accounts: All account with its type.
- Tax: Taxes with its component.
- Bank Account: Accounts with bank type.
- Product: Products with its details (sale price, cost price, accounts, taxes etc), Also manage tracked and Untracked Products.
- Invoice: Customer Invoice with tax. Also create payment in Xero if invoice are paid fully or partially in Odoo.
- Bills: Bills with tax. Also create payment in Xero if bills are paid fully or partially in Odoo.
- Inventory Adjustment: For tracked product if qty will be increasing or decreasing in Odoo using option like (Buying and selling inventory - bills and invoices, By Inventory adjustment, By Manufacturing process) it will be reflect in Xero.
- Attachment: Attachments of Invoice/Vendor Bill will be send to Xero.

User Guide
==========

'user_guide.pdf' is available in the 'doc' directory inside module.

Watch Video
===========

Go on https://www.youtube.com/watch?v=xGbWWSIAvNQ to watch the video demo.

Disclaimer
==========

Whenever there is a change in API from Xero or change in related Odoo objects you can contact us to look into it.

OAuth 2.0
OAuth 2
OAuth2
Auth 2
Auth 2.0
Xero Accounting
xero integration
Australia account integration
UK account integration
EU account integration
Europe account integration
Chart of accounts
Credit notes
Import Xero to Odoo
Export Odoo to Xero
Xero
Item
Product
Singapore Account
Inventory
Account
invoice
taxes
supplier
customer
journal entries
currencies
contact
integration
New Zealand Account Integration
Import
Export
Singapore account integration
Payment follow up
follow up
payment reminder
reminder
payment collection
collect payment
Payment overdue
overdue payment
overdue
payment
customer
customer payment
customer payment overdue
overdue customer payment
customer overdue payment reminder
customer overdue payment follow up
mail
payment reminder mail
due days
payment due
due payment
scheduler
analysis
follow up analysis
Accounting & Auditing Terms
accounting
accounting concepts
financial management
marginal benefit
letter of credit
asset
revenue
buyer
amount due
due amount
demand
cash
cash on delivery
deferred payment
period
duration
provision
cash flow
entrepreneur
monitoring
sale
feedback
requirement
effectiveness
following
auditing
audit
management
contract management
payment
payment term
accounting
connector
product
Auth2



    """,
    'author': 'Synconics Technologies Pvt. Ltd.',
    'website': 'http://www.synconics.com',
    'depends': ['sale_management', 'sale_stock'],
    'data': [
        'security/ir.model.access.csv',
        'security/security.xml',
        'data/data.xml',
        'views/xero_view.xml',
        'views/res_partner_view.xml',
        'views/product_view.xml',
        'views/account_view.xml',
        'views/account_invoice_view.xml',
        'views/menu.xml',
    ],
    'images': [
        'static/description/main_screen.png'
    ],
    "price": 350,
    "currency": "EUR",
    'external_dependencies': {
        'python' : ['requests_oauthlib'],
    },
    'application': True,
    'installable': True,
    'auto_install': False,
    'license': 'OPL-1',
}
