# -*- coding: utf-8 -*-
from openerp import models, fields, api
import datetime
import io
import csv
import base64
from openerp.exceptions import Warning

class Show(models.Model):
    _name = "netaddiction.show"

    name = fields.Char(string="Nome Fiera")
    show_quant_ids = fields.One2many(
        comodel_name='netaddiction.show.quant',
        inverse_name='name',
        string='Prodotti Partiti')
    show_return_ids = fields.One2many(
        comodel_name='netaddiction.return.quants',
        inverse_name='name',
        string='Prodotti Rientrati')
    show_sell_ids = fields.One2many(
        comodel_name='netaddiction.sell.quant',
        inverse_name='name',
        string='Prodotti Venduti')
    date_start = fields.Date(string="Data inizio")
    date_finish = fields.Date(string="Data fine")
    state = fields.Selection(string="Stato", selection=[('draft', 'Nuova'), ('open', 'Aperta'), ('close', 'Chiusa')], default="draft")

    exit_value = fields.Float(string="Valore acquistato uscito",
        help="Valore totale dei prodotti partiti per la fiera calcolato con i prezzi di carico secondo FIFO nel momento di creazione",
        compute="_get_exit_value")
    exit_sell_value = fields.Float(string="Valore ipotetico venduto uscito",
        help="Valore ipotetico di vendita dei prodotti partiti per la fiera calcolato con i prezzi al pubblico nel momento di creazione",
        compute="_get_sell_value")
    export_file = fields.Binary(string="Csv", attachment=True)
    import_file = fields.Binary(string="Csv Ritorno Fiera", attachment=True)

    sale_stock_value = fields.Float(string="Valore acquistato venduto", compute="_get_sale_stock_value")
    sale_sell_value = fields.Float(string="Valore venduto", compute="_get_sale_sell_value")

    @api.one
    def close_show(self):
        self.state = 'close'

    @api.one
    def _get_sale_stock_value(self):
        value = 0
        for line in self.show_sell_ids:
            value += float(line.stock_value)
        self.sale_stock_value = value

    @api.one
    def _get_sale_sell_value(self):
        value = 0
        for line in self.show_sell_ids:
            value += float(line.public_price)
        self.sale_sell_value = value

    @api.multi
    def import_csv(self):
        csv_file = base64.b64decode(self.import_file)
        csv_bytes = io.BytesIO(csv_file)
        spamreader = csv.reader(csv_bytes)

        for line in spamreader:
            barcode = line[0]
            if barcode == 'Barcode':
                continue

            barcodes = [barcode, barcode[1:], '0' + barcode, barcode.lower(), barcode.upper(), barcode.capitalize()]

            product = self.env['product.product'].search([('barcode', 'in', barcodes)])
            if product:
                value = 0
                res = self.env['netaddiction.show.quant'].search([('product_id', '=', product.id), ('name', '=', self.id)])
                if res:
                    q = 0
                    tot = 0
                    for pid in res:
                        tot += pid.stock_value
                        q += pid.qty
                    value = float(tot) / float(q)

                attr = {
                    'name': self.id,
                    'product_id': product.id,
                    'date_move': datetime.date.today(),
                    'qty': line[3],
                    'public_price': line[4],
                    'stock_value': value * float(line[3])
                }
                self.env['netaddiction.sell.quant'].create(attr)

    @api.multi
    def create_csv(self):
        self.ensure_one()
        tax_inc = self.env['account.tax'].search([('description', '=', '22v INC')]).id
        products = {}
        for pid in self.show_quant_ids:
            if pid.product_id.id in products:
                products[pid.product_id.id]['qty'] += pid.qty
            else:
                tr = 'R2'
                for tax in pid.product_id.taxes_id:
                    if tax.id == tax_inc:
                        tr = 'R1'
                products[pid.product_id.id] = {
                    'name': pid.product_id.display_name,
                    'qty': pid.qty,
                    'price': pid.public_price,
                    'unit_value': pid.stock_value / float(pid.qty),
                    'barcode': pid.product_id.barcode,
                    'iva': tr
                }

        output = io.BytesIO()
        writer = csv.writer(output)

        for pid in products:
            product = products[pid]
            csvdata = [product['name'], product['barcode'], product['price'], product['qty'], product['unit_value'], 'Multiplayer.com', product['iva']]
            writer.writerow(csvdata)

        self.export_file = base64.b64encode(output.getvalue()).decode()
        output.close()

    @api.one
    def _get_exit_value(self):
        value = 0
        for line in self.show_quant_ids:
            value += float(line.stock_value)
        self.exit_value = value

    @api.one
    def _get_sell_value(self):
        value = 0
        for line in self.show_quant_ids:
            value += float(line.qty) * float(line.public_price)
        self.exit_sell_value = value

    @api.model
    def add_quant_to_show(self, location_id, qta, show_id):
        show_id = int(show_id)
        this_show = self.browse(show_id)

        location = self.env['netaddiction.wh.locations.line'].browse(int(location_id))
        stock_show = self.env.ref('netaddiction_show.netaddiction_stock_show').id
        picking_type_show = self.env.ref('netaddiction_show.netaddiction_type_out_show').id
        wh_stock = self.env.ref('stock.stock_location_stock').id

        if int(qta) <= 0:
            return 'Dai, serio, mi stai prendendo per i fondelli. Come pretendi di spostare una quantità negativa?'
        if int(qta) > int(location.product_id.qty_available_now):
            return 'Non puoi scaricare più prodotti di quelli disponibili'
        if int(qta) > int(location.qty):
            return 'Non puoi scaricare più prodotti di quelli che contiene lo scaffale'

        # per prima cosa decremento la quantità sulla locazione
        diff = location.qty - int(qta)
        location.qty = diff
        # location.decrease(int(qta))
        # faccio gli spostamenti dal magazzino stock a quello fiere
        attr = {
            'picking_type_id': picking_type_show,
            'move_type': 'one',
            'priority': '1',
            'location_id': wh_stock,
            'location_dest_id': stock_show,
            'move_lines': [(0, 0, {'product_id': location.product_id.id, 'product_uom_qty': int(qta),
                'state': 'draft',
                'product_uom': location.product_id.uom_id.id,
                'name': 'WH/Stock > Magazzino Fiera',
                'origin': this_show.name})],
        }
        pick = self.env['stock.picking'].sudo().create(attr)
        pick.sudo().action_confirm()
        pick.sudo().force_assign()
        for line in pick.pack_operation_product_ids:
            line.sudo().write({'qty_done': line.product_qty})
        pick.sudo().do_transfer()

        quant_list = []
        inventory_value = 0
        for move in pick.sudo().move_lines:
            for q in move.quant_ids:
                quant_list.append(q.id)
                inventory_value += q.inventory_value

        data = {
            'name': show_id,
            'product_id': location.product_id.id,
            'date_move': datetime.date.today(),
            'qty': qta,
            'public_price': location.product_id.lst_price,
            'pick_id': pick.id,
            'quant_ids': [(6, False, quant_list)],
            'stock_value': inventory_value
        }
        self.env['netaddiction.show.quant'].sudo().create(data)

        if diff == 0:
            location.sudo().unlink()

        return 1

