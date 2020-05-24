# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

import datetime
from odoo import api, fields, models, _


class ProductTemplate(models.Model):
    _inherit = "product.template"

    taxes_id = fields.Many2many('account.tax', 'product_taxes_rel', 'prod_id', 'tax_id',
                                string='Customer Taxes', domain=[('type_tax_use', '!=', 'purchase')])
    supplier_taxes_id = fields.Many2many('account.tax', 'product_supplier_taxes_rel', 'prod_id', 'tax_id',
                                         string='Vendor Taxes', domain=[('type_tax_use', '!=', 'sale')])
    set_initial_stock = fields.Boolean(string='Set Initial Stock')


class ProductXeroCompany(models.Model):
    _name = "product.xero.company"
    _description = 'Product Xero'

    company_id = fields.Many2one('res.company', 'Company', required=True)
    xero_item_id = fields.Char('Xero ItemID')
    product_id = fields.Many2one('product.product', 'Product')


class ProductProduct(models.Model):
    _inherit = 'product.product'
    _description = 'Product'

    product_xero_company_ids = fields.One2many('product.xero.company', 'product_id', string="Xero Multi Company")

    _sql_constraints = [
        ('default_code_uniq', 'unique(default_code)', 'Internal Reference must be unique!'),
    ]

    @api.onchange('company_id')
    def _onchange_company(self):
        if self.company_id:
            xero_company = self.product_xero_company_ids.filtered(lambda l: l.company_id.id == self.company_id.id)
            if not xero_company:
                self.product_xero_company_ids = [(6, 0, {'company_id': self.company_id.id})]

    def import_product(self, product_list, xero, tracked_category, untracked_category, company=False, import_option=None):
        """
        Map: ItemID(Odoo) with ItemID(Xero)

        Create a product in odoo if product is not available with
        ItemID and company.

        If product record is available then it will update that particular record.
        """
        account_pool = self.env['account.account']
        tax_pool = self.env['account.tax']
        for product in product_list:
            property_account_income_id = False
            property_account_expense_id = False
            sale_tax = []
            purchase_tax = []
            if product.get('SalesDetails').get('AccountCode'):
                sale_account = account_pool.search([('code', '=', product.get('SalesDetails').get('AccountCode')), ('company_id', '=', company)])
                property_account_income_id = sale_account and sale_account[0].id or False
            if product.get('PurchaseDetails').get('AccountCode'):
                purchase_account = account_pool.search([('code', '=', product.get('PurchaseDetails').get('AccountCode')), ('company_id', '=', company)])
                property_account_expense_id = purchase_account and purchase_account[0] and purchase_account[0].id or False
            if product.get('PurchaseDetails').get('COGSAccountCode'):
                purchase_account = account_pool.search([('code', '=', product.get('PurchaseDetails').get('COGSAccountCode')), ('company_id', '=', company)])
                property_account_expense_id = purchase_account and purchase_account[0] and purchase_account[0].id or False
            if product.get('SalesDetails').get('TaxType'):
                sale_tax = tax_pool.search([('xero_tax_type', '=', product.get('SalesDetails').get('TaxType')), ('company_id', '=', company)])
            if product.get('PurchaseDetails').get('TaxType'):
                purchase_tax = tax_pool.search([('xero_tax_type', '=', product.get('PurchaseDetails').get('TaxType')), ('company_id', '=', company)])
            product_code = self.search([('default_code', '=', product.get('Code'))])
            # if product_code and not product_code.item_id:
            #     product_code.item_id = product.get('ItemID')
            xero_company = product_code.product_xero_company_ids.filtered(lambda l: l.company_id.id == company)
            if product_code and xero_company and not xero_company.xero_item_id:
                xero_company.xero_item_id = product.get('ItemID')
            elif product_code and not xero_company:
                product_code.product_xero_company_ids = [(0, 0, {'company_id': company,
                                                                 'xero_item_id': product.get('ItemID')
                                                                 })]

            # product_rec = self.search([('item_id', '=', product.get('ItemID'))])
            product_rec = self.search([]).filtered(lambda product_id: product_id.product_xero_company_ids.filtered(lambda l: l.company_id.id == company and l.xero_item_id == product.get('ItemID')))

            if product.get('IsTrackedAsInventory'):
                product_category = tracked_category
                # stock_account = account_pool.search([('code','=', product.get('InventoryAssetAccountCode')), ('company_id', '=', company)])
                product_type = 'product'
            else:
                product_category = untracked_category
                product_type = 'consu'
                # stock_account = False

            if product_rec and import_option in ['update', 'both']:
                product_rec[0].write({'name': product.get('Name', product.get('Code')),
                                      'description': product.get('Description'),
                                      'standard_price': product.get('PurchaseDetails').get('UnitPrice'),
                                      'list_price': product.get('SalesDetails').get('UnitPrice'),
                                      'default_code': product.get('Code'),
                                      'company_id': company,
                                      # 'product_xero_company_ids': [(0, 0, {'company_id': company,
                                      #                                       })],
                                      'type': product_type,
                                      'property_account_income_id': property_account_income_id,
                                      'property_account_expense_id': property_account_expense_id,
                                      # 'property_stock_account_input': stock_account,
                                      # 'property_stock_account_output': stock_account,
                                      'taxes_id': [(6, 0, [sale_tax[0].id])] if sale_tax else [(6, 0, [])],
                                      'supplier_taxes_id': [(6, 0, [purchase_tax[0].id])] if purchase_tax else [(6, 0, [])]})
                if product_category:
                    product_rec[0].write({'categ_id': product_category.id})
                if product.get('IsTrackedAsInventory'):
                    onhand_qty_id = self.env['stock.change.product.qty'].with_context({'xero_opening_stock': True}).create({
                            'product_id': product_rec[0].id,
                            'product_tmpl_id': product_rec[0].id,
                            'new_quantity': product.get('QuantityOnHand'),
                            # 'location_id': warehouse.lot_stock_id.id
                        })
                    onhand_qty_id.change_product_qty()
                self._cr.commit()
            elif not product_rec and import_option in ['create', 'both']:
                product_id = self.create({'name': product.get('Name', product.get('Code')),
                                          # 'item_id': product.get('ItemID'),
                                          'description': product.get('Description'),
                                          'standard_price': product.get('PurchaseDetails').get('UnitPrice'),
                                          'list_price': product.get('SalesDetails').get('UnitPrice'),
                                          'default_code': product.get('Code'),
                                          'company_id': company,
                                          'product_xero_company_ids': [(0, 0, {'company_id': company,
                                                                               'xero_item_id': product.get('ItemID')
                                                                            })],
                                          'type': product_type,
                                          'property_account_income_id': property_account_income_id,
                                          'property_account_expense_id': property_account_expense_id,
                                          # 'property_stock_account_input': stock_account,
                                          # 'property_stock_account_output': stock_account,
                                          'taxes_id': [(6, 0, [sale_tax[0].id])] if sale_tax else [],
                                          'supplier_taxes_id': [(6, 0, [purchase_tax[0].id])] if purchase_tax else []})

                if product_category:
                    product_id.update({'categ_id': product_category.id})
                if product.get('IsTrackedAsInventory'):
                    # warehouse = self.env['stock.warehouse'].search([('company_id', '=', company)], limit=1)
                    # if warehouse:
                    onhand_qty_id = self.env['stock.change.product.qty'].with_context({'xero_opening_stock': True}).create({
                            'product_id': product_id.id,
                            'product_tmpl_id': product_id.id,
                            'new_quantity': product.get('QuantityOnHand'),
                            # 'location_id': warehouse.lot_stock_id.id
                        })
                    onhand_qty_id.change_product_qty()
                self._cr.commit()

    def export_product(self, product_list, xero, last_export_date, company=False, item_ids=[]):
        """
        Map: ItemID(Odoo) with ItemID(Xero)

        Create a product in Xero if product is not available.

        If product record is available in xero then it will update that particular record.
        """
        property_pool = self.env['ir.property']
        account_pool = self.env['account.account']
        same_record = []
        final_product_list = []
        product_code_list = []
        if self._context.get('product_ids'):
            item_ids = self._context.get('product_ids')
        else:
            if len(item_ids) <= 0:
                if last_export_date:
                    item_ids = self.search(['|',('company_id', '=', company), ('company_id', '=', False), '|', ('write_date', '>=', last_export_date), ('create_date', '>=', last_export_date)])
                else:
                    item_ids = self.search(['|', ('company_id', '=', company), ('company_id', '=', False)])

        for product_id in item_ids:
            xero_company = product_id.product_xero_company_ids.filtered(lambda l: l.company_id.id == company)
            if not xero_company:
                product_id.product_xero_company_ids = [(0, 0, {'company_id': company})]
            for name in product_list:
                xero_company_id = product_id.product_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                if product_id.default_code == name.get('Code'):
                    if xero_company_id:
                        xero_company_id.xero_item_id = name.get('ItemID')
                    # else:
                        # product_id.product_xero_company_ids = [(0, 0, {'company_id': company,
                        #                                                 'xero_item_id': name.get('ItemID')})]

                    # if not product_id.item_id:
                    #     product_id.write({'item_id': name.get('ItemID')})
                else:
                    product_code_list.append(name.get('Code'))

                # xero_company_id = product_id.product_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                if xero_company_id and xero_company_id.xero_item_id == name.get('ItemID'):
                    same_record.append(product_id.id)
            # product_id.product_xero_company_ids = [(0, 0, {'company_id': company})]
            final_product_list.append(product_id.id)

        item_data = []
        data = []
        c = 0
        for record in self.browse(list(set(final_product_list).difference(set(same_record)))):
            res = 'product.template,' + str(record.product_tmpl_id.id)
            purchase_account = property_pool.search([('company_id', '=', company), ('res_id', '=', res),
                                                     ('name', '=', 'property_account_expense_id')], limit=1)
            sale_account = property_pool.search([('company_id', '=', company), ('res_id', '=', res),
                                                 ('name', '=', 'property_account_income_id')], limit=1)

            categ_res = 'product.category,' + str(record.categ_id.id)
            if not purchase_account:
                purchase_account = property_pool.search([('company_id', '=', company), '|' ,('res_id', '=', categ_res), ('res_id', '=', False),
                                                         ('name', '=', 'property_account_expense_categ_id')], limit=1)
            if not sale_account:
                sale_account = property_pool.search([('company_id', '=', company), '|', ('res_id', '=', categ_res), ('res_id', '=', False),
                                                     ('name', '=', 'property_account_income_categ_id')], limit=1)

            stock_account = property_pool.search([('company_id', '=', company), ('res_id', '=', categ_res),
                                                  ('name', '=', 'property_stock_account_input_categ_id')], limit=1)

            purchase_account_code = account_pool.browse(int(purchase_account.value_reference.split(',')[1])).code if purchase_account else ''
            sale_account_code = account_pool.browse(int(sale_account.value_reference.split(',')[1])).code if sale_account else ''
            stock_account_code = account_pool.browse(int(stock_account.value_reference.split(',')[1])).code if stock_account and stock_account.value_reference else ''

            sale_tax_type = False
            if record.taxes_id:
                taxes = record.taxes_id.filtered(lambda l: l.company_id.id == company)
                sale_tax_type = taxes[0] if taxes else ''
                # sale_tax_type = record.taxes_id[0]
            purchase_tax_type = False

            if record.supplier_taxes_id:
                supplier_taxes = record.supplier_taxes_id.filtered(lambda l: l.company_id.id == company)
                purchase_tax_type = supplier_taxes[0] if supplier_taxes else ''
                # purchase_tax_type = record.supplier_taxes_id[0]

            if record.default_code and record.default_code not in product_code_list:
                item_name = record.name and record.name[:49]
                code = record.default_code and record.default_code[:30]


                if record.categ_id.property_valuation == 'real_time':
                    item = {u'Code': code,
                            u'Name': item_name,
                            u'Description': record.description or u'',
                            u'PurchaseDescription': record.description or u'',
                            u'InventoryAssetAccountCode': stock_account_code,
                            u'PurchaseDetails': {u'UnitPrice': record.standard_price,
                                                 u'COGSAccountCode': purchase_account_code,
                                                 u'TaxType': purchase_tax_type.xero_tax_type if purchase_tax_type else u''},
                            u'SalesDetails': {u'UnitPrice': record.list_price,
                                              u'AccountCode': sale_account_code,
                                              u'TaxType': sale_tax_type.xero_tax_type if sale_tax_type and sale_tax_type.xero_tax_type else u''}
                            }
                else:
                    item = {u'Code': code,
                            u'Name': item_name,
                            u'Description': record.description or u'',
                            u'PurchaseDescription': record.description or u'',
                            u'PurchaseDetails': {u'UnitPrice': record.standard_price,
                                                 u'AccountCode': purchase_account_code,
                                                 u'TaxType': purchase_tax_type.xero_tax_type if purchase_tax_type else u''},
                            u'SalesDetails': {u'UnitPrice': record.list_price,
                                              u'AccountCode': sale_account_code,
                                              u'TaxType': sale_tax_type.xero_tax_type if sale_tax_type and sale_tax_type.xero_tax_type else u''}
                            }
                data.append(item)
                c += 1
                if c == 50:
                    item_data.append(data)
                    data = []
                    c = 0
            elif not record.default_code and record.name not in product_code_list:
                item_name = record.name and record.name[:49]
                name = record.name and record.name[:30]

                if record.categ_id.property_valuation == 'real_time':
                    item = {u'Code': name,
                            u'Name': item_name,
                            u'Description': record.description or u'',
                            u'PurchaseDescription': record.description or u'',
                            u'InventoryAssetAccountCode': stock_account_code,
                            u'PurchaseDetails': {u'UnitPrice': record.standard_price,
                                                 u'COGSAccountCode': purchase_account_code,
                                                 u'TaxType': purchase_tax_type.xero_tax_type if purchase_tax_type and purchase_tax_type.xero_tax_type else u''},
                            u'SalesDetails': {u'UnitPrice': record.list_price,
                                              u'AccountCode': sale_account_code,
                                              u'TaxType': sale_tax_type.xero_tax_type if sale_tax_type and sale_tax_type.xero_tax_type else u''}
                            }
                else:
                    item = {u'Code': name,
                            u'Name': item_name,
                            u'Description': record.description or u'',
                            u'PurchaseDescription': record.description or u'',
                            u'PurchaseDetails': {u'UnitPrice': record.standard_price,
                                                 u'AccountCode': purchase_account_code,
                                                 u'TaxType': purchase_tax_type.xero_tax_type if purchase_tax_type and purchase_tax_type.xero_tax_type else u''},
                            u'SalesDetails': {u'UnitPrice': record.list_price,
                                              u'AccountCode': sale_account_code,
                                              u'TaxType': sale_tax_type.xero_tax_type if sale_tax_type and sale_tax_type.xero_tax_type else u''}
                            }
                data.append(item)
                c += 1
                if c == 50:
                    item_data.append(data)
                    data = []
                    c = 0

        if data:
            item_data.append(data)
        for data in item_data:
            item_rec = xero.items.put(data)
            for item in item_rec:
                product_id = self.search(['|',('default_code', '=', item.get('Code')), ('name', '=', item.get('Code'))])
                xero_company = product_id.product_xero_company_ids.filtered(lambda l: l.company_id.id == company)
                xero_company.xero_item_id = item.get('ItemID')
                self._cr.commit()

        item_data = []
        data = []
        c = 0
        for product in self.browse(same_record):
            code = product.default_code and product.default_code[:30]
            item_name = product.name and product.name[:49]

            res = 'product.template,' + str(product.product_tmpl_id.id)
            purchase_account = property_pool.search([('company_id', '=', company), ('res_id', '=', res),
                                                     ('name', '=', 'property_account_expense_id')], limit=1)
            sale_account = property_pool.search([('company_id', '=', company), ('res_id', '=', res),
                                                 ('name', '=', 'property_account_income_id')], limit=1)

            categ_res = 'product.category,' + str(product.categ_id.id)
            if not purchase_account:
                purchase_account = property_pool.search([('company_id', '=', company), '|' ,('res_id', '=', categ_res), ('res_id', '=', False),
                                                         ('name', '=', 'property_account_expense_categ_id')], limit=1)
            if not sale_account:
                sale_account = property_pool.search([('company_id', '=', company), '|', ('res_id', '=', categ_res), ('res_id', '=', False),
                                                     ('name', '=', 'property_account_income_categ_id')], limit=1)

            stock_account = property_pool.search([('company_id', '=', company), ('res_id', '=', categ_res),
                                                  ('name', '=', 'property_stock_account_input_categ_id')], limit=1)

            purchase_account_code = account_pool.browse(int(purchase_account.value_reference.split(',')[1])).code if purchase_account else ''
            sale_account_code = account_pool.browse(int(sale_account.value_reference.split(',')[1])).code if sale_account else ''
            stock_account_code = account_pool.browse(int(stock_account.value_reference.split(',')[1])).code if stock_account and stock_account.value_reference else ''

            sale_tax_type = False
            if product.taxes_id:
                taxes = product.taxes_id.filtered(lambda l: l.company_id.id == company)
                sale_tax_type = taxes[0] if taxes else False
                # sale_tax_type = product.taxes_id[0]
            purchase_tax_type = False
            if product.supplier_taxes_id:
                supplier_taxes = product.supplier_taxes_id.filtered(lambda l: l.company_id.id == company)
                purchase_tax_type = supplier_taxes[0] if supplier_taxes else False
                # purchase_tax_type = product.supplier_taxes_id[0]

            xero_company = product.product_xero_company_ids.filtered(lambda l: l.company_id.id == company)
            if product.categ_id.property_valuation == 'real_time':
                items = {u'Code': code or name,
                        u'Name': item_name,
                        u'Description': product.description or u'',
                        u'PurchaseDescription': product.description or u'',
                        u'InventoryAssetAccountCode': stock_account_code,
                        u'PurchaseDetails': {u'UnitPrice': product.standard_price,
                                             u'COGSAccountCode': purchase_account_code,
                                             u'TaxType': purchase_tax_type.xero_tax_type if purchase_tax_type and purchase_tax_type.xero_tax_type else u''},
                        u'SalesDetails': {u'UnitPrice': product.list_price,
                                          u'AccountCode': sale_account_code,
                                          u'TaxType': sale_tax_type.xero_tax_type if sale_tax_type and sale_tax_type.xero_tax_type else u''},
                        u'ItemID': xero_company.xero_item_id}
            else:
                items = {u'Code': code or name,
                        u'Name': item_name,
                        u'Description': product.description or u'',
                        u'PurchaseDescription': product.description or u'',
                        u'PurchaseDetails': {u'UnitPrice': product.standard_price,
                                             u'AccountCode': purchase_account_code,
                                             u'TaxType': purchase_tax_type.xero_tax_type if purchase_tax_type and purchase_tax_type.xero_tax_type else u''},
                        u'SalesDetails': {u'UnitPrice': product.list_price,
                                          u'AccountCode': sale_account_code,
                                          u'TaxType': sale_tax_type.xero_tax_type if sale_tax_type and sale_tax_type.xero_tax_type else u''},
                        u'ItemID': xero_company.xero_item_id}

            data.append(items)
            c += 1
            if c == 50:
                item_data.append(data)
                data = []
                c = 0

        if data:
            item_data.append(data)
        for data in item_data:
            xero.items.save(data)
            self._cr.commit()

    def action_export_product(self):
        context = self._context
        for company_id in context.get('allowed_company_ids'):
            product_data = self.filtered(lambda product: product.company_id.id == company_id or not product.company_id)
            context.update({'product_ids': product_data})
            xero_account = self.env['xero.account'].search([('company_id', '=', company_id)], limit=1)
            xero_account.with_context(context).export_product()


