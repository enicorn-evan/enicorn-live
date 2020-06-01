# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _
from odoo.exceptions import UserError
import itertools
from odoo.tools import float_round
import babel.dates
from dateutil.relativedelta import relativedelta
import json
from odoo.tools.misc import get_lang
from odoo.addons.web.controllers.main import clean_action


class ProjectTask(models.Model):
    _inherit = "project.task"

    purchase_order_id = fields.Many2one('purchase.order', 'Purchase Order', compute='_compute_purchase_order_id',
                                        store=True, readonly=False, help="Purchase order to which the task is linked.")
    is_create_po = fields.Boolean("Is Create PO?")

    @api.depends('project_id', 'is_create_po')
    def _compute_purchase_order_id(self):
        for task in self:
            purchase_id = self.env['purchase.order'].search(
                [('project_task_id', '=', task.id)])
            task.purchase_order_id = purchase_id.id

    def create_po_from_task(self):
        """ Create Purchase Order From Task"""
        user = self.env['res.users'].browse(self._uid)
        po_lines = []

        product_id = self.env['product.product'].create({
            'name': self.name,
            'service_tracking': 'task_global_project',
            'type': 'consu',
            'uom_id': self.env.ref('uom.product_uom_unit').id,
        })

        po_lines.append((0, 0, {
            'name': product_id.name,
            'product_id': product_id.id,
            'product_uom': product_id.uom_id.id,
            'product_qty': 1,
            'price_unit': 1,
            'date_planned': fields.datetime.now(),
            'company_id': self.company_id.id,
            'partner_id': self.partner_id.id,
        }))

        if po_lines:
            purchase_obj = self.env['purchase.order'].create({
                'company_id': self.company_id.id,
                'date_order': fields.datetime.now(),
                'partner_id': self.partner_id.id,
                'user_id': user.id,
                'order_line': po_lines,
                'project_id': self.project_id.id,
                'project_task_id': self.id,
            })
            self.is_create_po = True

            return {
                'name': _('Purchase Order'),
                'view_mode': 'form',
                'view_id': self.env.ref('purchase.purchase_order_form').id,
                'res_model': 'purchase.order',
                'type': 'ir.actions.act_window',
                'res_id': purchase_obj.id,
            }

    def action_view_po(self):
        """ Show All Purchase Order Of This Task """
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "purchase.order",
            "views": [[False, "form"]],
            "res_id": self.purchase_order_id.id,
            "context": {"create": False, "show_sale": True},
        }


