# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

from odoo import api, fields, models, _
from odoo.exceptions import Warning


class ContactXeroCompany(models.Model):
    _name="contact.xero.company"
    _description = 'Contact Xero'

    company_id = fields.Many2one('res.company', 'Company', required=True)
    xero_contact_id = fields.Char('Xero ContctID')
    partner_id = fields.Many2one('res.partner', 'Contact')


class ResPartner(models.Model):
    _inherit = 'res.partner'
    _description = 'Partner'

    xero_name = fields.Char('Xero Conatct Name')
    skype_name = fields.Char('Skype')
    attention_to = fields.Char('AttentionTo')
    first_name = fields.Char('First Name')
    last_name = fields.Char('Last Name')
    bank_account_id = fields.Many2one('res.partner.bank', 'Bank Account')
    tax_number = fields.Char('Tax Number')
    direct_dial = fields.Char('Direct dial')
    contact_xero_company_ids = fields.One2many('contact.xero.company', 'partner_id', string="Xero Multi Company")

    @api.constrains('email')
    def _check_email(self):
        for obj in self:
            if obj.email:
                if '@' not in obj.email or '.' not in obj.email:
                    raise Warning(_('Please enter email in right format!'))
        return True

    @api.onchange('email')
    def onchange_email(self):
        if self.email:
            if '@' not in self.email or '.' not in self.email:
                raise Warning(_('Please enter email in right format!'))

    @api.onchange('company_id')
    def _onchange_company(self):
        if self.company_id:
            xero_company = self.contact_xero_company_ids.filtered(lambda l: l.company_id.id == self.company_id.id)
            if not xero_company:
                xero_company_id = self.env['contact.xero.company'].create({'company_id': self.company_id.id, 'partner_id': self.id})
                self.contact_xero_company_ids = [(6, 0, xero_company_id.ids)]
            # else:
            #     contact_xero = self.contact_xero_company_ids - self.contact_xero_company_ids.xero_company
            #     contact_xero.unlink()

    def import_contact(self, contact_list, xero, company=False, import_option=None):
        """
            Map: ContactID(Odoo) with ContactID(Xero)

            Create a contact in Odoo if contact is not available with
            ContactID and company.

            If contact record is available then it will update that particular record.
        """
        contact_email = []
        all_contacts = self.search(['|', ('company_id', '=', company), ('company_id', '=', False), ('parent_id', '=', False)])
        for contact_rec in all_contacts:
            contact_email.append(contact_rec.email)

        for contact_details in contact_list:
            active = True
            phone_list = []
            contactgroups_list = []
            country_id = False
            state_id = False
            po_country_id = False
            po_state_id = False
            bank_id = False
            currency_id = False
            is_po_address = False
            currency_pool = self.env['res.currency']
            country_pool = self.env['res.country']
            state_pool = self.env['res.country.state']
            account_pool = self.env['account.account']
            partner_bank_pool = self.env['res.partner.bank']
            # if contact_details.get('EmailAddress'):
            #     if contact_details.get('EmailAddress') in contact_email:
            #         same_contact = self.search([('email', '=', contact_details.get('EmailAddress')), ('company_id', '=', company)], limit=1)
            #         if same_contact and not same_contact.contact_id:
            #             same_contact.contact_id = contact_details.get('ContactID')

            # partner_rec = self.search([('contact_id', '=', contact_details.get('ContactID')),
            #                            ('company_id', '=', company)], limit=1)
            partner_rec = self.search([]).filtered(lambda partner:partner.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company and l.xero_contact_id == contact_details.get('ContactID')))

            if contact_details.get('Addresses'):
                for contact_val in contact_details.get('Addresses'):
                    if contact_val.get('AddressType') == 'STREET':
                        contact = contact_val
                        add_line1 = ''
                        add_line2 = ''
                        if contact.get('AddressLine1', False):
                            add_line1 += contact.get('AddressLine1', False)
                        if contact.get('AddressLine2', False):
                            add_line1 += ' '
                            add_line1 += contact.get('AddressLine2', False)
                        if contact.get('AddressLine3', False):
                            add_line2 += contact.get('AddressLine3', False)
                        if contact.get('AddressLine4', False):
                            add_line2 += ' '
                            add_line2 += contact.get('AddressLine4', False)

                        if contact.get('Country'):
                            country_id = country_pool.search([('name', '=' , contact.get('Country'))])
                            if country_id:
                                country_id = country_id[0]
                        if not country_id and contact.get('Country'):
                            country_id = country_pool.create({'name':  contact.get('Country')})
                        if contact.get('Region'):
                            state_id = state_pool.search(['|', ('name', '=' , contact.get('Region')),
                                              ('code', '=' , contact.get('Region'))])
                            if state_id:
                                state_id = state_id[0]
                        if not state_id and contact.get('Region') and country_id:
                            state_id = state_pool.create({'name':  contact.get('Region'),
                                                          'code': contact.get('Region'),
                                                          'country_id': country_id.id})

                    if contact_val.get('AddressType') == 'POBOX':
                        po_contact = contact_val
                        po_add_line1 = ''
                        po_add_line2 = ''
                        if po_contact.get('AddressLine1', False):
                            is_po_address = True
                            po_add_line1 += po_contact.get('AddressLine1', False)
                        if po_contact.get('AddressLine2', False):
                            is_po_address = True
                            po_add_line1 += ' '
                            po_add_line1 += po_contact.get('AddressLine2', False)
                        if po_contact.get('AddressLine3', False):
                            is_po_address = True
                            po_add_line2 += po_contact.get('AddressLine3', False)
                        if po_contact.get('AddressLine4', False):
                            is_po_address = True
                            po_add_line2 += ' '
                            po_add_line2 += po_contact.get('AddressLine4', False)

                        if po_contact.get('Country'):
                            is_po_address = True
                            po_country_id = country_pool.search([('name', '=' , po_contact.get('Country'))])
                            if po_country_id:
                                po_country_id = po_country_id[0]
                        if not po_country_id and po_contact.get('Country'):
                            po_country_id = country_pool.create({'name':  po_contact.get('Country')})
                        if po_contact.get('Region'):
                            is_po_address = True
                            po_state_id = state_pool.search(['|',('name', '=' , po_contact.get('Region')),
                                ('code', '=' , po_contact.get('Region'))])
                            if po_state_id:
                                po_state_id = po_state_id[0]
                        if not po_state_id and po_contact.get('Region') and po_country_id:
                            po_state_id = state_pool.create({'name':  po_contact.get('Region'),
                                                            'code': po_contact.get('Region'),
                                                            'country_id': po_country_id.id})

                sales_acc_id = account_pool.search([('user_type_id', '=', self.env.ref('account.data_account_type_receivable').id), ('company_id', '=', company)])
                purchase_acc_id = account_pool.search([('user_type_id', '=', self.env.ref('account.data_account_type_payable').id), ('company_id', '=', company)])
                currency_id = currency_pool.search([('name', '=', contact_details.get('DefaultCurrency'))])
                phone_number = ''
                mobile_number = ''
                for phone in contact_details.get('Phones'):
                    if phone.get('PhoneType', False):
                        if phone.get('PhoneType') == 'DEFAULT':
                            # if phone.get('PhoneCountryCode', False):
                            #     phone_number = '+'+phone.get('PhoneCountryCode', False)+' '+phone.get('PhoneNumber', False)
                            # else:
                            phone_number = phone.get('PhoneNumber', False)
                        if phone.get('PhoneType') == 'MOBILE':
                            # if phone.get('PhoneCountryCode', False):
                            #     mobile_number = '+'+phone.get('PhoneCountryCode', False)+' '+phone.get('PhoneNumber', False)
                            # else:
                            mobile_number = phone.get('PhoneNumber', False)
                        if phone.get('PhoneType') == 'DDI':
                            # if phone.get('PhoneCountryCode', False):
                            #     direct_dial = '+'+phone.get('PhoneCountryCode', False)+' '+phone.get('PhoneNumber', False)
                            # else:
                            direct_dial = phone.get('PhoneNumber', False)

                if contact_details.get('ContactStatus') != 'ACTIVE':
                    active = False
                if partner_rec and import_option in ['update', 'both']:
                    partner_rec.write({
                            'name':contact_details.get('Name'),
                            'phone': phone_number,
                            'mobile': mobile_number,
                            'direct_dial': direct_dial,
                            'first_name':contact_details.get('FirstName', False),
                            'last_name':contact_details.get('LastName', False),
                            # 'contact_id':contact_details.get('ContactID', False),
                            'active': active,
                            'skype_name':contact_details.get('SkypeUserName', False),
                            'email':contact_details.get('EmailAddress', False),
                            # 'customer': contact_details.get('IsCustomer', False),
                            # 'supplier': contact_details.get('IsSupplier', False),
                            'attention_to': contact.get('AttentionTo', False),
                            'city': contact.get('City', False),
                            'state_id': state_id and state_id.id or False,
                            'street': add_line1,
                            'street2': add_line2,
                            'zip': contact.get('PostalCode', False),
                            'country_id': country_id and country_id.id or False,
                            'website': contact_details.get('Website', False),
                            'property_account_receivable_id': sales_acc_id and sales_acc_id[0].id or False,
                            'property_account_payable_id': purchase_acc_id and purchase_acc_id[0].id or False,
                            'tax_number': contact_details.get('TaxNumber', False),
                            'bank_account_id': bank_id and bank_id.id or False,
                            'currency_id': currency_id and currency_id[0].id or False})

                    if contact_details.get('BankAccountDetails'):
                        bank_id = partner_bank_pool.search([('acc_number', '=' , contact_details.get('BankAccountDetails'))], limit=1)
                        if not bank_id:
                            partner_bank_pool.create({'acc_number': contact_details.get('BankAccountDetails'),
                                                      'partner_id': partner_rec.id})
                        else:
                            bank_id.partner_id = partner_rec.id

                    for contactgroups in contact_details.get('ContactGroups'):
                        group_id = self.env['res.partner.category'].search([('xero_tag_id', '=', contactgroups.get('ContactGroupID'))])
                        if group_id:
                            contactgroups_list.append(group_id.id)

                    contactgroups_list = list(set(contactgroups_list))
                    partner_rec.category_id = [(6, 0, contactgroups_list)] if contactgroups_list else []
                    if is_po_address:
                        invoice_address_id = partner_rec.child_ids.filtered(lambda x: x.type == "invoice")
                        if invoice_address_id:
                            invoice_address_id[0].write({'name': contact_details.get('Name', False),
                                'city': po_contact.get('City', False),
                                'country_id': po_country_id and po_country_id.id or False,
                                'state_id': po_state_id and po_state_id.id or False,
                                'attention_to': po_contact.get('AttentionTo', False),
                                'street': po_add_line1,
                                'street2': po_add_line2,
                                'zip': po_contact.get('PostalCode') or u'',
                                # 'company_id': company,
                                'contact_xero_company_ids': [(0, 0, {'company_id': company})],
                                'type': 'invoice',
                                # 'customer': False,
                                # 'supplier': False,
                                'parent_id':  partner_rec and  partner_rec.id or False})
                        else:
                            self.create({'name': contact_details.get('Name', False),
                                'city': po_contact.get('City', False),
                                'country_id': po_country_id and po_country_id.id or False,
                                'state_id': po_state_id and po_state_id.id or False,
                                'attention_to': po_contact.get('AttentionTo', False),
                                'street': po_add_line1,
                                'street2': po_add_line2,
                                'zip': po_contact.get('PostalCode') or u'',
                                # 'company_id': company,
                                'contact_xero_company_ids': [(0, 0, {'company_id': company})],
                                'type': 'invoice',
                                # 'customer': False,
                                # 'supplier': False,
                                'parent_id':  partner_rec and  partner_rec.id or False})

                    child_record = []
                    for record in partner_rec.child_ids.filtered(lambda x: x.type == "contact"):
                        child_record.append(record.email)
                    for contact_per in contact_details.get('ContactPersons'):
                        if contact_per.get('EmailAddress') in child_record:
                            child_rec = self.search([('parent_id', '=', partner_rec.id), ('email', '=', contact_per.get('EmailAddress'))], limit=1)
                            child_rec.write({
                                'name': contact_per.get('FirstName','') + ' ' + contact_per.get('LastName', False),
                                'first_name': contact_per.get('FirstName', False),
                                'last_name': contact_per.get('LastName', False),
                                'email': contact_per.get('EmailAddress', False),
                                # 'company_id': company,
                                'contact_xero_company_ids': [(0, 0, {'company_id': company})],
                                # 'customer': False,
                                # 'supplier': False,
                                'parent_id': partner_rec and partner_rec.id or False,
                                'type': 'contact'})
                        else:
                            self.create({
                                'name': contact_per.get('FirstName','') + ' ' + contact_per.get('LastName', False),
                                'first_name': contact_per.get('FirstName', False),
                                'last_name': contact_per.get('LastName', False),
                                'email': contact_per.get('EmailAddress', False),
                                # 'company_id': company,
                                'contact_xero_company_ids': [(0, 0, {'company_id': company})],
                                # 'customer': False,
                                # 'supplier': False,
                                'parent_id': partner_rec and partner_rec.id or False,
                                'type': 'contact'})
                    self._cr.commit()

                elif not partner_rec and import_option in ['create', 'both']:
                    partner_id = self.create({
                            'name':contact_details.get('Name', False),
                            'phone': phone_number,
                            'mobile': mobile_number,
                            'direct_dial': direct_dial,
                            'first_name':contact_details.get('FirstName', False),
                            'last_name':contact_details.get('LastName', False),
                            # 'contact_id':contact_details.get('ContactID', False),
                            'company_id': company,
                            'contact_xero_company_ids': [(0, 0, {'company_id': company,
                                                                 'xero_contact_id': contact_details.get('ContactID', False),
                                                                })],
                            'active': active,
                            'skype_name':contact_details.get('SkypeUserName', False),
                            'email':contact_details.get('EmailAddress', False),
                            # 'customer': contact_details.get('IsCustomer', False),
                            # 'supplier': contact_details.get('IsSupplier', False),
                            'city': contact.get('City', False),
                            'state_id': state_id and state_id.id or False,
                            'attention_to': contact.get('AttentionTo', False),
                            'street': add_line1,
                            'street2': add_line2,
                            'zip': contact.get('PostalCode', False),
                            'country_id': country_id and country_id.id or False,
                            'website': contact_details.get('Website', False),
                            'property_account_receivable_id': sales_acc_id and sales_acc_id[0].id or False,
                            'property_account_payable_id': purchase_acc_id and purchase_acc_id[0].id or False,
                            'tax_number': contact_details.get('TaxNumber', False),
                            'bank_account_id': bank_id and bank_id.id or False,
                            'currency_id': currency_id and currency_id[0].id or False})

                    if contact_details.get('BankAccountDetails'):
                        bank_id = partner_bank_pool.search([('acc_number', '=' , contact_details.get('BankAccountDetails'))], limit=1)
                        if not bank_id:
                            partner_bank_pool.create({'acc_number': contact_details.get('BankAccountDetails'),
                                                      'partner_id': partner_id.id})
                        else:
                            bank_id.partner_id = partner_id.id

                    for contactgroups in contact_details.get('ContactGroups'):
                        group_id = self.env['res.partner.category'].search([('xero_tag_id', '=', contactgroups.get('ContactGroupID'))])
                        if group_id:
                            contactgroups_list.append(group_id.id)

                    partner_id.category_id = [(6, 0, contactgroups_list)] if contactgroups_list else []
                    if is_po_address:
                        invoice_add_id = self.create({'name': contact_details.get('Name', False),
                            'city': po_contact.get('City', False),
                            'country_id': po_country_id and po_country_id.id or False,
                            'state_id': po_state_id and po_state_id.id or False,
                            'attention_to': po_contact.get('AttentionTo', False),
                            'street': po_add_line1,
                            'street2': po_add_line2,
                            'zip': po_contact.get('PostalCode') or u'',
                            'company_id': company,
                            'contact_xero_company_ids': [(0, 0, {'company_id': company})],
                            'type': 'invoice',
                            # 'customer': False,
                            # 'supplier': False,
                            'parent_id': partner_id and partner_id.id or False})
                    for contact_per in contact_details.get('ContactPersons'):
                        self.create({
                            'name': contact_per.get('FirstName','') + ' ' + contact_per.get('LastName', False),
                            'first_name': contact_per.get('FirstName', False),
                            'last_name': contact_per.get('LastName', False),
                            'email': contact_per.get('EmailAddress', False),
                            'company_id': company,
                            'contact_xero_company_ids': [(0, 0, {'company_id': company})],
                            # 'customer': False,
                            # 'supplier': False,
                            'parent_id': partner_id and partner_id.id or False,
                            'type': 'contact'})
                    self._cr.commit()

    def import_contact_overwrite(self, contact_list, xero, company=False, import_option=None):
        """
            Map: ContactID(Odoo) with ContactID(Xero)

            Create a contact in Odoo if contact is not available with
            ContactID and company.

            If contact record is available then it will update that particular record.
        """
        contact_email = []
        all_contacts = self.search(['|', ('company_id', '=', company), ('company_id', '=', False), ('parent_id', '=', False)])
        for contact_rec in all_contacts:
            contact_email.append(contact_rec.email)

        for contact_details in contact_list:
            active = True
            phone_list = []
            contactgroups_list = []
            country_id = False
            state_id = False
            po_country_id = False
            po_state_id = False
            bank_id = False
            currency_id = False
            is_po_address = False
            currency_pool = self.env['res.currency']
            country_pool = self.env['res.country']
            state_pool = self.env['res.country.state']
            account_pool = self.env['account.account']
            partner_bank_pool = self.env['res.partner.bank']
            if contact_details.get('EmailAddress'):
                if contact_details.get('EmailAddress') in contact_email:
                    same_contact = self.search([('email', '=', contact_details.get('EmailAddress')), ('parent_id', '=' , False), '|', ('company_id', '=', company), ('company_id', '=', False)], limit=1)
                    if same_contact:
                        xero_contact = same_contact.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                        if xero_contact and not xero_contact.xero_contact_id:
                            xero_contact.xero_contact_id = contact_details.get('ContactID')
                        elif not xero_contact:
                            same_contact.contact_xero_company_ids = [(0, 0, {'xero_contact_id': contact_details.get('ContactID'),
                                                                            'company_id': company})]

            # partner_rec = self.search([('contact_id', '=', contact_details.get('ContactID')),
            #                            ('company_id', '=', company)], limit=1)
            partner_rec = self.search([]).filtered(lambda partner:partner.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company and l.xero_contact_id == contact_details.get('ContactID')))
            if contact_details.get('Addresses'):
                for contact_val in contact_details.get('Addresses'):
                    if contact_val.get('AddressType') == 'STREET':
                        contact = contact_val
                        add_line1 = ''
                        add_line2 = ''
                        if contact.get('AddressLine1', False):
                            add_line1 += contact.get('AddressLine1', False)
                        if contact.get('AddressLine2', False):
                            add_line1 += ' '
                            add_line1 += contact.get('AddressLine2', False)
                        if contact.get('AddressLine3', False):
                            add_line2 += contact.get('AddressLine3', False)
                        if contact.get('AddressLine4', False):
                            add_line2 += ' '
                            add_line2 += contact.get('AddressLine4', False)

                        if contact.get('Country'):
                            country_id = country_pool.search([('name', '=' , contact.get('Country'))])
                            if country_id:
                                country_id = country_id[0]
                        if not country_id and contact.get('Country'):
                            country_id = country_pool.create({'name':  contact.get('Country')})
                        if contact.get('Region'):
                            state_id = state_pool.search(['|', ('name', '=' , contact.get('Region')),
                                              ('code', '=' , contact.get('Region'))])
                            if state_id:
                                state_id = state_id[0]
                        if not state_id and contact.get('Region') and country_id:
                            state_id = state_pool.create({'name':  contact.get('Region'),
                                                          'code': contact.get('Region'),
                                                          'country_id': country_id.id})

                    if contact_val.get('AddressType') == 'POBOX':
                        po_contact = contact_val
                        po_add_line1 = ''
                        po_add_line2 = ''
                        if po_contact.get('AddressLine1', False):
                            is_po_address = True
                            po_add_line1 += po_contact.get('AddressLine1', False)
                        if po_contact.get('AddressLine2', False):
                            is_po_address = True
                            po_add_line1 += ' '
                            po_add_line1 += po_contact.get('AddressLine2', False)
                        if po_contact.get('AddressLine3', False):
                            is_po_address = True
                            po_add_line2 += po_contact.get('AddressLine3', False)
                        if po_contact.get('AddressLine4', False):
                            is_po_address = True
                            po_add_line2 += ' '
                            po_add_line2 += po_contact.get('AddressLine4', False)

                        if po_contact.get('Country'):
                            is_po_address = True
                            po_country_id = country_pool.search([('name', '=' , po_contact.get('Country'))])
                            if po_country_id:
                                po_country_id = po_country_id[0]
                        if not po_country_id and po_contact.get('Country'):
                            po_country_id = country_pool.create({'name':  po_contact.get('Country')})
                        if po_contact.get('Region'):
                            is_po_address = True
                            po_state_id = state_pool.search(['|',('name', '=' , po_contact.get('Region')),
                                ('code', '=' , po_contact.get('Region'))])
                            if po_state_id:
                                po_state_id = po_state_id[0]
                        if not po_state_id and po_contact.get('Region') and po_country_id:
                            po_state_id = state_pool.create({'name':  po_contact.get('Region'),
                                                            'code': po_contact.get('Region'),
                                                            'country_id': po_country_id.id})

                sales_acc_id = account_pool.search([('user_type_id', '=', self.env.ref('account.data_account_type_receivable').id), ('company_id', '=', company)])
                purchase_acc_id = account_pool.search([('user_type_id', '=', self.env.ref('account.data_account_type_payable').id), ('company_id', '=', company)])
                currency_id = currency_pool.search([('name', '=', contact_details.get('DefaultCurrency'))])
                phone_number = ''
                mobile_number = ''
                for phone in contact_details.get('Phones'):
                    if phone.get('PhoneType', False):
                        if phone.get('PhoneType') == 'DEFAULT':
                            # if phone.get('PhoneCountryCode', False):
                            #     phone_number = '+'+phone.get('PhoneCountryCode', False)+' '+phone.get('PhoneNumber', False)
                            # else:
                            phone_number = phone.get('PhoneNumber', False)
                        if phone.get('PhoneType') == 'MOBILE':
                            # if phone.get('PhoneCountryCode', False):
                            #     mobile_number = '+'+phone.get('PhoneCountryCode', False)+' '+phone.get('PhoneNumber', False)
                            # else:
                            mobile_number = phone.get('PhoneNumber', False)
                        if phone.get('PhoneType') == 'DDI':
                            # if phone.get('PhoneCountryCode', False):
                            #     direct_dial = '+'+phone.get('PhoneCountryCode', False)+' '+phone.get('PhoneNumber', False)
                            # else:
                            direct_dial = phone.get('PhoneNumber', False)

                if contact_details.get('ContactStatus') != 'ACTIVE':
                    active = False
                if partner_rec and import_option in ['update', 'both']:
                    partner_rec.write({
                            'name':contact_details.get('Name'),
                            'phone': phone_number,
                            'mobile': mobile_number,
                            'direct_dial': direct_dial,
                            'first_name':contact_details.get('FirstName', False),
                            'last_name':contact_details.get('LastName', False),
                            # 'contact_id':contact_details.get('ContactID', False),
                            'active': active,
                            'skype_name':contact_details.get('SkypeUserName', False),
                            'email':contact_details.get('EmailAddress', False),
                            # 'customer': contact_details.get('IsCustomer', False),
                            # 'supplier': contact_details.get('IsSupplier', False),
                            'attention_to': contact.get('AttentionTo', False),
                            'city': contact.get('City', False),
                            'state_id': state_id and state_id.id or False,
                            'street': add_line1,
                            'street2': add_line2,
                            'zip': contact.get('PostalCode', False),
                            'country_id': country_id and country_id.id or False,
                            'website': contact_details.get('Website', False),
                            'property_account_receivable_id': sales_acc_id and sales_acc_id[0].id or False,
                            'property_account_payable_id': purchase_acc_id and purchase_acc_id[0].id or False,
                            'tax_number': contact_details.get('TaxNumber', False),
                            'bank_account_id': bank_id and bank_id.id or False,
                            'currency_id': currency_id and currency_id[0].id or False})

                    if contact_details.get('BankAccountDetails'):
                        bank_id = partner_bank_pool.search([('acc_number', '=' , contact_details.get('BankAccountDetails'))], limit=1)
                        if not bank_id:
                            partner_bank_pool.create({'acc_number': contact_details.get('BankAccountDetails'),
                                                      'partner_id': partner_rec.id})
                        else:
                            bank_id.partner_id = partner_rec.id

                    for contactgroups in contact_details.get('ContactGroups'):
                        group_id = self.env['res.partner.category'].search([('xero_tag_id', '=', contactgroups.get('ContactGroupID'))])
                        if group_id:
                            contactgroups_list.append(group_id.id)

                    contactgroups_list = list(set(contactgroups_list))
                    partner_rec.category_id = [(6, 0, contactgroups_list)] if contactgroups_list else []
                    if is_po_address:
                        invoice_address_id = partner_rec.child_ids.filtered(lambda x: x.type == "invoice")
                        if invoice_address_id:
                            invoice_address_id[0].write({'name': contact_details.get('Name'),
                                'city': po_contact.get('City', False),
                                'country_id': po_country_id and po_country_id.id or False,
                                'state_id': po_state_id and po_state_id.id or False,
                                'attention_to': po_contact.get('AttentionTo', False),
                                'street': po_add_line1,
                                'street2': po_add_line2,
                                'zip': po_contact.get('PostalCode') or u'',
                                # 'company_id': company,
                                'contact_xero_company_ids': [(0, 0, {'company_id': company})],
                                'type': 'invoice',
                                # 'customer': False,
                                # 'supplier': False,
                                'parent_id':  partner_rec and  partner_rec.id or False})
                        else:
                            self.create({'name': contact_details.get('Name'),
                                'city': po_contact.get('City', False),
                                'country_id': po_country_id and po_country_id.id or False,
                                'state_id': po_state_id and po_state_id.id or False,
                                'attention_to': po_contact.get('AttentionTo', False),
                                'street': po_add_line1,
                                'street2': po_add_line2,
                                'zip': po_contact.get('PostalCode') or u'',
                                # 'company_id': company,
                                'contact_xero_company_ids': [(0, 0, {'company_id': company})],
                                'type': 'invoice',
                                # 'customer': False,
                                # 'supplier': False,
                                'parent_id':  partner_rec and  partner_rec.id or False})

                    child_record = []
                    for record in partner_rec.child_ids.filtered(lambda x: x.type == "contact"):
                        child_record.append(record.email)
                    for contact_per in contact_details.get('ContactPersons'):
                        if contact_per.get('EmailAddress') in child_record:
                            child_rec = self.search([('parent_id', '=', partner_rec.id), ('email', '=', contact_per.get('EmailAddress'))], limit=1)
                            child_rec.write({
                                'name': contact_per.get('FirstName','') + ' ' + contact_per.get('LastName', False),
                                'first_name': contact_per.get('FirstName', False),
                                'last_name': contact_per.get('LastName', False),
                                'email': contact_per.get('EmailAddress', False),
                                # 'company_id': company,
                                'contact_xero_company_ids': [(0, 0, {'company_id': company})],
                                # 'customer': False,
                                # 'supplier': False,
                                'parent_id': partner_rec and partner_rec.id or False,
                                'type': 'contact'})
                        else:
                            self.create({
                                'name': contact_per.get('FirstName','') + ' ' + contact_per.get('LastName', False),
                                'first_name': contact_per.get('FirstName', False),
                                'last_name': contact_per.get('LastName', False),
                                'email': contact_per.get('EmailAddress', False),
                                # 'company_id': company,
                                'contact_xero_company_ids': [(0, 0, {'company_id': company})],
                                # 'customer': False,
                                # 'supplier': False,
                                'parent_id': partner_rec and partner_rec.id or False,
                                'type': 'contact'})
                    self._cr.commit()

                elif not partner_rec and import_option in ['create', 'both']:
                    partner_id = self.create({
                            'name':contact_details.get('Name', False),
                            'phone': phone_number,
                            'mobile': mobile_number,
                            'direct_dial': direct_dial,
                            'first_name':contact_details.get('FirstName', False),
                            'last_name':contact_details.get('LastName', False),
                            # 'contact_id':contact_details.get('ContactID', False),
                            'company_id': company,
                            'contact_xero_company_ids': [(0, 0, {'company_id': company,
                                                                 'xero_contact_id': contact_details.get('ContactID', False),
                                                                })],
                            'active': active,
                            'skype_name':contact_details.get('SkypeUserName', False),
                            'email':contact_details.get('EmailAddress', False),
                            # 'customer': contact_details.get('IsCustomer', False),
                            # 'supplier': contact_details.get('IsSupplier', False),
                            'city': contact.get('City', False),
                            'state_id': state_id and state_id.id or False,
                            'attention_to': contact.get('AttentionTo', False),
                            'street': add_line1,
                            'street2': add_line2,
                            'zip': contact.get('PostalCode', False),
                            'country_id': country_id and country_id.id or False,
                            'website': contact_details.get('Website', False),
                            'property_account_receivable_id': sales_acc_id and sales_acc_id[0].id or False,
                            'property_account_payable_id': purchase_acc_id and purchase_acc_id[0].id or False,
                            'tax_number': contact_details.get('TaxNumber', False),
                            'bank_account_id': bank_id and bank_id.id or False,
                            'currency_id': currency_id and currency_id[0].id or False})

                    if contact_details.get('BankAccountDetails'):
                        bank_id = partner_bank_pool.search([('acc_number', '=' , contact_details.get('BankAccountDetails'))], limit=1)
                        if not bank_id:
                            partner_bank_pool.create({'acc_number': contact_details.get('BankAccountDetails'),
                                                      'partner_id': partner_id.id})
                        else:
                            bank_id.partner_id = partner_id.id

                    for contactgroups in contact_details.get('ContactGroups'):
                        group_id = self.env['res.partner.category'].search([('xero_tag_id', '=', contactgroups.get('ContactGroupID'))])
                        if group_id:
                            contactgroups_list.append(group_id.id)

                    partner_id.category_id = [(6, 0, contactgroups_list)] if contactgroups_list else []
                    if is_po_address:
                        invoice_add_id = self.create({'name': contact_details.get('Name', False),
                            'city': po_contact.get('City', False),
                            'country_id': po_country_id and po_country_id.id or False,
                            'state_id': po_state_id and po_state_id.id or False,
                            'attention_to': po_contact.get('AttentionTo', False),
                            'street': po_add_line1,
                            'street2': po_add_line2,
                            'zip': po_contact.get('PostalCode') or u'',
                            'company_id': company,
                            'contact_xero_company_ids': [(0, 0, {'company_id': company})],
                            'type': 'invoice',
                            # 'customer': False,
                            # 'supplier': False,
                            'parent_id': partner_id and partner_id.id or False})
                    for contact_per in contact_details.get('ContactPersons'):
                        self.create({
                            'name': contact_per.get('FirstName','') + ' ' + contact_per.get('LastName', False),
                            'first_name': contact_per.get('FirstName', False),
                            'last_name': contact_per.get('LastName', False),
                            'email': contact_per.get('EmailAddress', False),
                            'company_id': company,
                            'contact_xero_company_ids': [(0, 0, {'company_id': company})],
                            # 'customer': False,
                            # 'supplier': False,
                            'parent_id': partner_id and partner_id.id or False,
                            'type': 'contact'})
                    self._cr.commit()

    def export_contact(self, contact_list, xero, last_export_date, company=False, contact_ids=[]):
        '''
        Map: ContactID(Odoo) with ContactID(Xero)

        Create a contact in xero if contact is not available.

        Note: If contact is available in xero with name which we going to
        export from odoo then it will skip that record.

        Constraint(Xero): The name of the Contact must be unique

        If contact record is available in xero then it will update that particular record.
        '''
        status = ''
        same_record = []
        final_contact_list = []
        contact_name_list = []
        count = 1
        if self._context.get('contact_ids'):
            contact_ids = self._context.get('contact_ids')
        else:
            if len(contact_ids) <= 0:
                if last_export_date:
                    # contact_ids = self.search([('company_id', '=', company), ('parent_id', '=', False), '|', ('create_date', '>=', last_export_date), ('write_date', '>=', last_export_date)])
                    contact_ids = self.search([('parent_id', '=', False), '|', ('company_id', '=', company), ('company_id', '=', False), '|', ('create_date', '>=', last_export_date), ('write_date', '>=', last_export_date)])
                    update_child_contact_ids = self.search(['|', ('company_id', '=', company), ('company_id', '=', False), ('parent_id', '!=', False), '|', ('create_date', '>=', last_export_date), ('write_date', '>=', last_export_date),
                        '|', ('active', '=', True), ('active', '=', False)]).mapped('parent_id').filtered(lambda l: not l.parent_id and l.name)
                    contact_ids = contact_ids.union(update_child_contact_ids)
                else:
                    contact_ids = self.search([('parent_id', '=', False), '|', ('company_id', '=', company), ('company_id', '=', False)])

        for contact_id in contact_ids:
            contact_name_list = []
            for contact in contact_list:
                contact_name_list.append(contact.get('Name').lower())
                # if contact_id.contact_id == contact.get('ContactID'):
                #     same_record.append(contact_id.id)
                xero_company = contact_id.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                if xero_company and xero_company.xero_contact_id == contact.get('ContactID'):
                    same_record.append(contact_id.id)
                elif xero_company and not xero_company.xero_contact_id:
                    xero_company.xero_contact_id = contact.get('ContactID')
                elif not xero_company:
                    contact_id.contact_xero_company_ids = [(0, 0, {'company_id': company,
                                                                   'xero_contact_id': contact.get('ContactID')})]
            final_contact_list.append(contact_id.id)

        data_list = []
        contact_list_data = []
        c = 0
        partner_ids = self.browse(list(set(final_contact_list).difference(set(same_record))))
        for partner_id in partner_ids:
            contact_name = ''

            if partner_id.name and partner_id.name.lower() in contact_name_list:
                name = partner_id.name.lower() + ' (' + str(count) + ')'
                contact_name = partner_id.name + ' (' + str(count) + ')'
                while(name in contact_name_list):
                    name = partner_id.name.lower() + ' (' + str(count) + ')'
                    contact_name = partner_id.name + ' (' + str(count) + ')'
                    count += 1
                contact_name_list.append(name)
            elif partner_id.name:
                contact_name_list.append(partner_id.name.lower())

            phone_list = []
            if partner_id.phone:
                phone_list.append({u'PhoneNumber': partner_id.phone or u'',
                                    u'PhoneType':  u'DEFAULT'})
            if partner_id.mobile:
                phone_list.append({u'PhoneNumber': partner_id.mobile or u'',
                                    u'PhoneType':  u'MOBILE'})
            if partner_id.direct_dial:
                phone_list.append({u'PhoneNumber': partner_id.direct_dial   or u'',
                                    u'PhoneType':  u'DDI'})

            contact_person_list = []
            po_country = u''
            po_state = u''
            po_city = u''
            po_zip = u''
            po_add_line1 = u''
            po_add_line2 = u''
            attention_to = u''
            i = 0
            for contact_per_id in partner_id.child_ids:
                if contact_per_id.type == 'contact':
                    i += 1
                    if contact_per_id.first_name:
                        FirstName = contact_per_id.first_name
                    else:
                        FirstName = contact_per_id.name
                    if i < 6:
                        contact_person_list.append({u'LastName':contact_per_id.last_name or u'',
                                                    u'EmailAddress':contact_per_id.email or u'',
                                                    u'IncludeInEmails': u'true',
                                                    u'FirstName':FirstName or u''})
                elif contact_per_id.type == 'invoice':
                    po_country = contact_per_id.country_id and contact_per_id.country_id.name or u''
                    po_state = contact_per_id.state_id and contact_per_id.state_id.name or u''
                    po_city = contact_per_id.city or u''
                    po_zip = contact_per_id.zip or u''
                    po_add_line1 = contact_per_id.street or u''
                    po_add_line2 = contact_per_id.street2 or u''
                    attention_to = contact_per_id.attention_to or u''

            if partner_id.active:
                status = 'ACTIVE'
            else:
                status = 'ARCHIVED'

            if contact_name:
                vals = {u'Name': contact_name or u''}
                partner_id.xero_name = contact_name
            else:
                vals = {u'Name': partner_id.name or u''}
                partner_id.xero_name = partner_id.name

            vals.update({u'ContactStatus': status,
                        u'EmailAddress': partner_id.email or u'',
                        u'SkypeUserName': partner_id.skype_name or u'',
                        u'TaxNumber': partner_id.tax_number or u'',
                        u'FirstName': partner_id.first_name or u'',
                        u'LastName': partner_id.last_name or u'',
                        # u'IsCustomer':partner_id.customer or False,
                        # u'IsSupplier':partner_id.supplier or False,
                        u'Addresses': [{
                                    u'City': partner_id.city or u'',
                                    u'AddressType': u'STREET',
                                    u'Country': partner_id.country_id and partner_id.country_id.name or u'',
                                    u'Region': partner_id.state_id and partner_id.state_id.name or u'',
                                    u'AttentionTo': partner_id.attention_to or u'',
                                    u'AddressLine1': partner_id.street or  u'',
                                    u'AddressLine2': partner_id.street2 or u'',
                                    u'PostalCode': partner_id.zip or u''},
                                    {
                                    u'City': po_city,
                                    u'AddressType': u'POBOX',
                                    u'Country': po_country,
                                    u'Region': po_state,
                                    u'AttentionTo': attention_to,
                                    u'AddressLine1': po_add_line1,
                                    u'AddressLine2': po_add_line2,
                                    u'PostalCode': po_zip}],
                        u'Phones': phone_list or [],
                        u'ContactPersons': contact_person_list or []
                    })
            if partner_id.bank_ids:
                vals.update({u'BankAccountDetails': partner_id.bank_ids[0].acc_number})
            contact_list_data.append(vals)
            c += 1
            if c == 50:
                data_list.append(contact_list_data)
                contact_list_data = []
                c = 0

        if contact_list_data:
            data_list.append(contact_list_data)
        for data in data_list:
            contact_details = xero.contacts.put(data)
            for contact in contact_details:
                contact_id = self.search([('xero_name' , '=', contact.get('Name'))], limit=1)
                # if contact_id:
                #     contact_id.contact_id = contact.get('ContactID', False)
                if contact_id:
                    xero_contact = contact_id.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                    xero_contact.xero_contact_id = contact.get('ContactID', False)
                    self._cr.commit()

        #Update Record
        contact_list_data = []
        data_list = []
        c = 0
        for contact_id in contact_list:
            if last_export_date:
                partner_ids = self.search([('write_date', '>', last_export_date), '|', ('company_id', '=', company), ('company_id', '=', False)])
                partner_id = partner_ids.filtered(lambda contact: contact.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company and l.xero_contact_id == contact_id.get('ContactID')))
                update_child_contact_ids = self.search([('parent_id', '!=', False), '|', ('create_date', '>=', last_export_date), ('write_date', '>=', last_export_date), '|', ('company_id', '=', company), ('company_id', '=', False),
                    '|', ('active', '=', True), ('active', '=', False)]).mapped('parent_id').filtered(lambda l: not l.parent_id and l.name and l.contact_xero_company_ids.filtered(lambda contact: contact.company_id.id == company and contact.xero_contact_id == contact_id.get('ContactID')))

                partner_id = partner_id.union(update_child_contact_ids)
            else:
                partner_id = self.search(['|', ('company_id', '=', company), ('company_id', '=', False)]).filtered(lambda contact: contact.contact_xero_company_ids.filtered(lambda l:l.company_id.id == company and l.xero_contact_id == contact_id.get('ContactID')))

            if partner_id:
                partner_id = partner_id[0]
                phone_list = []
                if partner_id.phone:
                    phone_list.append({u'PhoneNumber': partner_id.phone or u'',
                                        u'PhoneType':  u'DEFAULT'})
                if partner_id.mobile:
                    phone_list.append({u'PhoneNumber': partner_id.mobile or u'',
                                        u'PhoneType':  u'MOBILE'})
                if partner_id.direct_dial:
                    phone_list.append({u'PhoneNumber': partner_id.direct_dial   or u'',
                                        u'PhoneType':  u'DDI'})

                contact_person_list = []
                po_country = u''
                po_state = u''
                po_city = u''
                po_zip = u''
                po_add_line1 = u''
                po_add_line2 = u''
                attention_to = u''
                i = 0
                for contact_per_id in partner_id.child_ids:
                    if contact_per_id.type == 'contact':
                        i += 1
                        if contact_per_id.first_name:
                            FirstName = contact_per_id.first_name
                        else:
                            FirstName = contact_per_id.name
                        if i < 6:
                            contact_person_list.append({u'LastName':contact_per_id.last_name or u'',
                                                        u'EmailAddress':contact_per_id.email or u'',
                                                        u'IncludeInEmails': u'true',
                                                        u'FirstName':FirstName or u''}
                                                       )
                    elif contact_per_id.type == 'invoice':
                        po_country = contact_per_id.country_id and contact_per_id.country_id.name or u''
                        po_state = contact_per_id.state_id and contact_per_id.state_id.name or u''
                        po_city = contact_per_id.city or u''
                        po_zip = contact_per_id.zip or u''
                        po_add_line1 = contact_per_id.street or u''
                        po_add_line2 = contact_per_id.street2 or u''
                        attention_to = contact_per_id.attention_to or u''

                if partner_id.active:
                    status = 'ACTIVE'
                else:
                    status = 'ARCHIVED'

                vals = {u'Name': contact_id.get('Name') or u'',
                        u'ContactStatus': status,
                        u'EmailAddress': partner_id.email or u'',
                        u'SkypeUserName': partner_id.skype_name or u'',
                        u'TaxNumber': partner_id.tax_number or u'',
                        u'FirstName': partner_id.first_name or u'',
                        u'LastName': partner_id.last_name or u'',
                        # u'IsCustomer':partner_id.customer or False,
                        # u'IsSupplier':partner_id.supplier or False,
                        u'Addresses': [{
                                u'City': partner_id.city or u'',
                                u'AddressType': u'STREET',
                                u'Country': partner_id.country_id and partner_id.country_id.name or u'',
                                u'Region': partner_id.state_id and partner_id.state_id.name or u'',
                                u'AttentionTo': partner_id.attention_to or u'',
                                u'AddressLine1': partner_id.street or  u'',
                                u'AddressLine2': partner_id.street2 or u'',
                                u'PostalCode': partner_id.zip or u''},
                                {
                                u'City': po_city,
                                u'AddressType': u'POBOX',
                                u'Country': po_country,
                                u'Region': po_state,
                                u'AttentionTo': attention_to,
                                u'AddressLine1': po_add_line1,
                                u'AddressLine2': po_add_line2,
                                u'PostalCode': po_zip}],
                        u'Phones': phone_list or [],
                        u'ContactPersons': contact_person_list or []}
                if partner_id.bank_ids:
                    vals.update({u'BankAccountDetails': partner_id.bank_ids[0].acc_number})
                contact_list_data.append(vals)
                c += 1
                if c == 50:
                    data_list.append(contact_list_data)
                    contact_list_data = []
                    c = 0
        if contact_list_data:
            data_list.append(contact_list_data)
        for data in data_list:
            xero.contacts.save(data)
            self._cr.commit()

    def export_contact_overwrite(self, contact_list, xero, last_export_date, company=False, contact_ids=[]):
        '''
        Map: ContactID(Odoo) with ContactID(Xero)

        Create a contact in xero if contact is not available.

        Note: If contact is available in xero with name which we going to
        export from odoo then it will skip that record.

        Constraint(Xero): The name of the Contact must be unique

        If contact record is available in xero then it will update that particular record.
        '''
        status = ''
        same_record = []
        final_contact_list = []
        contact_name_list = []
        count = 1
        if self._context.get('contact_ids'):
            contact_ids = self._context.get('contact_ids')
        else:
            if len(contact_ids) <= 0:
                if last_export_date:
                    # contact_ids = self.search([('company_id', '=', company), ('parent_id', '=', False), '|', ('create_date', '>=', last_export_date), ('write_date', '>=', last_export_date)])
                    contact_ids = self.search([('parent_id', '=', False), '|', ('company_id', '=', company), ('company_id', '=', False), '|', ('create_date', '>=', last_export_date), ('write_date', '>=', last_export_date)])
                    update_child_contact_ids = self.search(['|', ('company_id', '=', company), ('company_id', '=', False), ('parent_id', '!=', False), '|', ('create_date', '>=', last_export_date), ('write_date', '>=', last_export_date),
                        '|', ('active', '=', True), ('active', '=', False)]).mapped('parent_id').filtered(lambda l: not l.parent_id and l.name)
                    contact_ids = contact_ids.union(update_child_contact_ids)
                else:
                    contact_ids = self.search([('parent_id', '=', False), '|', ('company_id', '=', company), ('company_id', '=', False)])

        for contact_id in contact_ids:
            contact_name_list = []
            for contact in contact_list:
                if contact_id.name.lower() == contact.get('Name').lower() and contact_id.email == contact.get('EmailAddress'):
                    # xero_contact = contact_id.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company and not l.xero_contact_id)
                    # if xero_contact:
                    #     xero_contact.write({'xero_contact_id': contact.get('ContactID')})

                    contact_name_list.append(contact.get('Name').lower())
                    # if contact_id.contact_id == contact.get('ContactID'):
                    #     same_record.append(contact_id.id)
                    xero_company = contact_id.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                    # if xero_company and xero_company.xero_contact_id == contact.get('ContactID'):
                    same_record.append(contact_id.id)
                    if xero_company and not xero_company.xero_contact_id:
                        xero_company.xero_contact_id = contact.get('ContactID')
                    elif not xero_company:
                        contact_id.contact_xero_company_ids = [(0, 0, {'company_id': company,
                                                                       'xero_contact_id': contact.get('ContactID')})]
            final_contact_list.append(contact_id.id)

        data_list = []
        contact_list_data = []
        c = 0
        partner_ids = self.browse(list(set(final_contact_list).difference(set(same_record))))
        for partner_id in partner_ids:
            contact_name = ''

            if partner_id.name and partner_id.name.lower() in contact_name_list:
                name = partner_id.name.lower() + ' (' + str(count) + ')'
                contact_name = partner_id.name + ' (' + str(count) + ')'
                while(name in contact_name_list):
                    name = partner_id.name.lower() + ' (' + str(count) + ')'
                    contact_name = partner_id.name + ' (' + str(count) + ')'
                    count += 1
                contact_name_list.append(name)
            elif partner_id.name:
                contact_name_list.append(partner_id.name.lower())

            phone_list = []
            if partner_id.phone:
                phone_list.append({u'PhoneNumber': partner_id.phone or u'',
                                    u'PhoneType':  u'DEFAULT'})
            if partner_id.mobile:
                phone_list.append({u'PhoneNumber': partner_id.mobile or u'',
                                    u'PhoneType':  u'MOBILE'})
            if partner_id.direct_dial:
                phone_list.append({u'PhoneNumber': partner_id.direct_dial   or u'',
                                    u'PhoneType':  u'DDI'})

            contact_person_list = []
            po_country = u''
            po_state = u''
            po_city = u''
            po_zip = u''
            po_add_line1 = u''
            po_add_line2 = u''
            attention_to = u''
            i = 0
            for contact_per_id in partner_id.child_ids:
                if contact_per_id.type == 'contact':
                    i += 1
                    if contact_per_id.first_name:
                        FirstName = contact_per_id.first_name
                    else:
                        FirstName = contact_per_id.name
                    if i < 6:
                        contact_person_list.append({u'LastName':contact_per_id.last_name or u'',
                                                    u'EmailAddress':contact_per_id.email or u'',
                                                    u'IncludeInEmails': u'true',
                                                    u'FirstName':FirstName or u''})
                elif contact_per_id.type == 'invoice':
                    po_country = contact_per_id.country_id and contact_per_id.country_id.name or u''
                    po_state = contact_per_id.state_id and contact_per_id.state_id.name or u''
                    po_city = contact_per_id.city or u''
                    po_zip = contact_per_id.zip or u''
                    po_add_line1 = contact_per_id.street or u''
                    po_add_line2 = contact_per_id.street2 or u''
                    attention_to = contact_per_id.attention_to or u''

            if partner_id.active:
                status = 'ACTIVE'
            else:
                status = 'ARCHIVED'

            if contact_name:
                vals = {u'Name': contact_name or u''}
                partner_id.xero_name = contact_name
            else:
                vals = {u'Name': partner_id.name or u''}
                partner_id.xero_name = partner_id.name

            vals.update({u'ContactStatus': status,
                        u'EmailAddress': partner_id.email or u'',
                        u'SkypeUserName': partner_id.skype_name or u'',
                        u'TaxNumber': partner_id.tax_number or u'',
                        u'FirstName': partner_id.first_name or u'',
                        u'LastName': partner_id.last_name or u'',
                        # u'IsCustomer':partner_id.customer or False,
                        # u'IsSupplier':partner_id.supplier or False,
                        u'Addresses': [{
                                    u'City': partner_id.city or u'',
                                    u'AddressType': u'STREET',
                                    u'Country': partner_id.country_id and partner_id.country_id.name or u'',
                                    u'Region': partner_id.state_id and partner_id.state_id.name or u'',
                                    u'AttentionTo': partner_id.attention_to or u'',
                                    u'AddressLine1': partner_id.street or  u'',
                                    u'AddressLine2': partner_id.street2 or u'',
                                    u'PostalCode': partner_id.zip or u''},
                                    {
                                    u'City': po_city,
                                    u'AddressType': u'POBOX',
                                    u'Country': po_country,
                                    u'Region': po_state,
                                    u'AttentionTo': attention_to,
                                    u'AddressLine1': po_add_line1,
                                    u'AddressLine2': po_add_line2,
                                    u'PostalCode': po_zip}],
                        u'Phones': phone_list or [],
                        u'ContactPersons': contact_person_list or []
                    })
            if partner_id.bank_ids:
                vals.update({u'BankAccountDetails': partner_id.bank_ids[0].acc_number})
            contact_list_data.append(vals)
            c += 1
            if c == 50:
                data_list.append(contact_list_data)
                contact_list_data = []
                c = 0

        if contact_list_data:
            data_list.append(contact_list_data)
        for data in data_list:
            contact_details = xero.contacts.put(data)
            for contact in contact_details:
                contact_id = self.search([('xero_name' , '=', contact.get('Name'))], limit=1)
                # if contact_id:
                #     contact_id.contact_id = contact.get('ContactID', False)
                if contact_id:
                    xero_contact = contact_id.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                    xero_contact.xero_contact_id = contact.get('ContactID', False)
                    self._cr.commit()

        #Update Record
        contact_list_data = []
        data_list = []
        c = 0
        for contact_id in contact_list:
            if last_export_date:
                partner_ids = self.search([('write_date', '>', last_export_date), '|', ('company_id', '=', company), ('company_id', '=', False)])
                partner_id = partner_ids.filtered(lambda contact: contact.contact_xero_company_ids.filtered(lambda l: l.company_id.id == company and l.xero_contact_id == contact_id.get('ContactID')))
                update_child_contact_ids = self.search([('parent_id', '!=', False), '|', ('create_date', '>=', last_export_date), ('write_date', '>=', last_export_date),
                    '|', ('active', '=', True), ('active', '=', False)]).mapped('parent_id').filtered(lambda l: not l.parent_id and l.name and (l.company_id.id == company or not l.company_id) \
                    and l.contact_xero_company_ids.filtered(lambda contact: contact.company_id.id == company and contact.xero_contact_id == contact_id.get('ContactID')))
                partner_id = partner_id.union(update_child_contact_ids)
            else:
                partner_id = self.search(['|', ('company_id', '=', company), ('company_id', '=', False)]).filtered(lambda contact: contact.contact_xero_company_ids.filtered(lambda l:l.company_id.id == company and l.xero_contact_id == contact_id.get('ContactID')))

            if partner_id:
                partner_id = partner_id[0]
                phone_list = []
                if partner_id.phone:
                    phone_list.append({u'PhoneNumber': partner_id.phone or u'',
                                        u'PhoneType':  u'DEFAULT'})
                if partner_id.mobile:
                    phone_list.append({u'PhoneNumber': partner_id.mobile or u'',
                                        u'PhoneType':  u'MOBILE'})
                if partner_id.direct_dial:
                    phone_list.append({u'PhoneNumber': partner_id.direct_dial   or u'',
                                        u'PhoneType':  u'DDI'})

                contact_person_list = []
                po_country = u''
                po_state = u''
                po_city = u''
                po_zip = u''
                po_add_line1 = u''
                po_add_line2 = u''
                attention_to = u''
                i = 0
                for contact_per_id in partner_id.child_ids:
                    if contact_per_id.type == 'contact':
                        i += 1
                        if contact_per_id.first_name:
                            FirstName = contact_per_id.first_name
                        else:
                            FirstName = contact_per_id.name
                        if i < 6:
                            contact_person_list.append({u'LastName':contact_per_id.last_name or u'',
                                                        u'EmailAddress':contact_per_id.email or u'',
                                                        u'IncludeInEmails': u'true',
                                                        u'FirstName':FirstName or u''}
                                                       )
                    elif contact_per_id.type == 'invoice':
                        po_country = contact_per_id.country_id and contact_per_id.country_id.name or u''
                        po_state = contact_per_id.state_id and contact_per_id.state_id.name or u''
                        po_city = contact_per_id.city or u''
                        po_zip = contact_per_id.zip or u''
                        po_add_line1 = contact_per_id.street or u''
                        po_add_line2 = contact_per_id.street2 or u''
                        attention_to = contact_per_id.attention_to or u''

                if partner_id.active:
                    status = 'ACTIVE'
                else:
                    status = 'ARCHIVED'

                xero_contact_id = partner_id.contact_xero_company_ids.filtered(lambda contact: contact.company_id.id == company).xero_contact_id
                vals = {u'Name': contact_id.get('Name') or u'',
                        u'ContactID': xero_contact_id,
                        u'ContactStatus': status,
                        u'EmailAddress': partner_id.email or u'',
                        u'SkypeUserName': partner_id.skype_name or u'',
                        u'TaxNumber': partner_id.tax_number or u'',
                        u'FirstName': partner_id.first_name or u'',
                        u'LastName': partner_id.last_name or u'',
                        # u'IsCustomer':partner_id.customer or False,
                        # u'IsSupplier':partner_id.supplier or False,
                        u'Addresses': [{
                                u'City': partner_id.city or u'',
                                u'AddressType': u'STREET',
                                u'Country': partner_id.country_id and partner_id.country_id.name or u'',
                                u'Region': partner_id.state_id and partner_id.state_id.name or u'',
                                u'AttentionTo': partner_id.attention_to or u'',
                                u'AddressLine1': partner_id.street or  u'',
                                u'AddressLine2': partner_id.street2 or u'',
                                u'PostalCode': partner_id.zip or u''},
                                {
                                u'City': po_city,
                                u'AddressType': u'POBOX',
                                u'Country': po_country,
                                u'Region': po_state,
                                u'AttentionTo': attention_to,
                                u'AddressLine1': po_add_line1,
                                u'AddressLine2': po_add_line2,
                                u'PostalCode': po_zip}],
                        u'Phones': phone_list or [],
                        u'ContactPersons': contact_person_list or []}
                if partner_id.bank_ids:
                    vals.update({u'BankAccountDetails': partner_id.bank_ids[0].acc_number})
                contact_list_data.append(vals)

                c += 1
                if c == 50:
                    data_list.append(contact_list_data)
                    contact_list_data = []
                    c = 0
        if contact_list_data:
            data_list.append(contact_list_data)
        for data in data_list:
            test = xero.contacts.save(data)
            self._cr.commit()

    def action_export_contact(self):
        context = self._context
        for company_id in context.get('allowed_company_ids'):
            contact_data = self.filtered(lambda contact: contact.company_id.id == company_id or not contact.company_id)
            context.update({'contact_ids': contact_data})
            xero_account = self.env['xero.account'].search([('company_id', '=', company_id)], limit=1)
            xero_account.with_context(context).export_contact()


