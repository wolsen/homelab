#!/usr/bin/python
import models
import time
from flask import Flask, jsonify, abort, make_response, request

app = Flask(__name__)


def show_msg(msg):
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    print "{} {}".format(now, msg)


@app.route('/power/api/v1.0/computer/<string:comp_id>', methods=['GET'])
def get_task(comp_id):
    computer = models.get_computer(name=comp_id)
    if not computer:
        print "Computer %s not found" % comp_id
        abort(404)

    power_state = computer.get_power_state()
    show_msg('Query power state of {} ({})'.format(comp_id, power_state))
    return jsonify({'power_state': power_state})


@app.errorhandler(404)
def not_found(error):
    return make_response(jsonify({'error': 'Not found'}), 404)


@app.route('/power/api/v1.0/computer/<string:comp_id>', methods=['PUT'])
def power_task(comp_id):
    computer = models.get_computer(name=comp_id)
    if not computer:
        print "Computer %s not found" % comp_id
        abort(404)

    print request.json.keys()

    action = request.json['action']
    if not computer.is_valid_action(action):
        print "Bad action: %s" % action
        abort(400)

    show_msg('{} {}'.format(action, comp_id))
    if action == 'on':
        computer.poweron()
    elif action == 'off':
        computer.poweroff()
    elif action == 'hardoff':
        computer.poweroff()
    return jsonify({'power_states': computer.get_power_state()})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)

