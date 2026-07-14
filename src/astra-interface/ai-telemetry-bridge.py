"""
    ai-telemetry-bridge.py

    This software bridges the ASTRA Antenna Interface telemetry from the RP2040 to 
    other end points. The service receives telemetry over the USB CDC interface, 
    maintains a telemetry object state for the system and pushes it to an MQTT pubsub 
    (via nanomq)for immedate usage, debugging, and database ingestion. 

"""
import asyncio
import argparse
import os
import sys
import traceback
import serial
import json
import time
from datetime import datetime, timezone

import aiomqtt

"""
    Telemetry from the serial handler is routed to the MQTT 'astra/ai/telmetry/<event_type>' channel.

    Expected <event_type> keys include 'imu-data', 'gps-data'. Other types are logging or exception messages which 
    should end up on the logging MQTT channels. This is an implict scheme driven by the rp2040 embedded software design. 
"""
async def telemetry_mqtt_handler(options, telemetryQ, logQ, telemetry_period):

    # create MQTT connection to the local nanomq server
    mqtt_client = aiomqtt.Client(hostname=options.mqtt, port=1883, keep_alive=600, reconnect=True)


    while True:

        if options.verbose:
            print("update telemetry handler")

        try:
            tdata = telemetryQ.get_nowait()
            
            if tdata is not None:
                tdata_json = json.dumps(tdata)
            else:
                tdata_json = None

            if options.verbose:
                print("telemetry object: ", tdata_json) 
            try:
                async with mqtt_client:
                    evt = tdata['event']
                    await mqtt_client.publish(f"astra/ai/telemetry/{evt}", payload=tdata_json.encode('utf-8'))
                    if options.verbose:
                        print("telemetry object sent to mqtt")

            except aiomqtt.ConnectError as err:
                if options.verbose:
                    print(f"Connection lost; Reconnect attempt every {telemetry_period} seconds ...")
                
                status = {'event':'error', 'source':'telemetry_mqtt_handler', 'value':f"mqtt connection lost {err}"}
                await logQ.put(status)

                await asyncio.sleep(1)
            except Exception as e:
                print(f"telemetry exception {e}")

            status = {'event':'status', 'source':'telemetry_mqtt_handler', 'value':f"dispatched {tdata['event']}"}
            await logQ.put(status)

            if options.verbose:
                print(status)

        except Exception as e:
            pass

        await asyncio.sleep(telemetry_period)

"""
    State machine info from the serial handler is routed to the MQTT 'astra/ai/state/<event_type>' channel. States 
    generally change in response to commands issued to the end point device. 

    Expected <event_type> keys include 'display-state', 'command-state' and 'diode-state' used for internal state machine
    tracking of operations and configuration. Other types are telemetry and logging or exception messages which should 
    end up on the associated telmetry or logging MQTT channels. This is an implict schema driven by the rp2040 embedded
    software design. 

"""
async def state_mqtt_handler(options, stateQ, logQ, state_period):

    # create MQTT connection to the local nanomq server
    mqtt_client = aiomqtt.Client(hostname=options.mqtt, port=1883, keep_alive=600, reconnect=True)


    while True:
        if options.verbose:
            print("update state handler")

        try:
            sdata = stateQ.get_nowait()
            
            if sdata is not None:
                sdata_json = json.dumps(sdata)
            else:
                sdata_json = None

            if options.verbose:
                print("state object: ", sdata_json)

            try:
                async with mqtt_client:
                    evt = sdata['event']
                    await mqtt_client.publish(f"astra/ai/state/{evt}", payload=sdata_json.encode('utf-8'))
                    if options.verbose:
                        print("state object sent to mqtt")

            except aiomqtt.ConnectError as err:
                if options.verbose:
                    print(f"Connection lost; Reconnect attempt every {state_period} seconds ...")      
                status = {'event':'exception', 'source':'state_mqtt_handler', 'value':f"mqtt connection lost {err}"}
                await logQ.put(status)
                await asyncio.sleep(1)
                continue

            status = {'event':'status', 'source':'state_mqtt_handler', 'value':f"dispatched {sdata['event']}"}
            await logQ.put(status)

            if options.verbose:
                print(status)

        except:
            pass

        await asyncio.sleep(state_period)

