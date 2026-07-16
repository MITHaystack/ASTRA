"""
    astra-mqtt2db.py

    This software collects data from a set of MQTT telmetry streams which contain JSON 
    objects. The objects are assumed to be telemetry from the RP2040 with time stamps
    added during the collection process. The resulting objects are pushed into a MongoDB
    database as timeseries objects. For each object type an instantaneous state object
    is also maintained and updated when a new state change is detected. Logging from
    the MQTT log stream is also handled with options for both database and local
    logging via loguru. 

"""
import asyncio
import argparse
import os
import sys
import socket
import traceback
import serial
import json
import time
from datetime import datetime, timezone

from loguru import logger
import aiomqtt

from pymongo import AsyncMongoClient


"""
    Connects to the MQTT feed for telemetry from the ASTRA Antenna Interface. Pulls in the JSON
    telemetry objects and sends them to the telemetryQ for database ingestion. Telemetry is 
    handled as a time series database. 
"""
async def telemetry_mqtt_handler(options, telemetryQ, logQ, telemetry_period):

    while True:
        if options.verbose:
            print("update telemetry mqtt handler")

        # create MQTT connection to the local nanomq server
        try:
            async with aiomqtt.Client(hostname=options.mqtt, port=1883, keep_alive=600, reconnect=True) as mqtt_client:
                await mqtt_client.subscribe("astra/ai/telemetry/#")

                tdata = None
                try:
                    async for message in mqtt_client.messages():
                        if message is not None:
                            tdata = json.loads(message.payload.decode('utf-8'))
                            await telemetryQ.put(tdata)
                        if options.verbose:
                            print("got telemetry: ", message)
                except aiomqtt.ConnectError as err:
                    if options.verbose:
                        print(f"Connection lost; Reconnect attempt every {telemetry_period} seconds ...")
                    status = {'event':'exception', 'source':'telemetry_mqtt_handler', 'value':f"mqtt connection lost {err}"}
                    await logQ.put(status)
                    continue
                except json.JSONDecodeError as err:
                    if options.verbose:
                        print(f"Problem decoding json command object, {message}")
                    status = {'event':'exception', 'source':'telemetry_mqtt_handler', 'value':f"json decode problem {err}"}
                    await logQ.put(status)
                    continue
                except Exception as err:
                    print(f"exception in command handler {err}")
   
                status = {'event':'status', 'source':'telemetry_mqtt_handler', 'value':f"dispatched {tdata}"}
                await logQ.put(status)

                if options.verbose:
                    print(status)

        except Exception as err:
            print(f"telemetry loop global exception {err}")
            pass

        await asyncio.sleep(telemetry_period)

"""
    Connects to the MQTT feed for state information from the ASTRA Antenna Interface. Pulls in the JSON
    state objects and sends them to the stateQ for database ingestion. State information is treated as
    a updating object and not a time series. 
"""
async def state_mqtt_handler(options, stateQ, logQ, state_period):

    while True:
        if options.verbose:
            print("update state mqtt handler")

        # create MQTT connection to the local nanomq server
        try:
            async with aiomqtt.Client(hostname=options.mqtt, port=1883, keep_alive=600, reconnect=True) as mqtt_client:
                await mqtt_client.subscribe("astra/ai/state/#")

                tdata = None
                try:
                    async for message in mqtt_client.messages():
                        if message is not None:
                            sdata = json.loads(message.payload.decode('utf-8'))
                            await stateQ.put(sdata)
                        if options.verbose:
                            print("got state: ", message)
                except aiomqtt.ConnectError as err:
                    if options.verbose:
                        print(f"Connection lost; Reconnect attempt every {state_period} seconds ...")
                    status = {'event':'exception', 'source':'state_mqtt_handler', 'value':f"mqtt connection lost {err}"}
                    await logQ.put(status)
                    continue
                except json.JSONDecodeError as err:
                    if options.verbose:
                        print(f"Problem decoding json command object, {message}")
                    status = {'event':'exception', 'source':'state_mqtt_handler', 'value':f"json decode problem {err}"}
                    await logQ.put(status)
                    continue
                except Exception as err:
                    print(f"exception in command handler {err}")
   
                status = {'event':'status', 'source':'state_mqtt_handler', 'value':f"dispatched {sdata}"}
                await logQ.put(status)

                if options.verbose:
                    print(status)

        except Exception as err:
            print(f"state loop global exception {err}")
            pass

        await asyncio.sleep(state_period)

