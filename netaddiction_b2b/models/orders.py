# -*- coding: utf-8 -*-

from openerp import models, fields, api
import openerp.addons.decimal_precision as dp

class Orders(models.Model):
    _inherit = 'sale.order'

    is_b2b = fields.Boolean(string="B2B")

    @api.multi
    def simulate_delivery_price(self,subdivision):
        self.ensure_one()

        if not self.is_b2b:
            return super(Orders,self).simulate_delivery_price(subdivision)

    @api.constrains('partner_id','pricelist_id')
    def set_b2b(self):
        self.is_b2b = self.partner_id.is_b2b
        self.delivery_option = 'asap'


    @api.multi
    def set_delivery_price(self):
    	if not self.is_b2b:
            return super(Orders,self).set_delivery_price()
        