class ShowQuant(models.Model):
    _name = "netaddiction.show.quant"

    name = fields.Many2one(
        comodel_name="netaddiction.show",
        string="Fiera")
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Prodotto")
    date_move = fields.Date(string="Data spostamento")
    qty = fields.Integer(string="Quantità")
    stock_value = fields.Float(string="Valore acquistato")
    public_price = fields.Float(string="Prezzo al pubblico")
    quant_ids = fields.Many2many(string="Rigo Magazzino", comodel_name="stock.quant")
    pick_id = fields.Many2one(string="Picking", comodel_name="stock.picking")

class SellQuant(models.Model):
    _name = "netaddiction.sell.quant"

    name = fields.Many2one(
        comodel_name="netaddiction.show",
        string="Fiera")
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Prodotto")
    date_move = fields.Date(string="Data Creazione")
    qty = fields.Integer(string="Quantità")
    public_price = fields.Float(string="Prezzo al pubblico Totale")
    stock_value = fields.Float(string="Valore acquistato")

class ReturnQuant(models.Model):
    _name = "netaddiction.return.quants"

    name = fields.Many2one(
        comodel_name="netaddiction.show",
        string="Fiera")
    product_id = fields.Many2one(
        comodel_name="product.product",
        string="Prodotto")
    date_move = fields.Date(string="Data Rientro")
    qty = fields.Integer(string="Quantità")