class Project(models.Model):
    _inherit = 'project.project'

    def _plan_prepare_values(self):
        currency = self.env.company.currency_id
        uom_hour = self.env.ref('uom.product_uom_hour')
        hour_rounding = uom_hour.rounding
        billable_types = ['non_billable', 'non_billable_project',
                          'billable_time', 'billable_fixed']

        values = {
            'projects': self,
            'currency': currency,
            'timesheet_domain': [('project_id', 'in', self.ids)],
            'profitability_domain': [('project_id', 'in', self.ids)],
            'stat_buttons': self._plan_get_stat_button(),
        }

        #
        # Hours, Rates and Profitability
        #
        dashboard_values = {
            'hours': dict.fromkeys(billable_types + ['total'], 0.0),
            'rates': dict.fromkeys(billable_types + ['total'], 0.0),
            'profit': {
                'invoiced': 0.0,
                'to_invoice': 0.0,
                'cost': 0.0,
                'total': 0.0,
            }
        }

        # hours from non-invoiced timesheets that are linked to canceled so
        canceled_hours_domain = [('project_id', 'in', self.ids), (
            'timesheet_invoice_type', '!=', False), ('so_line.state', '=', 'cancel')]
        total_canceled_hours = sum(self.env['account.analytic.line'].search(
            canceled_hours_domain).mapped('unit_amount'))
        dashboard_values['hours']['canceled'] = float_round(
            total_canceled_hours, precision_rounding=hour_rounding)
        dashboard_values['hours'][
            'total'] += float_round(total_canceled_hours, precision_rounding=hour_rounding)

        # hours (from timesheet) and rates (by billable type)
        dashboard_domain = [('project_id', 'in', self.ids), ('timesheet_invoice_type', '!=', False),
                            '|', ('so_line', '=', False), ('so_line.state', '!=', 'cancel')]  # force billable type
        dashboard_data = self.env['account.analytic.line'].read_group(
            dashboard_domain, ['unit_amount', 'timesheet_invoice_type'], ['timesheet_invoice_type'])
        dashboard_total_hours = sum(
            [data['unit_amount'] for data in dashboard_data]) + total_canceled_hours
        for data in dashboard_data:
            billable_type = data['timesheet_invoice_type']
            dashboard_values['hours'][billable_type] = float_round(
                data.get('unit_amount'), precision_rounding=hour_rounding)
            dashboard_values['hours'][
                'total'] += float_round(data.get('unit_amount'), precision_rounding=hour_rounding)
            # rates
            rate = round(data.get('unit_amount') / dashboard_total_hours *
                         100, 2) if dashboard_total_hours else 0.0
            dashboard_values['rates'][billable_type] = rate
            dashboard_values['rates']['total'] += rate

        # rates from non-invoiced timesheets that are linked to canceled so
        dashboard_values['rates']['canceled'] = float_round(
            100 * total_canceled_hours / (dashboard_total_hours or 1), precision_rounding=hour_rounding)

        # profitability, using profitability SQL report
        profit = dict.fromkeys(['invoiced', 'to_invoice', 'cost',
                                'expense_cost', 'expense_amount_untaxed_invoiced', 'total'], 0.0)
        profitability_raw_data = self.env['project.profitability.report'].read_group([('project_id', 'in', self.ids)], [
                                                                                     'project_id', 'amount_untaxed_to_invoice', 'amount_untaxed_invoiced', 'timesheet_cost', 'expense_cost', 'expense_amount_untaxed_invoiced'], ['project_id'])
        for data in profitability_raw_data:
            profit['invoiced'] += data.get('amount_untaxed_invoiced', 0.0)
            profit['to_invoice'] += data.get('amount_untaxed_to_invoice', 0.0)
            profit['cost'] += data.get('timesheet_cost', 0.0)
            profit['expense_cost'] += data.get('expense_cost', 0.0)
            profit[
                'expense_amount_untaxed_invoiced'] += data.get('expense_amount_untaxed_invoiced', 0.0)
        profit['total'] = sum([profit[item] for item in profit.keys()])
        dashboard_values['profit'] = profit

        total_vendor_po = 0.0
        for project in self:
            for task in project.task_ids:
                total_vendor_po += task.purchase_order_id.amount_untaxed
        profit['total'] -= total_vendor_po

        values['dashboard'] = dashboard_values

        #
        # Time Repartition (per employee per billable types)
        #
        user_ids = self.env['project.task'].sudo().read_group(
            [('project_id', 'in', self.ids), ('user_id', '!=', False)], ['user_id'], ['user_id'])
        user_ids = [user_id['user_id'][0] for user_id in user_ids]
        employee_ids = self.env['res.users'].sudo().search_read(
            [('id', 'in', user_ids)], ['employee_ids'])
        # flatten the list of list
        employee_ids = list(itertools.chain.from_iterable(
            [employee_id['employee_ids'] for employee_id in employee_ids]))

        aal_employee_ids = self.env['account.analytic.line'].read_group(
            [('project_id', 'in', self.ids), ('employee_id', '!=', False)], ['employee_id'], ['employee_id'])
        employee_ids.extend(
            list(map(lambda x: x['employee_id'][0], aal_employee_ids)))

        employees = self.env['hr.employee'].sudo().browse(employee_ids)
        repartition_domain = [('project_id', 'in', self.ids), ('employee_id', '!=', False),
                              ('timesheet_invoice_type', '!=', False)]  # force billable type
        # repartition data, without timesheet on cancelled so
        repartition_data = self.env['account.analytic.line'].read_group(repartition_domain + ['|', ('so_line', '=', False), ('so_line.state', '!=', 'cancel')], [
                                                                        'employee_id', 'timesheet_invoice_type', 'unit_amount'], ['employee_id', 'timesheet_invoice_type'], lazy=False)
        # read timesheet on cancelled so
        cancelled_so_timesheet = self.env['account.analytic.line'].read_group(
            repartition_domain + [('so_line.state', '=', 'cancel')], ['employee_id', 'unit_amount'], ['employee_id'], lazy=False)
        repartition_data += [{**canceled, 'timesheet_invoice_type': 'canceled'} for canceled in cancelled_so_timesheet]

        # set repartition per type per employee
        repartition_employee = {}
        for employee in employees:
            repartition_employee[employee.id] = dict(
                employee_id=employee.id,
                employee_name=employee.name,
                non_billable_project=0.0,
                non_billable=0.0,
                billable_time=0.0,
                billable_fixed=0.0,
                canceled=0.0,
                total=0.0,
            )
        for data in repartition_data:
            employee_id = data['employee_id'][0]
            repartition_employee.setdefault(employee_id, dict(
                employee_id=data['employee_id'][0],
                employee_name=data['employee_id'][1],
                non_billable_project=0.0,
                non_billable=0.0,
                billable_time=0.0,
                billable_fixed=0.0,
                canceled=0.0,
                total=0.0,
            ))[data['timesheet_invoice_type']] = float_round(data.get('unit_amount', 0.0), precision_rounding=hour_rounding)
            repartition_employee[employee_id][
                '__domain_' + data['timesheet_invoice_type']] = data['__domain']
        # compute total
        for employee_id, vals in repartition_employee.items():
            repartition_employee[employee_id]['total'] = sum([vals[inv_type] for inv_type in [*billable_types, 'canceled']])
        hours_per_employee = [repartition_employee[employee_id][
            'total'] for employee_id in repartition_employee]
        values['repartition_employee_max'] = (
            max(hours_per_employee) if hours_per_employee else 1) or 1
        values['repartition_employee'] = repartition_employee

        #
        # Table grouped by SO / SOL / Employees
        #
        timesheet_forecast_table_rows = self._table_get_line_values()
        if timesheet_forecast_table_rows:
            values['timesheet_forecast_table'] = timesheet_forecast_table_rows
        return values

    def _plan_get_stat_button(self):
        stat_buttons = []
        if len(self) == 1:
            edit_project = self.env.ref('project.edit_project')
            stat_buttons.append({
                'name': _('Project'),
                'icon': 'fa fa-puzzle-piece',
                'action': _to_action_data('project.project', res_id=self.id,
                                          views=[[edit_project.id, 'form']])
            })
        ts_tree = self.env.ref('hr_timesheet.hr_timesheet_line_tree')
        ts_form = self.env.ref('hr_timesheet.hr_timesheet_line_form')
        stat_buttons.append({
            'name': _('Timesheets'),
            'icon': 'fa fa-calendar',
            'action': _to_action_data(
                'account.analytic.line',
                domain=[('project_id', 'in', self.ids)],
                views=[(ts_tree.id, 'list'), (ts_form.id, 'form')],
            )
        })

        # if only one project, add it in the context as default value
        tasks_domain = [('project_id', 'in', self.ids)]
        tasks_context = self.env.context

        # filter out all the projects that have no tasks
        task_projects_ids = self.env['project.task'].read_group(
            [('project_id', 'in', self.ids)], ['project_id'], ['project_id'])
        task_projects_ids = [p['project_id'][0] for p in task_projects_ids]

        if len(task_projects_ids) == 1:
            tasks_context = {**tasks_context, 'default_project_id': task_projects_ids[0]}
        stat_buttons.append({
            'name': _('Tasks'),
            'count': sum(self.mapped('task_count')),
            'icon': 'fa fa-tasks',
            'action': _to_action_data(
                action=self.env.ref('project.action_view_task'),
                domain=tasks_domain,
                context=tasks_context
            )
        })

        # task_po_ids = self.env['project.task'].search_read([
        #     ('project_id', 'in', self.ids), ('purchase_order_id', '!=', False)
        # ], ['purchase_order_id'])
        # task_po_ids = [o['purchase_order_id'][0] for o in task_po_ids]
        # po_orders = self.env['purchase.order'].browse(task_po_ids)
        # stat_buttons.append({
        #     'name': _('PO Orders'),
        #     'count': len(po_orders),
        #     'icon': 'fa fa-dollar',
        #     'action': _to_action_data(
        #         action=self.env.ref('purchase.purchase_rfq'),
        #         domain=[('id', 'in', po_orders.ids)],
        #         context={'create': False,
        #                  'edit': False, 'delete': False}
        #     )
        # })

        if self.env.user.has_group('sales_team.group_sale_salesman_all_leads'):
            # read all the sale orders linked to the projects' tasks
            task_so_ids = self.env['project.task'].search_read([
                ('project_id', 'in', self.ids), ('sale_order_id', '!=', False)
            ], ['sale_order_id'])
            task_so_ids = [o['sale_order_id'][0] for o in task_so_ids]

            sale_orders = self.mapped('sale_line_id.order_id') | self.env[
                'sale.order'].browse(task_so_ids)
            if sale_orders:
                stat_buttons.append({
                    'name': _('Sales Orders'),
                    'count': len(sale_orders),
                    'icon': 'fa fa-dollar',
                    'action': _to_action_data(
                        action=self.env.ref('sale.action_orders'),
                        domain=[('id', 'in', sale_orders.ids)],
                        context={'create': False,
                                 'edit': False, 'delete': False}
                    )
                })

                invoice_ids = self.env['sale.order'].search_read(
                    [('id', 'in', sale_orders.ids)], ['invoice_ids'])
                invoice_ids = list(itertools.chain(
                    *[i['invoice_ids'] for i in invoice_ids]))
                invoice_ids = self.env['account.move'].search_read(
                    [('id', 'in', invoice_ids), ('type', '=', 'out_invoice')], ['id'])
                invoice_ids = list(map(lambda x: x['id'], invoice_ids))

                if invoice_ids:
                    stat_buttons.append({
                        'name': _('Invoices'),
                        'count': len(invoice_ids),
                        'icon': 'fa fa-pencil-square-o',
                        'action': _to_action_data(
                            action=self.env.ref(
                                'account.action_move_out_invoice_type'),
                            domain=[('id', 'in', invoice_ids),
                                    ('type', '=', 'out_invoice')],
                            context={'create': False, 'delete': False}
                        )
                    })

        return stat_buttons


def _to_action_data(model=None, *, action=None, views=None, res_id=None, domain=None, context=None):
    # pass in either action or (model, views)
    if action:
        assert model is None and views is None
        act = clean_action(action.read()[0])
        model = act['res_model']
        views = act['views']
    # FIXME: search-view-id, possibly help?
    descr = {
        'data-model': model,
        'data-views': json.dumps(views),
    }
    if context is not None:  # otherwise copy action's?
        descr['data-context'] = json.dumps(context)
    if res_id:
        descr['data-res-id'] = res_id
    elif domain:
        descr['data-domain'] = json.dumps(domain)
    return descr
