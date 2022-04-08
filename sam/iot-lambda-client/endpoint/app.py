##########################################################################################
#
#  Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#  SPDX-License-Identifier: MIT-0
#
#  Permission is hereby granted, free of charge, to any person obtaining a copy of this
#  software and associated documentation files (the “Software”), to deal in the Software
#  without restriction, including without limitation the rights to use, copy, modify,
#  merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
#  permit persons to whom the Software is furnished to do so.
#
#  THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
#  INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
#  PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
#  HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
#  OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
#  SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#
##########################################################################################

from asyncio import events
import json
import uuid
from awscrt import io, mqtt, auth, http
from awsiot import mqtt_connection_builder
import time
from datetime import datetime
import os
import sys
import threading

g_client_id_prefix = ""
g_endpoint = ""

g_message_ack_topic_prefix = ""
g_message_topic_prefix = ""

g_received_count = 0

g_is_ack_received = False
g_message_id = None
g_device_response = None

g_timeout = 10


def get_milliseconds():
    return round(time.time() * 1000)

# Callback when the subscribed topic receives a message
def on_message_received(topic, payload, dup, qos, retain, **kwargs):
    print(f"Received message from topic '{topic}': {payload}")

    global g_is_ack_received
    global g_message_id
    global g_device_response

    obj = json.loads(payload)

    g_is_ack_received = False
    g_device_response = None

    if ('response' in obj.keys()) and (not obj['response'] == None):
        g_device_response = obj['response']

    # Ack as last thing for concurrency
    if ('id' in obj.keys()) and (obj['id'] == g_message_id):
        g_is_ack_received = True


def do_request(p_method, p_request, p_timeout):
    ts_start = get_milliseconds()

    global g_is_ack_received
    global g_endpoint
    global g_client_id_prefix

    g_is_ack_received = False

    print(
        f"Performing request '{p_request}' for method '{p_method}' with timeout '{p_timeout}'")

    event_loop_group = io.EventLoopGroup(1)
    host_resolver = io.DefaultHostResolver(event_loop_group)
    client_bootstrap = io.ClientBootstrap(event_loop_group, host_resolver)
    credentials_provider = auth.AwsCredentialsProvider.new_default_chain(client_bootstrap)
    proxy_options = None

    ################################################################################
    #  Create & Connect Client

    mqtt_client_id = f"{g_client_id_prefix}_{g_message_id}"

    print(f"Client ID: '{mqtt_client_id}'")

    mqtt_connection = mqtt_connection_builder.websockets_with_default_aws_signing(
                endpoint=g_endpoint,
                client_bootstrap=client_bootstrap,
                region=g_region,
                credentials_provider=credentials_provider,
                http_proxy_options=proxy_options,
                client_id=mqtt_client_id,
                clean_session=False,
                keep_alive_secs=30)

    connect_future = mqtt_connection.connect()
    connect_future.result()

    print("Connected!")

    ################################################################################
    # Subscribe to Topic

    message_ack_topic = f"{g_message_ack_topic_prefix}"

    print(f"Subscribing to topic '{message_ack_topic}'...")
    subscribe_future, packet_id = mqtt_connection.subscribe(
        topic=message_ack_topic,
        qos=mqtt.QoS.AT_LEAST_ONCE,
        callback=on_message_received)

    subscribe_result = subscribe_future.result()
    print("Subscribed with {}".format(str(subscribe_result['qos'])))

    ################################################################################
    # Send Command

    message = {
        "timestamp": str(get_milliseconds()),
        "request": p_request,
        "id": g_message_id
    }

    message_json = json.dumps(message)

    message_topic = f"{g_message_topic_prefix}"

    print(f"Publishing message '{message_json}' on topic '{message_topic}'")

    mqtt_connection.publish(
        topic=message_topic,
        payload=message_json,
        qos=mqtt.QoS.AT_MOST_ONCE)

    ################################################################################
    # Wait for ACK

    wtstart = get_milliseconds()
    is_timed_out = False
    while not (g_is_ack_received or is_timed_out):
        is_timed_out = (get_milliseconds() - wtstart) > (p_timeout * 1000)
        time.sleep(0.001)
    print(
        f"Waiting time: {get_milliseconds() - wtstart} ms, timeout: {p_timeout * 1000} ms")

    ################################################################################
    # Evaluate Response OR Timeout

    response = None

    print(f"Is Timed-Out: {is_timed_out}")
    print(f"Is ACK Received: {g_is_ack_received}")
    print(f"Device Response: {g_device_response}")

    if is_timed_out:
        response = {
            'statusCode': 500,
            'body': json.dumps({
                'result': 'timeout',
                'elapsed': str(get_milliseconds() - ts_start),
            }),
            'headers': {
                'Content-Type': 'application/json'
            }
        }
    elif g_is_ack_received:
        response = {
            'statusCode': 200,
            'body': json.dumps({
                'result': 'ok',
                'elapsed': str(get_milliseconds() - ts_start),
                'response': g_device_response
            }),
            'headers': {
                'Content-Type': 'application/json'
            }
        }
    else:
        response = {
            'statusCode': 500,
            'body': json.dumps({
                'result': 'internal_error',
                'elapsed': str(get_milliseconds() - ts_start),
            }),
            'headers': {
                'Content-Type': 'application/json'
            }
        }

    ################################################################################
    # Disconnect Client

    print("Disconnecting...")
    disconnect_future = mqtt_connection.disconnect()
    disconnect_future.result()
    print("Disconnected!")

    print(f"Process Elapsed: {get_milliseconds() - ts_start}")

    return response


