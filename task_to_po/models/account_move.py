# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import models, fields, api, _


class AccountMove(models.Model):
    _inherit = "account.move"

    project_id = fields.Many2one('project.project', string="Project Name")
    project_task_id = fields.Many2one('project.task', string="Project Task")
