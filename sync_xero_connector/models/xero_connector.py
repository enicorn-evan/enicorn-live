# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

import base64
import json
import ast
import requests
from odoo import api, fields, models, _
from odoo.addons.sync_xero_connector.lib.xero.auth import PublicCredentials,PrivateCredentials, OAuth2Credentials
from odoo.addons.sync_xero_connector.lib.xero.constants import XeroScopes
from odoo.exceptions import UserError, ValidationError, Warning
from odoo.addons.sync_xero_connector.lib.xero import Xero
from datetime import datetime
from odoo.addons.sync_xero_connector.lib.xero.exceptions import (
    XeroAccessDenied,
    XeroBadRequest,
    XeroException,
    XeroExceptionUnknown,
    XeroForbidden,
    XeroInternalError,
    XeroNotAvailable,
    XeroNotFound,
    XeroNotImplemented,
    XeroNotVerified,
    XeroRateLimitExceeded,
    XeroUnauthorized,
)


class MisMatchLog(models.Model):
    _name = 'mismatch.log'
    _description = 'Mismatch Log'

    name = fields.Char('Name')
    source_model = fields.Char('Source Model')
    source_id = fields.Char('Source Id')
    description = fields.Char('Description')
    exported_date = fields.Datetime('Exported Date')


class XeroAccount(models.Model):
    _name = 'xero.account'
    _description = 'Xero Account'

    def generate_url(self):
        credentials = PublicCredentials(str(self.consumer_key), str(self.consumer_secret))
        self.url = credentials.url
        self.oauth_token = credentials.state.get('oauth_token', False)
        self.oauth_token_secret = credentials.state.get('oauth_token_secret', False)
        self.oauth_expires_at = credentials.state.get('oauth_expires_at', False)
        self.oauth_authorization_expires_at = credentials.state.get('oauth_authorization_expires_at', False)
        self.consumer_key = credentials.state.get('consumer_key', False)
        self.consumer_secret = credentials.state.get('consumer_secret', False)

    name = fields.Char('Name')
    url = fields.Char('Url')
    rsa_key_file = fields.Binary('RSA key File')
    filename = fields.Char('File Name')
    authentication_number = fields.Char('Authentication Code')
    account_type = fields.Selection([('private', 'Private'),
                                     ('public', 'Public')], string='Account Type', default='private')
    import_option = fields.Selection([('create', 'Create'),
                                      ('update', 'Update'),
                                      ('both', 'Both')], string='Option', default='create')
    inv_without_product = fields.Boolean('If you want to import invoice without product tick this')
    oauth_token = fields.Char(string='Oauth Token')
    oauth_token_secret = fields.Char(string='Oauth Token Secret')
    oauth_request_token = fields.Char(string='Oauth Request Token')
    oauth_request_token_secret = fields.Char(string='Oauth Request Token Secret')
    oauth_expires_at = fields.Datetime(string='Oauth Expires At')
    oauth_authorization_expires_at = fields.Datetime(string='Oauth Authorization Expires At')
    consumer_key = fields.Char(string='Consumer Key')
    consumer_secret = fields.Char(string='Consumer Secret')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.user.company_id.id)
    customer_inv_journal_id = fields.Many2one('account.journal', string='Customer Invoice Journal')
    vendor_bill_journal_id = fields.Many2one('account.journal', string='Vendor Bill Journal')
    miscellaneous_operations_journal_id = fields.Many2one('account.journal', string='Miscellaneous Operations Journal')
    active = fields.Boolean(string='Active', default=True)
    auth = fields.Char(string='Auth')
    journal_ids = fields.Many2many('account.journal', string="Payment Journal")
    tracked_category_id = fields.Many2one('product.category', string="Tracked Category", required=False)
    untracked_category_id = fields.Many2one('product.category', string="Untracked Category", required=False)
    adjustment_account_id = fields.Many2one('account.account', string='Inventory Adjustment Account')
    last_create_contact_import_date = fields.Datetime(string='Contact Create Import Date')
    last_update_contact_import_date = fields.Datetime(string='Contact update Import Date')
    last_contact_export_date = fields.Datetime(string='Contact Export Date')
    last_create_product_import_date = fields.Datetime(string='Product Create Import Date')
    last_update_product_import_date = fields.Datetime(string='Product Update Import Date')
    last_product_export_date = fields.Datetime(string='Product Export Date')
    last_create_invoice_import_date = fields.Datetime(string='Invoice Create Import Date')
    last_update_invoice_import_date = fields.Datetime(string='Invoice Update Import Date')
    last_invoice_export_date = fields.Datetime(string='Invoice Export Date')
    last_create_creditnote_import_date = fields.Datetime(string='Creditnote Create Import Date')
    last_update_creditnote_import_date = fields.Datetime(string='Creditnote Update Import Date')
    last_creditnote_export_date = fields.Datetime(string='Creditnote Export Date')
    last_journal_export_date = fields.Datetime(string='Journal Export Date')
    last_attachment_export_date = fields.Datetime(string='Attachment Export Date')
    export_disable = fields.Boolean(string='Disable Export', default=False)
    import_export_creditnotes = fields.Selection([('import', 'Import'), ('export', 'Export')], string='Credit Notes', default='import')

    oauth_type = fields.Selection([('oauth1', 'OAuth1.0'), ('oauth2', 'OAuth2.0')], string='OAuth Type', default='oauth2')
    client_id = fields.Char(string='Client ID')
    client_secret = fields.Char(string='Client Secret')
    callback_uri = fields.Char('Call Back URI')
    raw_url = fields.Char('Generated Raw URL')
    raw_uri = fields.Char('Raw URI')
    state = fields.Char('State')
    token = fields.Char('Token')
    xero_org_ids = fields.One2many('xero.organization', 'xero_account_id', string='Xero Organization Ids')
    xero_org_id = fields.Many2one('xero.organization', string='Import/Export Xero Organization')
    contact_overwrite = fields.Boolean(string='Contact Overwrite')

    def _re_authenticate(self):
        self.ensure_one()
        if self.account_type == 'public':
            new_credentials = PublicCredentials(consumer_key=self.consumer_key, consumer_secret=self.consumer_secret, verified=True, oauth_token=self.oauth_request_token, oauth_token_secret=self.oauth_request_token_secret)
            return Xero(new_credentials)
        elif self.account_type == 'private':
            public_key = base64.b64decode(self.rsa_key_file)
            credentials = PrivateCredentials(str(self.consumer_key), public_key)
            return Xero(credentials)

    def _authenticate(self):
        self.ensure_one()
        if self.account_type == 'public':
            if not self.authentication_number:
                raise ValidationError(_('Please enter authentication number!'))
            new_credentials = PublicCredentials(consumer_key=self.consumer_key, consumer_secret=self.consumer_secret, callback_uri=None, verified=False or u'', oauth_token=self.oauth_token, oauth_token_secret=self.oauth_token_secret, oauth_expires_at=None, oauth_authorization_expires_at=None)
            new_credentials.verify(str(self.authentication_number))
            self.auth = Xero(new_credentials)
            self.oauth_request_token = new_credentials.state.get('oauth_token', False)
            self.oauth_request_token_secret = new_credentials.state.get('oauth_token_secret', False)
            return Xero(new_credentials)
        elif self.account_type == 'private':
            public_key = base64.b64decode(self.rsa_key_file)
            credentials = PrivateCredentials(str(self.consumer_key), public_key)
            return Xero(credentials)

    def generate_url_auth2(self):
        self.ensure_one()
        my_scope = [XeroScopes.ACCOUNTING_SETTINGS, XeroScopes.OPENID, XeroScopes.PROFILE, XeroScopes.EMAIL, XeroScopes.OFFLINE_ACCESS, XeroScopes.ACCOUNTING_TRANSACTIONS, XeroScopes.ACCOUNTING_CONTACTS, XeroScopes.ACCOUNTING_ATTACHMENTS]
        credentials = OAuth2Credentials(self.client_id, self.client_secret, scope=my_scope, callback_uri=self.callback_uri)
        url = credentials.generate_url()
        self.raw_url = url
        self.state = credentials.state.get('auth_state')

    def authenticate(self):
        self.ensure_one()
        my_scope = [XeroScopes.ACCOUNTING_SETTINGS, XeroScopes.OPENID, XeroScopes.PROFILE, XeroScopes.EMAIL, XeroScopes.OFFLINE_ACCESS, XeroScopes.ACCOUNTING_TRANSACTIONS, XeroScopes.ACCOUNTING_CONTACTS, XeroScopes.ACCOUNTING_ATTACHMENTS]
        new_credentials = OAuth2Credentials(self.client_id, self.client_secret, scope=my_scope, callback_uri=self.callback_uri)
        if not self.raw_uri:
            raise UserError(_('Please Add Raw URI.'))
        try:
            new_credentials.verify(self.raw_uri)
        except XeroAccessDenied as e:
            raise UserError(_('XeroAccessDenied %s'% e))
        except Exception as e:
            raise UserError(e)

        self.token = new_credentials.token

        xero = Xero(new_credentials)
        self.auth = Xero(new_credentials)

        tenants = new_credentials.get_tenants()
        tenant_list = []
        for tenant in tenants:
            xero_org_id = self.xero_org_ids.filtered(lambda l: l.xero_tenant_id == tenant.get('tenantId'))
            if not xero_org_id:
                new_credentials.tenant_id = tenant.get('tenantId')
                org = xero.organisations.all()
                tenant_data = {'name': org[0].get('Name'),
                                'xero_id': tenant.get('id'),
                                'xero_tenant_id': tenant.get('tenantId'),
                                'xero_tenant_type': tenant.get('tenantType'),
                                'xero_account_id': self.id,
                                }
                tenant_list.append((0, 0, tenant_data))
        self.xero_org_ids = tenant_list

        return Xero(new_credentials)

    def re_authenticate(self):
        self.ensure_one()
        my_scope = [XeroScopes.ACCOUNTING_SETTINGS, XeroScopes.OPENID, XeroScopes.PROFILE, XeroScopes.EMAIL, XeroScopes.OFFLINE_ACCESS, XeroScopes.ACCOUNTING_TRANSACTIONS, XeroScopes.ACCOUNTING_CONTACTS, XeroScopes.ACCOUNTING_ATTACHMENTS]
        new_credentials = OAuth2Credentials(self.client_id, self.client_secret, scope=my_scope, callback_uri=self.callback_uri, token=ast.literal_eval(self.token))

        if new_credentials.expired():
            try:
                new_credentials.refresh()
            except Exception as e:
                raise UserError(_('Your Token has been expired %s, you need to Reauthentication' % e))
            self.state = new_credentials.state
            self.token = new_credentials.token

        if not self.xero_org_id:
            raise UserError('Please configure Xero Organization for Import/Export Operation.')
        new_credentials.tenant_id = self.xero_org_id.xero_tenant_id
        return Xero(new_credentials)

    def xero_auth(self):
        self.ensure_one()
        if self.oauth_type == 'oauth1':
            if self.account_type == 'public' and not self.authentication_number:
                raise Warning(_('Please enter Authentication Number!'))
            xero = self._re_authenticate() if self.auth else self._authenticate()
            # company = self.company_id.id
        else:
            if not self.xero_org_id:
                raise Warning(_('Please configure Xero Organization for Import/Export Operation.'))
            xero = self.re_authenticate()
            # company = self.xero_org_id.company_id.id
        # return xero, company
        return xero

    @api.model
    def run_scheduler(self):
        for record in self.search([]):
            if record.oauth_authorization_expires_at:
                date = fields.datetime.now()
                cmp_date = record.oauth_authorization_expires_at
                if cmp_date <= date:
                    record.url = False
                    record.authentication_number = False
                    record.oauth_token = False
                    record.oauth_token_secret = False
                    record.oauth_request_token = False
                    record.oauth_request_token_secret = False
                    record.oauth_expires_at = False
                    record.oauth_authorization_expires_at = False
                    record.auth = False

    @api.model
    def automatic_import(self):
        for record in self.search([('active', '=', True)]):
            if record.oauth_type == 'oauth2' or (record.oauth_type == 'oauth1' and record.account_type == 'private' and record.consumer_key and record.rsa_key_file):
                xero = record.xero_auth()
                # Import Currency
                currency_list = xero.currencies.all()
                self.env['res.currency'].import_currency(currency_list, xero)
                # Import Tax
                tax_list = xero.taxrates.all()
                self.env['account.tax'].import_tax(tax_list, xero, company=record.company_id.id, import_option=record.import_option)
                # Import Account
                account_list = xero.accounts.all()
                self.env['account.account'].import_account(account_list, xero, company=record.company_id.id, import_option=record.import_option)
                # Import Contact Group
                # group_list = xero.contactgroups.all()
                # self.env['res.partner.category'].import_contact_group(group_list, xero)
                # Import Contacts
                record.import_contact_overwrite() if record.contact_overwrite else record.import_contact()
                # Import Bank Account
                bank_account_list = xero.accounts.filter(Type='BANK')
                self.env['res.partner.bank'].import_bank_account(bank_account_list, xero, import_option=record.import_option, company=record.company_id.id)
                if not record.inv_without_product:
                    # Import Product
                    record.import_product()
                # Import Invoice
                record.import_invoice()
                # Import Manual Journal
                record.import_manual_journal()
                # Import Credit Notes
                if record.import_export_creditnotes == 'import':
                    record.import_credit_notes()

    @api.model
    def automatic_export(self):
        for record in self.search([('active', '=', True)]):
            if record.oauth_type == 'oauth2' or (record.oauth_type == 'oauth1' and record.account_type == 'private' and record.consumer_key and record.rsa_key_file):
                xero = record.xero_auth()
                # Export Taxes
                tax_rates = xero.taxrates.all()
                self.env['account.tax'].export_tax(tax_rates, xero, company=record.company_id.id, disable_export=record.export_disable)
                # Export Accounts
                account_list = xero.accounts.all()
                self.env['account.account'].export_account(account_list, xero, company=record.company_id.id, disable_export=record.export_disable)
                # Export Bank Accounts
                bank_account_list = xero.accounts.filter(Type='BANK')
                self.env['res.partner.bank'].export_bank_account(bank_account_list, xero, company=record.company_id.id, disable_export=record.export_disable)
                # Export Contact Groups
                group_list = xero.contactgroups.all()
                self.env['res.partner.category'].export_contact_group(group_list, xero)
                # Export Contacts
                record.export_contact_overwrite()if record.contact_overwrite else record.export_contact()
                # Export Products
                record.export_product()
                # Export invoices
                record.export_invoice()
                record.export_payment()
                # Export credit Notes
                if record.import_export_creditnotes == 'export':
                    record.export_credit_notes()
                    record.export_credit_notes_payment()
                # Export Inventory Adjustments
                self.env['stock.move.line'].create_inventory_adjustments(xero, company=record.company_id.id)
                #Export Attachment
                self.env['ir.attachment'].export_attachments(xero, company=record.company_id.id)

    def import_currency(self):
        self.ensure_one()
        xero = self.xero_auth()
        currency_list = xero.currencies.all()
        self.env['res.currency'].import_currency(currency_list, xero)

    def import_tax(self):
        self.ensure_one()
        xero = self.xero_auth()
        tax_list = xero.taxrates.all()
        self.env['account.tax'].import_tax(tax_list, xero, company=self.company_id.id, import_option=self.import_option)

    def import_account(self):
        self.ensure_one()
        xero = self.xero_auth()
        account_list = xero.accounts.all()
        self.env['account.account'].import_account(account_list, xero, company=self.company_id.id, import_option=self.import_option)

    def import_bank_account(self):
        self.ensure_one()
        xero = self.xero_auth()
        bank_account_list = xero.accounts.filter(Type='BANK')
        self.env['res.partner.bank'].import_bank_account(bank_account_list, xero, import_option=self.import_option, company=self.company_id.id)

    def import_contact(self):
        self.ensure_one()
        xero = self.xero_auth()

        group_list = xero.contactgroups.all()
        self.env['res.partner.category'].import_contact_group(group_list, xero)
        page = 0
        while True:
            page += 1
            contact_list = []
            if self.last_create_contact_import_date and self.import_option == 'create':
                contact_list = xero.contacts.filter(since=self.last_create_contact_import_date, page=page)
            elif self.last_update_contact_import_date and self.import_option == 'update':
                contact_list = xero.contacts.filter(since=self.last_update_contact_import_date, page=page)
            elif self.import_option == 'both' and self.last_create_contact_import_date and self.last_update_contact_import_date:
                min_date = min(self.last_create_contact_import_date, self.last_update_contact_import_date)
                contact_list = xero.contacts.filter(since=min_date, page=page)
            else:
                contact_list = xero.contacts.filter(page=page)
            if contact_list:
                    self.env['res.partner'].import_contact(contact_list, xero, company=self.company_id.id, import_option=self.import_option)
            else:
                break

        if self.import_option == 'create':
            self.last_create_contact_import_date = fields.Datetime.now()
        elif self.import_option == 'update':
            self.last_update_contact_import_date = fields.Datetime.now()
        elif self.import_option == 'both':
            self.last_create_contact_import_date = fields.Datetime.now()
            self.last_update_contact_import_date = fields.Datetime.now()

    def import_contact_overwrite(self):
        self.ensure_one()
        xero = self.xero_auth()

        group_list = xero.contactgroups.all()
        self.env['res.partner.category'].import_contact_group(group_list, xero)
        page = 0
        while True:
            page += 1
            contact_list = []
            if self.last_create_contact_import_date and self.import_option == 'create':
                contact_list = xero.contacts.filter(since=self.last_create_contact_import_date, page=page)
            elif self.last_update_contact_import_date and self.import_option == 'update':
                contact_list = xero.contacts.filter(since=self.last_update_contact_import_date, page=page)
            elif self.import_option == 'both' and self.last_create_contact_import_date and self.last_update_contact_import_date:
                min_date = min(self.last_create_contact_import_date, self.last_update_contact_import_date)
                contact_list = xero.contacts.filter(since=min_date, page=page)
            else:
                contact_list = xero.contacts.filter(page=page)
            if contact_list:
                    self.env['res.partner'].import_contact_overwrite(contact_list, xero, company=self.company_id.id, import_option=self.import_option)
            else:
                break

        if self.import_option == 'create':
            self.last_create_contact_import_date = fields.Datetime.now()
        elif self.import_option == 'update':
            self.last_update_contact_import_date = fields.Datetime.now()
        elif self.import_option == 'both':
            self.last_create_contact_import_date = fields.Datetime.now()
            self.last_update_contact_import_date = fields.Datetime.now()

    def import_product(self):
        self.ensure_one()
        xero = self.xero_auth()

        if self.last_create_product_import_date and self.import_option == 'create':
            product_list = xero.items.filter(since=self.last_create_product_import_date)
        elif self.last_update_product_import_date and self.import_option == 'update':
            product_list = xero.items.filter(since=self.last_update_product_import_date)
        elif self.import_option == 'both' and self.last_create_product_import_date and self.last_update_product_import_date:
            min_date = min(self.last_create_product_import_date,self.last_update_product_import_date)
            product_list = xero.items.filter(since=min_date)
        else:
            product_list = xero.items.all()
        self.env['product.product'].import_product(product_list, xero, self.tracked_category_id, self.untracked_category_id, company=self.company_id.id, import_option=self.import_option)

        if self.import_option == 'create':
            self.last_create_product_import_date = fields.Datetime.now()
        elif self.import_option == 'update':
            self.last_update_product_import_date = fields.Datetime.now()
        else:
            self.last_create_product_import_date = fields.Datetime.now()
            self.last_update_product_import_date = fields.Datetime.now()

    def import_invoice(self):
        self.ensure_one()
        xero = self.xero_auth()

        page = 0
        while True:
            page += 1
            invoice_list = []
            if self.last_create_invoice_import_date and self.import_option == 'create':
                invoice_list = xero.invoices.filter(since=self.last_create_invoice_import_date, page=page)
            elif self.last_update_invoice_import_date and self.import_option == 'update':
                invoice_list = xero.invoices.filter(since=self.last_update_invoice_import_date, page=page)
            elif self.import_option == 'both' and self.last_create_invoice_import_date and self.last_update_invoice_import_date:
                min_date = min(self.last_create_invoice_import_date, self.last_update_invoice_import_date)
                invoice_list = xero.invoices.filter(since=min_date, page=page)
            else:
                invoice_list = xero.invoices.filter(page=page)

            if invoice_list:
                self.env['account.move'].import_invoice(self.id, invoice_list , xero, company=self.company_id.id, without_product=self.inv_without_product, import_option=self.import_option, customer_inv_journal_id=self.customer_inv_journal_id, vendor_bill_journal_id=self.vendor_bill_journal_id)
            else:
                break

        if self.import_option == 'create':
            self.last_create_invoice_import_date = fields.Datetime.now()
        elif self.import_option == 'update':
            self.last_update_invoice_import_date = fields.Datetime.now()
        else:
            self.last_create_invoice_import_date = fields.Datetime.now()
            self.last_update_invoice_import_date = fields.Datetime.now()

    def import_credit_notes(self):
        self.ensure_one()
        xero = self.xero_auth()

        page = 0
        while True:
            page += 1
            credit_notes_list = []
            if self.last_create_creditnote_import_date and self.import_option == 'create':
                credit_notes_list = xero.creditnotes.filter(since=self.last_create_creditnote_import_date, page=page)
            elif self.last_update_creditnote_import_date and self.import_option == 'update':
                credit_notes_list = xero.creditnotes.filter(since=self.last_update_creditnote_import_date, page=page)
            elif self.import_option == 'both' and self.last_create_creditnote_import_date and self.last_update_creditnote_import_date:
                min_date = min(self.last_create_creditnote_import_date, self.last_update_creditnote_import_date)
                credit_notes_list = xero.creditnotes.filter(since=min_date, page=page)
            else:
                credit_notes_list = xero.creditnotes.filter(page=page)

            if credit_notes_list:
                self.env['account.move'].import_credit_notes(self.id, credit_notes_list , xero, company=self.company_id.id, without_product=self.inv_without_product, import_option=self.import_option, customer_inv_journal_id=self.customer_inv_journal_id, vendor_bill_journal_id=self.vendor_bill_journal_id)
            else:
                break

        if self.import_option == 'create':
            self.last_create_creditnote_import_date = fields.Datetime.now()
        elif self.import_option == 'update':
            self.last_update_creditnote_import_date = fields.Datetime.now()
        else:
            self.last_create_creditnote_import_date = fields.Datetime.now()
            self.last_update_creditnote_import_date = fields.Datetime.now()

    def import_manual_journal(self):
        self.ensure_one()
        xero = self.xero_auth()

        page = 0
        while True:
            page += 1
            journal_list = []
            journal_list = xero.manualjournals.filter(page=page)
            if journal_list:
                self.env['account.move'].import_manual_journal(journal_list, xero, company=self.company_id.id, import_option=self.import_option)
            else:
                break

    def export_tax(self):
        self.ensure_one()
        xero = self.xero_auth()

        tax_rates = xero.taxrates.all()
        self.env['account.tax'].export_tax(tax_rates, xero, company=self.company_id.id, disable_export=self.export_disable)

    def export_account(self):
        self.ensure_one()
        xero = self.xero_auth()

        account_list = xero.accounts.all()
        self.env['account.account'].export_account(account_list, xero, company=self.company_id.id, disable_export=self.export_disable)

    def export_bank_account(self):
        self.ensure_one()
        xero = self.xero_auth()

        bank_account_list = xero.accounts.filter(Type='BANK')
        self.env['res.partner.bank'].export_bank_account(bank_account_list, xero, company=self.company_id.id, disable_export=self.export_disable)

    def export_contact(self):
        self.ensure_one()
        xero = self.xero_auth()

        group_list = xero.contactgroups.all()
        self.env['res.partner.category'].export_contact_group(group_list, xero)
        contact_list = xero.contacts.all()
        self.env['res.partner'].export_contact(contact_list, xero, self.last_contact_export_date, company=self.company_id.id)
        if not self._context.get('contact_ids'):
            self.last_contact_export_date = fields.Datetime.now()

    def export_contact_overwrite(self):
        self.ensure_one()
        xero = self.xero_auth()

        group_list = xero.contactgroups.all()
        self.env['res.partner.category'].export_contact_group(group_list, xero)
        contact_list = xero.contacts.all()
        self.env['res.partner'].export_contact_overwrite(contact_list, xero, self.last_contact_export_date, company=self.company_id.id)
        if not self._context.get('contact_ids'):
            self.last_contact_export_date = fields.Datetime.now()

    def export_product(self):
        self.ensure_one()
        xero = self.xero_auth()

        product_list = xero.items.all()
        self.env['product.product'].export_product(product_list, xero, self.last_product_export_date, company=self.company_id.id)
        if not self._context.get('product_ids'):
            self.last_product_export_date = fields.Datetime.now()

    def export_invoice(self):
        self.ensure_one()
        xero = self.xero_auth()

        invoice_list = xero.invoices.all()
        self.env['account.move'].export_invoice(invoice_list , xero, self.last_invoice_export_date, company=self.company_id.id, disable_export=self.export_disable)
        if not self._context.get('invoice_ids'):
            self.last_invoice_export_date = fields.Datetime.now()

    def export_payment(self):
        self.ensure_one()
        xero = self.xero_auth()

        self.env['account.move'].export_payment(xero, company=self.company_id.id, disable_export=self.export_disable)

    def export_credit_notes(self):
        self.ensure_one()
        xero = self.xero_auth()

        credit_notes_list = xero.creditnotes.all()
        self.env['account.move'].export_credit_notes(credit_notes_list , xero, self.last_creditnote_export_date, company=self.company_id.id, disable_export=self.export_disable)
        if not self._context.get('invoice_ids'):
            self.last_creditnote_export_date = fields.Datetime.now()

    def export_credit_notes_payment(self):
        self.ensure_one()
        xero = self.xero_auth()

        self.env['account.move'].export_credit_notes_payment(xero, company=self.company_id.id, disable_export=self.export_disable)

    def export_inventory_adjustments(self):
        self.ensure_one()
        xero = self.xero_auth()

        self.env['stock.move.line'].create_inventory_adjustments(xero, company=self.company_id.id, adjustment_account=self.adjustment_account_id)

    def export_attachments(self):
        self.ensure_one()
        xero = self.xero_auth()

        self.env['ir.attachment'].export_attachments(xero, self.last_attachment_export_date, company=self.company_id.id)
        self.last_attachment_export_date = fields.Datetime.now()

    # def export_manual_journal(self):
    #     if self.account_type == 'public' and not self.authentication_number:
    #         raise Warning(_('Please enter Authentication Number!'))
    #     xero = self._re_authenticate() if self.auth else self._authenticate()
    #     journal_list = xero.manualjournals.all()
    #     self.env['account.move'].export_manual_journal(journal_list ,xero, company=self.company_id.id)


class XeroOrganization(models.Model):
    _name = 'xero.organization'
    _description = 'Xero Organization'

    name = fields.Char(string='Name', readonly=True)
    xero_id = fields.Char(string='Xero ID', readonly=True)
    xero_tenant_id = fields.Char(string='Tenant Id', readonly=True)
    xero_tenant_type = fields.Char(string='Tenant Type', readonly=True)
    # company_id = fields.Many2one('res.company', string='Company')
    active = fields.Boolean(string='Active', default=True)
    xero_account_id = fields.Many2one('xero.account', string='Xero Account')
