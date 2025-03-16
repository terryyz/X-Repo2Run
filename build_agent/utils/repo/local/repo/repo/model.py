class Coffee:
    def __init__(self,coffee_id,coffee_name,cost):
        self.coffee_id = coffee_id
        self.coffee_name = coffee_name
        self.cost = cost

class Order:
    def __init__(self, order_id, coffee_id,coffee_name, cost, status,additions):
        self.order_id = order_id
        self.coffee_id = coffee_id
        self.coffee_name = coffee_name
        self.cost = cost
        self.status = status
        self.additions = additions




class Payment:
    def __init__(self, order_id, payment_type, card_name = None, card_number = None, card_exp = None):
        self.order_id = order_id
        self.payment_type = payment_type
        self.card_name = card_name
        self.card_number = card_number
        self.card_exp = card_exp