"""
    Log info from the serial handler is routed to the MQTT 'astra/ai/log/<event type>' channel. 

    Expected types include 'exception', 'status', 'info'
"""
async def log_mqtt_handler(options, logQ, log_period):

    # create MQTT connection to the local nanomq server
    mqtt_client = aiomqtt.Client(hostname=options.mqtt, port=1883, keep_alive=600, reconnect=True)


    while True:
        if options.verbose:
            print("update log handler")
        try:
            ldata = logQ.get_nowait()

            if ldata is not None:
                ldata_json = json.dumps(ldata)
            else:
                ldata_json = None

            if options.verbose:
                print("log object: ", ldata_json)

            try:
                async with mqtt_client:
                    evt = ldata['event']
                    await mqtt_client.publish(f"astra/ai/log/{evt}", payload=ldata_json.encode('utf-8'))
                    if options.verbose:
                        print("log object sent to mqtt")

            except aiomqtt.ConnectError as err:
                if options.verbose:
                    print(f"Connection lost {err}; Reconnect attempt every {log_period} seconds ...")
                status = {'event':'exception', 'source':'log_mqtt_handler', 'value':f"mqtt connection lost {err}"}
                await logQ.put(status)
               
                await asyncio.sleep(1)
                continue


            status = {'event':'status', 'source':'log_mqtt_handler', 'value':f"dispatched {ldata['event']}"}
            await logQ.put(status)

            if options.verbose:
                print(status)

        except Exception as e:
            pass

        await asyncio.sleep(log_period)

"""
    Commands come in from the associated mqtt channel 'ai-command' and
    are routed to the serial handler. 
"""
async def command_mqtt_handler(options, eventQ, logQ, cmd_period):

    while True:
        if options.verbose:
            print("update command handler")

        # create MQTT connection to the local nanomq server
        try:
            async with aiomqtt.Client(hostname=options.mqtt, port=1883, keep_alive=600, reconnect=True) as mqtt_client:
                await mqtt_client.subscribe("astra/ai/command")

                cmd = None
                try:
                    async for message in mqtt_client.messages():
                        if message is not None:
                            cmd = json.loads(message.payload.decode('utf-8'))
                            await eventQ.put(cmd)
                        if options.verbose:
                            print("sent command: ", message)
                except aiomqtt.ConnectError as err:
                    if options.verbose:
                        print(f"Connection lost; Reconnect attempt every {cmd_period} seconds ...")
                    status = {'event':'exception', 'source':'command_mqtt_handler', 'value':f"mqtt connection lost {err}"}
                    await logQ.put(status)
                    continue
                except json.JSONDecodeError as err:
                    if options.verbose:
                        print(f"Problem decoding json command object, {cmd}")
                    status = {'event':'exception', 'source':'command_mqtt_handler', 'value':f"json decode problem {err}"}
                    await logQ.put(status)
                    continue
                except Exception as err:
                    print(f"exception in command handler {err}")
   
                status = {'event':'status', 'source':'command_mqtt_handler', 'value':f"dispatched {cmd}"}
                await logQ.put(status)

                if options.verbose:
                    print(status)

        except Exception as err:
            print(f"command loop global exception {err}")
            pass


        await asyncio.sleep(cmd_period)




