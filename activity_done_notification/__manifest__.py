{
    'name': 'Activity Done Notification',
    'version': '13.0.1',
    'category': 'Mail Notification',
    'license': 'OPL-1',
    'summary': 'Notify assigner when assignee marks activity done.',

    'author': 'Enicorn Limited',
    'maintainer': 'Enicorn Limited',

    'depends': ['mail'],
    'data': [
        'data/email_template.xml',
    ],

    'installable': True,
    'auto_install': False,
    'application': True,
    'price': 30.00,
    'currency': 'USD',
}