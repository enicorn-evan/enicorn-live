# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

import math
import time
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval
from datetime import datetime


class AccountJournal(models.Model):
    _inherit = "account.journal"

    xero_account_id = fields.Many2one('account.account', string="Xero Account")


class TaxComponent(models.Model):
    _name = 'tax.component'
    _description = "Tax Components"

    name = fields.Char('Name')
    rate = fields.Float('Rate')
    tax_id = fields.Many2one('account.tax', 'Tax')

    _sql_constraints = [
        ('rate_check', 'CHECK(rate >= 0 AND rate <= 100)', 'Please Enter Rate Value Between 0 to 100!'),
    ]


class AccountTax(models.Model):
    _inherit = 'account.tax'
    _description = 'Account Tax'

    name = fields.Char(string='Tax Name', size=50, required=True, translate=True)
    xero_tax_type = fields.Char('Xero Tax Type', copy=False)
    componet_ids = fields.One2many('tax.component', 'tax_id', 'Components')

    @api.model
    def create(self, values):
        if values.get('componet_ids') and values.get('componet_ids')[0][0] != 6:
            amount = 0.0
            for component in values.get('componet_ids'):
                amount += component[2].get('rate')
            values.update({'amount': amount})
        return super(AccountTax, self).create(values)

    def write(self, values):
        if values.get('componet_ids') and values.get('componet_ids')[0][0] != 6:
            amount = self.amount
            for component in values.get('componet_ids'):
                if component[2] and component[2].get('rate'):
                    amount += component[2].get('rate')
            values.update({'amount': amount})
        return super(AccountTax, self).write(values)

    def _compute_amount(self, base_amount, price_unit, quantity=1.0, product=None, partner=None, line_amount_type=False):
        """ Returns the amount of a single tax. base_amount is the actual amount on which the tax is applied, which is
            price_unit * quantity eventually affected by previous taxes (if tax is include_base_amount XOR price_include)
        """
        self.ensure_one()
        if self.amount_type == 'fixed':
            # Use copysign to take into account the sign of the base amount which includes the sign
            # of the quantity and the sign of the price_unit
            # Amount is the fixed price for the tax, it can be negative
            # Base amount included the sign of the quantity and the sign of the unit price and when
            # a product is returned, it can be done either by changing the sign of quantity or by changing the
            # sign of the price unit.
            # When the price unit is equal to 0, the sign of the quantity is absorbed in base_amount then
            # a "else" case is needed.
            if base_amount:
                return math.copysign(quantity, base_amount) * self.amount
            else:
                return quantity * self.amount

        price_include = self._context.get('force_price_include', self.price_include)

        # <=> new_base = base / (1 + tax_amount)
        if self.amount_type == 'percent' and (price_include or line_amount_type == 'Inclusive'):
            return base_amount - (base_amount / (1 + self.amount / 100))

        # base * (1 + tax_amount) = new_base
        if self.amount_type == 'percent' and not price_include:
            return base_amount * self.amount / 100

        # base / (1 - tax_amount) = new_base
        if self.amount_type == 'division' and not price_include:
            return base_amount / (1 - self.amount / 100) - base_amount
        # <=> new_base * (1 - tax_amount) = base
        if self.amount_type == 'division' and (price_include or line_amount_type == 'Inclusive'):
            return base_amount - (base_amount * (self.amount / 100))
        if self.amount_type == 'code':
            company = self.env.company
            localdict = {'base_amount': base_amount, 'price_unit':price_unit, 'quantity': quantity, 'product':product, 'partner':partner, 'company': company}
            safe_eval(self.python_compute, localdict, mode="exec", nocopy=True)
            return localdict['result']

    def compute_all(self, price_unit, currency=None, quantity=1.0, product=None, partner=None, is_refund=False, handle_price_include=True, line_amount_type=False):
        """ Returns all information required to apply taxes (in self + their children in case of a tax group).
            We consider the sequence of the parent for group of taxes.
                Eg. considering letters as taxes and alphabetic order as sequence :
                [G, B([A, D, F]), E, C] will be computed as [A, D, F, C, E, G]

            'handle_price_include' is used when we need to ignore all tax included in price. If False, it means the
            amount passed to this method will be considered as the base of all computations.

        RETURN: {
            'total_excluded': 0.0,    # Total without taxes
            'total_included': 0.0,    # Total with taxes
            'total_void'    : 0.0,    # Total with those taxes, that don't have an account set
            'taxes': [{               # One dict for each tax in self and their children
                'id': int,
                'name': str,
                'amount': float,
                'sequence': int,
                'account_id': int,
                'refund_account_id': int,
                'analytic': boolean,
            }],
        } """
        if not line_amount_type:
            line_amount_type = self._context.get('line_amount_type')
        if not self:
            company = self.env.company
        else:
            company = self[0].company_id

        # 1) Flatten the taxes.
        taxes = self.flatten_taxes_hierarchy()

        # 2) Avoid mixing taxes having price_include=False && include_base_amount=True
        # with taxes having price_include=True. This use case is not supported as the
        # computation of the total_excluded would be impossible.
        base_excluded_flag = False  # price_include=False && include_base_amount=True
        included_flag = False  # price_include=True
        for tax in taxes:
            # if (line_amount_type and line_amount_type == 'Inclusive') or tax.price_include:
            if tax.price_include:
                included_flag = True
            elif tax.include_base_amount or line_amount_type == 'Inclusive':
                base_excluded_flag = True
            if base_excluded_flag and included_flag:
                raise UserError(_('Unable to mix any taxes being price included with taxes affecting the base amount but not included in price.'))

        # 3) Deal with the rounding methods
        if not currency:
            currency = company.currency_id
        # By default, for each tax, tax amount will first be computed
        # and rounded at the 'Account' decimal precision for each
        # PO/SO/invoice line and then these rounded amounts will be
        # summed, leading to the total amount for that tax. But, if the
        # company has tax_calculation_rounding_method = round_globally,
        # we still follow the same method, but we use a much larger
        # precision when we round the tax amount for each line (we use
        # the 'Account' decimal precision + 5), and that way it's like
        # rounding after the sum of the tax amounts of each line
        prec = currency.decimal_places

        # In some cases, it is necessary to force/prevent the rounding of the tax and the total
        # amounts. For example, in SO/PO line, we don't want to round the price unit at the
        # precision of the currency.
        # The context key 'round' allows to force the standard behavior.
        round_tax = False if company.tax_calculation_rounding_method == 'round_globally' else True
        round_total = True
        if 'round' in self.env.context:
            round_tax = bool(self.env.context['round'])
            round_total = bool(self.env.context['round'])

        if not round_tax:
            prec += 5

        # 4) Iterate the taxes in the reversed sequence order to retrieve the initial base of the computation.
        #     tax  |  base  |  amount  |
        # /\ ----------------------------
        # || tax_1 |  XXXX  |          | <- we are looking for that, it's the total_excluded
        # || tax_2 |   ..   |          |
        # || tax_3 |   ..   |          |
        # ||  ...  |   ..   |    ..    |
        #    ----------------------------
        def recompute_base(base_amount, fixed_amount, percent_amount, division_amount):
            # Recompute the new base amount based on included fixed/percent amounts and the current base amount.
            # Example:
            #  tax  |  amount  |   type   |  price_include  |
            # -----------------------------------------------
            # tax_1 |   10%    | percent  |  t
            # tax_2 |   15     |   fix    |  t
            # tax_3 |   20%    | percent  |  t
            # tax_4 |   10%    | division |  t
            # -----------------------------------------------

            # if base_amount = 145, the new base is computed as:
            # (145 - 15) / (1.0 + 30%) * 90% = 130 / 1.3 * 90% = 90
            return (base_amount - fixed_amount) / (1.0 + percent_amount / 100.0) * (100 - division_amount) / 100

        base = round(price_unit * quantity, prec)
        # For the computation of move lines, we could have a negative base value.
        # In this case, compute all with positive values and negate them at the end.
        sign = 1
        if base < 0:
            base = -base
            sign = -1

        # Store the totals to reach when using price_include taxes (only the last price included in row)
        total_included_checkpoints = {}
        i = len(taxes) - 1
        store_included_tax_total = True
        # Keep track of the accumulated included fixed/percent amount.
        incl_fixed_amount = incl_percent_amount = incl_division_amount = 0
        # Store the tax amounts we compute while searching for the total_excluded
        cached_tax_amounts = {}
        if handle_price_include:
            for tax in reversed(taxes):
                tax_repartition_lines = (
                    is_refund
                    and tax.refund_repartition_line_ids
                    or tax.invoice_repartition_line_ids
                ).filtered(lambda x: x.repartition_type == "tax")
                sum_repartition_factor = sum(tax_repartition_lines.mapped("factor"))

                if tax.include_base_amount or (line_amount_type and line_amount_type == 'Inclusive'):
                    base = recompute_base(base, incl_fixed_amount, incl_percent_amount, incl_division_amount)
                    incl_fixed_amount = incl_percent_amount = incl_division_amount = 0
                    store_included_tax_total = True
                if tax.price_include or self._context.get('force_price_include') or (line_amount_type and line_amount_type == 'Inclusive'):
                    if tax.amount_type == 'percent':
                        incl_percent_amount += tax.amount * sum_repartition_factor
                    elif tax.amount_type == 'division':
                        incl_division_amount += tax.amount * sum_repartition_factor
                    elif tax.amount_type == 'fixed':
                        incl_fixed_amount += quantity * tax.amount * sum_repartition_factor
                    else:
                        # tax.amount_type == other (python)
                        tax_amount = tax._compute_amount(base, price_unit, quantity, product, partner, line_amount_type=line_amount_type) * sum_repartition_factor
                        incl_fixed_amount += tax_amount
                        # Avoid unecessary re-computation
                        cached_tax_amounts[i] = tax_amount
                    if store_included_tax_total:
                        total_included_checkpoints[i] = base
                        store_included_tax_total = False
                i -= 1

        total_excluded = recompute_base(base, incl_fixed_amount, incl_percent_amount, incl_division_amount)

        # 5) Iterate the taxes in the sequence order to compute missing tax amounts.
        # Start the computation of accumulated amounts at the total_excluded value.
        base = total_included = total_void = total_excluded
        taxes_vals = []
        i = 0
        cumulated_tax_included_amount = 0
        for tax in taxes:
            tax_repartition_lines = (is_refund and tax.refund_repartition_line_ids or tax.invoice_repartition_line_ids).filtered(lambda x: x.repartition_type == 'tax')
            sum_repartition_factor = sum(tax_repartition_lines.mapped('factor'))

            #compute the tax_amount
            if ((self._context.get('force_price_include') or tax.price_include) or (line_amount_type and line_amount_type == 'Inclusive')) and total_included_checkpoints.get(i) :
                # We know the total to reach for that tax, so we make a substraction to avoid any rounding issues
                tax_amount = total_included_checkpoints[i] - (base + cumulated_tax_included_amount)
                cumulated_tax_included_amount = 0
            else:
                tax_amount = tax.with_context(force_price_include=False)._compute_amount(
                    base, sign * price_unit, quantity, product, partner, line_amount_type=line_amount_type)

            # Round the tax_amount multiplied by the computed repartition lines factor.
            tax_amount = round(tax_amount, prec)
            factorized_tax_amount = round(tax_amount * sum_repartition_factor, prec)

            if (tax.price_include and not total_included_checkpoints.get(i)) or (line_amount_type and line_amount_type == 'Inclusive'):
                cumulated_tax_included_amount += factorized_tax_amount

            # If the tax affects the base of subsequent taxes, its tax move lines must
            # receive the base tags and tag_ids of these taxes, so that the tax report computes
            # the right total
            subsequent_taxes = self.env['account.tax']
            subsequent_tags = self.env['account.account.tag']
            if tax.include_base_amount or line_amount_type == 'Inclusive':
                subsequent_taxes = taxes[i+1:]
                subsequent_tags = subsequent_taxes.get_tax_tags(is_refund, 'base')

            # Compute the tax line amounts by multiplying each factor with the tax amount.
            # Then, spread the tax rounding to ensure the consistency of each line independently with the factorized
            # amount. E.g:
            #
            # Suppose a tax having 4 x 50% repartition line applied on a tax amount of 0.03 with 2 decimal places.
            # The factorized_tax_amount will be 0.06 (200% x 0.03). However, each line taken independently will compute
            # 50% * 0.03 = 0.01 with rounding. It means there is 0.06 - 0.04 = 0.02 as total_rounding_error to dispatch
            # in lines as 2 x 0.01.
            repartition_line_amounts = [round(tax_amount * line.factor, prec) for line in tax_repartition_lines]
            total_rounding_error = round(factorized_tax_amount - sum(repartition_line_amounts), prec)
            nber_rounding_steps = int(abs(total_rounding_error / currency.rounding))
            rounding_error = round(nber_rounding_steps and total_rounding_error / nber_rounding_steps or 0.0, prec)

            for repartition_line, line_amount in zip(tax_repartition_lines, repartition_line_amounts):

                if nber_rounding_steps:
                    line_amount += rounding_error
                    nber_rounding_steps -= 1

                taxes_vals.append({
                    'id': tax.id,
                    'name': partner and tax.with_context(lang=partner.lang).name or tax.name,
                    'amount': sign * line_amount,
                    'base': round(sign * base, prec),
                    'sequence': tax.sequence,
                    'account_id': tax.cash_basis_transition_account_id.id if tax.tax_exigibility == 'on_payment' else repartition_line.account_id.id,
                    'analytic': tax.analytic,
                    # 'price_include': tax.price_include or self._context.get('force_price_include'),
                    # 'tax_exigibility': tax.tax_exigibility,
                    'tax_repartition_line_id': repartition_line.id,
                    'tag_ids': (repartition_line.tag_ids + subsequent_tags).ids,
                    'tax_ids': subsequent_taxes.ids,
                })

                if not repartition_line.account_id:
                    total_void += line_amount

            # Affect subsequent taxes
            if tax.include_base_amount or line_amount_type == 'Inclusive':
                base += factorized_tax_amount

            total_included += factorized_tax_amount
            i += 1

        return {
            'base_tags': taxes.mapped(is_refund and 'refund_repartition_line_ids' or 'invoice_repartition_line_ids').filtered(lambda x: x.repartition_type == 'base').mapped('tag_ids').ids,
            'taxes': taxes_vals,
            'total_excluded': sign * (currency.round(total_excluded) if round_total else total_excluded),
            'total_included': sign * (currency.round(total_included) if round_total else total_included),
            'total_void': sign * (currency.round(total_void) if round_total else total_void),
        }

    def import_tax(self, tax_list, xero, company=False, import_option=None):
        """
            Map: Tax Type(Odoo) with Tax Type(Xero)

            Create a tax in odoo if tax is not available with
            tax type and company.

            Note: If any record is already available with same name in odoo which we
            going to import from xero then it will skip that particuler record.

            Constraint: Tax Name must be unique per company

            If tax record is available then it will update that particular record.
        """
        for tax in tax_list:
            if tax.get('Status') == 'ACTIVE':
                sub_tax = []
                amount = 0.0
                if tax.get('ReportTaxType') == 'INPUT':
                    tax_type = 'purchase'
                elif tax.get('ReportTaxType') == 'OUTPUT':
                    tax_type = 'sale'
                else:
                    tax_type = 'none'
                for tax_comp in tax.get('TaxComponents'):
                    sub_tax.append(self.env['tax.component'].create({
                        'name': tax_comp.get('Name'),
                        'rate': tax_comp.get('Rate')}).id)
                    amount += tax_comp.get('Rate')
                parent_tax_rec = self.search([('xero_tax_type', '=', tax.get('TaxType')),
                                              ('company_id', '=', company)])
                avilable_tax_ids = self.search([('company_id', '=', company), ('name', '=', tax.get('Name'))])
                if avilable_tax_ids:
                    avilable_tax_ids.write({'xero_tax_type': tax.get('TaxType')})
                if parent_tax_rec and import_option in ['update', 'both']:
                    parent_tax_rec[0].write({
                        'amount': amount,
                        'xero_tax_type': tax.get('TaxType'),
                        'componet_ids': [(6, 0, sub_tax)],
                        'type_tax_use': tax_type,
                        'company_id': company,
                    })
                    self._cr.commit()
                elif not parent_tax_rec and not avilable_tax_ids and import_option in ['create', 'both']:
                    self.create({'name': tax.get('Name'),
                                 'amount': amount,
                                 'xero_tax_type': tax.get('TaxType'),
                                 'componet_ids': [(6, 0, sub_tax)],
                                 'type_tax_use': tax_type,
                                 'company_id': company,
                                 })
                    self._cr.commit()

    def export_tax(self, tax_list, xero, company=False, disable_export=False):
        """
            Map: Tax Type(Odoo) with Tax Type(Xero)

            Create a tax in Xero if tax is not available with
            tax type.

            Note: If any record is already available with same name in Xero which we
            going to export from Odoo then it will skip that particular record.

            Constraint: Tax Name must be unique in Xero

        """
        if not disable_export:
            same_tax = []
            final_tax_list = []
            tax_name_list = []
            organisation_detail = xero.organisations.all()
            for tax_id in self.search([('company_id', '=', company)]):
                for tax in tax_list:
                    if tax.get('Name') == tax_id.name:
                        if not tax_id.xero_tax_type:
                            tax_id.xero_tax_type = tax.get('TaxType')
                    else:
                        tax_name_list.append(tax.get('Name'))
                    if tax_id.xero_tax_type == tax.get('TaxType'):
                        same_tax.append(tax_id.id)
                final_tax_list.append(tax_id.id)

            for save_tax in self.browse(list(set(final_tax_list).difference(set(same_tax)))):
                if save_tax.name not in tax_name_list:
                    tax_type = False
                    if save_tax.type_tax_use in ['sale', 'none']:
                        tax_type = 'OUTPUT'
                    elif save_tax.type_tax_use in ['purchase']:
                        tax_type = 'INPUT'

                    components = []
                    for component in save_tax.componet_ids:
                        # components.append({u'TaxComponent': {u'Name': component.name,
                        #                                      u'Rate': component.rate}
                        #                    })
                        components.append({u'Name': component.name,
                                           u'Rate': component.rate
                                           })

                    if len(components) < 1:
                        tax_rate = save_tax.amount if save_tax.amount_type == 'percent' else 0.0
                        # components.append({u'TaxComponent': {u'Name': ' '.join([save_tax.name, str(tax_rate)]),
                        #                                      u'Rate': tax_rate}})
                        components.append({u'Name': ' '.join([save_tax.name, str(tax_rate)]),
                                                             u'Rate': tax_rate})

                    tax_line = save_tax.invoice_repartition_line_ids.filtered(lambda l: l.repartition_type == 'tax')
                    line = save_tax.invoice_repartition_line_ids.filtered(lambda l: l.repartition_type == 'tax' and l.factor_percent != 100)
                    if save_tax.amount_type != 'percent':
                        description = save_tax.amount_type + ' type tax not exported odoo to xero.'
                        mismatch_vals = {'name': save_tax.name,
                                         'source_model': 'account.tax',
                                         'source_id': save_tax.id,
                                         'description': description,
                                         'exported_date': datetime.now()
                                         }
                        self.env['mismatch.log'].create(mismatch_vals)
                        continue
                    if line or len(tax_line) != 1:
                        description = 'must be add 100 percentage repartition line for export tax (odoo to xero).'
                        mismatch_vals = {'name': save_tax.name,
                                         'source_model': 'account.tax',
                                         'source_id': save_tax.id,
                                         'description': description,
                                         'exported_date': datetime.now()
                                         }
                        self.env['mismatch.log'].create(mismatch_vals)
                        continue

                    if organisation_detail[0].get('CountryCode') in ['AU', 'NZ', 'GB']:
                        tax_details = xero.taxrates.put({u'Name': save_tax.name,
                                                         u'ReportTaxType': tax_type,
                                                         u'TaxComponents': components})
                    else:
                        tax_details = xero.taxrates.put({u'Name': save_tax.name,
                                                         u'TaxComponents': components})

                    save_tax.xero_tax_type = tax_details[0].get('TaxType', False)
                    self._cr.commit()