"""
    The serial communications thread takes telemetry and log information and outputs it
    to the MQTT data interface. Incoming data are also read in a single line format
    and the associated command is converted from a json to python object and queued for
    handling. This is a little inefficent but opens up object validation or more direct
    filtering and usage. 
"""
async def communications_handler(options, telemetryQ, stateQ, eventQ, logQ, com_period):
    # no initial connection
    usb_serial = None
    event_cnt = 0

    while True:
        if options.verbose:
            print("update communications handler")

        if usb_serial is None:
            try:
                usb_serial = serial.Serial(options.dev, timeout = 1.0)
            except (serial.SerialException, EOFError) as e:
                usb_serial = None
                asyncio.sleep(0.1)
                continue
            except Exception as e:
                print(f"Exception not expected {e}")
                asyncio.sleep(0.1)
                continue 

        # send command if available
        # outgoing commands to the RP2040 
        try:
            cmd = eventQ.get_nowait()
            if cmd is not None:
                cmd_json = json.dumps(cmd)
                usb_serial.write(cmd_json.encode('utf-8'))
                usb_serial.write("\n".encode('utf-8'))
        except (serial.SerialException, EOFError) as e:
                if options.verbose:
                    print("serial exception EOF error, attempt reconnect")
                asyncio.sleep(0.1)
                usb_serial = None
                continue
        except Exception as e:
            pass

        # get serial json objects and split into telmetry, state, and log information streams
         # grab line from the serial port
        try:
            line = usb_serial.readline()
        except (serial.SerialException, EOFError) as e:
                asyncio.sleep(0.1)
                usb_serial = None
                continue
        except Exception as e:
            if options.verbose:
                print("problem reading serial line")
                print(e)
            else:
                pass

        event = None
        try:
            event = json.loads(line.decode("utf-8").rstrip())
            event_cnt += 1
        except:
            if options.verbose:
                print(f"problem parsing json from line : {line}")
            else:
                pass
        

        # add a timestamp locally since the RP2040 doesn't really
        # maintain a clock. The GPS provided time only exists for the
        # GPS telemetry. We are going to assume the the NTP based time
        # for ASTRA is available and better. 
        if event is not None:
            utc_timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            try:
                event['datetime_utc'] = utc_timestamp
            except Exception as e:
                if options.verbose:
                    print(f"problem creating utc timestamp {e}")
                else:
                    pass

        if options.verbose and event is not None:
            print(f"event {event_cnt} : {event}")
        elif options.verbose and event is None:
            print("event is None")

        try:
            if event is not None:
                match event['event']:
                    case 'ai-gps-data' | 'ai-imu-data':
                        #print("dispatch to telemetryQ")
                        await telemetryQ.put(event)
                    case 'ai-command-state' | 'ai-display-state' | 'ai-diode-state':
                        #print("dispatch to stateQ")
                        await stateQ.put(event)
                    case 'exception' | 'status' | 'info':
                        #print("dispatch to logQ")
                        await logQ.put(event)
                    case _:
                        if options.verbose:
                            print(f"unknown event {event}")

        except Exception as e:
            if options.verbose:
                print(e)
            else:
                pass


        await asyncio.sleep(com_period)




def parse_command_line():
    scriptname = os.path.basename(sys.argv[0])

    formatter = argparse.RawDescriptionHelpFormatter(scriptname)
    width = formatter._width

    title = "rp-telemetry-bridge.py"
    copyright = "Copyright (c) 2026 Massachusetts Institute of Technology"
    shortdesc = "Handle telemetry from the ASTRA antenna interface unit connected via USB and send to MQTT."
    desc = "\n".join(
        (
            "*" * width,
            "*{0:^{1}}*".format(title, width - 2),
            "*{0:^{1}}*".format(copyright, width - 2),
            "*{0:^{1}}*".format("", width - 2),
            "*{0:^{1}}*".format(shortdesc, width - 2),
            "*" * width,
        )
    )

    parser = argparse.ArgumentParser(
        description=desc,
        prefix_chars="-",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "-d",
        "--dev",
        dest="dev",
        default="/dev/ttyACM2",
        help=(
            "The serial device associated with the antenna interface unit."
        ),
    )
    
    parser.add_argument(
        "-m",
        "--mqtt",
        dest="mqtt",
        default="127.0.0.1",
        help=(
            "The mqtt device IP associated with the antenna interface unit."
        ),
    )


    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        dest="verbose",
        default=False,
        help="Makes the output information more verbose.",
    )

    options = parser.parse_args()

    return options


"""
    Primary Thread Startup 
"""
async def main():
    print("ai-telemetry-bridge startup")

    # Parse the Command Line for configuration
    options = parse_command_line()

    print("create async control")
    eventQ = asyncio.Queue()
    telemetryQ = asyncio.Queue()
    stateQ = asyncio.Queue()
    logQ = asyncio.Queue()


    print("set update periods")
    # set update periods in seconds
    com_period = 0.05
    log_period = 0.1
    telemetry_period = 0.05
    state_period = 0.1
    cmd_period = 0.1
     
    print("activate interfaces")
    comm_handler = communications_handler(options, telemetryQ, stateQ, eventQ, logQ, com_period)
    telemetry_handler = telemetry_mqtt_handler(options,telemetryQ,logQ,telemetry_period)    
    state_handler = state_mqtt_handler(options,stateQ,logQ,state_period)    
    log_handler   = log_mqtt_handler(options,logQ,log_period)    
    command_handler = command_mqtt_handler(options,eventQ,logQ,cmd_period)    

    print("setup asyncio tasks")
    clients = [asyncio.create_task(comm_handler)]
    clients.append(asyncio.create_task(telemetry_handler))
    clients.append(asyncio.create_task(state_handler))
    clients.append(asyncio.create_task(log_handler))
    clients.append(asyncio.create_task(command_handler))
 
    print("run")

    await asyncio.gather(*clients)


asyncio.run(main())