class StockMoveLine(models.Model):
    _inherit = "stock.move.line"

    xero_invoice_number = fields.Char('Xero Invoice Number', readonly=True, copy=False)
    xero_invoice_id = fields.Char('Xero Invoice ID', readonly=True, copy=False)
    xero_opening_stock = fields.Boolean(string="Xero Opening Stock")

    @api.model
    def create(self, vals):
        if self._context.get('xero_opening_stock'):
            vals.update({'xero_opening_stock': True})
        return super(StockMoveLine, self).create(vals)

    def create_inventory_adjustments(self, xero, company=False, adjustment_account=False):
        move_lines = self.search([('product_id.categ_id.property_valuation', '=', 'real_time'),
                                      '|',
                                    ('location_id.usage', 'in', ['inventory', 'production']),
                                    ('location_dest_id.usage', 'in', ['inventory','production']),
                                    ('state', '=', 'done'),
                                    ('xero_invoice_id', '=', False),
                                    ('xero_invoice_number', '=', False),
                                    ('move_id.company_id', '=', company),
                                    ('xero_opening_stock', '=', False)])

        for move in move_lines:
            product_code = move.product_id.default_code[:30] if move.product_id.default_code else move.product_id.name[:30]
            if move.location_id.usage in ['inventory', 'production']:
                description = (str(move.move_id.reference) + '-' + 'Inventory Adjustment') if move.location_id.usage == 'inventory' else (str(move.move_id.reference) + '-' + 'Inventory Adjustment (Manufacturing)')
                invoice_data = {u'Type': u'ACCPAY',
                          u'Contact': {u'Name': u'Stock Journal (Odoo)'},
                          u'InvoiceNumber': description,
                          u'Date': move.date or fields.Date.today(),
                          u'DueDate': move.date or fields.Date.today(),
                          u'LineAmountTypes': u'NoTax',
                          u'Status': u'AUTHORISED',
                          u'LineItems': [{u'ItemCode': product_code,
                                          u'Description': move.product_id.description or move.product_id.name,
                                          u'Quantity': move.qty_done,
                                          u'UnitAmount': move.product_id.standard_price,
                                          u'AccountCode': (move.product_id.categ_id.property_stock_account_input_categ_id and move.product_id.categ_id.property_stock_account_input_categ_id.code) or 630,
                                          },
                                          {
                                          u'Description': 'Stock Movement',
                                          u'Quantity': move.qty_done,
                                          u'UnitAmount': -(move.product_id.standard_price),
                                          u'AccountCode': (adjustment_account and adjustment_account.code or 401),
                                          }]}
                inv_rec = xero.invoices.put(invoice_data)
                move.write({'xero_invoice_id': inv_rec[0]['InvoiceID'], 'xero_invoice_number': inv_rec[0]['InvoiceNumber']})
                self._cr.commit()
            elif move.location_dest_id.usage in ['inventory', 'production']:
                description = (str(move.move_id.reference) + '-' + 'Inventory Adjustment') if move.location_dest_id.usage == 'inventory' else (str(move.move_id.reference) + '-' + 'Inventory Adjustment (Manufacturing)')
                creditnote_data = {u'Type': u'ACCPAYCREDIT',
                          u'Contact': {u'Name': u'Stock Journal (Odoo)'},
                          u'CreditNoteNumber': description,
                          u'Date': move.date or fields.Date.today(),
                          u'DueDate': move.date or fields.Date.today(),
                          u'LineAmountTypes': u'NoTax',
                          u'Status': u'AUTHORISED',
                          u'LineItems': [{u'ItemCode': product_code,
                                          u'Description': move.product_id.description or move.product_id.name,
                                          u'Quantity': move.qty_done,
                                          u'UnitAmount': move.product_id.standard_price,
                                          u'AccountCode': (move.product_id.categ_id.property_stock_account_input_categ_id and move.product_id.categ_id.property_stock_account_input_categ_id.code) or 630,
                                          },
                                          {
                                          u'Description': 'Stock Movement',
                                          u'Quantity': move.qty_done,
                                          u'UnitAmount': -(move.product_id.standard_price),
                                          u'AccountCode': (adjustment_account and adjustment_account.code or 401),
                                          }]}
                creditnote_rec = xero.creditnotes.put(creditnote_data)
                move.write({'xero_invoice_id': creditnote_rec[0]['CreditNoteID'], 'xero_invoice_number': creditnote_rec[0]['CreditNoteID']})
                self._cr.commit()
        return True