class PartnerCategory(models.Model):
    _inherit = 'res.partner.category'
    _description = 'Partner Tags'

    xero_tag_id = fields.Char(string='Tag')

    def import_contact_group(self, group_list, xero):
        """
            Map: Xero Tag(Odoo) with ContactGroupID(Xero)

            Create a Partner Tags in Odoo if contact group is not available with ContactGroupID.

            If Partner Tag record is available then it will update that particular record.
        """
        for group in group_list:
            if group.get('Status') == 'ACTIVE':
                group_record = self.search(['|', ('xero_tag_id', '=', group.get('ContactGroupID')),
                                            ('name', '=', group.get('Name'))])
                if group_record:
                    group_record.write({'xero_tag_id': group.get('ContactGroupID'),
                                        'active': True})
                else:
                    self.create({'name': group.get('Name'), 'xero_tag_id': group.get('ContactGroupID'),
                                 'active': True})
                self._cr.commit()

    def export_contact_group(self, group_list, xero):
        """
            Map: Xero Tag(Odoo) with ContactGroupID(Xero)

            Create a Contact Group in Xero if not available.

            If Contact Group record is available in Xero then it will update that particular record.
        """
        same_group = []
        final_group_list = []
        for group_id in self.search([]):
            for group in group_list:
                if group_id.xero_tag_id == group.get('ContactGroupID') or group_id.name == group.get('Name'):
                    if not group_id.xero_tag_id:
                        group_id.xero_tag_id = group.get('ContactGroupID')
                    same_group.append(group_id.id)
            final_group_list.append(group_id.id)

        for save_group in self.browse(list(set(final_group_list).difference(set(same_group)))):
            group_details = xero.contactgroups.put({u'Name': save_group.name})
            save_group.xero_tag_id = group_details[0].get('ContactGroupID', False)
            self._cr.commit()

        for record in self.browse(same_group):
            group_details = xero.contactgroups.save({u'Name': record.name})
            self._cr.commit()
