# -*- coding: utf-8 -*-
{
    'name': "NetAddiction Account",
    'summary': "Modulo di gestione Fatture",

    'description':"""
    Gestione delle fatture
    """,
    'author': "Netaddiction",

    'website': "http://www.netaddiction.it",
    'category': 'Technical Settings',
    'version': '1',
    'depends': ['base','product','sale','purchase','mrp','account','netaddiction_products',
        'netaddiction_special_offers', 'netaddiction_b2b','netaddiction_purchase_orders','netaddiction_warehouse'],
    'data': [
        'views/invoice.xml',
        'views/registro_corrispettivi.xml',
    ]
}