def handler(event, context):

    global g_client_id_prefix
    global g_endpoint
    global g_message_ack_topic_prefix
    global g_message_topic_prefix
    global g_region
    
    g_client_id_prefix = os.environ.get("CLIENT_ID_PREFIX")
    g_endpoint = os.environ.get("WSS_ENDPOINT")
    g_region = os.environ.get("AWS_REGION")

    method = None
    request = None
    target = None
    timeout = None
    response = None

    print (f"Events: '{event}'")

    if ('queryStringParameters' in event.keys()):
        params = event['queryStringParameters']

        print (f"Params: '{params}'")

        if ('method' in params.keys()):
            method = params['method']

        if ('request' in params.keys()):
            request = params['request']

        if ('target' in params.keys()):
            target = params['target']

        if ('timeout' in params.keys()):
            try:
                param_timeout = params['timeout']
                timeout = int(param_timeout)
                if timeout <= 0 or timeout > 60:
                    print(
                        f"Timeout value value '{timeout}' is out of range (0-60), replace with default one")
                    timeout = g_timeout
            except:
                print(
                    f"Timeout value '{param_timeout}' is not a number, getting default one '{g_timeout}'.")
                timeout = g_timeout
        else:
            print("No timeout value passed, assuming default one")
            timeout = g_timeout

    if method != None and request != None and target != None:

        global g_message_id
        g_message_id = str(uuid.uuid4())

        print(f"Message ID: {g_message_id}")

        g_message_ack_topic_prefix = f"{g_client_id_prefix}/{g_message_id}/{target}/{method}/ack"
        g_message_topic_prefix     = f"{target}/{method}/{g_client_id_prefix}/{g_message_id}"

        print(f"Message topic: {g_message_topic_prefix}")
        print(f"ACK topic: {g_message_ack_topic_prefix}")

        response = do_request(method, request, timeout)
    else:
        response = {
            'statusCode': 500,
            'body': json.dumps({
                'result': 'invalid_parameters',
                'response': 'The \'method\' and/or \'request\' and/or \'target\' query parameters are missing!'
            }),
            'headers': {
                'Content-Type': 'application/json'
            }
        }

    print(f"Response: {response}")

    return response