#!/usr/bin/python3

import sys
import os

# Do not ask me why this needs to be included now...
sys.path.append("./eevee")
os.environ['EEVEE_SRC_PATH'] = "./eevee"

import eevee
import lappd
import multiprocessing
import pickle
import queue
import argparse
import socket
import time

#
# Utility function to dump a pedestal subtracted event
# Note that it MUTATES the events!!
#
def dump(event):
    # # Dump the entire detection in ASCII
    print("# event number = %d\n# y_max = %d" % (event.evt_number, (1 << ((1 << event.resolution) - 1)) - 1))
    for channel, amplitudes in event.channels.items():
        print("# BEGIN CHANNEL %d\n# drs4_offset: %d" % (channel, event.offsets[channel]))
        for t, ampl in enumerate(amplitudes):
            print("%d %d %d" % (t, ampl, channel))
        print("# END OF CHANNEL %d (EVENT %d)" % (channel, event.evt_number))
        
    # End this detection (because \n, this will have an additional newline)
    print("# END OF EVENT %d\n" % event.evt_number)
    

#
# STEP 0 - parse command line arguments
#
##################################
parser = argparse.ArgumentParser(description='Get calibration data from Eevee boards speaking protocol MK01.')

parser.add_argument('board', metavar='IP_ADDRESS', type=str, help='IP address of the target board')
parser.add_argument('N', metavar='NUM_SAMPLES', type=int, help='The number of samples to request')
parser.add_argument('i', metavar='INTERVAL', type=float, help='The interval (seconds) between software triggers')

parser.add_argument('-p', '--pedestal', action="store_true", help='Take pedestals. (Automatically turns on -o)')
parser.add_argument('-s', '--subtract', metavar='PEDESTAL_FILE', type=str, help='Pedestal to subtract from incoming amplitude data')
parser.add_argument('-a', '--aim', metavar='UDP_PORT', type=int, default=1338, help='Aim the given board at the given UDP port on this machine. Defaults to 1338')
parser.add_argument('-l', '--listen', action="store_true", help='Passively listen at IP_ADDRESS for incoming data.  Interval and samples are ignored.')
parser.add_argument('-o', '--offset', action="store_true", help='Retain ROI channel offsets for incoming events.  (Order by capacitor, instead of ordering by time)')
parser.add_argument('-r', '--register', dest='registers', metavar='REGISTER', type=str, nargs=1, action='append', help='Peek and document the given register before listening for events')
parser.add_argument('-q', '--quiet', action="store_true", help='Do not write anything to stdout (useful for profiling)')
parser.add_argument('-e', '--external', action="store_true", help='Do not send software triggers (i.e. expect an external trigger)')

args = parser.parse_args()

# Simple sanity check
if not args.N > 0:
    raise Exception("Number of samples must be greater than 0")

if args.i < 0:
    raise Exception("Interval must be positive")

# If we are pedestalling, force persistent offsets
if args.pedestal:
    args.offset = True
    
#
# STEP 1 - get control connections
#
#######################################

listen_here = None

if args.listen:
    listen_here = '0.0.0.0'
else:
    # Open up a control connection
    board = eevee.board(args.board)

    # Aim the board at ourself
    #  This sets the outgoing data path port on the board to port
    #  And sets the destination for data path packets to port
    board.aimNBIC()
    
    # Convenience shortcut
    listen_here = board.s.getsockname()[0]

    #
    # If we are pedestalling, make sure that that the board is in full
    # readout mode
    # XXX Magic numbers... this needs to be standardized via an
    # This is LAPPD specific stuff now.
    # Very bad design practice.
    #                  
    readout_mode = board.peeknow(0x328)
    if args.pedestal:

        # Force full readout, if its not in there
        if(readout_mode < 1025):
            print("WARNING: Board was not in full readout (ROI set to %d).  Forcing..." % readout_mode, file=sys.stderr)
            board.pokenow(0x328, 1025)


#
# STEP 2 - fork an event reconstructor
#
########################################

# This forks (process) and returns a process safe queue.Queue.
# The fork listens for, and then reassembles, fragmented data
#
# Data is in the form of dictionaries, that have event header fields
# augmented with a list of channels that link to hits
#

# Required for multiprocess stuff
# Try using a manager to handle weird bottleneck?
eventQueue = multiprocessing.Queue(args.N)

# Since we are in UNIX, this will operate via a fork()
intakeProcess = None
if __name__ == '__main__':
    intakeProcess = multiprocessing.Process(target=lappd.intake, args=((listen_here, args.aim), eventQueue, args.offset, args.subtract))
    intakeProcess.start()
    
# The reconstructor will push an Exception object on the queue when the socket is open
# and ready to receive data.  Use the existing queue, so we don't need to make a new lock
if not isinstance(eventQueue.get(), Exception):
    raise Exception("First event received did not indicate permission to proceed. Badly broken.")

print("Lock passed, intake process is now listening...", file=sys.stderr)

#
# STEP 4 - pedestal the board
#
######################################

# Are we just listening?
if args.listen:
    while args.N > 0:
        try:
            # Grab an event
            event = eventQueue.get()

            # Output it
            print("Event %d:\n\tReconstruction time: %e seconds\n\tQueue delay: %e seconds" % (event.evt_number, event.finish - event.start, time.time() - event.prequeue), file=sys.stderr)

            if not args.quiet:
                dump(event)
                
            args.N -= 1

            # Explicitly free the memory
            eventQueue.task_done()
            del(event)
            
        except Exception as e:
            import traceback
            traceback.print_exc(file=sys.stderr)

# So we are not just listening, lets do something

events = []
import time

for i in range(0, args.N):
    # --- Note that these are magic numbers...
    if not args.external:
        # Suppress board readback and response!
        board.pokenow(0x320, (1 << 6), readback=False, silent=True) #, silent=True, readback=False)
    
    # Sleep for the specified delay
    time.sleep(args.i)

    # Add it to the event queue
    try:
        event = eventQueue.get(timeout=0.1)
        print("Received event %d" % (event.evt_number), file=sys.stderr)
        # Push it onto the processing queue
        events.append(event)

        # Output the ascii dump
        if not args.quiet:
            dump(event)
            
    except queue.Empty:
        print("Timed out (+100ms) on soft trigger %d." % i, file=sys.stderr)

# Should we build a pedestal with these events?
if args.pedestal:

    # BEETLEJUICE BEETLEJUICE BEETLEJUICE
    activePedestal = event.pedestal(events)

    # Write it out
    if len(events) > 0:
        pickle.dump(activePedestal, open("%s.pedestal" % events[0].board_id.hex(), "wb"))

    # Restore board state
    board.pokenow(0x328, readout_mode)

# If doing hardware triggers, the event queue is probably
# loaded with events
# Send the death signal to the child and wait for it
print("Sending interrupt signal to intake process (get out of recvfrom())...", file=sys.stderr)
from os import kill
from signal import SIGINT
kill(intakeProcess.pid, SIGINT)
intakeProcess.join()
