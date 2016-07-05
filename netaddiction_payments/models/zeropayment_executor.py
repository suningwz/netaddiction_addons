# -*- coding: utf-8 -*-

import payment_exception
from float_compare import isclose
from openerp import models, fields, api


class ZeroPaymentExecutor(models.TransientModel):
    """Classe di utilità associata a un transient model per effettuare e registrare
    pagamenti con cc tramite bnl positivity, e per registrare carte di credito da BO in maniera sicura
    """
    _name = "netaddiction.zeropayment.executor"


    def set_order_zero_payment(self,order_id):
        order = self.env["sale.order"].search([("id","=",order_id)])
        
        if not order:
            raise payment_exception.PaymentException(payment_exception.ZERO,"order id non valido!")

        if not isclose(order.amount_total,0.0):
            raise payment_exception.PaymentException(payment_exception.ZERO,"ordine non a 0! pagamento dovuto: % s" % order.amount_total)

        zeropayment_journal  = self.env['ir.model.data'].get_object('netaddiction_payments','zeropay_journal')
        order.payment_method_id = zeropayment_journal.id

        if order.state == 'draft':
            order.action_confirm()

        if order.state == 'sale':
            inv_lst = []

            for line in order.order_line:
                #resetto la qty_to_invoice di tutte le linee
                line.qty_to_invoice = 0
            for delivery in order.picking_ids:                    
                for stock_move in delivery.move_lines_related:
                    self._set_order_to_invoice(stock_move,order)

                self._set_delivery_to_invoice(delivery,order)

                inv_lst += order.action_invoice_create()

            for inv in inv_lst:
                invoice = self.env['account.invoice'].search([("id","=",inv)])
                invoice.signal_workflow('invoice_open')

    @api.one
    def _set_order_to_invoice(self,stock_move,order):
        """dato 'order' imposta qty_to_invoice alla quantità giusta solo per i prodotti che si trovano in 'stock_move'
        """
        prod_id = stock_move.product_id
        qty = stock_move.product_uom_qty

        lines = [line for line in order.order_line if line.product_id == prod_id ]
        for line in lines:
            qty_to_invoice = qty if qty < line.product_uom_qty else line.product_uom_qty

            line.qty_to_invoice += qty_to_invoice

            qty = qty - qty_to_invoice

            if qty <= 0:
                break

    @api.one
    def _set_delivery_to_invoice(self,pick,order):
        """dato 'order' imposta qty_to_invoice per una spedizione 
        """
        lines = [line for line in order.order_line if line.is_delivery and line.price_unit == pick.carrier_price and  line.qty_invoiced < line.product_uom_qty]

        if lines:
            lines[0].qty_to_invoice = 1
