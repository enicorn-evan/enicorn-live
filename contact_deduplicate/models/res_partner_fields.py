# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models, _


class ResPartnerField(models.Model):
    _name = 'res.partner.fields'

    name = fields.Char()
    field = fields.Char()

    def _update_res_partner_fields(self):
        fields = self.env['res.partner'].fields_get()
        for field, value in fields.items():
            name = value.get('string', None)
            if name:
                exists = self.env['res.partner.fields'].search([('name', '=', name), ('field', '=', field)])
                if not exists:
                    self.env['res.partner.fields'].create({'name': name, 'field': field})