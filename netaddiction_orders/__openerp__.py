# -*- coding: utf-8 -*-
{
    'name': "NetAddiction Orders",
    'summary': "Nuova Gestione sale.order",

    'description': """
    Modulo della gestione degli ordini
    """,
    'author': "Netaddiction",

    'website': "http://www.netaddiction.it",
    'category': 'Technical Settings',
    'version': '1.0',
    'depends': ['base', 'product', 'sale', 'purchase', 'mrp', 'account', 'netaddiction_customer_care', 'netaddiction_customer', 'netaddiction_special_offers', 'netaddiction_payments', 'netaddiction_products'],
    'data': [
        'views/orders.xml',
        'views/tappetini.xml'
    ]
}
