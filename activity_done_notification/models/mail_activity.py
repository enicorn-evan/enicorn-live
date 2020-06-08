from odoo import models, _


class MailActivityExt(models.Model):
    _inherit = 'mail.activity'

    def _action_done(self, feedback=False, attachment_ids=None):
        body_template = self.env.ref('activity_done_notification.activity_done_email_notifier')
        for activity in self:
            model_description = self.env['ir.model']._get(activity.res_model).display_name
            body = body_template.render(
                dict(activity=activity, model_description=model_description, assignee=self.env.user.name, feedback=feedback),
                engine='ir.qweb',
                minimal_qcontext=True
            )
            record = self.env[activity.res_model].browse(activity.res_id)
            if activity.user_id:
                record.message_notify(
                    partner_ids=activity.create_uid.partner_id.ids,
                    body=body,
                    subject=_('%s is done with the assigned activity %s by you.') % (self.env.user.name, activity.summary or activity.activity_type_id.name),
                    record_name=activity.res_name,
                    feedback=feedback,
                    model_description=model_description,
                    email_layout_xmlid='mail.mail_notification_light',
                )
        return super(MailActivityExt, self)._action_done(feedback=feedback, attachment_ids=attachment_ids)

