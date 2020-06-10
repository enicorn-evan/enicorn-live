# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _
import odoo.addons.decimal_precision as dp
from odoo.tools import float_is_zero

class account_move(models.Model):
    _inherit = 'account.move'

    discount_method = fields.Selection([('fix', 'Fixed'), ('per', 'Percentage')],'Discount Method')
    discount_amount = fields.Float('Discount Amount')
    discount_amt = fields.Float(string='- Discount', readonly=True, compute='_compute_amount')
    amount_untaxed = fields.Float(string='Subtotal', digits=dp.get_precision('Account'),store=True, readonly=True, compute='_compute_amount',track_visibility='always')
    amount_tax = fields.Float(string='Tax', digits=dp.get_precision('Account'),store=True, readonly=True, compute='_compute_amount')
    amount_total = fields.Float(string='Total', digits=dp.get_precision('Account'),store=True, readonly=True, compute='_compute_amount')

    def calc_discount(self):
        for calc in self:
            calc._calculate_discount()

    @api.depends('discount_amount')
    def _calculate_discount(self):
        res = discount = 0.0
        for self_obj in self:
            if self_obj.discount_method == 'fix':
                res = self_obj.discount_amount
            elif self_obj.discount_method == 'per':
                res = self_obj.amount_untaxed * (self_obj.discount_amount/ 100)
            else:
                res = discount
        return res

    @api.depends(
        'line_ids.debit',
        'line_ids.credit',
        'line_ids.currency_id',
        'line_ids.amount_currency',
        'line_ids.amount_residual',
        'line_ids.amount_residual_currency',
        'line_ids.payment_id.state')
    def _compute_amount(self):
        invoice_ids = [move.id for move in self if move.id and move.is_invoice(include_receipts=True)]
        self.env['account.payment'].flush(['state'])
        if invoice_ids:
            self._cr.execute(
                '''
                    SELECT move.id
                    FROM account_move move
                    JOIN account_move_line line ON line.move_id = move.id
                    JOIN account_partial_reconcile part ON part.debit_move_id = line.id OR part.credit_move_id = line.id
                    JOIN account_move_line rec_line ON
                        (rec_line.id = part.credit_move_id AND line.id = part.debit_move_id)
                        OR
                        (rec_line.id = part.debit_move_id AND line.id = part.credit_move_id)
                    JOIN account_payment payment ON payment.id = rec_line.payment_id
                    JOIN account_journal journal ON journal.id = rec_line.journal_id
                    WHERE payment.state IN ('posted', 'sent')
                    AND journal.post_at = 'bank_rec'
                    AND move.id IN %s
                ''', [tuple(invoice_ids)]
            )
            in_payment_set = set(res[0] for res in self._cr.fetchall())
        else:
            in_payment_set = {}

        for move in self:
            total_untaxed = 0.0
            total_untaxed_currency = 0.0
            total_tax = 0.0
            total_tax_currency = 0.0
            total_residual = 0.0
            total_residual_currency = 0.0
            total = 0.0
            total_currency = 0.0
            currencies = set()

            for line in move.line_ids:
                if line.currency_id:
                    currencies.add(line.currency_id)

                if move.is_invoice(include_receipts=True):
                    # === Invoices ===

                    if not line.exclude_from_invoice_tab:
                        # Untaxed amount.
                        total_untaxed += line.balance
                        total_untaxed_currency += line.amount_currency
                        total += line.balance
                        total_currency += line.amount_currency
                    elif line.tax_line_id:
                        # Tax amount.
                        total_tax += line.balance
                        total_tax_currency += line.amount_currency
                        total += line.balance
                        total_currency += line.amount_currency
                    elif line.account_id.user_type_id.type in ('receivable', 'payable'):
                        # Residual amount.
                        total_residual += line.amount_residual
                        total_residual_currency += line.amount_residual_currency
                else:
                    # === Miscellaneous journal entry ===
                    if line.debit:
                        total += line.balance
                        total_currency += line.amount_currency

            if move.type == 'entry' or move.is_outbound():
                sign = 1
            else:
                sign = -1
            move.amount_untaxed = sign * (total_untaxed_currency if len(currencies) == 1 else total_untaxed)
            move.amount_tax = sign * (total_tax_currency if len(currencies) == 1 else total_tax)
            move.amount_total = sign * (total_currency if len(currencies) == 1 else total)
            move.amount_residual = -sign * (total_residual_currency if len(currencies) == 1 else total_residual)
            move.amount_untaxed_signed = -total_untaxed
            move.amount_tax_signed = -total_tax
            move.amount_total_signed = abs(total) if move.type == 'entry' else -total
            move.amount_residual_signed = total_residual

            currency = len(currencies) == 1 and currencies.pop() or move.company_id.currency_id
            is_paid = currency and currency.is_zero(move.amount_residual) or not move.amount_residual

            # Compute 'invoice_payment_state'.
            if move.type == 'entry':
                move.invoice_payment_state = False
            elif move.state == 'posted' and is_paid:
                if move.id in in_payment_set:
                    move.invoice_payment_state = 'in_payment'
                else:
                    move.invoice_payment_state = 'paid'
            else:
                move.invoice_payment_state = 'not_paid'

            #Calculate Discount
            move.amount_untaxed = sum(line.price_subtotal for line in move.invoice_line_ids)
            res = move._calculate_discount()
            move.discount_amt = res
            move.amount_total = move.amount_untaxed - res + move.amount_tax
            amount_total_company_signed = move.amount_total
            amount_untaxed_signed = move.amount_untaxed
            if move.currency_id and move.currency_id != move.company_id.currency_id:
                amount_total_company_signed = move.currency_id.compute(move.amount_total, move.company_id.currency_id)
                amount_untaxed_signed = move.currency_id.compute(move.amount_untaxed, move.company_id.currency_id)
            sign = move.type in ['in_refund', 'out_refund'] and -1 or 1
            move.amount_total_company_signed = amount_total_company_signed * sign
            move.amount_total_signed = move.amount_total * sign
            move.amount_untaxed_signed = amount_untaxed_signed * sign

    @api.model_create_multi
    def create(self, vals_list):
        for val in vals_list:     
            if 'flag' in val:
                val.pop('flag')
                res = super(account_move,self).create(vals_list)
                
            else:
                res = super(account_move,self).create(vals_list)         
                if res.discount_method and res.discount_amount:
                    if res.state in 'draft':    
                        for line in res.invoice_line_ids:
                            if line.product_id:
                                account = line.account_id.id    
                
                        discount_vals = {
                        'account_id': account, 
                        'quantity': 1,
                        'price_unit': -res.discount_amt,
                        'name': "Discount", 
                        'exclude_from_invoice_tab': True,
                        }        
                        res.with_context(check_move_validity=False).write({
                            'invoice_line_ids' : [(0,0,discount_vals)]
                            })                         
        return res                     

    
class account_payment(models.Model):
    _inherit = "account.payment"

    def _prepare_payment_moves(self): 

        res = super(account_payment,self)._prepare_payment_moves()
        
        if self._context.get('default_type') == 'in_invoice' :
            for rec in res:
                rec.update({'flag':True})        
        return res