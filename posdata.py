#!/usr/bin/env python3

import json
import moonraker_api
import asyncio
from async_timeout import timeout as asyncio_timeout
from typing import Any
import datetime
import csv
import time
import sys
import termios

class PrinterMotionData:
    def __init__(self, outfile, quiet = False):
        self.quiet = quiet
        self.outfile = outfile
        self.outh = open(self.outfile, "w")
        self.outcsv = csv.DictWriter(self.outh,
                                     ['filename', # name of the file being printed
                                      'rectime',  # unix timestamp in ns of record
                                      'time', 'origts', # time since print command, original timestamp
                                      'live_position_x',
                                      'live_position_y',
                                      'live_position_z',
                                      'live_position_e', # extruder position
                                      'live_velocity'])
        self.outcsv.writeheader()

        self.filename = None
        self.print_state = None
        self.time_offset = None

    def close(self):
        self.outh.close()

    def motion_report(self, timestamp, data):
        if self.time_offset is not None:
            pos = data.get('live_position', None)
            if pos is None:
                x, y, z, e = None, None, None, None
            else:
                x, y, z, e = pos

            row = {'filename': self.filename or 'unknown',
                   'rectime': time.time_ns(),
                   'time': timestamp + self.time_offset,
                   'origts': timestamp,
                   'live_position_x': x,
                   'live_position_y': y,
                   'live_position_z': z,
                   'live_position_e': e,
                   'live_velocity': data.get('live_velocity', None)
            }
            if not self.quiet:
                print(row)

            self.outcsv.writerow(row)

        return True

    def print_stats(self, timestamp, data):
        if 'state' in data:
            # changes from printing, cancelled,paused,etc.
            self.print_state = data['state']
            print(f"Print state changed to {self.print_state}", file=sys.stderr)
            self.outh.flush()

        if 'filename' in data:
            # only set when the file is first selected
            # repeat prints do not set the filename
            self.filename = data['filename']
            print(f"Print file changed to {self.filename}", file=sys.stderr)

        if self.time_offset is None and 'total_duration' in data:
            # might want to average this or something
            self.time_offset = data['total_duration'] - timestamp
            print(f"Set time_offset to {self.time_offset}, gather position data enabled", file=sys.stderr)

class PrinterStatus(moonraker_api.MoonrakerListener):
    def __init__(self, host, port, pmd, api_key = ""):
        self.running = False
        self.pmd = pmd
        self.client = moonraker_api.MoonrakerClient(
            self,
            host,
            port,
            api_key,
        )

    async def start(self) -> None:
        """Start the websocket connection."""
        self.running = True
        return await self.client.connect()

    async def stop(self) -> None:
        """Stop the websocket connection."""
        self.running = False
        await self.client.disconnect()

    async def on_notification(self, method: str, data: Any) -> None:
        """Notifies of state updates."""

        # Subscription notifications
        if method == "notify_status_update":
            message, timestamp = data
            #print(timestamp, message)

            for k in message:
                if k == "motion_report":
                    self.pmd.motion_report(timestamp, message[k])
                elif k == "print_stats":
                    self.pmd.print_stats(timestamp, message[k])
                else:
                    print(f"ERROR: {timestamp}: Notification {k} is not handled", file=sys.stderr)
                    raise NotImplementedError(f"{timestamp}: Notification {k} is not handled")
        else:
            print(f"ERROR: {timestamp}: Notification method {method} is not handled", file=sys.stderr)
            raise NotImplementedError(f"Notification method '{method}' not handled")

    async def wait_for_klippy(self):
        while True:
            r = await self.client.get_klipper_status()
            if r == "ready": return True

    async def get_toolhead_status(self):
        r = await self.client.call_method('printer.objects.query', objects={'toolhead': None})
        return r['status']['toolhead']

    async def initialize(self):
        self.objects_list = (await self.client.call_method('printer.objects.list'))['objects']

    def subscribe(self, objects):
        obj = {}
        for o in objects:
            if o not in self.objects_list:
                raise ValueError(f"{o} is not in printer.objects.list")

            obj[o] = None

        return self.client.call_method('printer.objects.subscribe', objects=obj)

    def cancel_subscriptions(self):
        return self.client.call_method('printer.objects.subscribe', objects={})

class ReadkeyWithTimeout:
    def __init__(self, timeout_ds = 1):
        self.timeout = timeout_ds

    async def readkey(self):
        fd = sys.stdin.fileno()
        prev = termios.tcgetattr(fd)

        # stolen from:
        # https://stackoverflow.com/questions/66056513/async-io-reading-char-from-input-blocks-output
        # and the implementation of readchar.readchar
        #
        # obviously only works on POSIX.

        term = termios.tcgetattr(fd)

        try:
            term[3] &= ~(termios.ICANON | termios.ECHO) # | termios.IGNBRK | termios.BRKINT)
            term[6][termios.VMIN] = 0
            term[6][termios.VTIME] = self.timeout # 100 milliseconds or 1 decisecond
            termios.tcsetattr(fd, termios.TCSAFLUSH, term)

            ch = ''
            while ch == '':
                ch = sys.stdin.read(1)
                await asyncio.sleep(0)

        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, prev)

        return ch

async def main():
    import argparse
    p = argparse.ArgumentParser(description="Dump printer location data from Klipper using the Moonraker API into a CSV file")
    p.add_argument("host", help="Hostname")
    p.add_argument("port", type=int, help="Port")
    p.add_argument("output", help="Output file")
    p.add_argument("-q", dest="quiet", action="store_true", help="Quiet output")

    args = p.parse_args()

    ms = PrinterStatus(args.host, args.port, pmd=PrinterMotionData(args.output, quiet=args.quiet))
    await ms.start()

    try:
        async with asyncio_timeout(10):
            await ms.wait_for_klippy()

        print("Klipper ready")
    except TimeoutError:
        print("ERROR: Klippy isn't ready.")
        await ms.stop()
        await ms.client.session.close()
        return

    await ms.initialize()
    th = await ms.get_toolhead_status()
    if th['homed_axes'] != 'xyz':
        print("WARNING: Printer does not appear to be homed. Location data may be incorrect!")

    print("Subscribing to motion data and print stats")
    await ms.subscribe(['motion_report', 'print_stats'])
    print("Listening for motion data and print stats")
    print("press Q to quit")

    rc = ReadkeyWithTimeout()

    while True:
        k = await rc.readkey()
        if k == "q" or k == "Q":
            break

    print("Cancelling subscriptions")
    await ms.cancel_subscriptions()
    print("Waiting for any pending notifications to be handled")
    await asyncio.sleep(2) # hacky, no guarantee everything is done
    print(f"Closed output file {ms.pmd.outfile}")
    ms.pmd.close()

    await ms.stop()
    await ms.client.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
