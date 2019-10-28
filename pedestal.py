#!/usr/bin/python3

import lappd
import math
import sys
from scipy import stats

# Since I can just compute mean and variance
import statistics

#
# The pedestal system is a separate import,
# because maybe you don't want to take pedestals.
# 

import datetime

class pedestal(object):

    def __init__(self, samples):

        # Did we receive any samples?
        if not len(samples):
            raise Exception("Did not receive any samples!")
        
        # Some board information
        self.board_id = samples[0].board_id

        # Event sample from which the pedestal is constructed
        self.samples = samples

        # Use the first event to determine the list of channels
        self.chan_list = samples[0].channels.keys()

        # Sanity checks on the pedestal samples
        for sample in samples:
            
            if not isinstance(sample, lappd.event):
                raise Exception("Encountered non-event in list of samples.  Nonsense.")
            
            if not self.chan_list == sample.channels.keys():
                raise Exception("Provided sample events for pedestaling have inhomogeneous channel content.  This .... is ... U N A C C E P T A B L E E E E ---- U N A C C E P T A B L E E E E E E E")
            if not sample.keep_offset:
                raise Exception("Refusing to build pedestals with torn data (ROI mode)")
            
        # Set up for pedestals
        self.nobs = {}
        self.minmax = {}
        self.mean = {}
        self.variance = {}
        self.skewness = {}
        self.kurtosis = {}
        
        # Compute the pedestal
        for chan_id in self.chan_list:
            amplitude_lists = []
            for event in self.samples:
                amplitude_lists.append(event.channels[chan_id])

            # Now compute the pedestals
            self.nobs[chan_id], self.minmax[chan_id], self.mean[chan_id], self.variance[chan_id], self.skewness[chan_id], self.kurtosis[chan_id] = stats.describe(amplitude_lists)

            # Take the square root of the variance
            # But then its still called variance when its not...
            # self.variance = np.sqrt(self.variance)
                        
        # Remove the samples because python can't pickle it
        del(self.samples)
        del(self.chan_list)
    #
    # Mutate an event by subtracting off a pedestal
    #
    def subtract(self, event):

        # # Has the event been torn?
        # if not event.keep_offset:
        #     # It has, so we need to use the offset to
        #     # correctly pedestal
        #     adjust = lambda x,delta : if delta < 0 
        #     pass
        # else:
        for chan_id, amplitudes in event.channels.items():
            event.channels[chan_id] = [ (amplitudes[i] - self.mean[chan_id][i]) for i in range(0, len(self.mean[chan_id]))]
            
#
# Generate a test pedestal, with normally distributed event samples
#
def generatePedestal(resolution, chan_list, numsamples, scale):

    import random

    # Compute the maximum value pedestal in any channel for this set of events.
    # Since this is for pedestals, we don't want the channel useless
    # (a pedestal near saturation is useless)
    #
    # We set pedestals' offsets to be, at most 1/8 of the channel's dynamic range
    maxy = 1 << ((1 << resolution) - 3) - 1

    # Generate some random offsets
    base_amplitudes = {}
    for chan_id in chan_list:
        base_amplitudes[chan_id] = [random.randrange(maxy) for i in range(0, numsamples)]

    ampl_list = []
    for chan_id, base in base_amplitudes.items():

        # Make some new fluxes
        flux = stats.norm.rvs(size=numsamples, scale=scale)

        # Apply them to the base amplitudes
        ampl_list.append([math.floor( base[i] + flux[i]*base[i] ) for i in range(0, numsamples)])

    # Make a (zero-offsets) event that has these features
    # Amplitude list for generateEvent() needs to be order preserving, or else the zip() will get the orders
    # screwed up

    print("Pedestal: %d channels, with %d samples each @ %d-bit" % (len(chan_list), numsamples, 1 << resolution), file=sys.stderr)
    return lappd.event.generateEvent(555, resolution, chan_list, [0]*len(chan_list), ampl_list)

