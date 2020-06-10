# -*- coding: utf-8 -*-
# Part of BrowseInfo. See LICENSE file for full copyright and licensing details.

import odoo.addons.decimal_precision as dp
from odoo import api, fields, models, _


class sale_order(models.Model):
    _inherit = 'sale.order'

    @api.depends('discount_amount')
    def _calculate_discount(self):
        res=0.0
        discount = 0.0
        for self_obj in self:
            if self_obj.discount_method == 'fix':
                discount = self_obj.discount_amount
                res = discount
            elif self_obj.discount_method == 'per':
                discount = self_obj.amount_untaxed * (self_obj.discount_amount/ 100)
                res = discount
            else:
                res = discount
        return res


    @api.depends('order_line.price_total','discount_amount')
    def _amount_all(self):
        """
        Compute the total amounts of the SO.
        """
        cur_obj = self.env['res.currency']
        for order in self:
            amount_untaxed = amount_tax = 0.0
            for line in order.order_line:
                amount_untaxed += line.price_subtotal
                amount_tax += line.price_tax

            order.update({
                          'amount_untaxed': amount_untaxed,
                          'amount_tax': amount_tax,
                          'amount_total': amount_untaxed + amount_tax,
                          })
            res = self._calculate_discount()
            order.update({'discount_amt' : res,
                          'amount_total': amount_untaxed + amount_tax-res
                          })


    discount_method = fields.Selection([('fix', 'Fixed'), ('per', 'Percentage')], 'Discount Method')
    discount_amount = fields.Float('Discount Amount')
    discount_amt = fields.Monetary(compute='_amount_all', string='- Discount', digits_compute=dp.get_precision('Account'), store=True, readonly=True)

    def _prepare_invoice(self):

        res = super(sale_order,self)._prepare_invoice()
        res.update({'discount_method': self.discount_method,'discount_amount': self.discount_amount,'discount_amt': self.discount_amt,})
        return res
        
class sale_order_line(models.Model):
    _inherit = 'sale.order.line'

    is_apply_on_discount_amount =  fields.Boolean("Tax Apply After Discount")
    discount_method = fields.Selection([('fix', 'Fixed'), ('per', 'Percentage')], 'Discount Method')

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:s