"""
    Connects to the MQTT feed for long information from the ASTRA Antenna Interface. Pulls in the JSON
    log objects and sends them to the logQ for loguru output. Long information is treated as a non
    database object but this allows for log centralization. 
"""
async def log_mqtt_handler(options, logQ, log_period):

    while True:
        if options.verbose:
            print("update log mqtt handler")

        # create MQTT connection to the local nanomq server
        try:
            async with aiomqtt.Client(hostname=options.mqtt, port=1883, keep_alive=600, reconnect=True) as mqtt_client:
                await mqtt_client.subscribe("astra/ai/state/#")

                tdata = None
                try:
                    async for message in mqtt_client.messages():
                        if message is not None:
                            ldata = json.loads(message.payload.decode('utf-8'))
                            await logQ.put(ldata)
                        if options.verbose:
                            print("got state: ", message)
                except aiomqtt.ConnectError as err:
                    if options.verbose:
                        print(f"Connection lost; Reconnect attempt every {log_period} seconds ...")
                    status = {'event':'exception', 'source':'state_mqtt_handler', 'value':f"mqtt connection lost {err}"}
                    await logQ.put(status)
                    continue
                except json.JSONDecodeError as err:
                    if options.verbose:
                        print(f"Problem decoding json command object, {message}")
                    status = {'event':'exception', 'source':'state_mqtt_handler', 'value':f"json decode problem {err}"}
                    await logQ.put(status)
                    continue
                except Exception as err:
                    print(f"exception in command handler {err}")
   
                status = {'event':'status', 'source':'state_mqtt_handler', 'value':f"dispatched {ldata}"}
                await logQ.put(status)

                if options.verbose:
                    print(status)

        except Exception as err:
            print(f"state loop global exception {err}")
            pass

        await asyncio.sleep(log_period)

""" 
    Accepts telemetry message objects from the telemtryQ and then adds them to the
    database as timeseries objects sorted by object type. 
"""
async def telemetry_db_handler(options, telemetryQ, logQ, telemetry_period):

    while True:

        if options.verbose:
            print("update telemetry db handler")

        try:
            tdata = telemetryQ.get_nowait()
            
            if tdata is not None:
                match tdata['event']:
                    case 'gps-data':
                        pass
                    case 'imu-data':
                        pass
                    case 'motion-data':
                        pass
                    case _:
                        if options.verbose:
                            print(f"unknown log event {msg}")
            else:
                tdata = None

            if options.verbose:
                print("telemetry object: ", tdata) 

        except Exception as e:
            if options.verbose:
                print(f"telemetry db exception {e}")
            else:
                pass

        await asyncio.sleep(telemetry_period)


""" 
    Accepts state message objects from the stateQ and then adds them to the
    database as updated objects sorted by object type. 
"""
async def state_db_handler(options, stateQ, logQ, state_period):

    while True:

        if options.verbose:
            print("update state db handler")

        try:
            sdata = stateQ.get_nowait()
            
            if sdata is not None:
                match sdata['event']:
                    case 'ai-display-state':
                        pass
                    case 'ai-diode-state':
                        pass
                    case 'ai-command-state':
                        pass
                    case _:
                        if options.verbose:
                            print(f"unknown log event {msg}")
            else:
                tdata = None

            if options.verbose:
                print("telemetry object: ", tdata) 

        except Exception as e:
            if options.verbose:
                print(f"state db exception {e}")
            else:
                pass

        await asyncio.sleep(state_period)