class BankAccount(models.Model):
    _inherit = 'res.partner.bank'
    _description = 'Bank Account'

    acc_id = fields.Char('Xero AccountID', readonly=True)

    def import_bank_account(self, bank_account_list, xero, import_option=None, company=False):
        """
            Map: AccountID(Odoo) with AccountID(Xero)

            Create a bank account in Odoo if account is not available.

            If bank account record is available then it will update that particular record.
        """
        partner_pool = self.env['res.partner']
        currency_pool = self.env['res.currency']
        for bank_account in bank_account_list:
            if bank_account.get('Status') == 'ACTIVE':
                partner = partner_pool.search([('name', '=', bank_account.get('Name'))])
                if not partner:
                    partner = partner_pool.create({'name': bank_account.get('Name'), 'company_id': company})
                else:
                    partner = partner[0]

                currency = currency_pool.search([('name', '=', bank_account.get('CurrencyCode'))])
                bank_account_rec = self.search([('acc_id', '=', bank_account.get('AccountID'))])
                available_acc_ids = self.search([('acc_number', '=', bank_account.get('BankAccountNumber'))])
                if bank_account_rec and import_option in ['update', 'both']:
                    bank_account_rec[0].write({'partner_id': partner.id,
                                               'currency_id': currency and currency[0].id or False,
                                               'acc_number': bank_account.get('BankAccountNumber')})
                    self._cr.commit()
                elif not bank_account_rec and not available_acc_ids and import_option in ['create', 'both']:
                    self.create({'acc_id': bank_account.get('AccountID'),
                                 'partner_id': partner.id,
                                 'currency_id': currency and currency[0].id or False,
                                 'acc_number': bank_account.get('BankAccountNumber'),
                                 'company_id': company})
                    self._cr.commit()

    def export_bank_account(self, bank_account_list, xero, company=False, disable_export=False):
        """
            Map: AccountID(Odoo) with AccountID(Xero)

            Create a bank account in Xero if bank account is not available.

            Note: If any record is already available with same BankAccountNumber in Xero which we
            going to export from Odoo then it will skip that particular record.

            Constraint(Xero): The Bank Account Number must be unique

            If bank account record is available in Xero then it will update that particular record.
        """
        if not disable_export:
            same_accounts = []
            final_account_list = []
            account_number_list = []
            for bank_account_id in self.search([('company_id', '=', company)]):
                for bank_account in bank_account_list:
                    account_number_list.append(bank_account.get('BankAccountNumber'))
                    if bank_account_id.acc_id == bank_account.get('AccountID'):
                        same_accounts.append(bank_account_id.id)
                final_account_list.append(bank_account_id.id)

            for save_account in self.browse(list(set(final_account_list).difference(set(same_accounts)))):
                if save_account.acc_number not in account_number_list:
                    acc_rec = xero.accounts.put({u'Name': save_account.partner_id.name + " " + save_account.acc_number,
                                                 u'Type': u'BANK',
                                                 u'BankAccountType': u'BANK',
                                                 u'BankAccountNumber': save_account.acc_number,
                                                 u'CurrencyCode': save_account.currency_id.name,
                                                 u'Code': save_account.acc_number[-6:] or False})
                    save_account.write({'acc_id': acc_rec[0]['AccountID']})
                    self._cr.commit()


