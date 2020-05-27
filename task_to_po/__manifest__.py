{
    'name': 'PO From Task',
    'summary': 'Create Purchase Order From Task',
    'description': """
                - Create PO directly from Task and allow Project view
    """,
    'category': 'Operations/Project',
    'version': '13.0',
    'author': 'Key Concepts',
    'website': 'http://keyconcepts.co.in',
    'depends': ['project', 'purchase', 'stock', 'sale_timesheet'],
    'data': [
        'views/purchase_order_view.xml',
        'views/project_view.xml',
        'views/hr_timesheet_templates.xml',
    ],
    "sequence": 1,
    'installable': True,
    'application': False,
}
