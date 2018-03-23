# -*- coding: utf-8 -*-
from suds.client import Client
from openerp import api, fields, models
from ..settings import MERCHANT_ID, SHOP_TOKEN
import traceback


class ChannelPilotOrder(models.Model):
    _inherit = 'sale.order'

    from_channelpilot = fields.Boolean(string='Da ChannelPilot', default=False)
    channelpilot_marketplace = fields.Char(string="Marketplace ChannelPilot")
    cp_order_id_external = fields.Char(string='Id Ordine External')
    cp_typedID = fields.Char(string='Id ChannelPilot')
    cp_typeTitle = fields.Char(string='Tipo ChannelPilot')
    cp_original_date = fields.Char(string='Data pagamento su ChannelPilot')
    cp_delivered = fields.Boolean(string='Spedito ChannelPilot', default=False)

    @api.model
    def _get_channelpilot_orders(self):
        client = Client("https://seller.api.channelpilot.com/3_0?wsdl")
        # for method in client.wsdl.services[0].ports[0].methods.values():
        #     print '%s(%s)' % (method.name, ', '.join('%s: %s' % (part.type, part.name) for part in method.soap.input.body.parts))
        cpAuth = client.factory.create(u'CPAuth')
        cpAuth.merchantId = MERCHANT_ID
        cpAuth.shopToken = SHOP_TOKEN
        response = client.service.getNewMarketplaceOrders(cpAuth)
        if not response or not response.header or not response.header.resultCode or response.header.resultCode != 200:
            # BAD RESPONSE inviare mail
            self._send_cp_error_mail(" [CHANNELPILOT -  IMPORT ORDERS] return da getNewMarketplaceOrders: %s -" % response, '[CHANNELPILOT -  IMPORT ORDERS] getNewMarketplaceOrders bad Status ')
            return
        cp_orders = []
        problems = []
        self._send_cp_error_mail("  %s" % response, '[CHANNELPILOT -  DEBUG] getNewMarketplaceOrders result ')
        for order in response.managedArticles:
            # JUICE
            try:
                (user, user_shipping, user_billing) = self._create_cp_customer_and_addresses(order.customer, order.addressDelivery, order.addressInvoice)
                cp_order = self._create_cp_order(order, user, user_shipping, user_billing, client)
                cp_orders.append(cp_order)
            except Exception as e:
                problems.append("Problemi nel creare l'ordine %s - Ecco l'eccezione  %s  ****  %s " % (order, traceback.format_exc(), ''.join(traceback.format_stack())))
        if problems:
            self._send_cp_error_mail(" [CHANNELPILOT -  IMPORT ORDERS] return da getNewMarketplaceOrders: %s - Questi gli ordini problematici: %s" % (response, problems), '[CHANNELPILOT -  IMPORT ORDERS] problemi nella conversione di alcuni')

        if cp_orders:
            response_imported = client.service.setImportedOrders(cpAuth, cp_orders, False)
            if not response_imported or not response_imported.header or response_imported.header.resultCode != 200:
                # bad shit
                self._send_cp_error_mail(" [CHANNELPILOT -  IMPORT ORDERS] return da setImportedOrders: %s - Questo cp_deliveries: %s" % (response_imported, cp_orders), '[CHANNELPILOT -  IMPORT ORDERS] problemi nella setImportedOrders ')
            else:
                # alright
                problems = []
                for result in response_imported.updateResults:
                    if result.header.resultCode != 200:
                        # bad shit
                        problems.append(result)
                if problems:
                    self._send_cp_error_mail(" [CHANNELPILOT -  DELIVERY] return da setImportedOrders: %s - Questo cp_deliveries: %s - Questo è problems: %s" % (response_imported, cp_orders, problems), '[CHANNELPILOT -  IMPORT ORDERS] problemi nella setImportedOrders 2 ')

        return response

    def _create_cp_customer_and_addresses(self, cp_customer, cp_invoice, cp_delivery):
        u"""
        Crea utente e indirizzi sul backoffice, se non esistono già.

        Utenti e indirizzi vengono flaggati per essere ritrovati.
        """
        user = self.env["res.partner"].search([("email", "=", cp_customer.email)])
        user = user[0] if user else None
        name = cp_delivery.nameFull
        name = name if "company" not in cp_delivery else name + " C/O " + cp_delivery.company
        country_id_1 = self.env["res.country"].search([('code', '=', cp_delivery.countryIso2)])[0]
        country_id_2 = self.env["res.country"].search([('code', '=', cp_invoice.countryIso2)])[0]
        shipping_dict = {'name': name, 'street': cp_delivery.streetTitle, 'phone': self._get_phone(cp_customer, cp_delivery), 'country_id': country_id_1.id, 'city': cp_delivery.city, 'zip': cp_delivery.zip, 'street2': cp_delivery.streetNumber}
        billing_dict = {'name': name, 'street': cp_invoice.streetTitle, 'phone': self._get_phone(cp_customer, cp_invoice), 'country_id': country_id_2.id, 'city': cp_invoice.city, 'zip': cp_invoice.zip, 'street2': cp_invoice.streetNumber}
        user_shipping = None
        user_billing = None
        if user:
            # l'utente esiste già vediamo se posso risparmiarmi di creare anche gli indirizzi
            find_ship_address = False
            for child in user.child_ids:
                if child.type == "delivery" and child.equals(shipping_dict):
                    find_ship_address = True
                    user_shipping = child
                    break
            if not find_ship_address:
                shipping_dict['company_id'] = user.company_id.id
                shipping_dict['is_company'] = False
                shipping_dict['type'] = 'delivery'
                shipping_dict['customer'] = True
                shipping_dict['parent_id'] = user.id
                user_shipping = self.env["res.partner"].create(shipping_dict)
            billings = [child for child in user.child_ids if child.type == 'invoice']
            if billings:
                user_billing = billings[0]
            else:
                billing_dict['company_id'] = user.company_id.id
                billing_dict['is_company'] = False
                billing_dict['type'] = 'delivery'
                billing_dict['customer'] = True
                billing_dict['parent_id'] = user.id
                user_billing = self.env["res.partner"].create(billing_dict)
        else:
            # creare user e indirizzo che sega
            company_id = self.env["res.company"].search([("name", "=", "Multiplayer.com")])[0].id
            user = self.env["res.partner"].create({
                'name': cp_customer.nameFull,
                'company_id': company_id,
                'email': cp_customer.email,
                'is_company': True,
                'customer': True,
                'type': 'contact',
                'phone': cp_customer.phone if "phone" in cp_customer else "",
                'notify_email': 'none',
                'from_channelpilot': True, })
            shipping_dict['company_id'] = user.company_id.id
            shipping_dict['is_company'] = False
            shipping_dict['type'] = 'delivery'
            shipping_dict['customer'] = True
            shipping_dict['parent_id'] = user.id
            shipping_dict['from_channelpilot'] = True
            billing_dict['company_id'] = user.company_id.id
            billing_dict['is_company'] = False
            billing_dict['type'] = 'delivery'
            billing_dict['customer'] = True
            billing_dict['parent_id'] = user.id
            billing_dict['from_channelpilot'] = True
            user_shipping = self.env["res.partner"].create(shipping_dict)
            user_billing = self.env["res.partner"].create(billing_dict)

        return (user, user_shipping, user_billing)

    def _get_phone(self, cp_customer, cp_delivery):
        """Utility per il numero di telefono."""
        if "phone" in cp_delivery and cp_delivery.phone:
            return cp_delivery.phone
        elif "mobile" in cp_customer and cp_customer.mobile:
            return cp_customer.mobile
        elif "phone" in cp_customer and cp_customer.phone:
            return cp_customer.phone
        else:
            return None

    def _create_cp_order(self, order, user, user_shipping, user_billing, client):
        """Crea l'ordine sul backoffice."""
        payment = order.payment
        brt = self.env["delivery.carrier"].search([('name', '=', 'Corriere Espresso BRT')])[0].id
        # TODO: AGGIUNGERE CONTROLLO CONTRASSEGNO PER QUANDO ANDREMO UNO SHOPPING CON CONTRASSEGNO
        journal_id = self.env['ir.model.data'].get_object('netaddiction_channelpilot', 'channel_journal').id
        cp_typedID = payment.typeID
        cp_typeTitle = payment.typeTitle
        cp_original_date = payment.paymentTime
        bo_order = self.env["sale.order"].create({
            'partner_id': user.id,
            'partner_invoice_id': user_billing.id,
            'partner_shipping_id': user_shipping.id,
            'state': 'draft',
            'delivery_option': 'all',
            'carrier_id': brt,
            'payment_method_id': journal_id,
            'cp_typedID': cp_typedID,
            'cp_typeTitle': cp_typeTitle,
            'cp_original_date': cp_original_date,
            'from_channelpilot': True,
            'channelpilot_marketplace': order.orderHeader.source,
            'cp_order_id_external': order.orderHeader.orderIdExternal,
            'delivery_desired_price': order.shipping.costs.gross,
        })
        for product in order.itemsOrdered:
                quantity = product.quantityOrdered
                prod = self.env["product.product"].browse(product.article.id)
                if not prod:
                    raise Exception("problema con l'ordine %s , Non si trova il prodotto %s" % (order.id, product.article.id))
                order_line = self.env["sale.order.line"].create({
                    "order_id": bo_order.id,
                    "product_id": prod.id,
                    "product_uom_qty": quantity,
                    "product_uom": prod.uom_id.id,
                    "name": prod.display_name,
                    "price_unit": product.costSingle,
                })

        bo_order.manual_confirm()
        cp_status = client.factory.create(u'CPOrderStatus')
        cp_status.hasError = False
        cp_header = client.factory.create(u'CPOrderHeader')
        cp_header.orderId = bo_order.id
        cp_header.source = order.orderHeader.source,
        cp_header.orderIdExternal = order.orderHeader.orderIdExternal
        cp_header.status = cp_status
        cp_order_return = client.factory.create(u'CPOrder')
        cp_order_return.orderHeader = cp_header
        return cp_order_return

    @api.multi
    def manual_confirm(self):
        """Override per permettere il nuovo metodo di pagamento ChannelPilot."""
        cp_journal = self.env['ir.model.data'].get_object('netaddiction_channelpilot', 'channel_journal')
        for order in self:
            if order.state not in ('draft', 'pending'):
                # raise ValidationError("ordine non in draft")
                continue
            if order.payment_method_id and order.payment_method_id.id == cp_journal.id:
                transient = self.env["netaddiction.channelpilot.executor"].create({})
                transient.register_payment(order.partner_id.id, order.amount_total, order.id)
                transient.unlink()

        super(ChannelPilotOrder, self).manual_confirm()

    def _send_cp_error_mail(self, body, subject):
        """Utility invio mail errore channelpilot."""
        values = {
            'subject': subject,
            'body_html': body,
            'email_from': "shopping@multiplayer.com",
            # TODO 'email_to': "ecommerce-servizio@netaddiction.it",
            'email_to': "andrea.bozzi@netaddiction.it, andrea.alunni@netaddiction.it, matteo.piciucchi@netaddiction.it",
        }

        email = self.env['mail.mail'].create(values)
        email.send()

    @api.model
    def _notify_cp_deliveries_cron(self):
        # Cron per impostare a spedito gli ordini cp
        orders = self.env["sale.order"].search([("from_channelpilot", "=", True), ("cp_delivered", "=", False), ("state", "=", "done")])
        if not orders:
            return []

        client = Client("https://seller.api.channelpilot.com/3_0?wsdl")
        cpAuth = client.factory.create(u'CPAuth')
        cpAuth.merchantId = MERCHANT_ID
        cpAuth.shopToken = SHOP_TOKEN
        cp_deliveries = []
        for order in orders:
            cp_status = client.factory.create(u'CPOrderStatus')
            cp_status.hasError = False
            cp_header = client.factory.create(u'CPOrderHeader')
            cp_header.orderId = order.id
            cp_delivery = client.factory.create(u'CPDelivery')
            cp_delivery.orderHeader = cp_header
            cp_delivery.carrierName = "BRT"
            cp_delivery.deliveryTime = order.picking_ids[0].date_of_shipping_home + "T12:00:00+01:00"
            cp_delivery.isDeliveryCompleted = True
            cp_delivery.trackingNumber = order.picking_ids[0].delivery_barcode
            cp_deliveries.append(cp_delivery)

        if cp_deliveries:
            response_deliveries = client.service.registerDeliveries(cpAuth, cp_deliveries)
            if not response_deliveries or not response_deliveries.header or response_deliveries.header.resultCode != 200:
                # bad shit
                self._send_cp_error_mail(" [CHANNELPILOT -  DELIVERY] return da registerDeliveries: %s - Questi gli ordini presi in esame: %s - Questo cp_deliveries: %s" % (response_deliveries, orders, cp_deliveries), '[CHANNELPILOT -  DELIVERY] problemi nella conferma delle spedizioni ')
            else:
                # alright
                problems = []
                for result in response_deliveries.updateResults:
                    if result.header.resultCode != 200:
                        # bad shit
                        problems.append(result)
                    else:
                        temp = [x for x in orders if x.id == result.orderId]
                        if temp:
                            temp[0].cp_delivered = True
                        else:
                            # problemssss
                            problems.append("Non trovo l'ordine di questo risultato: %s " % result)
                if problems:
                    self._send_cp_error_mail(" [CHANNELPILOT -  DELIVERY] return da registerDeliveries: %s - Questi gli ordini presi in esame: %s - Questo cp_deliveries: %s - Questo è problems: %s" % (response_deliveries, orders, cp_deliveries, problems), '[CHANNELPILOT -  DELIVERY] problemi nella conferma delle spedizioni 2 ')