class AccountAccount(models.Model):
    _inherit = 'account.account'
    _description = 'Account'

    acc_id = fields.Char('Xero AccountID', readonly=True, copy=False)
    account_type_xero = fields.Selection([
            # Asset
            ('current', 'CURRENT'),
            ('noncurrent', 'NONCURRENT'),
            ('fixed', 'FIXED'),
            ('inventory', 'INVENTORY'),
            ('prepayment', 'PREPAYMENT'),

            # Liability
            ('bank', 'BANK'),
            ('liability', 'LIABILITY'),
            ('currliab', 'CURRLIAB'),
            ('equity', 'EQUITY'),
            ('termliab', 'TERMLIAB'),
            ('paygliability', 'PAYGLIABILITY'),
            ('wagespayableliability', 'WAGESPAYABLELIABILITY'),
            ('superannuationliability', 'SUPERANNUATIONLIABILITY'),

            # Expense
            ('depreciatn', 'DEPRECIATN'),
            ('directcosts', 'DIRECTCOSTS'),
            ('expense', 'EXPENSE'),
            ('overheads', 'OVERHEADS'),
            ('superannuationexpense', 'SUPERANNUATIONEXPENSE'),
            ('wagesexpense', 'WAGESEXPENSE'),

            # Income
            ('otherincome', 'OTHERINCOME'),
            ('revenue', 'REVENUE'),
            ('sales', 'SALES'),
        ], string='Xero Account Type', default='sales')
    use_as_inventory_in_xero = fields.Boolean(string="Use As Inventory In Xero")

    def import_account(self, account_list, xero, company=False, import_option=None):
        """
            Map: AccountID(Odoo) with AccountID(Xero)

            Create a account in Odoo if account is not available with
            AccountID and company.

            Note: If any record is already available with same code in Odoo which we
            going to import from xero then it will skip that particular record.

            Constraint(Odoo): The code of the account must be unique per company

            If account record is available then it will update that particular record.
        """
        account_mapping = {'bank': self.env.ref('account.data_account_type_liquidity'),
                           'current': self.env.ref('account.data_account_type_current_assets'),
                           'currliab': self.env.ref('account.data_account_type_current_liabilities'),
                           'depreciatn': self.env.ref('account.data_account_type_depreciation'),
                           'directcosts': self.env.ref('account.data_account_type_expenses'),
                           'equity': self.env.ref('account.data_account_type_equity'),
                           'expense': self.env.ref('account.data_account_type_expenses'),
                           'fixed': self.env.ref('account.data_account_type_fixed_assets'),
                           'inventory': self.env.ref('account.data_account_type_current_assets'),
                           'liability': self.env.ref('account.data_account_type_current_liabilities'),
                           'noncurrent': self.env.ref('account.data_account_type_non_current_assets'),
                           'otherincome': self.env.ref('account.data_account_type_other_income'),
                           'overheads': self.env.ref('account.data_account_type_expenses'),
                           'prepayment': self.env.ref('account.data_account_type_prepayments'),
                           'revenue': self.env.ref('account.data_account_type_revenue'),
                           'sales': self.env.ref('account.data_account_type_revenue'),
                           'termliab': self.env.ref('account.data_account_type_non_current_liabilities'),
                           'paygliability': self.env.ref('account.data_account_type_current_liabilities'),
                           'wagesexpense': self.env.ref('account.data_account_type_expenses'),
                           'superannuationexpense': self.env.ref('account.data_account_type_expenses'),
                           'superannuationliability': self.env.ref('account.data_account_type_non_current_liabilities'),
                            }

        for account in account_list:
            if account.get('Status') == 'ACTIVE' and account.get('Type'):
                account_type = str(account['Type'].lower())
                if account_mapping.get(account_type):
                    user_type = account_mapping[account_type]
                    account_rec = self.search([('acc_id', '=', account.get('AccountID')),
                                               ('company_id', '=', company)])
                    if account.get('Type') == 'BANK' and not account.get('Code'):
                        raise UserError(_('Please enter unique code for account \'%s\' on Xero side.')% (account.get('Name')))
                    available_acc_ids = self.search([('code', '=', account.get('Code')),
                                                     ('company_id', '=', company)])

                    if available_acc_ids and not available_acc_ids.acc_id and available_acc_ids.name == account.get('Name'):
                        available_acc_ids.acc_id = account.get('AccountID')
                    tax_id = self.env['account.tax'].search([('xero_tax_type', '=', account.get('TaxType')),
                                                             ('company_id', '=', company)])

                    if not account_rec and not available_acc_ids and import_option in ['create', 'both']:
                        self.create({'name': account.get('Name'),
                                     'code': account.get('Code'),
                                     'acc_id': account.get('AccountID'),
                                     'company_id': company,
                                     'tax_ids': [(6, 0, [tax_id[0].id])] if tax_id else [],
                                     'user_type_id': user_type and user_type.id or False,
                                     'use_as_inventory_in_xero': True if account_type == 'inventory' else False,
                                     'account_type_xero': account_type})
                        self._cr.commit()

    def export_account(self, account_list, xero, company=False, disable_export=False):
        """
            Map: AccountID(Odoo) with AccountID(Xero)

            Create a account in Xero if account is not available with
            AccountID.

            Note: If any record is already available with same name or code in Xero which we
            going to export from Odoo then it will skip that particular record.

            Constraint(Xero): The name and code of the account must be unique
        """
        if not disable_export:
            same_accounts = []
            final_account_list = []
            account_name_list = []
            account_code_list = []
            organisation_detail = xero.organisations.all()
            account_mapping = {self.env.ref('account.data_account_type_receivable').id: 'CURRENT',
                                self.env.ref('account.data_account_type_payable').id: 'CURRLIAB',
                                # self.env.ref('account.data_account_type_liquidity').id: 'BANK',
                                # self.env.ref('account.data_account_type_credit_card').id: 'BANK',
                                self.env.ref('account.data_account_type_current_assets').id: 'CURRENT',
                                self.env.ref('account.data_account_type_non_current_assets').id: 'NONCURRENT',
                                self.env.ref('account.data_account_type_prepayments').id: 'PREPAYMENT',
                                self.env.ref('account.data_account_type_fixed_assets').id: 'FIXED',
                                self.env.ref('account.data_account_type_current_liabilities').id: 'CURRLIAB',
                                self.env.ref('account.data_account_type_non_current_liabilities').id: 'TERMLIAB',
                                self.env.ref('account.data_account_type_equity').id: 'EQUITY',
                                self.env.ref('account.data_unaffected_earnings').id: 'REVENUE',
                                self.env.ref('account.data_account_type_other_income').id: 'OTHERINCOME',
                                self.env.ref('account.data_account_type_revenue').id: 'REVENUE',
                                self.env.ref('account.data_account_type_depreciation').id: 'DEPRECIATN',
                                self.env.ref('account.data_account_type_expenses').id: 'EXPENSE',
                                self.env.ref('account.data_account_type_direct_costs').id: 'EXPENSE'}

            account_ids = self.search([('company_id', '=', company)])
            for account_id in account_ids:
                for account in account_list:
                    if account_id.name.lower() == account.get('Name').lower() and account_id.code == account.get('Code'):
                        if not account_id.acc_id:
                            account_id.write({'acc_id': account.get('AccountID')})
                    else:
                        account_name_list.append(account.get('Name'))
                    account_code_list.append(account.get('Code'))
                    if account_id.acc_id == account.get('AccountID'):
                        same_accounts.append(account_id.id)
                final_account_list.append(account_id.id)

            for save_account in self.browse(list(set(final_account_list).difference(set(same_accounts)))):
                if save_account.code not in account_code_list and save_account.name not in account_name_list:
                    if account_mapping.get(save_account.user_type_id.id):
                        if len(account_ids) >= 30:
                            time.sleep(1)
                        account = account_mapping[save_account.user_type_id.id]
                        if save_account.use_as_inventory_in_xero:
                            account = 'INVENTORY'
                        tax = None
                        if save_account.tax_ids:
                            tax = save_account.tax_ids[0]

                        data = {u'Code': save_account.code,
                                u'Name': save_account.name,
                                u'Type': account}
                        if organisation_detail[0].get('CountryCode') in ['AU']:
                            data.update({u'TaxType': tax.xero_tax_type if tax else 'BASEXCLUDED'})
                        else:
                            data.update({u'TaxType': tax.xero_tax_type if tax else None})
                        acc_rec = xero.accounts.put(data)
                        save_account.acc_id = acc_rec[0]['AccountID']
                        self._cr.commit()
