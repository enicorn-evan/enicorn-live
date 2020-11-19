from odoo import api, SUPERUSER_ID

def _initial_setup(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['res.partner.fields']._update_res_partner_fields()
    env.cr.commit()