class ProductsMovement(models.TransientModel):

    _name = "netaddiction.show.returned.move"

    barcode = fields.Char(string="Barcode")
    product_id = fields.Many2one(string="Prodotto", comodel_name="product.product")
    qty_available = fields.Integer(string="Qtà in fiera")
    show_id = fields.Many2one(string="Fiera", comodel_name="netaddiction.show")
    qty_to_move = fields.Integer(string="Quantità da riallocare")
    new_allocation = fields.Many2one(string="Dove Allocare", comodel_name="netaddiction.wh.locations")
    message = fields.Char(string="Messaggio")

    @api.onchange('barcode')
    def search_product(self):
        loc = self.env['netaddiction.wh.locations'].search([('barcode', '=', '0000000001'), ('company_id', '=', self.env.user.company_id.id)])
        if self.barcode:
            barcodes = [str(self.barcode), '0' + str(self.barcode), str(self.barcode).upper(), str(self.barcode).lower(), str(self.barcode).capitalize(), str(self.barcode)[1:]]
            product = self.env['product.product'].sudo().search([('barcode', 'in', barcodes)])
            if product:
                self.product_id = product[0].id

                if self.show_id:
                    result = self.env['netaddiction.show.quant'].search([('name', '=', self.show_id.id), ('product_id', '=', product[0].id)])
                    if result:
                        qta = 0
                        for res in result:
                            qta += res.qty
                        sell = self.env['netaddiction.sell.quant'].search([('name', '=', self.show_id.id), ('product_id', '=', product[0].id)])
                        if sell:
                            for s in sell:
                                qta -= s.qty
                        returned = self. env['netaddiction.return.quants'].search([('name', '=', self.show_id.id), ('product_id', '=', product[0].id)])
                        if returned:
                            for s in returned:
                                qta -= s.qty
                        if qta < 0:
                            qta = 0
                        self.qty_available = qta
                        self.qty_to_move = qta
                        self.new_allocation = loc.id

    @api.one
    def execute(self):
        if self.qty_to_move <= 0:
            raise Warning('Seriamente vuoi spostare una quantità negativa o uguale a zero?')
        if self.qty_to_move > self. qty_available:
            raise Warning('Ma come ti viene in mente di caricare una qunatità maggiore di quella disponibile in Magazzino Fiere?!')
        if not self.show_id:
            raise Warning('Devi inserire una Fiera')
        product = self.env['netaddiction.show.quant'].search([('name', '=', self.show_id.id), ('product_id', '=', self.product_id.id)])
        if len(product) == 0:
            raise Warning('Il prodotto che stai cercando di caricare non fa parte della fiera selezionata')
        if not self.new_allocation:
            raise Warning('Devi selezionare un ripiano dove allocare')

        stock_show = self.env.ref('netaddiction_show.netaddiction_stock_show').id
        picking_type_show = self.env.ref('netaddiction_show.netaddiction_type_in_show').id
        wh_stock = self.env.ref('stock.stock_location_stock').id
        attr = {
            'picking_type_id': picking_type_show,
            'move_type': 'one',
            'priority': '1',
            'location_id': stock_show,
            'location_dest_id': wh_stock,
            'move_lines': [(0, 0, {'product_id': self.product_id.id, 'product_uom_qty': int(self.qty_to_move),
                'state': 'draft',
                'product_uom': self.product_id.uom_id.id,
                'name': 'Magazzino Fiera > WH/Stock',
                'origin': self.show_id.name})],
        }
        pick = self.env['stock.picking'].sudo().create(attr)
        pick.sudo().action_confirm()
        pick.sudo().force_assign()
        for line in pick.pack_operation_product_ids:
            line.sudo().write({'qty_done': line.product_qty})
        pick.sudo().do_transfer()

        self.env['netaddiction.wh.locations.line'].sudo().allocate(self.product_id.id, self.qty_to_move, self.new_allocation.id)

        not_sell = {
            'name': self.show_id.id,
            'product_id': self.product_id.id,
            'qty': self.qty_to_move,
            'date_move': datetime.date.today()
        }
        self.env['netaddiction.return.quants'].sudo().create(not_sell)

        self.barcode = False
        self.product_id = False
        self.qty_available = False
        self.qty_to_move = False
        self.message = 'Prodotto Riallocato Correttamente'