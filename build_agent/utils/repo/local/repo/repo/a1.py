from flask import Flask, jsonify, url_for
from flask_restful import reqparse
from model import Coffee, Order, Payment

app = Flask(__name__)
order_db = []
payment_db = []

order_counter = 0

coffee_db = [
    Coffee(1, 'short black', 2.80),
    Coffee(2, 'long black', 3.00),
    Coffee(3, 'cafe latte', 3.40),
    Coffee(4, 'cappuccino', 3.50),
    Coffee(5, 'flat white', 3.60),
]

@app.route("/orders", methods=['GET'])
def get_orders():
    return jsonify([st.__dict__ for st in order_db])

@app.route('/orders/status/<status>', methods=['GET'])
def get_orders_bystatus(status):
    return jsonify([row.__dict__ for row in order_db if str(row.status).lower() == str(status).lower()])

@app.route('/orders/<order_id>', methods=['GET'])
def get_order_byid(order_id):
    for row in order_db:
        if int(row.order_id) == int(order_id):
            return jsonify([row.__dict__])
    return jsonify(order_id=False), 404

@app.route("/orders", methods=['POST'])
def create_order():
    global order_counter
    parser = reqparse.RequestParser()
    parser.add_argument('coffee_id', type=int, required=True)
    parser.add_argument('additions', type=str, action='append')
    args = parser.parse_args()

    coffee_id = args.get("coffee_id")
    additions = args.get("additions")
    for row in coffee_db:
        if int(row.coffee_id) == int(coffee_id):
            coffee = row
            break
    else:
        return jsonify(coffee_id=False), 404

    order_counter += 1
    new = Order(order_counter, coffee_id, coffee.coffee_name, coffee.cost, 'open', additions)
    order_db.append(new)
    return jsonify({
        'data':new.__dict__,
        'payment': {
            'link':url_for('create_payment',order_id=order_counter),
            'method':'POST'
        }

    }), 201

@app.route("/orders/<order_id>", methods=['DELETE'])
def delete_order(order_id):
    # can be deleted before payment
    row = next((x for x in order_db if x.order_id == int(order_id)), None)
    is_paid = any(int(row.order_id) == int(order_id) for row in payment_db)

    if row is None:
        return jsonify(order_id=False), 404
    elif is_paid:
        return jsonify(is_paid = True), 401
    else:
        del order_db[order_db.index(row)]
        return jsonify(order_id=order_id), 204

@app.route("/orders/<order_id>", methods=['PUT'])
def update_order(order_id):
    # can be updated if status is 'open' and no payment
    parser = reqparse.RequestParser()
    parser.add_argument('coffee_id', type=int, required=True)
    parser.add_argument('additions', type=str, action='append')
    old = next((x for x in order_db if x.order_id == int(order_id)), None)

    if old is None:
        return jsonify(order_id=False), 404

    if old.status is not 'open':
        return jsonify(status=False), 401

    is_paid = any(int(row.order_id) == int(order_id) for row in payment_db)
    if is_paid:
        return jsonify(is_paid=True), 401

    args = parser.parse_args()
    coffee_id = args.get("coffee_id")
    additions = args.get("additions")

    for item in coffee_db:
        if item.coffee_id == coffee_id:
            coffee = item
            break
    else:
        return jsonify( coffee_id=False), 404

    old.coffee_id = coffee_id
    old.coffee_name = coffee.coffee_name
    old.cost = coffee.cost
    old.status = 'open'
    old.additions = additions

    return jsonify({
        'data': old.__dict__,
        'payment': {
            'link':url_for('create_payment',order_id=order_counter),
            'method':'POST'
        }
    }), 201

@app.route("/orders/<order_id>", methods=['PATCH'])
def update_order_status(order_id):
    row = next((x for x in order_db if x.order_id == int(order_id)), None)
    if row is None:
        return jsonify(order_id=False), 404

    parser = reqparse.RequestParser()
    parser.add_argument('status', type=str, required=True)
    args = parser.parse_args()
    status = args.get("status")
    is_paid = any(int(row.order_id) == int(order_id) for row in payment_db)
    paid = False
    if is_paid is True:
        paid = True

    if is_paid is False and status == 'release':
        return jsonify(is_paid = False), 402

    if row.status is not 'open' and status == 'open':
        return jsonify(status=False), 404

    row.status = str(status)
    return jsonify({
        'data': row.__dict__,
        'is_paid': paid
    }) , 202

@app.route("/payments/<order_id>", methods=['POST'])
def create_payment(order_id):
    parser = reqparse.RequestParser()
    parser.add_argument('payment_type', type=str,required=True)
    parser.add_argument('card_name', type=str)
    parser.add_argument('card_num', type=int)
    parser.add_argument('card_exp', type=str)
    args = parser.parse_args()

    if not any(row.order_id == int(order_id) for row in order_db):
        return jsonify(order_id=False), 404

    payment_type = args.get("payment_type")
    if payment_type.lower() == 'card':
        card_name = args.get("card_name")
        card_num = args.get("card_num")
        card_exp = args.get("card_exp")
        new = Payment(order_id, payment_type, card_name, card_num, card_exp)

    else:
        new = Payment(order_id, payment_type)
    payment_db.append(new)
    order = next((x for x in order_db if x.order_id == int(order_id)), None)
    return jsonify({
        'data':[new.__dict__],
        'order':[order.__dict__]
    }), 201


@app.route("/payments/<order_id>", methods=['GET'])
def get_payment(order_id):
    order = next((x for x in order_db if x.order_id == int(order_id)), None)
    payment = next((x for x in payment_db if x.order_id == int(order_id)), None)

    if order is None:
        jsonify(order_id=False), 404
    elif payment is None:
        return jsonify({
            'payment': False,
            'order': order.__dict__,
        })
    else:
        return jsonify({
            'payment': payment.__dict__,
            'order': order.__dict__,
        })



if __name__ == "__main__":
    app.run(debug=True)