##########################################################################################
#
#  Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#  SPDX-License-Identifier: MIT-0
#
#  Permission is hereby granted, free of charge, to any person obtaining a copy of this
#  software and associated documentation files (the "Software"), to deal in the Software
#  without restriction, including without limitation the rights to use, copy, modify,
#  merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
#  permit persons to whom the Software is furnished to do so.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
#  INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
#  PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
#  HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
#  OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
#  SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
##########################################################################################

import argparse
import json
import uuid
from awscrt import io, mqtt
from awsiot import mqtt_connection_builder
import time
from datetime import datetime
import random

g_received_count = 0
g_is_command_received = False
g_message_id = None
g_request = None
g_method = None
g_caller = None
g_timeout = 10000

g_operations = ["add", "sum", "div", "mul"]

def get_milliseconds():
    return round(time.time() * 1000)

# Callback when the subscribed topic receives a message
def on_message_received(topic, payload, dup, qos, retain, **kwargs):
    print(f"Received message from topic '{topic}': {payload}")

    global g_is_command_received
    global g_message_id
    global g_request
    global g_method
    global g_caller

    topicsplit = topic.split("/")
    g_method = topicsplit[1]
    g_caller = topicsplit[2]

    obj = json.loads(payload)

    print ("Obj: {obj}")

    g_is_command_received = False
    if ('id' in obj.keys()):
        g_is_command_received = True
        g_message_id = obj['id']

    if ('request' in obj.keys()):
        g_request = obj['request']

    if ('operation' in obj.keys()):
        req_op = obj['operation']
        if (req_op.upper() in (op.upper() for op in g_operations)):
            print ("Allowed operator: {req_op}")
    else:
        print ("Missing parameter 'operation'")



def connect(device_id, endpoint, port, cert_path, key_path):
    ts_start = get_milliseconds()

    event_loop_group = io.EventLoopGroup(1)
    host_resolver = io.DefaultHostResolver(event_loop_group)
    client_bootstrap = io.ClientBootstrap(event_loop_group, host_resolver)

    ################################################################################
    ### Create & Connect Client

    mqtt_connection = mqtt_connection_builder.mtls_from_path(
        client_id=device_id,
        endpoint=endpoint,
        port=int(port),
        cert_filepath=cert_path,
        pri_key_filepath=key_path,
        client_bootstrap=client_bootstrap,
        clean_session=False,
        keep_alive_secs=30
    )

    connect_future = mqtt_connection.connect()
    connect_future.result()

    print("Connected!")

    ################################################################################
    ### Subscribe to Topic

    message_topic = f"{device_id}/#"

    print(f"Subscribing to topic '{message_topic}' ...")

    subscribe_future, packet_id = mqtt_connection.subscribe(
        topic=message_topic,
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=on_message_received)

    subscribe_result = subscribe_future.result()

    print("Subscribed with {}".format(str(subscribe_result['qos'])))

    ################################################################################
    ### Wait for Command

    global g_is_command_received

    print("Waiting for command ...")

    while True:

        if g_is_command_received:
            res_time = get_milliseconds()

            print(f"Send ACK")
            g_is_command_received = False

            message_json = json.dumps({
                    'id':g_message_id,
                    'response':f"Your request was '{g_request}'. Some random response: '{random.random() * 1000}'"
                })

            g_message_ack_topic = f"{g_caller}/{g_message_id}/{device_id}/{g_method}/ack"

            print(f"Publishing message '{message_json}' on topic '{g_message_ack_topic}'")

            res, _ = mqtt_connection.publish(
                topic=g_message_ack_topic,
                payload=message_json,
                qos=mqtt.QoS.AT_LEAST_ONCE
            )

            res.result()

            print(f"Response '{res}' elapsed: {get_milliseconds() - res_time} ms")

        time.sleep(0.001)

def parse_args():
    parser = argparse.ArgumentParser(description="Device Shadow sample keeps a property in sync across client and server")

    parser.add_argument('--endpoint', required=True, help="Your AWS IoT custom endpoint, not including a port. Ex: \"w6zbse3vjd5b4p-ats.iot.us-west-2.amazonaws.com\"")
    parser.add_argument('--port', default="8883", help="Endpoint port")
    parser.add_argument('--cert', required=True, help="File path to your client certificate, in PEM format")
    parser.add_argument('--key', required=True, help="File path to your private key file, in PEM format")
    parser.add_argument('--client-id', default="test-" + str(uuid.uuid4()), help="Client ID for MQTT connection.")

    return parser.parse_args()

if __name__ == '__main__':
    g_args = parse_args()

    print(f"args: {g_args}")

    print(f"Endpoint: {g_args.endpoint}")
    print(f"Port: {g_args.port}")
    print(f"Cert Path: {g_args.cert}")
    print(f"Key Path: {g_args.key}")
    print(f"Client ID: {g_args.client_id}")

    connect(g_args.client_id, g_args.endpoint, g_args.port, g_args.cert, g_args.key)