""" 
    Accepts log message objects from the logging Q and then outputs them sorted by
    log level to a loguru instance. Note there will be both local and remote timestamps. 
"""
async def log_handler(options, logQ, l_log, log_period):

    while True:

        if options.verbose:
            print("update log handler")

        try:
            ldata = logQ.get_nowait()
            
            if ldata is not None:
                msg = f"{ldata['source']({ldata['datetime_utc']}):ldata['value']}"
                match ldata['event']:
                    case 'exception' | 'error':
                        l_log.error(msg)
                    case 'warning':
                        l_log.warning(msg)
                    case 'status' | 'success':
                        l_log.success(msg)
                    case 'info':
                        l_log.info(msg)
                    case 'debug':
                        l_log.debug(msg)
                    case _:
                        if options.verbose:
                            print(f"unknown log event {msg}")
            else:
                ldata = None

            if options.verbose:
                print("log object: ", ldata) 

        except Exception as e:
            print(f"log handler exception {e}")

        await asyncio.sleep(log_period)



def parse_command_line():
    scriptname = os.path.basename(sys.argv[0])

    formatter = argparse.RawDescriptionHelpFormatter(scriptname)
    width = formatter._width

    title = "astra-mqtt2db.py"
    copyright = "Copyright (c) 2026 Massachusetts Institute of Technology"
    shortdesc = "Handle MQTT JSON object telemetry from the ASTRA antenna interface and send to database."
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
        "--dbase",
        dest="database",
        default="mongodb://localhost:27017/",
        help=(
            "The MongoDB database used for storage of the telemetry timeseries and state."
        ),
    )
    
    parser.add_argument(
        "-m",
        "--mqtt",
        dest="mqtt",
        default="localhost",
        help=(
            "The mqtt device IP associated with the antenna interface unit streams."
        ),
    )

    parser.add_argument(
        "-l",
        "--log",
        dest="log",
        default=None,
        help=(
            "The path for loguru logging of the Log telemetry."
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
    print("astra-mqtt2db startup")

    # Parse the Command Line for configuration
    options = parse_command_line()

    print("create async control")
    telemetryQ = asyncio.queue.Queue()
    stateQ = asyncio.queue.Queue()
    logQ = asyncio.queue.Queue()

    # create Database client
    db_client = AsyncMongoClient("mongodb://localhost:27017/")

    # create local logging
    print("setup logging")
    logger.remove()
    if options.log is not None:
        logger.add(f"{options.log}/astra-ai-mqtt.log", enqueue=True, level="INFO", rotation="8MB")

    print("set update periods")
    # set update periods in seconds
    log_period = 0.1
    telemetry_period = 0.1
    state_period = 0.1
     
    print("activate interfaces")
    telemetry_input_handler = telemetry_mqtt_handler(options, telemetryQ, logQ, telemetry_period)
    state_input_handler = state_mqtt_handler(options, stateQ, logQ, state_period)
    log_input_handler = log_mqtt_handler(options,logQ,log_period)

    telemetry_update_handler = telemetry_db_handler(options,telemetryQ,logQ,db_client,telemetry_period)    
    state_update_handler = state_db_handler(options,stateQ,logQ,db_client,state_period)    
    log_output_handler   = log_handler(options,logQ,logger,log_period)    
 
    print("setup asyncio tasks")
    clients = [asyncio.create_task(telemetry_input_handler)]
    clients.append(asyncio.create_task(state_input_handler))
    clients.append(asyncio.create_task(log_input_handler))
    clients.append(asyncio.create_task(telemetry_update_handler)) 
    clients.append(asyncio.create_task(state_update_handler))
    clients.append(asyncio.create_task(log_output_handler))
 
    print("run")

    await asyncio.gather(*clients)


asyncio.run(main())