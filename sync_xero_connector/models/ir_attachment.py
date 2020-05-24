# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

from odoo import api, fields, models, _


class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    def export_attachments(self, xero, last_attachment_export_date, company=False):
        for invoice in self.env['account.move'].search([('xero_invoice_id', '!=', False), ('type', 'in', ['in_invoice', 'out_invoice']), ('company_id', '=', company)]):
            count = 1
            if last_attachment_export_date:
                attachments = self.search([('res_model', '=', 'account.move'), ('res_id', '=', invoice.id), ('create_date', '>=', last_attachment_export_date)])
            else:
                attachments = self.search([('res_model', '=', 'account.move'), ('res_id', '=', invoice.id)])

            for attachment in attachments:
                if count < 10:
                    attachment_type = 'Invoices' if invoice.type == 'out_invoice' else 'Receipts'
                    if not attachment.file_size > 3000000:
                        file = open(str(attachment._filestore()) + '/' + str(attachment.store_fname), 'rb')
                        xero.attachments.put_attachment(invoice.xero_invoice_id,
                                attachment.name, file, attachment.mimetype, include_online=True, attachment_model=attachment_type)
                        file.close()
                    count += 1
        for invoice in self.env['account.move'].search([('xero_invoice_id', '!=', False), ('type', 'in', ['in_refund', 'out_refund']), ('company_id', '=', company)]):
            count = 1
            if last_attachment_export_date:
                attachments = self.search([('res_model', '=', 'account.move'), ('res_id', '=', invoice.id), ('create_date', '>=', last_attachment_export_date)])
            else:
                attachments = self.search([('res_model', '=', 'account.move'), ('res_id', '=', invoice.id)])

            for attachment in attachments:
                if count < 10:
                    attachment_type = 'Creditnotes' if invoice.type == 'out_refund' else 'Refunds'
                    if not attachment.file_size > 3000000:
                        file = open(str(attachment._filestore()) + '/' + str(attachment.store_fname), 'rb')
                        xero.attachments.put_attachment(invoice.xero_invoice_id,
                                attachment.name, file, attachment.mimetype, include_online=True, attachment_model=attachment_type)
                        file.close()
                    count += 1

        partners = self.env['res.partner'].search(['|', ('company_id', '=', company), ('company_id', '=', False)]).filtered(lambda partner: partner.contact_xero_company_ids.filtered(lambda contact: contact.xero_contact_id != False and contact.company_id.id == company))
        for partner in partners:
            count = 1
            if last_attachment_export_date:
                attachments = self.search([('res_model', '=', 'res.partner'), ('res_id', '=', partner.id), ('create_date', '>=', last_attachment_export_date)])
            else:
                attachments = self.search([('res_model', '=', 'res.partner'), ('res_id', '=', partner.id)])

            for attachment in attachments:
                if count < 10:
                    if not attachment.file_size > 3000000:
                        file = open(str(attachment._filestore()) + '/' + str(attachment.store_fname), 'rb')
                        contact = partner.contact_xero_company_ids.filtered(lambda contact: contact.company_id.id == company)
                        xero.attachments.put_attachment(contact.xero_contact_id,
                                attachment.name, file, attachment.mimetype, include_online=True, attachment_model= 'Contacts')
                        file.close()
                    count += 1
