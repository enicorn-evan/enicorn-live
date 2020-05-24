# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

import datetime
import logging
import time
from odoo import api, fields, models, _
from odoo.exceptions import Warning, UserError

_logger = logging.getLogger(__name__)


class AccountMoveLineXeroLog(models.Model):
    _name = 'account.move.line.xero.log'
    _description = 'Account Move Line'

    name = fields.Char('Name of Payment Line')
    xero_payment = fields.Char('Xero Payment ID', copy=False)


class account_payment(models.Model):
    _inherit = "account.payment"

    xero_payment_id = fields.Char('Xero Payment ID', copy=False)


class AccountMove(models.Model):
    _inherit = 'account.move'

    xero_invoice_id = fields.Char('Xero Invoice ID', readonly=True, copy=False)
    xero_invoice_number = fields.Char('Xero Invoice Number', readonly=True, copy=False)
    line_amount_type = fields.Selection([
        ('Exclusive', 'Exclusive'),
        ('Inclusive', 'Inclusive'),
        ('NoTax', 'NoTax'),
        ], 'Line Amount Type', default='Exclusive')
    xero_credit_note_allocation = fields.Boolean(string="Xero Credit Note Allocation")
    xero_manual_journal_id = fields.Char('Xero Manual Journal ID', readonly=True, copy=False)
    is_manual_journal = fields.Boolean(string='Is Manual Journal')
    able_to_xero_export = fields.Boolean(string="Able to Xero Export", default='True')

    def tax_calculation(self):
        self.invoice_line_ids.with_context({'check_move_validity': False,'line_amount_type': self.line_amount_type})._onchange_product_id()
        if self.line_amount_type == 'NoTax':
            self.invoice_line_ids.with_context({'check_move_validity': False, 'line_amount_type': self.line_amount_type}).write({'tax_ids': [(6, 0, [])]})
        self.with_context({'check_move_validity': False,'line_amount_type': self.line_amount_type})._onchange_invoice_line_ids()
        self.with_context({'check_move_validity': False, 'line_amount_type': self.line_amount_type})._recompute_dynamic_lines(recompute_all_taxes=True)
        self.with_context({'line_amount_type': self.line_amount_type})._compute_invoice_taxes_by_group()

    @api.model
    def default_get(self, default_fields):
        res = super(AccountMove, self).default_get(default_fields)
        tax_type = self.env['ir.config_parameter'].get_param('account.show_line_subtotals_tax_selection')
        if tax_type == 'tax_included':
            res['line_amount_type'] = 'Inclusive'
        elif tax_type == 'tax_excluded':
            res['line_amount_type'] = 'Exclusive'
        return res

    @api.model
    def fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        res = super(AccountMove, self).fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if self._context.get('default_type') in ['out_receipt', 'in_receipt', 'entry'] and view_type == 'tree':
            for action in res.get('toolbar').get('action'):
                if action.get('name') == 'Export In Xero':
                    res.get('toolbar').get('action').remove(action)
        return res

    def pay_creditnote(self, xero, partner, xero_invoice, invoice_id, type, company=False):
        for payment in xero_invoice.get('Allocations'):
            domain = [('move_id.xero_invoice_id', '=', payment.get('Invoice').get('InvoiceID')),
                      ('partner_id', '=', self.env['res.partner']._find_accounting_partner(partner).id),
                      ('reconciled', '=', False),
                      '|',
                      '&', ('amount_residual_currency', '!=', 0.0), ('currency_id', '!=', None),
                      '&', ('amount_residual_currency', '=', 0.0), '&', ('currency_id', '=', None), ('amount_residual', '!=', 0.0)]
            if invoice_id.type in ('out_invoice', 'in_refund'):
                domain.extend([('credit', '>', 0), ('debit', '=', 0)])
            else:
                domain.extend([('credit', '=', 0), ('debit', '>', 0)])
            lines = self.env['account.move.line'].search(domain)
            if len(lines) != 0:
                invoice_id.with_context({'allocation_amount': payment['Amount']}).js_assign_outstanding_line(lines.id)

    def pay_invoice(self, xero_account_id, xero, partner, xero_invoice, odoo_invoice, type, company=False):
        partner_pool = self.env['res.partner']
        currency_pool = self.env['res.currency']
        account_pool = self.env['account.account']
        xero_pool = self.env['xero.account']
        company_pool = self.env['res.company']
        move_line_pool = self.env['account.move.line.xero.log']
        if partner and xero_invoice and odoo_invoice:
            invoice = odoo_invoice
            partner_id = partner_pool._find_accounting_partner(partner).id
            if xero_invoice.get('Payments'):
                for payment in xero_invoice.get('Payments'):
                    payment_line = move_line_pool.search([('xero_payment', '=', payment.get('PaymentID'))])
                    currency_id = currency_pool.search([('name', '=', xero_invoice.get('CurrencyCode'))], limit=1)
                    if not currency_id:
                        currency_list = xero.currencies.all()
                        currency_pool.import_currency(currency_list, xero)
                        currency_id = currency_pool.search([('name', '=', xero_invoice.get('CurrencyCode'))], limit=1)

                    if payment.get('PaymentID'):
                        xero_payment_id = xero.payments.get(payment.get('PaymentID'))
                        payment_account = xero_payment_id[0].get('Account')
                        account = account_pool.search([('code', '=', payment_account.get('Code')), ('acc_id', '=', payment_account.get('AccountID'))],limit=1)
                        if not account:
                            account_list = xero.accounts.all()
                            account_pool.import_account(account_list, xero, company=company, import_option='create')
                            account = account_pool.search([('code', '=', payment_account.get('Code')), ('acc_id', '=', payment_account.get('AccountID'))],limit=1)

                        # xero_account_id = xero_pool.search([('company_id', '=', company)], limit=1)
                        xero_account = xero_pool.browse(xero_account_id)
                        payment_journal = False
                        for journal in xero_account.journal_ids:
                            if journal.default_debit_account_id.id == account.id or journal.default_credit_account_id.id == account.id:
                                payment_journal = journal
                                break
                        if not payment_journal:
                            company_id = company_pool.browse(company)
                            raise UserError(_("Please Create or Add 'Payment Journal' for account \'%s %s\' of company \'%s\'.")% (account.code, account.name, company_id.name))

                    if not payment_line:
                        date = payment.get('Date')
                        account_payment_vals = {
                                            'invoice_ids': [(6, 0, odoo_invoice.ids)],
                                            'amount': payment.get('Amount'),
                                            'currency_id': currency_id and currency_id.id or False,
                                            'partner_id': partner_id,
                                            'company_id': company,
                                            'journal_id': payment_journal and payment_journal.id or False,
                                            'payment_date': date or fields.Date.today(),
                                            'partner_type': odoo_invoice.type in ('out_invoice', 'out_refund') and 'customer' or 'supplier',
                                            'xero_payment_id': payment.get('PaymentID') or False,
                                            }
                        if type in ['out_invoice', 'in_refund']:
                            account_payment_vals.update({'payment_type':invoice.type in ('out_invoice', 'in_refund') and 'inbound' or 'outbound',
                                        'payment_method_id': self.env.ref('account.account_payment_method_manual_in').id})
                        elif type in ['in_invoice', 'out_refund']:
                            account_payment_vals.update({'payment_type':invoice.type in ('in_invoice', 'out_refund') and 'outbound' or 'inbound',
                                        'payment_method_id': self.env.ref('account.account_payment_method_manual_out').id})
                        account_payment = invoice.env['account.payment'].create([account_payment_vals])
                        move_line_pool.create({'name': partner.name, 'xero_payment': payment.get('PaymentID')})
                        account_payment.invoice_ids.state = 'posted'
                        if account_payment.invoice_ids.state == 'posted':
                            if xero_invoice.get('CurrencyRate'):
                                account_payment.with_context({'CurrencyRate': payment.get('CurrencyRate')}).post()
                            else:
                                account_payment.post()
                            self._cr.commit()

    def import_invoice(self, xero_account_id, invoice_list, xero, company=False, without_product=False, import_option=None, customer_inv_journal_id=False, vendor_bill_journal_id=False):
        inv_line_pool = self.env['account.move.line']
        inv_pool = self.env['account.move']
        tax_pool = self.env['account.tax']
        account_pool = self.env['account.account']
        product_pool = self.env['product.product']
        partner_pool = self.env['res.partner']
        currency_pool = self.env['res.currency']
        # xero_account = self.env['xero.account'].search([('company_id', '=', company)], limit=1)
        xero_account = self.env['xero.account'].browse(xero_account_id)
        for invoice in invoice_list:
            if invoice.get('Total') != 0.0:
                invoice_res = self.search([('xero_invoice_id', '=', invoice.get('InvoiceID'))])
                if invoice_res and import_option in ['update', 'both']:
                    if invoice.get('Status') == 'VOIDED' and invoice_res[0].state == 'posted':
                        invoice_res[0].button_draft()
                    if invoice.get('Status') in ['DELETED', 'VOIDED'] and invoice_res[0].state == 'draft':
                        invoice_res[0].button_cancel()
                    if invoice_res[0].state != 'cancel' and invoice_res[0].invoice_payment_state != 'paid':
                        if invoice_res[0].state == 'draft':
                            available_lines = []
                            flag = 0
                            if invoice:
                                sub_tax = invoice.get('SubTotal') + invoice.get('TotalTax')
                                if float("%.2f"%sub_tax) != invoice.get('Total'):
                                    flag = 1

                                line_items = []
                                for lines in invoice.get('LineItems'):
                                    available_lines.append(lines.get('LineItemID'))
                                    line = inv_line_pool.search([('xero_invoice_line_id', '=', lines.get('LineItemID')),('company_id', '=', company)])
                                    if flag == 1:
                                        line_amount = lines.get('LineAmount') - lines.get('TaxAmount')
                                        unit_amount = line_amount / lines.get('Quantity')
                                    else:
                                        line_amount = lines.get('LineAmount')
                                        unit_amount = lines.get('UnitAmount')

                                    if lines.get('TaxType'):
                                        tax_id = tax_pool.search([('xero_tax_type', '=', lines.get('TaxType')),('company_id', '=', company)])
                                    else:
                                        tax_id = False

                                    acc = account_pool.search([('code', '=', lines.get('AccountCode')),('company_id', '=', company)])
                                    if not acc and invoice.get('Type') == 'ACCREC':
                                        acc = self.env['ir.property'].get('property_account_income_categ_id', 'product.category')
                                    elif not acc and invoice.get('Type') == 'ACCPAY':
                                        acc = self.env['ir.property'].get('property_account_expense_categ_id', 'product.category')
                                    if line:
                                        if lines.get('ItemCode'):
                                            if without_product:
                                                vals = {'name': lines.get('Description') or 'Didn\'t specify',
                                                        'price_unit': unit_amount or 0.0,
                                                        'company_id': company,
                                                        'tax_ids': [(6, 0, [tax_id.id])] if tax_id else [],
                                                        'quantity': lines.get('Quantity') or 1,
                                                        'discount': lines.get('DiscountRate') or 0.0,
                                                        'xero_invoice_line_id': lines.get('LineItemID'),
                                                        'move_id': invoice_res[0].id,
                                                        }
                                                if acc:
                                                    vals.update({'account_id': acc and acc.id})
                                                    line.with_context({'check_move_validity': False, 'line_amount_type': invoice.get('LineAmountTypes')}).write(vals)
                                                    line.with_context({'check_move_validity': False, 'line_amount_type': invoice.get('LineAmountTypes')})._onchange_mark_recompute_taxes()

                                            elif not without_product:
                                                product = product_pool.search([('default_code', '=', lines.get('ItemCode'))])
                                                if not product:
                                                    raise Warning("Please First Import Product.")
                                                for product_id in product:
                                                    inv_line_val = {'name': lines.get('Description') or product_id.description or 'Didn\'t specify',
                                                                    'price_unit': unit_amount or product_id.lst_price,
                                                                    'tax_base_amount': unit_amount or product_id.lst_price,
                                                                    'quantity': lines.get('Quantity') or 1,
                                                                    'company_id': company,
                                                                    'product_id': product_id and product_id.id or False,
                                                                    'tax_ids': [(6, 0, [tax_id.id])] if tax_id else [],
                                                                    'discount': lines.get('DiscountRate') or 0.0,
                                                                    'xero_invoice_line_id': lines.get('LineItemID'),
                                                                    'move_id': invoice_res[0].id,
                                                                    }
                                                    if acc:
                                                        inv_line_val.update({'account_id': acc and acc.id})
                                                        line.with_context({'check_move_validity': False, 'line_amount_type': invoice.get('LineAmountTypes')}).write(inv_line_val)
                                                        line.with_context({'check_move_validity': False, 'line_amount_type': invoice.get('LineAmountTypes')})._onchange_mark_recompute_taxes()

                                        else:
                                            vals = {'name': lines.get('Description') or 'Didn\'t specify',
                                                    'price_unit': unit_amount or 0.0,
                                                    'company_id': company,
                                                    'tax_ids': [(6, 0, [tax_id.id])] if tax_id else [],
                                                    'quantity': lines.get('Quantity') or 1,
                                                    'discount': lines.get('DiscountRate') or 0.0,
                                                    'xero_invoice_line_id': lines.get('LineItemID'),
                                                    'move_id': invoice_res[0].id,
                                                    }
                                            if acc:
                                                vals.update({'account_id': acc and acc.id})
                                                line.with_context({'check_move_validity': False, 'line_amount_type': invoice.get('LineAmountTypes')}).write(vals)
                                                line.with_context({'check_move_validity': False, 'line_amount_type': invoice.get('LineAmountTypes')})._onchange_mark_recompute_taxes()

                                    else:
                                        if lines.get('ItemCode'):
                                            if without_product:
                                                vals = {'name': lines.get('Description') or 'Didn\'t specify',
                                                        'price_unit': unit_amount or 0.0,
                                                        'company_id': company,
                                                        'tax_ids': [(6, 0, [tax_id.id])] if tax_id else [],
                                                        'quantity': lines.get('Quantity') or 1,
                                                        'discount': lines.get('DiscountRate') or 0.0,
                                                        'xero_invoice_line_id': lines.get('LineItemID'),
                                                        'move_id': invoice_res[0].id,
                                                        }
                                                if acc:
                                                    vals.update({'account_id': acc and acc.id})
                                                    line_items.append(vals)
                                            elif not without_product:
                                                product = product_pool.search([('default_code', '=', lines.get('ItemCode'))])
                                                if not product:
                                                    raise Warning("Please First Import Product.")
                                                for product_id in product:
                                                    inv_line_val = {'name': lines.get('Description') or product_id.description or 'Didn\'t specify',
                                                                    'price_unit': unit_amount or product_id.lst_price,
                                                                    'quantity': lines.get('Quantity') or 1,
                                                                    'company_id': company,
                                                                    'product_id': product_id and product_id.id or False,
                                                                    'tax_ids': [(6, 0, [tax_id.id])] if tax_id else [],
                                                                    'discount': lines.get('DiscountRate') or 0.0,
                                                                    'xero_invoice_line_id': lines.get('LineItemID'),
                                                                    'move_id': invoice_res[0].id,
                                                                    }
                                                    if acc:
                                                        inv_line_val.update({'account_id': acc and acc.id})
                                                        line_items.append(inv_line_val)
                                        else:
                                            vals = {'name': lines.get('Description') or 'Didn\'t specify',
                                                    'price_unit': unit_amount or 0.0,
                                                    'company_id': company,
                                                    'tax_ids': [(6, 0, [tax_id.id])] if tax_id else [],
                                                    'quantity': lines.get('Quantity') or 1,
                                                    'discount': lines.get('DiscountRate') or 0.0,
                                                    'xero_invoice_line_id': lines.get('LineItemID'),
                                                    'move_id': invoice_res[0].id,
                                                    }
                                            if acc:
                                                vals.update({'account_id': acc and acc.id})
                                                line_items.append(vals)

                                if line_items:
                                    line_ids = inv_line_pool.with_context({'check_move_validity': False, 'line_amount_type': invoice.get('LineAmountTypes')}).create(line_items)

                                if invoice['Type'] == 'ACCREC':
                                    xero_type = 'out_invoice'
                                else:
                                    xero_type = 'in_invoice'

                                partner = partner_pool.search(['|', ('company_id', '=', company), ('company_id', '=', False)]).filtered(lambda partner: partner.contact_xero_company_ids.filtered(lambda contact: contact.xero_contact_id == invoice.get('Contact').get('ContactID') and contact.company_id.id == company))
                                if not partner:
                                    xero_account.import_contact_overwrite() if xero_account.contact_overwrite else xero_account.import_contact()
                                    partner = partner_pool.search(['|', ('company_id', '=', company), ('company_id', '=', False)]).filtered(lambda partner: partner.contact_xero_company_ids.filtered(lambda contact: contact.xero_contact_id == invoice.get('Contact').get('ContactID') and contact.company_id.id == company))

                                currency_id = currency_pool.search([('name', '=', invoice.get('CurrencyCode'))])

                                vals = {
                                    'partner_id': partner and partner[0].id or False,
                                    'currency_id': currency_id and currency_id.id or False,
                                    'invoice_date': invoice.get('DateString'),
                                    'invoice_date_due': invoice.get('DueDateString'),
                                    'xero_invoice_id': invoice.get('InvoiceID'),
                                    'xero_invoice_number': invoice.get('InvoiceNumber'),
                                    'amount_tax': invoice.get('TotalTax'),
                                    'type': xero_type,
                                    'company_id': company,
                                    'line_amount_type': invoice.get('LineAmountTypes'),
                                }
                                context = dict(self.env.context)
                                context.update({'check_move_validity': False, 'line_amount_type': invoice.get('LineAmountTypes')})
                                self.env.context = context
                                invoice_res[0].write(vals)
                                if context.get('check_move_validity'):
                                    del context['check_move_validity']
                                    self.env.context = context
                                invoice_res[0]._compute_amount()
                                for invoice_lines in invoice_res[0].invoice_line_ids:
                                    if invoice_lines.xero_invoice_line_id not in available_lines:
                                        invoice_lines.unlink()
                                invoice_res[0].with_context({'check_move_validity': False, 'line_amount_type': invoice.get('LineAmountTypes')})._recompute_dynamic_lines(recompute_all_taxes=True)
                                invoice_res[0].with_context({'line_amount_type': invoice.get('LineAmountTypes')})._onchange_invoice_line_ids()
                                invoice_res[0].with_context({'line_amount_type': invoice.get('LineAmountTypes')})._compute_invoice_taxes_by_group()
                                # invoice_res[0]._onchange_currency()
                        if invoice.get('Status') == 'AUTHORISED' and invoice_res[0].state in ['draft', 'posted'] and invoice_res[0].invoice_line_ids:
                            if invoice_res[0].state == 'draft':
                                invoice_res[0].with_context({'CurrencyRate': invoice.get('CurrencyRate')}).action_post()
                            if invoice.get('AmountPaid') != 0.0 or invoice.get('Total') !=  invoice.get('AmountDue'):
                                if invoice_res[0].type in ('out_invoice', 'out_refund') and invoice.get('Type') == 'ACCREC':
                                    self.pay_invoice(xero_account_id, xero, invoice_res[0].partner_id, invoice, invoice_res[0], type='out_invoice', company=company)
                                else:
                                    self.pay_invoice(xero_account_id, xero, invoice_res[0].partner_id, invoice, invoice_res[0], type='out_invoice', company=company)
                        if invoice.get('Status') == 'PAID' and invoice_res[0].state in ['draft', 'posted'] and invoice_res[0].invoice_line_ids:
                            if invoice_res[0].state == 'draft':
                                invoice_res[0].with_context({'CurrencyRate': invoice.get('CurrencyRate')}).action_post()
                            if invoice_res[0].type in ('out_invoice', 'out_refund') and invoice.get('Type') == 'ACCREC':
                                self.pay_invoice(xero_account_id, xero, invoice_res[0].partner_id, invoice, invoice_res[0], type='out_invoice', company=company)
                            else:
                                self.pay_invoice(xero_account_id, xero, invoice_res[0].partner_id, invoice, invoice_res[0], type='out_invoice', company=company)

                elif not invoice_res and import_option in ['create', 'both']:
                    flag = 0
                    if invoice and invoice.get('Status') not in ['DELETED', 'VOIDED']:
                        partner = partner_pool.search(['|', ('company_id', '=', company), ('company_id', '=', False)]).filtered(lambda partner: partner.contact_xero_company_ids.filtered(lambda contact: contact.xero_contact_id == invoice.get('Contact').get('ContactID') and contact.company_id.id == company))
                        if not partner:
                            xero_account.import_contact_overwrite() if xero_account.contact_overwrite else xero_account.import_contact()
                            partner = partner_pool.search(['|', ('company_id', '=', company), ('company_id', '=', False)]).filtered(lambda partner: partner.contact_xero_company_ids.filtered(lambda contact: contact.xero_contact_id == invoice.get('Contact').get('ContactID') and contact.company_id.id == company))

                        invoice_lines = []
                        sub_tax = invoice.get('SubTotal') + invoice.get('TotalTax')
                        if float("%.2f"%sub_tax) != invoice.get('Total'):
                            flag = 1

                        for lines in invoice.get('LineItems'):
                            acc = account_pool.search([('code', '=', lines.get('AccountCode')),('company_id', '=', company)])
                            if not acc and invoice.get('Type') == 'ACCREC':
                                acc = self.env['ir.property'].get('property_account_income_categ_id', 'product.category')
                            elif not acc and invoice.get('Type') == 'ACCPAY':
                                acc = self.env['ir.property'].get('property_account_expense_categ_id', 'product.category')

                            if flag == 1:
                                line_amount = lines.get('LineAmount') - lines.get('TaxAmount')
                                unit_amount = line_amount / lines.get('Quantity')
                            else:
                                line_amount = lines.get('LineAmount')
                                unit_amount = lines.get('UnitAmount')

                            if lines.get('TaxType'):
                                tax_id = tax_pool.search([('xero_tax_type', '=', lines.get('TaxType')),('company_id', '=', company)])
                            else:
                                tax_id = False

                            if lines.get('ItemCode'):
                                if without_product:
                                    vals = {'name': lines.get('Description') or 'Didn\'t specify',
                                            'price_unit': unit_amount or 0.0,
                                            'company_id': company,
                                            'tax_ids': [(6, 0, [tax_id.id])] if tax_id else [],
                                            'account_id': acc and acc.id or False,
                                            'quantity': lines.get('Quantity') or 1,
                                            'discount': lines.get('DiscountRate') or 0.0,
                                            'xero_invoice_line_id': lines.get('LineItemID'),
                                            }
                                    if acc:
                                        vals.update({'account_id': acc and acc.id})
                                        invoice_lines.append((0, 0, vals))

                                elif not without_product:
                                    product = product_pool.search([('default_code', '=', lines.get('ItemCode'))])
                                    if not product:
                                        raise Warning("Please First Import Product.")
                                    for product_id in product:
                                        inv_line_val = {'name': lines.get('Description') or product_id.description or 'Didn\'t specify',
                                                        'price_unit': unit_amount,
                                                        'company_id': company,
                                                        'quantity': lines.get('Quantity') or 1,
                                                        'product_id': product_id and product_id.id or False,
                                                        'tax_ids': [(6, 0, [tax_id.id])] if tax_id else [],
                                                        'discount': lines.get('DiscountRate') or 0.0,
                                                        'xero_invoice_line_id': lines.get('LineItemID'),
                                                        }
                                        if acc:
                                            inv_line_val.update({'account_id': acc.id})
                                            invoice_lines.append((0, 0, inv_line_val))
                            else:
                                vals = {'name': lines.get('Description') or 'Didn\'t specify',
                                        'price_unit': unit_amount or 0.0,
                                        'company_id': company,
                                        'tax_ids': [(6, 0, [tax_id.id])] if tax_id else [],
                                        'account_id': acc and acc.id or False,
                                        'quantity': lines.get('Quantity') or 1,
                                        'discount': lines.get('DiscountRate') or 0.0,
                                        'xero_invoice_line_id': lines.get('LineItemID'),
                                        }
                                if acc:
                                    vals.update({'account_id': acc and acc.id})
                                    invoice_lines.append((0, 0, vals))

                        if invoice['Type'] == 'ACCREC':
                            xero_type = 'out_invoice'
                        else:
                            xero_type = 'in_invoice'

                        currency_id = currency_pool.search([('name', '=', invoice.get('CurrencyCode'))])
                        if invoice.get('Type') == 'ACCREC':
                            journal_id = customer_inv_journal_id
                        elif invoice.get('Type') == 'ACCPAY':
                            journal_id = vendor_bill_journal_id
                        inv_default = {'partner_id': partner and partner.id or False,
                                       'currency_id': currency_id and currency_id[0].id or False,
                                       'company_id': company,
                                       'journal_id': journal_id and journal_id.id or False,
                                       'invoice_date': invoice.get('DateString'),
                                       'invoice_date_due': invoice.get('DueDateString'),
                                       'xero_invoice_id': invoice.get('InvoiceID'),
                                       'xero_invoice_number': invoice.get('InvoiceNumber'),
                                       'amount_tax': invoice.get('TotalTax'),
                                       'type': xero_type,
                                       'line_amount_type':invoice.get('LineAmountTypes'),
                                       }
                        invoice_type = self.env.context.copy()
                        invoice_type.update({'type': xero_type, 'line_amount_type': invoice.get('LineAmountTypes')})
                        if invoice_lines:
                            inv_default.update({'invoice_line_ids': invoice_lines})

                        inv_id = inv_pool.with_context(invoice_type).create(inv_default)
                        inv_id._compute_amount()
                        inv_id._onchange_invoice_line_ids()
                        inv_id._onchange_currency()
                        self._cr.commit()
                        if inv_id and invoice.get('Status') in ['AUTHORISED', 'PAID'] and inv_id.invoice_line_ids:
                            if inv_id.state == 'draft':
                                inv_id.with_context({'CurrencyRate': invoice.get('CurrencyRate')}).action_post()

                            if inv_id and invoice.get('Status') == 'AUTHORISED':
                                if invoice.get('AmountPaid') != 0.0 or invoice.get('Total') !=  invoice.get('AmountDue'):
                                    if inv_id.type in ['out_invoice', 'out_refund']:
                                        self.pay_invoice(xero_account_id, xero, inv_id.partner_id, invoice, inv_id, type='out_invoice', company=company)
                                    else:
                                        self.pay_invoice(xero_account_id, xero, inv_id.partner_id, invoice, inv_id, type='out_invoice', company=company)
                            if inv_id and invoice.get('Status') == 'PAID':
                                if inv_id.type in ['out_invoice', 'out_refund']:
                                    self.pay_invoice(xero_account_id, xero, inv_id.partner_id, invoice, inv_id, type='out_invoice', company=company)
                                else:
                                    self.pay_invoice(xero_account_id, xero, inv_id.partner_id, invoice, inv_id, type='out_invoice', company=company)

    def import_credit_notes(self, xero_account_id,credit_notes_list, xero, company=False, without_product=False, import_option=None, customer_inv_journal_id=False, vendor_bill_journal_id=False):
        partner_pool = self.env['res.partner']
        currency_pool = self.env['res.currency']
        account_pool = self.env['account.account']
        product_pool = self.env['product.product']
        ir_property_pool = self.env['ir.property']
        tax_pool = self.env['account.tax']
        # xero_account = self.env['xero.account'].search([('company_id', '=', company)], limit=1)
        xero_account = self.env['xero.account'].browse(xero_account_id)
        for credit_note in credit_notes_list:
            InvoiceData = {}
            if credit_note.get('Total') != 0.0:
                current_credit_note = self.search([('xero_invoice_id', '=', credit_note.get('CreditNoteID')), ('xero_invoice_number','=', credit_note.get('CreditNoteNumber')), ('company_id', '=', company)], limit=1)

                if current_credit_note and current_credit_note.state == 'draft' and import_option in ['update', 'both']:
                    current_credit_note.invoice_line_ids.with_context({'check_move_validity': False}).unlink()
                invoice_type = 'out_refund' if credit_note['Type'] == 'ACCRECCREDIT' else 'in_refund'
                if current_credit_note.state == 'draft' or not current_credit_note:
                    customer = partner_pool.search(['|', ('company_id', '=', company), ('company_id', '=', False)]).filtered(lambda partner: partner.contact_xero_company_ids.filtered(lambda contact: contact.xero_contact_id == credit_note.get('Contact').get('ContactID') and contact.company_id.id == company))
                    if not customer:
                        xero_account.import_contact_overwrite() if xero_account.contact_overwrite else xero_account.import_contact()
                        customer = partner_pool.search(['|', ('company_id', '=', company), ('company_id', '=', False)]).filtered(lambda partner: partner.contact_xero_company_ids.filtered(lambda contact: contact.xero_contact_id == credit_note.get('Contact').get('ContactID') and contact.company_id.id == company))

                    if credit_note.get('Type') == 'ACCRECCREDIT':
                        journal_id = customer_inv_journal_id
                    elif credit_note.get('Type') == 'ACCPAYCREDIT':
                        journal_id = vendor_bill_journal_id
                    currency_id = currency_pool.search([('name', '=', credit_note.get('CurrencyCode'))], limit=1)
                    InvoiceData.update({'partner_id': customer.id or False,
                                        'currency_id': currency_id and currency_id.id or False,
                                        'invoice_date': credit_note.get('DateString'),
                                        'invoice_date_due': credit_note.get('DueDateString'),
                                        'xero_invoice_number': credit_note.get('CreditNoteNumber'),
                                        'xero_invoice_id': credit_note.get('CreditNoteID'),
                                        'amount_tax': credit_note.get('TotalTax'),
                                        'type': invoice_type,
                                        'journal_id': journal_id and journal_id.id or False,
                                        'company_id': company,
                                        'invoice_line_ids': [],
                                        'line_amount_type': credit_note.get('LineAmountTypes')})

                    invoice_lines = []
                    for line in credit_note.get('LineItems'):
                        product_id = False
                        account_id = account_pool.search([('code', '=', line.get('AccountCode')), ('company_id', '=', company)], limit=1)
                        if line.get('ItemCode'):
                            product_id = product_pool.search([('default_code', '=', line.get('ItemCode'))], limit=1)
                        if product_id:
                            if credit_note['Type'] == 'ACCRECCREDIT':
                                account_id = product_id.property_account_income_id or product_id.categ_id.property_account_income_categ_id
                            else:
                                account_id = product_id.property_account_expense_id or product_id.categ_id.property_account_expense_categ_id
                        if not account_id and credit_note['Type'] == 'ACCRECCREDIT':
                            account_id = ir_property_pool.get('property_account_income_categ_id', 'product.category')
                        elif not account_id and credit_note['Type'] == 'ACCPAYCREDIT':
                            account_id = ir_property_pool.get('property_account_expense_categ_id', 'product.category')

                        if line.get('TaxType'):
                            tax_id = tax_pool.search([('xero_tax_type', '=', line.get('TaxType')), ('company_id', '=', company)], limit=1)

                        if line.get('ItemCode'):
                            if without_product:
                                inv_line_data = {
                                        'name': line.get('Description') or 'Didn\'t specify',
                                        'price_unit': line.get('UnitAmount') or 0.0,
                                        'company_id': company,
                                        'tax_ids': [(6, 0, [tax_id.id])] if tax_id else [],
                                        'account_id': account_id.id,
                                        'quantity': line.get('Quantity') or 1}
                                invoice_lines.append((0, 0, inv_line_data))
                            elif not without_product:
                                if not product_id:
                                    raise Warning("Please First Import Product.")
                                inv_line_data = {
                                        'product_id': product_id.id,
                                        'name': (line.get('Description') or product_id.description or product_id.name),
                                        'price_unit': line.get('UnitAmount') or 0.0,
                                        'company_id': company,
                                        'tax_ids': [(6, 0, [tax_id.id])] if tax_id else [],
                                        'account_id': account_id.id,
                                        'quantity': line.get('Quantity') or 1}
                                invoice_lines.append((0, 0, inv_line_data))
                        else:
                            inv_line_data = {
                                        'name': line.get('Description') or 'Didn\'t specify',
                                        'price_unit': line.get('UnitAmount') or 0.0,
                                        'company_id': company,
                                        'tax_ids': [(6, 0, [tax_id.id])] if tax_id else [],
                                        'account_id': account_id.id,
                                        'quantity': line.get('Quantity') or 1}
                            invoice_lines.append((0, 0, inv_line_data))

                    InvoiceData.update({'invoice_line_ids': invoice_lines})
                if current_credit_note and import_option in ['update', 'both']:
                    if current_credit_note.state == 'posted' and credit_note.get('Status') == 'VOIDED':
                        current_credit_note.button_draft()
                    if current_credit_note.state == 'draft' and credit_note.get('Status') in ['DELETED', 'VOIDED']:
                        current_credit_note.button_cancel()
                    if current_credit_note.state != 'cancel' and current_credit_note.invoice_payment_state != 'paid':
                        context = self.env.context.copy()
                        context.update({'type': invoice_type, 'check_move_validity': False, 'line_amount_type': credit_note.get('LineAmountTypes')})
                        current_credit_note.with_context(context).write(InvoiceData)
                        current_credit_note._compute_amount()
                        current_credit_note._onchange_invoice_line_ids()
                        self._cr.commit()
                elif not current_credit_note and import_option in ['create', 'both']:
                    if credit_note.get('Status') not in ['VOIDED', 'DELETED']:
                        context = self.env.context.copy()
                        context.update({'type': invoice_type, 'check_move_validity': False, 'line_amount_type': credit_note.get('LineAmountTypes')})
                        current_credit_note = self.with_context(context).create(InvoiceData)
                        current_credit_note._compute_amount()
                        current_credit_note._onchange_invoice_line_ids()
                        self._cr.commit()

                if current_credit_note.state != 'cancel' and current_credit_note.invoice_payment_state != 'paid':
                    if credit_note.get('Status') in ['AUTHORISED', 'PAID'] and current_credit_note.invoice_line_ids:
                        if current_credit_note.state == 'draft':
                            current_credit_note.with_context({'CurrencyRate': credit_note.get('CurrencyRate')}).post()
                        if credit_note.get('Payments'):
                            self.pay_invoice(xero_account_id, xero, current_credit_note.partner_id, credit_note, current_credit_note, type=current_credit_note.type, company=company)
                        if credit_note.get('Allocations') and credit_note.get('Status') == 'PAID':
                            self.pay_creditnote(xero, current_credit_note.partner_id, credit_note, current_credit_note, type=current_credit_note.type, company=company)

    def import_manual_journal(self, journal_list, xero, company=False, import_option=None):
        tax_pool = self.env['account.tax']
        move_line_pool = self.env['account.move.line']
        for journal in journal_list:
            journal_res = self.search([('xero_manual_journal_id', '=', journal.get('ManualJournalID'))], limit=1)

            if journal_res and journal_res.state == 'draft' and import_option in ['update', 'both'] and journal.get('Status') in ['DRAFT', 'POSTED']:
                journal_res.write({
                    'date': journal.get('Date'),
                    'ref': journal.get('Narration'),
                    'line_amount_type': journal.get('LineAmountTypes'),
                    })
                journal_line_list = []

                journal_res.line_ids.unlink()
                for line_id in journal.get('JournalLines'):
                    account = self.env['account.account'].search([('code', '=', line_id.get('AccountCode')), ('company_id', '=', company)], limit=1)
                    if not account:
                        _logger.info("Account Code '%s' is not available. Please First Import Chart of Account.", line_id.get('AccountCode'))
                        raise Warning(("Account Code '%s' is not available. Please First Import Chart of Account.") % line_id.get('AccountCode'))

                    credit = debit = 0
                    if journal.get('LineAmountTypes') == 'Exclusive':
                        if '-' in str(line_id.get('LineAmount')):
                            credit = abs(line_id.get('LineAmount'))
                        else:
                            debit = line_id.get('LineAmount')

                        credit_tax_amount = debit_tax_amount = 0
                        journal_line = {}
                        if line_id.get('TaxType') and line_id.get('TaxAmount') != 0:
                            tax_id = tax_pool.search([('xero_tax_type', '=', line_id.get('TaxType')), ('company_id', '=', company)], limit=1)
                            journal_line = {'tax_ids': [(6, 0, tax_id.ids)]}
                            if '-' in str(line_id.get('TaxAmount')):
                                credit_tax_amount = abs(line_id.get('TaxAmount'))
                            else:
                                debit_tax_amount = line_id.get('TaxAmount')

                            for tax in tax_id.invoice_repartition_line_ids:
                                if tax.repartition_type == 'tax':
                                    journal_line_list.append((0, 0, {
                                      'account_id': tax.account_id.id if tax.account_id else account.id,
                                      'name': tax_id[0].name,
                                      'debit': debit_tax_amount,
                                      'credit': credit_tax_amount,
                                      'move_id': journal_res.id,
                                      }))

                    elif journal.get('LineAmountTypes') == 'Inclusive':
                        credit_tax_amount = debit_tax_amount = 0
                        journal_line = {}
                        if line_id.get('TaxType') and line_id.get('TaxAmount') != 0:
                            tax_id = tax_pool.search([('xero_tax_type', '=', line_id.get('TaxType')), ('company_id', '=', company)])
                            journal_line = {'tax_ids': [(6, 0, tax_id.ids)]}
                            if '-' in str(line_id.get('TaxAmount')):
                                credit_tax_amount = abs(line_id.get('TaxAmount'))
                            else:
                                debit_tax_amount = line_id.get('TaxAmount')

                            for tax in tax_id.invoice_repartition_line_ids:
                                if tax.repartition_type == 'tax':
                                    journal_line_list.append((0, 0, {
                                      'account_id': tax.account_id.id if tax.account_id else account.id,
                                      'name': tax_id[0].name,
                                      'debit': debit_tax_amount,
                                      'credit': credit_tax_amount,
                                      'move_id': journal_res.id,
                                      }))
                        if '-' in str(line_id.get('LineAmount')):
                            credit = abs(line_id.get('LineAmount')) - credit_tax_amount
                        else:
                            debit = line_id.get('LineAmount') - debit_tax_amount

                    elif journal.get('LineAmountTypes') == 'NoTax':
                        journal_line = {}
                        credit = debit = 0
                        if '-' in str(line_id.get('LineAmount')):
                            credit = abs(line_id.get('LineAmount'))
                        else:
                            debit = line_id.get('LineAmount')

                    journal_line.update({
                          'account_id': account.id,
                          'name': line_id.get('Description'),
                          'debit': debit,
                          'credit': credit,
                          'move_id': journal_res.id,
                          })

                    journal_line_list.append((0, 0, journal_line))
                journal_res.write({'line_ids': journal_line_list})
                journal_res._onchange_recompute_dynamic_lines()

                if journal.get('Status').lower() == 'posted':
                    # super(AccountMove, journal_res).post()
                    journal_res.post()
                self._cr.commit()

            elif not journal_res and import_option in ['create', 'both'] and journal.get('Status') in ['DRAFT','POSTED']:
                xero_account_id = self.env['xero.account'].search([('company_id', '=', company)], limit=1)
                journal_id = self.create({
                    'date': journal.get('Date'),
                    'ref': journal.get('Narration'),
                    'line_amount_type': journal.get('LineAmountTypes'),
                    'journal_id': xero_account_id.miscellaneous_operations_journal_id.id,
                    'xero_manual_journal_id': journal.get('ManualJournalID'),
                    'is_manual_journal': True,
                    })

                journal_line_list = []
                for line_id in journal.get('JournalLines'):
                    account = self.env['account.account'].search([('code', '=', line_id.get('AccountCode')),('company_id', '=', company)], limit=1)

                    if not account:
                        _logger.info("Account Code '%s' is not available. Please First Import Chart of Account.",line_id.get('AccountCode'))
                        raise Warning(("Account Code '%s' is not available. Please First Import Chart of Account.") % line_id.get('AccountCode'))

                    credit = debit = 0

                    if journal.get('LineAmountTypes') == 'Exclusive':
                        if '-' in str(line_id.get('LineAmount')):
                            credit = abs(line_id.get('LineAmount'))
                        else:
                            debit = line_id.get('LineAmount')

                        credit_tax_amount = debit_tax_amount = 0
                        journal_line = {}
                        if line_id.get('TaxType') and line_id.get('TaxAmount') != 0:
                            tax_id = tax_pool.search([('xero_tax_type', '=', line_id.get('TaxType')),('company_id', '=', company)], limit=1)
                            journal_line = {'tax_ids': [(6, 0, tax_id.ids)]}
                            if '-' in str(line_id.get('TaxAmount')):
                                credit_tax_amount = abs(line_id.get('TaxAmount'))
                            else:
                                debit_tax_amount = line_id.get('TaxAmount')

                            for tax in tax_id.invoice_repartition_line_ids:
                                if tax.repartition_type == 'tax':
                                    journal_line_list.append((0, 0, {
                                      'account_id': tax.account_id.id if tax.account_id else account.id,
                                      'name': tax_id.name,
                                      'debit': debit_tax_amount,
                                      'credit': credit_tax_amount,
                                      'move_id': journal_id.id,
                                      }))

                    elif journal.get('LineAmountTypes') == 'Inclusive':
                        credit_tax_amount = debit_tax_amount = 0
                        journal_line = {}
                        if line_id.get('TaxType') and line_id.get('TaxAmount') != 0:
                            tax_id = tax_pool.search([('xero_tax_type', '=', line_id.get('TaxType')),('company_id', '=', company)], limit=1)
                            journal_line = {'tax_ids': [(6, 0, tax_id.ids)]}

                            if '-' in str(line_id.get('TaxAmount')):
                                credit_tax_amount = abs(line_id.get('TaxAmount'))
                            else:
                                debit_tax_amount = line_id.get('TaxAmount')

                            for tax in tax_id.invoice_repartition_line_ids:
                                if tax.repartition_type == 'tax':
                                    journal_line_list.append((0, 0, {
                                      'account_id': tax.account_id.id if tax.account_id else account.id,
                                      'name': tax_id.name,
                                      'debit': debit_tax_amount,
                                      'credit': credit_tax_amount,
                                      'move_id': journal_id.id,
                                      }))
                        if '-' in str(line_id.get('LineAmount')):
                            credit = abs(line_id.get('LineAmount')) - credit_tax_amount
                        else:
                            debit = line_id.get('LineAmount') - debit_tax_amount

                    elif journal.get('LineAmountTypes') == 'NoTax':
                        credit = debit = 0
                        journal_line = {}
                        if '-' in str(line_id.get('LineAmount')):
                            credit = abs(line_id.get('LineAmount'))
                        else:
                            debit = line_id.get('LineAmount')

                    journal_line.update({'account_id': account.id,
                                         'name': line_id.get('Description'),
                                         'debit': debit,
                                         'credit': credit,
                                         'move_id': journal_id.id,
                                         })
                    journal_line_list.append((0, 0, journal_line))

                journal_id.write({'line_ids': journal_line_list})
                journal_id._onchange_recompute_dynamic_lines()
                if journal.get('Status').lower() == 'posted':
                    # super(AccountMove, journal_id).post()
                    journal_id.post()
                self._cr.commit()

    def export_invoice(self, invoice_list, xero, last_export_date, company=False, disable_export=False):
        xero_account = self.env['xero.account'].search([('company_id', '=', company)], limit=1)
        if self._context.get('invoice_ids'):
            invoice_ids = self._context.get('invoice_ids')
        else:
            if last_export_date:
                invoice_ids = self.search([('company_id', '=', company),
                                           ('able_to_xero_export', '=', True),
                                           ('type', 'in', ['out_invoice', 'in_invoice']),
                                           ('state', '!=', 'cancel'),
                                           '|', ('write_date', '>=', last_export_date),
                                           ('create_date', '>=', last_export_date)])
            else:
                invoice_ids = self.search([('company_id', '=', company),
                                           ('able_to_xero_export', '=', True),
                                           ('type', 'in', ['out_invoice', 'in_invoice']),
                                           ('state', '!=', 'cancel')])
        update_invoice_data = []
        update_invoice_data_list = []
        create_invoice_data = []
        create_invoice_data_list = []
        count = 0
        c = 0
        request = 0
        for invoice_id in invoice_ids:
            if invoice_id.type == 'out_invoice':
                type = u'ACCREC'
            elif invoice_id.type == 'in_invoice':
                type = u'ACCPAY'
            if not invoice_id.partner_id:
                description = 'Customer must be set for export (Odoo to Xero)'
                mismatch_vals = {'name': invoice_id.type,
                                 'source_model': 'account.move',
                                 'source_id': invoice_id.id,
                                 'description': description,
                                 'exported_date': datetime.datetime.now()
                                 }
                self.env['mismatch.log'].create(mismatch_vals)
                continue
            if invoice_id.xero_invoice_id:
                for xero_inv in invoice_list:
                    if xero_inv.get('InvoiceID') == invoice_id.xero_invoice_id and xero_inv.get('Status') in ['DRAFT','SUBMITTED'] :
                        invoice_currency_rate = 0.0
                        status = u'DRAFT'
                        if invoice_id.state == 'draft':
                            status = u'DRAFT'
                        elif invoice_id.state == 'posted':
                            status = u'AUTHORISED'
                            if invoice_id.currency_id.id != invoice_id.company_id.currency_id.id:
                                if invoice_id.type == 'out_invoice':
                                    if not invoice_id.line_ids[0].amount_currency == 0.0 and not invoice_id.line_ids[0].debit == 0.0:
                                        invoice_currency_rate = abs(invoice_id.line_ids[0].amount_currency / invoice_id.line_ids[0].debit)
                                else:
                                    if not invoice_id.line_ids[0].amount_currency == 0.0 and not invoice_id.line_ids[0].credit == 0.0:
                                        invoice_currency_rate = abs(invoice_id.line_ids[0].amount_currency / invoice_id.line_ids[0].credit)

                        line_amount_type = invoice_id.line_amount_type

                        if invoice_id.partner_id.parent_id:
                            contact = invoice_id.partner_id.parent_id.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company)

                            if contact.xero_contact_id:
                                contact_id = {u'ContactID': contact.xero_contact_id}
                        else:
                            contact = invoice_id.partner_id.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                            if contact.xero_contact_id:
                                contact_id = {u'ContactID': contact.xero_contact_id}

                        invoice_data = {u'Type': type,
                                        u'InvoiceID': invoice_id.xero_invoice_id,
                                        u'Status': status,
                                        u'LineAmountTypes': line_amount_type,
                                        u'Contact': contact_id,
                                        u'Date': invoice_id.invoice_date or fields.Date.today(),
                                        u'DueDate': invoice_id.invoice_date_due or fields.Date.today(),
                                        u'CurrencyCode': invoice_id.currency_id.name,
                                        }
                        if invoice_id.type == 'out_invoice':
                            invoice_data.update({u'Reference': invoice_id.name or u''})
                        elif invoice_id.type == 'in_invoice':
                            invoice_data.update({u'InvoiceNumber': invoice_id.name or u''})

                        if invoice_currency_rate:
                            invoice_data.update({u'CurrencyRate': invoice_currency_rate})
                        line_items = []
                        for inv_line in invoice_id.invoice_line_ids:
                            if inv_line.tax_ids:
                                tax_type = inv_line.tax_ids[0]
                            else:
                                if invoice_id.type == 'out_invoice':
                                    tax_type = self.env['account.tax'].search([('type_tax_use', '=', 'sale'), ('amount', '=', 0), ('company_id', '=', company)], limit=1)
                                    if not tax_type:
                                        company_id = self.env['res.company'].browse(company)
                                        raise UserError(_('Please create account tax of type \'SALE\' and amount = 0.0 for Company: %s')% (company_id.name))
                                else:
                                    tax_type = self.env['account.tax'].search([('type_tax_use', '=', 'purchase'), ('amount', '=', 0), ('company_id', '=', company)], limit=1)
                                    if not tax_type:
                                        company_id = self.env['res.company'].browse(company)
                                        raise UserError(_('Please create account tax of type \'PURCHASE\' and amount = 0.0 for Company: %s')%(company_id.name))
                            if not tax_type.xero_tax_type:
                                tax_rates = xero.taxrates.all()
                                self.env['account.tax'].export_tax(tax_rates, xero, company=company, disable_export=disable_export)
                            if inv_line.xero_invoice_line_id:
                                vals = {u'LineItemID': inv_line.xero_invoice_line_id,
                                        u'AccountCode': inv_line.account_id.code,
                                        u'Description': inv_line.name or inv_line.product_id.name,
                                        u'UnitAmount': inv_line.price_unit,
                                        u'TaxType': u'' if inv_line.move_id.line_amount_type == 'NoTax' else  tax_type and tax_type.xero_tax_type or u'',
                                        u'ValidationErrors': [],
                                        u'Quantity': inv_line.quantity,
                                        }
                            else:
                                vals = {u'AccountCode': inv_line.account_id.code,
                                        u'Description': inv_line.name or inv_line.product_id.name,
                                        u'UnitAmount': inv_line.price_unit,
                                        u'TaxType': u'' if inv_line.move_id.line_amount_type == 'NoTax' else  tax_type and tax_type.xero_tax_type or u'',
                                        u'ValidationErrors': [],
                                        u'Quantity': inv_line.quantity,
                                        }
                            if invoice_id.type == 'out_invoice':
                                vals.update({u'DiscountRate': inv_line.discount or 0.0})

                            if inv_line.product_id:
                                product = inv_line.product_id.product_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                                if not product.xero_item_id:
                                    xero_account.export_product()
                                vals.update({u'ItemCode': inv_line.product_id.default_code})
                            line_items.append(vals)
                        if line_items:
                            invoice_data.update({u'LineItems': line_items})
                        # invoice in draft state individual request
                        if invoice_id.state == 'draft':
                            request += 1
                            if request > 30:
                                time.sleep(1)
                            inv_rec = xero.invoices.save(invoice_data)

                            line_item_ids = []
                            for lines in inv_rec[0].get('LineItems'):
                                line_item_ids.append(lines.get('LineItemID'))
                            index = 0
                            for lines in invoice_id.invoice_line_ids:
                                lines.write({'xero_invoice_line_id': line_item_ids[index], 'move_id': invoice_id.id})
                                index += 1
                            self._cr.commit()
                        else:
                            update_invoice_data.append(invoice_data)
                            count += 1
                            if count == 50:
                                update_invoice_data_list.append(update_invoice_data)
                                update_invoice_data = []
                                count = 0

            elif not invoice_id.xero_invoice_id:
                if invoice_id.state == 'posted':
                    # set state of invoice 'paid' not possible at a time.
                    status = u'AUTHORISED'
                else:
                    status = u'DRAFT'

                invoice_currency_rate = 0.0
                if invoice_id.state == 'posted' and invoice_id.currency_id.id != invoice_id.company_id.currency_id.id:
                    if invoice_id.type == 'out_invoice':
                        if not invoice_id.line_ids[0].amount_currency == 0.0 and not invoice_id.line_ids[0].debit == 0.0:
                            invoice_currency_rate = abs(invoice_id.line_ids[0].amount_currency / invoice_id.line_ids[0].debit)
                    else:
                        if not invoice_id.line_ids[0].amount_currency == 0.0 and not invoice_id.line_ids[0].credit == 0.0:
                            invoice_currency_rate = abs(invoice_id.line_ids[0].amount_currency / invoice_id.line_ids[0].credit)

                line_amount_type = invoice_id.line_amount_type

                partner_details = {}
                if invoice_id.partner_id.parent_id:
                    contact = invoice_id.partner_id.parent_id.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                    if not contact.xero_contact_id:
                        xero_account.export_contact_overwrite() if xero_account.contact_overwrite else xero_account.export_contact()
                    partner_details = {u'ContactID': contact.xero_contact_id}
                else:
                    contact = invoice_id.partner_id.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                    if not contact.xero_contact_id:
                        xero_account.export_contact_overwrite() if xero_account.contact_overwrite else xero_account.export_contact()
                    partner_details = {u'ContactID': contact.xero_contact_id}
                final_invoice_data = {u'Type': type,
                                      u'Contact': partner_details,
                                      # u'Date': invoice_id.invoice_date and datetime.datetime.strftime(invoice_id.invoice_date, "%Y-%m-%d") or datetime.datetime.strftime(fields.Date.today(), "%Y-%m-%d"),
                                      # u'DueDate': invoice_id.invoice_date_due and datetime.datetime.strftime(invoice_id.invoice_date_due, "%Y-%m-%d") or datetime.datetime.strftime(fields.Date.today(), "%Y-%m-%d"),
                                      u'Date': invoice_id.invoice_date or fields.Date.today(),
                                      u'DueDate': invoice_id.invoice_date_due or fields.Date.today(),
                                      u'Status': status,
                                      u'LineAmountTypes': line_amount_type,
                                      u'CurrencyCode': invoice_id.currency_id.name,
                                      }
                if invoice_id.type == 'out_invoice':
                    final_invoice_data.update({u'Reference': invoice_id.name or u''})
                elif invoice_id.type == 'in_invoice':
                    final_invoice_data.update({u'InvoiceNumber': invoice_id.name or u''})

                if invoice_currency_rate:
                    final_invoice_data.update({u'CurrencyRate': invoice_currency_rate})
                if invoice_id.invoice_line_ids:
                    line_items = []
                    for invoice_line in invoice_id.invoice_line_ids:
                        if invoice_line.tax_ids:
                            tax_type = invoice_line.tax_ids[0]
                        else:
                            if invoice_id.type == 'out_invoice':
                                tax_type = self.env['account.tax'].search([('type_tax_use', '=', 'sale'), ('amount', '=', 0), ('company_id', '=', company)], limit=1)
                                if not tax_type:
                                    company_id = self.env['res.company'].browse(company)
                                    raise UserError(_('Please create account tax of type \'SALE\' and amount = 0.0 for Company: %s')% (company_id.name))
                            else:
                                tax_type = self.env['account.tax'].search([('type_tax_use', '=', 'purchase'), ('amount', '=', 0), ('company_id', '=', company)], limit=1)
                                if not tax_type:
                                    company_id = self.env['res.company'].browse(company)
                                    raise UserError(_('Please create account tax of type \'PURCHASE\' and amount = 0.0 for Company: %s')%(company_id.name))
                        if not tax_type.xero_tax_type:
                            tax_rates = xero.taxrates.all()
                            self.env['account.tax'].export_tax(tax_rates, xero, company=company, disable_export=disable_export)
                        vals = {u'AccountCode': invoice_line.account_id.code,
                                u'Description': invoice_line.name or invoice_line.product_id.name,
                                u'UnitAmount': invoice_line.price_unit,
                                u'TaxType': u'' if invoice_line.move_id.line_amount_type == 'NoTax' else  tax_type and tax_type.xero_tax_type or u'',
                                u'ValidationErrors': [],
                                u'Quantity': invoice_line.quantity,
                            }
                        if invoice_id.type == 'out_invoice':
                            vals.update({u'DiscountRate': invoice_line.discount or 0.0})
                        if invoice_line.product_id:
                            product = invoice_line.product_id.product_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                            if not product.xero_item_id:
                                xero_account.export_product()
                            vals.update({u'ItemCode': invoice_line.product_id.default_code})
                        line_items.append(vals)
                    if line_items:
                        final_invoice_data.update({u'LineItems': line_items})

                # invoice draft individual request
                if invoice_id.state == 'draft':
                    request += 1
                    if request > 30:
                        time.sleep(1)
                    inv_rec = xero.invoices.put(final_invoice_data)
                    line_item_ids = []
                    for lines in inv_rec[0].get('LineItems'):
                        line_item_ids.append(lines.get('LineItemID'))
                    index = 0
                    for lines in invoice_id.invoice_line_ids:
                        lines.write({'xero_invoice_line_id': line_item_ids[index], 'move_id': invoice_id.id})
                        index += 1
                    invoice_id.write({'xero_invoice_id': inv_rec[0].get('InvoiceID'), 'xero_invoice_number': inv_rec[0].get('InvoiceNumber')})
                    self._cr.commit()

                else:
                    # invoice request batch process
                    create_invoice_data.append(final_invoice_data)
                    c += 1
                    if c == 50:
                        create_invoice_data_list.append(create_invoice_data)
                        create_invoice_data = []
                        c = 0

        if create_invoice_data:
            create_invoice_data_list.append(create_invoice_data)

        for data in create_invoice_data_list:
            inv_rec = xero.invoices.put(data)
            for inv in inv_rec:
                if inv.get('Type') == 'ACCREC':
                    invoice_id = self.search([('name', '=', inv.get('Reference')), ('company_id', '=', company)])
                else:
                    invoice_id = self.search([('name', '=', inv.get('InvoiceNumber')), ('company_id', '=', company)])
                line_item_ids = []
                for lines in inv.get('LineItems'):
                    line_item_ids.append(lines.get('LineItemID'))
                index = 0
                for lines in invoice_id.invoice_line_ids:
                    lines.write({'xero_invoice_line_id': line_item_ids[index], 'move_id': invoice_id.id})
                    index += 1
                invoice_id.write({'xero_invoice_id': inv.get('InvoiceID'), 'xero_invoice_number': inv.get('InvoiceNumber')})
                self._cr.commit()

        if update_invoice_data:
            update_invoice_data_list.append(update_invoice_data)

        for data in update_invoice_data_list:
            inv_rec = xero.invoices.save(data)
            for inv in inv_rec:
                if inv.get('Type') == 'ACCREC':
                    invoice_id = self.search([('name', '=', inv.get('Reference')), ('type', '=', 'out_invoice'), ('company_id', '=', company)])
                else:
                    invoice_id = self.search([('name', '=', inv.get('InvoiceNumber')), ('type', '=', 'in_invoice'), ('company_id', '=', company)])
                line_item_ids = []
                for lines in inv.get('LineItems'):
                    line_item_ids.append(lines.get('LineItemID'))
                index = 0
                for lines in invoice_id.invoice_line_ids:
                    lines.write({'xero_invoice_line_id': line_item_ids[index], 'move_id': invoice_id.id})
                    index += 1
                self._cr.commit()

    def export_payment(self, xero, company=False, disable_export=False):
        data = []
        payment_data = []
        c = 0
        invoice_ids = self.search([('company_id', '=', company),
                                   ('able_to_xero_export', '=', True),
                                   ('type', 'in', ['out_invoice', 'in_invoice']),
                                   ('state', '!=', 'cancel')])
        for invoice_id in invoice_ids:
            for inv_payment in invoice_id._get_reconciled_info_JSON_values():
                payment = self.env['account.payment'].browse(inv_payment.get('account_payment_id'))
                if not payment.xero_payment_id and payment.state == 'posted':
                    if invoice_id.type == 'out_invoice':
                        payment_type = u'ACCRECPAYMENT'
                        type = u'ACCREC'
                    elif invoice_id.type == 'in_invoice':
                        payment_type = u'ACCPAYPAYMENT'
                        type = u'ACCPAY'
                    if not payment.move_line_ids[0].journal_id.xero_account_id:
                        raise UserError(_('Please select your xero account on payment Journal: %s')%(payment.move_line_ids[0].journal_id.name))
                    if not payment.move_line_ids[0].journal_id.xero_account_id.acc_id:
                        account_list = xero.accounts.all()
                        self.env['account.account'].export_account(account_list, xero, company=company, disable_export=disable_export)
                    if not payment.journal_id.xero_account_id.acc_id:
                        raise UserError(_('Please select correct Xero account for Payment.'))
                    if type == 'ACCREC':
                        if payment.currency_id != payment.company_id.currency_id and payment.currency_id == invoice_id.currency_id:
                            currency_rate = abs(payment.move_line_ids[0].amount_currency / payment.move_line_ids[0].debit)
                        elif payment.currency_id == payment.company_id.currency_id and payment.currency_id != invoice_id.currency_id:
                            currency_rate = abs(payment.move_line_ids[1].amount_currency / payment.move_line_ids[1].debit)
                        elif payment.currency_id and (payment.currency_id != invoice_id.company_id.currency_id or payment.currency_id != invoice_id.currency_id):
                            currency_rate = abs(payment.move_line_ids[1].amount_currency / payment.move_line_ids[1].debit)
                        elif payment.currency_id == payment.company_id.currency_id == invoice_id.currency_id:
                            currency_rate = 1.00
                        else:
                            currency_rate = 1.00
                    else:
                        if payment.currency_id != payment.company_id.currency_id and payment.currency_id == invoice_id.currency_id:
                            currency_rate = abs(payment.move_line_ids[0].amount_currency / payment.move_line_ids[0].credit)
                        elif payment.currency_id == payment.company_id.currency_id and payment.currency_id != invoice_id.currency_id:
                            currency_rate = abs(payment.move_line_ids[1].amount_currency / payment.move_line_ids[1].credit)
                        elif payment.currency_id and (payment.currency_id != invoice_id.company_id.currency_id or payment.currency_id != invoice_id.currency_id):
                            currency_rate = abs(payment.move_line_ids[1].amount_currency / payment.move_line_ids[1].credit)
                        elif payment.currency_id == payment.company_id.currency_id == invoice_id.currency_id:
                            currency_rate = 1.00
                        else:
                            currency_rate = 1.00

                    # if payment.currency_id == invoice_id.currency_id:
                    #     # amount = payment.amount
                    #     amount = inv_payment.get('amount')
                    # else:
                    #     amount = abs(payment.move_line_ids[1].amount_currency)
                    amount = inv_payment.get('amount')

                    if invoice_id.partner_id.parent_id:
                        contact = invoice_id.partner_id.parent_id.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                        if contact.xero_contact_id:
                            contact_id = {
                                u'ContactID': contact.xero_contact_id,
                                u'Name': invoice_id.partner_id.parent_id.name or False
                                }
                    else:
                        contact = invoice_id.partner_id.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                        if contact.xero_contact_id:
                            contact_id = {
                                u'ContactID': contact.xero_contact_id,
                                u'Name': invoice_id.partner_id.name or False
                                }
                    payment_vals = {u'Date': payment.payment_date or False,
                                    u'Amount': amount or 0.0,
                                    u'Reference': payment.name,
                                    u'CurrencyRate': currency_rate,
                                    u'PaymentType': payment_type,
                                    u'Status' : 'Paid',
                                    u'IsReconciled': 'true',
                                    u'Account': {
                                                u'AccountID': payment.journal_id.xero_account_id.acc_id or False,
                                                },
                                    u'Invoice': {u'Type': type,
                                                 u'InvoiceID': invoice_id.xero_invoice_id or False,
                                                 u'InvoiceNumber': invoice_id.xero_invoice_number or False,
                                                 u'Contact': contact_id,
                                                 },
                                    }
                    data.append(payment_vals)
                    c += 1
                    if c == 50:
                        payment_data.append(data)
                        data = []
                        c = 0

        if data:
            payment_data.append(data)
        for data in payment_data:
            xero_payment = xero.payments.put(data)
            for payment in xero_payment:
                payment_id = self.env['account.payment'].search([('name', '=', payment.get('Reference')), ('company_id', '=', company)])
                payment_id.xero_payment_id = payment.get('PaymentID')
                self._cr.commit()

    def export_credit_notes(self, credit_notes_list, xero, last_export_date, company=False, disable_export=False):
        partner_pool = self.env['res.partner']
        product_pool = self.env['product.product']
        xero_account = self.env['xero.account'].search([('company_id', '=', company)], limit=1)
        if self._context.get('invoice_ids'):
            invoice_ids = self._context.get('invoice_ids')
        else:
            if last_export_date:
                invoice_ids = self.search([('company_id', '=', company),
                                           ('able_to_xero_export', '=', True),
                                           ('type', 'in', ['out_refund', 'in_refund']),
                                           ('state', '!=', 'cancel'),
                                           '|', ('write_date', '>=', last_export_date),
                                           ('create_date', '>=', last_export_date)])
            else:
                invoice_ids = self.search([('company_id', '=', company),
                                           ('able_to_xero_export', '=', True),
                                           ('type', 'in', ['out_refund', 'in_refund']),
                                           ('state', '!=', 'cancel')])

        update_creditnote_data = []
        update_creditnote_data_list = []
        create_creditnote_data = []
        create_creditnote_data_list = []
        c = 0
        count = 0
        request = 0
        for invoice_id in invoice_ids:
            if invoice_id.type == 'out_refund':
                type = u'ACCRECCREDIT'
            elif invoice_id.type == 'in_refund':
                type = u'ACCPAYCREDIT'

            if not invoice_id.partner_id:
                description = 'Customer must be set for export (Odoo to Xero)'
                mismatch_vals = {'name': invoice_id.type,
                                 'source_model': 'account.move',
                                 'source_id': invoice_id.id,
                                 'description': description,
                                 'exported_date': datetime.datetime.now()
                                 }
                self.env['mismatch.log'].create(mismatch_vals)
                continue
            if invoice_id.xero_invoice_id:
                for xero_inv in credit_notes_list:
                    if xero_inv.get('CreditNoteID') == invoice_id.xero_invoice_id and xero_inv.get('Status') in ['DRAFT','SUBMITTED'] : #['SUBMITTED','AUTHORISED']
                        invoice_currency_rate = 0.0
                        status = u'DRAFT'

                        if invoice_id.state == 'draft':
                            status = u'DRAFT'
                        elif invoice_id.state == 'posted':
                            status = u'AUTHORISED'
                            if invoice_id.currency_id.id != invoice_id.company_id.currency_id.id:
                                if invoice_id.type == 'in_refund':
                                    if not invoice_id.line_ids[0].amount_currency == 0.0 and not invoice_id.line_ids[0].debit == 0.0:
                                        invoice_currency_rate = abs(invoice_id.line_ids[0].amount_currency / invoice_id.line_ids[0].debit)
                                else:
                                    if not invoice_id.line_ids[0].amount_currency == 0.0 and not invoice_id.line_ids[0].credit == 0.0:
                                        invoice_currency_rate = abs(invoice_id.line_ids[0].amount_currency / invoice_id.line_ids[0].credit)

                        line_amount_type = invoice_id.line_amount_type
                        if invoice_id.partner_id.parent_id:
                            contact = invoice_id.partner_id.parent_id.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                            if contact.xero_contact_id:
                                contact_id = {u'ContactID': contact.xero_contact_id}
                        else:
                            contact = invoice_id.partner_id.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                            if contact.xero_contact_id:
                                contact_id = {u'ContactID': contact.xero_contact_id}

                        invoice_data = {u'Type': type,
                                        u'CreditNoteID': invoice_id.xero_invoice_id,
                                        u'Status': status,
                                        u'Reference': invoice_id.name or u'',
                                        u'LineAmountTypes': line_amount_type,
                                        u'Contact': contact_id,
                                        u'Date': invoice_id.invoice_date or fields.Date.today(),
                                        u'DueDate': invoice_id.invoice_date_due or fields.Date.today(),
                                        u'CurrencyCode': invoice_id.currency_id.name,
                                        }
                        if invoice_currency_rate:
                            invoice_data.update({u'CurrencyRate': invoice_currency_rate})

                        line_items = []
                        for inv_line in invoice_id.invoice_line_ids:
                            if inv_line.tax_ids:
                                tax_type = inv_line.tax_ids[0]
                            else:
                                if invoice_id.type == 'in_refund':
                                    tax_type = self.env['account.tax'].search([('type_tax_use', '=', 'sale'), ('amount', '=', 0), ('company_id', '=', company)], limit=1)
                                    if not tax_type:
                                        company_id = self.env['res.company'].browse(company)
                                        raise UserError(_('Please create account tax of type \'SALE\' and amount = 0.0 for Company: %s')% (company_id.name))
                                else:
                                    tax_type = self.env['account.tax'].search([('type_tax_use', '=', 'purchase'), ('amount', '=', 0), ('company_id', '=', company)], limit=1)
                                    if not tax_type:
                                        company_id = self.env['res.company'].browse(company)
                                        raise UserError(_('Please create account tax of type \'PURCHASE\' and amount = 0.0 for Company: %s')%(company_id.name))
                            if not tax_type.xero_tax_type:
                                tax_rates = xero.taxrates.all()
                                self.env['account.tax'].export_tax(tax_rates, xero, company=company, disable_export=disable_export)

                            if inv_line.xero_invoice_line_id:
                                vals = {u'LineItemID': inv_line.xero_invoice_line_id,
                                        u'AccountCode': inv_line.account_id.code,
                                        u'Description': inv_line.name or inv_line.product_id.name,
                                        u'UnitAmount': inv_line.price_unit,
                                        u'TaxType': tax_type and tax_type.xero_tax_type if line_amount_type != 'NoTax' else u'',
                                        # u'ValidationErrors': [],
                                        u'Quantity': inv_line.quantity,
                                        }
                            else:
                                vals = {u'AccountCode': inv_line.account_id.code,
                                        u'Description': inv_line.name or inv_line.product_id.name,
                                        u'UnitAmount': inv_line.price_unit,
                                        u'TaxType': tax_type and tax_type.xero_tax_type if line_amount_type != 'NoTax' else u'',
                                        # u'ValidationErrors': [],
                                        u'Quantity': inv_line.quantity,
                                        }

                            if inv_line.product_id:
                                product = inv_line.product_id.product_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                                if not product.xero_item_id:
                                    xero_account.export_product()
                                vals.update({u'ItemCode': inv_line.product_id.default_code})
                            line_items.append(vals)

                            if line_items:
                                invoice_data.update({u'LineItems': line_items})

                            if invoice_id.state == 'draft':
                                request += 1
                                if request > 30:
                                    time.sleep(1)
                                inv_rec = xero.creditnotes.save(invoice_data)
                            else:
                                update_creditnote_data.append(invoice_data)
                                count += 1
                                if count == 50:
                                    update_creditnote_data_list.append(update_creditnote_data)
                                    update_creditnote_data = []
                                    count = 0

            elif not invoice_id.xero_invoice_id:
                if invoice_id.state == 'posted':
                     # set state of invoice 'paid' not possible at a time.
                    status = u'AUTHORISED'
                else:
                    status = u'DRAFT'

                invoice_currency_rate = 0.0
                if invoice_id.state == 'posted' and invoice_id.currency_id.id != invoice_id.company_id.currency_id.id:
                    if invoice_id.type == 'out_refund':
                        if not invoice_id.line_ids[0].amount_currency == 0.0 and not invoice_id.line_ids[0].debit == 0.0:
                            invoice_currency_rate = abs(invoice_id.line_ids[0].amount_currency / invoice_id.line_ids[0].debit)
                    else:
                        if not invoice_id.line_ids[0].amount_currency == 0.0 and not invoice_id.line_ids[0].credit == 0.0:
                            invoice_currency_rate = abs(invoice_id.line_ids[0].amount_currency / invoice_id.line_ids[0].credit)

                line_amount_type = invoice_id.line_amount_type

                partner_details = {}
                if invoice_id.partner_id.parent_id:
                    contact = invoice_id.partner_id.parent_id.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                    if not contact.xero_contact_id:
                        xero_account.export_contact_overwrite() if xero_account.contact_overwrite else xero_account.export_contact()
                    partner_details = {u'ContactID': contact.xero_contact_id}
                else:
                    contact = invoice_id.partner_id.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                    if not contact.xero_contact_id:
                        xero_account.export_contact_overwrite() if xero_account.contact_overwrite else xero_account.export_contact()
                    partner_details = {u'ContactID': contact.xero_contact_id}

                final_invoice_data = {u'Type': type,
                                      u'Contact': partner_details,
                                      u'Reference': invoice_id.name or u'',
                                      u'Date': invoice_id.invoice_date or fields.Date.today(),
                                      u'DueDate': invoice_id.invoice_date_due or fields.Date.today(),
                                      u'Status': status,
                                      u'LineAmountTypes': line_amount_type,
                                      u'CurrencyCode': invoice_id.currency_id.name,
                                      }

                if invoice_currency_rate:
                    final_invoice_data.update({u'CurrencyRate': invoice_currency_rate})
                if invoice_id.invoice_line_ids:
                    line_items = []
                    for invoice_line in invoice_id.invoice_line_ids:
                        if invoice_line.tax_ids:
                            tax_type = invoice_line.tax_ids[0]
                        else:
                            if invoice_id.type == 'out_refund':
                                tax_type = self.env['account.tax'].search([('type_tax_use', '=', 'sale'), ('amount', '=', 0), ('company_id', '=', company)], limit=1)
                                if not tax_type:
                                    company_id = self.env['res.company'].browse(company)
                                    raise UserError(_('Please create account tax of type \'SALE\' and amount = 0.0 for Company: %s')% (company_id.name))
                            else:
                                tax_type = self.env['account.tax'].search([('type_tax_use', '=', 'purchase'), ('amount', '=', 0), ('company_id', '=', company)], limit=1)
                                if not tax_type:
                                    company_id = self.env['res.company'].browse(company)
                                    raise UserError(_('Please create account tax of type \'PURCHASE\' and amount = 0.0 for Company: %s')%(company_id.name))
                        if not tax_type.xero_tax_type:
                            tax_rates = xero.taxrates.all()
                            self.env['account.tax'].export_tax(tax_rates, xero, company=company, disable_export=disable_export)
                        vals = {u'AccountCode': invoice_line.account_id.code,
                                u'Description': invoice_line.name or invoice_line.product_id.name,
                                u'UnitAmount': invoice_line.price_unit,
                                u'TaxType': tax_type and tax_type.xero_tax_type if line_amount_type != 'NoTax' else u'',
                                # u'ValidationErrors': [],
                                u'Quantity': invoice_line.quantity,
                            }

                        if invoice_line.product_id:
                            product = invoice_line.product_id.product_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                            if not product.xero_item_id:
                                xero_account.export_product()
                            vals.update({u'ItemCode': invoice_line.product_id.default_code})
                        line_items.append(vals)
                    if line_items:
                        final_invoice_data.update({u'LineItems': line_items})
                # creditnote draft state individual request
                if invoice_id.state == 'draft':
                    request += 1
                    if request > 30:
                        time.sleep(1)
                    inv_rec = xero.creditnotes.put(final_invoice_data)
                    invoice_id.write({'xero_invoice_id': inv_rec[0].get('CreditNoteID'), 'xero_invoice_number': inv_rec[0].get('CreditNoteNumber')})
                    self._cr.commit()
                else:
                    # creditnote batch processing
                    create_creditnote_data.append(final_invoice_data)
                    c += 1
                    if c == 50:
                        create_creditnote_data_list.append(create_creditnote_data)
                        create_creditnote_data = []
                        c = 0

        if create_creditnote_data:
            create_creditnote_data_list.append(create_creditnote_data)
        for data in create_creditnote_data_list:
            inv_rec = xero.creditnotes.put(data)
            for inv in inv_rec:
                invoice_id = self.search([('name', '=', inv.get('Reference')), ('company_id', '=', company)])
                invoice_id.write({'xero_invoice_id': inv.get('CreditNoteID'), 'xero_invoice_number': inv.get('CreditNoteNumber')})
                self._cr.commit()

        if update_creditnote_data:
            update_creditnote_data_list.append(update_creditnote_data)
        for data in update_creditnote_data_list:
            inv_rec = xero.creditnotes.save(data)

    def allocate_credit_note_payment(self, credit_note_guid, allocations, xero):
        """
        Must pass in xero as it needs credentials if using public method.

        allocations should be an array of dictionaries containing amount, invoice:invoice idXero GUIDs for the contacts.
        """
        # Store the original endpoint base_url

        old_base_url = xero.creditnotes.base_url
        old_name = xero.creditnotes.name
        old_singular = xero.creditnotes.singular
        # Call the API
        try:
            xero.creditnotes.base_url = '{}/CreditNotes/{}'.format(old_base_url, credit_note_guid)
            xero.creditnotes.name = 'Allocations'
            xero.creditnotes.singular = 'Allocation'
            xero.creditnotes.put(allocations)
        except:
            raise
        finally:
            # Reset the base_url
            xero.creditnotes.base_url = old_base_url
            xero.creditnotes.name = old_name
            xero.creditnotes.singular = old_singular

    def export_credit_notes_payment(self, xero, company=False, disable_export=False):
        payment_data = []
        data = []
        c = 0
        count = 0
        invoice_ids = self.search([('company_id', '=', company),
                                   ('able_to_xero_export', '=', True),
                                   ('type', 'in', ['out_refund', 'in_refund']),
                                   ('state', 'not in', ['draft', 'cancel'])])
        for invoice_id in invoice_ids:
            allocations = []
            if not invoice_id.xero_credit_note_allocation and invoice_id.invoice_payment_state == 'paid':
                for payment in invoice_id._get_reconciled_info_JSON_values():
                    pay_invoice = self.browse(payment['move_id'])
                    if pay_invoice.xero_invoice_id:
                        allocations.append({u'AppliedAmount': payment['amount'],
                                            u'Date': payment['date'],
                                            u'Invoice': {u'InvoiceID': pay_invoice.xero_invoice_id}})

                if allocations:
                    self.allocate_credit_note_payment(invoice_id.xero_invoice_id, allocations, xero)
                    invoice_id.xero_credit_note_allocation = True
                    self._cr.commit()

            for inv_payment in invoice_id._get_reconciled_info_JSON_values():
                payment = self.env['account.payment'].browse(inv_payment.get('account_payment_id'))
                if not payment.xero_payment_id and payment.state == 'posted':
                    if invoice_id.type == 'in_refund':
                        payment_type = u'ACCRECPAYMENT'
                        type = u'ACCRECCREDIT'
                    elif invoice_id.type == 'out_refund':
                        payment_type = u'ACCPAYPAYMENT'
                        type = u'ACCPAYCREDIT'
                    if not payment.move_line_ids[0].journal_id.xero_account_id:
                        raise UserError(_('Please select your xero account on payment Journal: %s')%(payment.move_line_ids[0].journal_id.name))
                    if not payment.move_line_ids[0].journal_id.xero_account_id.acc_id:
                        account_list = xero.accounts.all()
                        self.env['account.account'].export_account(account_list, xero, company=company, disable_export=disable_export)
                    if not payment.journal_id.xero_account_id.acc_id:
                        raise UserError(_('Please select correct Xero account for Payment.'))
                    if type == 'ACCRECCREDIT':
                        if payment.currency_id != payment.company_id.currency_id and payment.currency_id == invoice_id.currency_id:
                            currency_rate = abs(payment.move_line_ids[0].amount_currency / payment.move_line_ids[0].debit)
                        elif payment.currency_id == payment.company_id.currency_id and payment.currency_id != invoice_id.currency_id:
                            currency_rate = abs(payment.move_line_ids[1].amount_currency / payment.move_line_ids[1].debit)
                        elif payment.currency_id and (payment.currency_id != invoice_id.company_id.currency_id or payment.currency_id != invoice_id.currency_id):
                            currency_rate = abs(payment.move_line_ids[1].amount_currency / payment.move_line_ids[1].debit)
                        elif payment.currency_id == payment.company_id.currency_id == invoice_id.currency_id:
                            currency_rate = 1.00
                        else:
                            currency_rate = 1.00
                    else:
                        if payment.currency_id != payment.company_id.currency_id and payment.currency_id == invoice_id.currency_id:
                            currency_rate = abs(payment.move_line_ids[0].amount_currency / payment.move_line_ids[1].credit)
                        elif payment.currency_id == payment.company_id.currency_id and payment.currency_id != invoice_id.currency_id:
                            currency_rate = abs(payment.move_line_ids[1].amount_currency / payment.move_line_ids[1].credit)
                        elif payment.currency_id and (payment.currency_id != invoice_id.company_id.currency_id or payment.currency_id != invoice_id.currency_id):
                            currency_rate = abs(payment.move_line_ids[1].amount_currency / payment.move_line_ids[1].credit)
                        elif payment.currency_id == payment.company_id.currency_id == invoice_id.currency_id:
                            currency_rate = 1.00
                        else:
                            currency_rate = 1.00
                    # if payment.currency_id == invoice_id.currency_id:
                    #     # amount = payment.amount
                    #     amount = inv_payment.get('amount')
                    # else:
                    #     amount = abs(payment.move_line_ids[1].amount_currency)
                    amount = inv_payment.get('amount')

                    if invoice_id.partner_id.parent_id:
                        contact = invoice_id.partner_id.parent_id.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                        if contact.xero_contact_id:
                            contact_id = {u'ContactID': contact.xero_contact_id}
                    else:
                        contact = invoice_id.partner_id.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                        if contact.xero_contact_id:
                            contact_id = {u'ContactID': contact.xero_contact_id}

                    payment_vals = {u'Date': payment.payment_date or False,
                                    u'Amount': amount or 0.0,
                                    u'Reference': payment.name or False,
                                    u'CurrencyRate': currency_rate,
                                    u'PaymentType': payment_type,
                                    u'Status': 'Paid',
                                    u'IsReconciled': 'true',
                                    u'Account': {
                                                u'AccountID': payment.journal_id.xero_account_id.acc_id or False,
                                                },
                                    u'Invoice': {
                                                u'Type': type,
                                                u'InvoiceID': invoice_id.xero_invoice_id or False,
                                                u'InvoiceNumber': invoice_id.xero_invoice_number or False,
                                                u'Contact': contact_id,
                                                },
                                    }

                    data.append(payment_vals)
                    c += 1
                    if c == 50:
                        payment_data.append(data)
                        data = []
                        c = 0

        if data:
            payment_data.append(data)
        for data in payment_data:
            xero_payment = xero.payments.put(data)
            for payment in xero_payment:
                payment_id = self.env['account.payment'].search([('name', '=', payment.get('Reference')), ('company_id', '=', company)])
                payment_id.xero_payment_id = payment.get('PaymentID')
                self._cr.commit()

    def action_export_invoice(self):
        context = self._context
        for company_id in context.get('allowed_company_ids'):
            invoice_data = self.filtered(lambda invoice: (invoice.company_id.id == company_id or not invoice.company_id) and invoice.able_to_xero_export)
            if invoice_data:
                context.update({'invoice_ids': invoice_data})
                xero_account = self.env['xero.account'].search([('company_id', '=', company_id)], limit=1)
                if invoice_data[0].type in ['out_invoice','in_invoice']:
                    xero_account.with_context(context).export_invoice()
                elif invoice_data[0].type in ['out_refund','in_refund'] and xero_account.import_export_creditnotes == 'export':
                    xero_account.with_context(context).export_credit_notes()


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    xero_invoice_line_id = fields.Char('Xero InvoiceLine ID', readonly=True, copy=False)
    xero_invoice_payment_id = fields.Char('Xero Payment ID', readonly=True, copy=False)

    def _reconcile_lines(self, debit_moves, credit_moves, field):
        """ This function loops on the 2 recordsets given as parameter as long as it
            can find a debit and a credit to reconcile together. It returns the recordset of the
            account move lines that were not reconciled during the process.
        """
        if self._context.get('allocation_amount'):
            (debit_moves + credit_moves).read([field])
            to_create = []
            cash_basis = debit_moves and debit_moves[0].account_id.internal_type in ('receivable', 'payable') or False
            cash_basis_percentage_before_rec = {}
            dc_vals ={}
            while (debit_moves and credit_moves):
                debit_move = debit_moves[0]
                credit_move = credit_moves[0]
                company_currency = debit_move.company_id.currency_id
                # We need those temporary value otherwise the computation might be wrong below
                temp_amount_residual = min(debit_move.amount_residual, -credit_move.amount_residual)
                temp_amount_residual_currency = min(debit_move.amount_residual_currency, -credit_move.amount_residual_currency)
                dc_vals[(debit_move.id, credit_move.id)] = (debit_move, credit_move, temp_amount_residual_currency)
                amount_reconcile = min(debit_move[field], -credit_move[field])

                #Remove from recordset the one(s) that will be totally reconciled
                # For optimization purpose, the creation of the partial_reconcile are done at the end,
                # therefore during the process of reconciling several move lines, there are actually no recompute performed by the orm
                # and thus the amount_residual are not recomputed, hence we have to do it manually.
                if amount_reconcile == debit_move[field]:
                    debit_moves -= debit_move
                else:
                    debit_moves[0].amount_residual -= temp_amount_residual
                    debit_moves[0].amount_residual_currency -= temp_amount_residual_currency

                if amount_reconcile == -credit_move[field]:
                    credit_moves -= credit_move
                else:
                    credit_moves[0].amount_residual += temp_amount_residual
                    credit_moves[0].amount_residual_currency += temp_amount_residual_currency
                #Check for the currency and amount_currency we can set
                currency = False
                amount_reconcile_currency = 0
                if field == 'amount_residual_currency':
                    currency = credit_move.currency_id.id
                    amount_reconcile_currency = temp_amount_residual_currency
                    amount_reconcile = temp_amount_residual

                if cash_basis:
                    tmp_set = debit_move | credit_move
                    cash_basis_percentage_before_rec.update(tmp_set._get_matched_percentage())

                to_create.append({
                    'debit_move_id': debit_move.id,
                    'credit_move_id': credit_move.id,
                    'amount': self._context.get('allocation_amount'),
                    'amount_currency': amount_reconcile_currency,
                    'currency_id': currency,
                })

            cash_basis_subjected = []
            part_rec = self.env['account.partial.reconcile']
            for partial_rec_dict in to_create:
                debit_move, credit_move, amount_residual_currency = dc_vals[partial_rec_dict['debit_move_id'], partial_rec_dict['credit_move_id']]
                # /!\ NOTE: Exchange rate differences shouldn't create cash basis entries
                # i. e: we don't really receive/give money in a customer/provider fashion
                # Since those are not subjected to cash basis computation we process them first
                if not amount_residual_currency and debit_move.currency_id and credit_move.currency_id:
                    part_rec.create(partial_rec_dict)
                else:
                    cash_basis_subjected.append(partial_rec_dict)

            for after_rec_dict in cash_basis_subjected:
                new_rec = part_rec.create(after_rec_dict)
                # if the pair belongs to move being reverted, do not create CABA entry
                if cash_basis and not (
                        new_rec.debit_move_id.move_id == new_rec.credit_move_id.move_id.reversed_entry_id
                        or
                        new_rec.credit_move_id.move_id == new_rec.debit_move_id.move_id.reversed_entry_id
                ):
                    new_rec.create_tax_cash_basis_entry(cash_basis_percentage_before_rec)
            return debit_moves+credit_moves
        else:
            return super(AccountMoveLine, self)._reconcile_lines(debit_moves, credit_moves, field)
