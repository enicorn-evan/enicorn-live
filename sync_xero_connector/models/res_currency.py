# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

from odoo import api, fields, models, _


class ResCurrency(models.Model):
    _inherit = 'res.currency'
    _description = 'Currency'

    symbol = fields.Char(help="Currency sign, to be used when printing amounts.", required=False)

    def import_currency(self, currency_list, xero):
        """
            Map: currency name(Odoo) with currency code(Xero)

            Create a currency in odoo if currency is not available for given
            name and company.

            If Currency record is available then it will update that particular record.
        """
        for currency in currency_list:
            inactive_currency = self.search([('name', '=', currency.get('Code')), ('active', '=', False)])
            active_currency = self.search([('name', '=', currency.get('Code')), ('active', '=', True)])
            if inactive_currency:
                inactive_currency[0].write({'active': True})
                self._cr.commit()
            elif not inactive_currency and not active_currency:
                self.create({'name': currency.get('Code'), 'active': True})
                self._cr.commit()

    @api.model
    def _get_conversion_rate_by_amount(self, from_currency, to_currency):
        """ Convert the amount as per xero currency rates """

        to_currency = to_currency.with_env(self.env)
        return to_currency.rate / from_currency

    def compute(self, from_amount, to_currency, round=True):
        """ Convert `from_amount` from currency `self` to `to_currency`. """
        company = self.env['res.company'].browse(self._context.get('company_id')) or self.env['res.users']._get_company()
        date = self._context.get('date') or fields.Date.today()
        self, to_currency = self or to_currency, to_currency or self
        assert self, "compute from unknown currency"
        assert to_currency, "compute to unknown currency"
        # apply conversion rate
        if self == to_currency:
            to_amount = from_amount
        else:
            if self._context.get('CurrencyRate'):
                to_amount = from_amount * self._get_conversion_rate_by_amount(self._context.get('CurrencyRate'),to_currency)
            else:
                to_amount = from_amount * self._get_conversion_rate(self, to_currency, company, date)
        # apply rounding
        return to_currency.round(to_amount) if round else to_amount
