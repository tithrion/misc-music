#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# ZYNTHIAN PROJECT: Zynthian Control Device Driver
#
# Zynthian Control Device Driver for "Akai MPK 225"
#
# Copyright (C) 2024 Oscar Aceña <oscaracena@gmail.com> (Original MPK Mini Mk3)
#               2025 Steffen Klein <steffen@klein-network.de> (MPK 225 Adapter)
#
# ******************************************************************************
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 2 of
# the License, or any later version.
#
# ******************************************************************************

import time
import logging
from bisect import bisect

from zyncoder.zyncore import lib_zyncore
from zyngine.zynthian_signal_manager import zynsigman

from zyngine.ctrldev.zynthian_ctrldev_base import zynthian_ctrldev_zynmixer
from zyngine.ctrldev.zynthian_ctrldev_base_extended import CONST, KnobSpeedControl, IntervalTimer, ButtonTimer
from zyngine.ctrldev.zynthian_ctrldev_base_ui import ModeHandlerBase


# ------------------------------------------------------------------------------
# Akai MPK 225 MIDI controller
# ------------------------------------------------------------------------------
#
# IMPORTANT CONFIGURATION NOTE:
# Since we generally lack the Sysex documentation to programmatically configure
# the MPK 225, this driver assumes the device is manually configured to send
# specific CCs and Notes.
#
# EXPECTED HARDWARE MAPPING (Global / Generic Preset):
# 
# Knobs 1-8:       CC 24 - 31  (Absolute 0-127)
# Pads Bank A 1-8: Note 36 - 43 (C1 - G1)
# Pads Bank B 1-8: Note 44 - 51 (G#1 - D#2)
# Transport:       MMC or CC 115-119 (Driver listens to both if possible)
#                  Stop=116, Play=118, Rec=119
#
# ------------------------------------------------------------------------------

# General Constants
CONST.MIDI_NOTE_OFF = 0x80
CONST.MIDI_NOTE_ON = 0x90
CONST.MIDI_CC = 0xB0
CONST.MIDI_PC = 0xC0
CONST.MIDI_SYSEX = 0xF0

# Function/State constants
FN_VOLUME = 0x01
FN_PAN = 0x02
FN_SOLO = 0x03
FN_MUTE = 0x04
FN_SELECT = 0x06

# --------------------------------------------------------------------------
# 'Akai MPK 225' device controller class
# --------------------------------------------------------------------------
class zynthian_ctrldev_akai_mpk_225(zynthian_ctrldev_zynmixer):

    dev_ids = ["MPK225 IN 1"]
    driver_name = "Akai MPK 225"
    driver_description = "Full UI integration (Requires Manual Device Config)"
    unroute_from_chains = False
    autoload_flag = False

    def __init__(self, state_manager, idev_in, idev_out):
        self._mixer_handler = MixerHandler(state_manager, idev_out)
        self._device_handler = DeviceHandler(state_manager, idev_out)
        self._pattern_handler = PatternHandler(state_manager, idev_out)
        
        # Default to Mixer Handler
        self._current_handler = self._mixer_handler
        self._current_screen = None

        self._signals = [
            (zynsigman.S_GUI,
                zynsigman.SS_GUI_SHOW_SCREEN,
                self._on_gui_show_screen),
        ]
        super().__init__(state_manager, idev_in, idev_out)

    def init(self):
        super().init()
        for signal, subsignal, callback in self._signals:
            zynsigman.register(signal, subsignal, callback)
        
        # Send a wake up / init message if needed?
        # For now, just log.
        logging.info("MPK 225 Driver Initialized. Please ensure Pads/Knobs are mapped to default CCs.")

    def end(self):
        for signal, subsignal, callback in self._signals:
            zynsigman.unregister(signal, subsignal, callback)
        super().end()

    def midi_event(self, ev: bytes):
        evtype = (ev[0] >> 4) & 0x0F
        channel = ev[0] & 0x0F

        if evtype == CONST.MIDI_CC:
            ccnum = ev[1] & 0x7F
            ccval = ev[2] & 0x7F
            
            # Dispatch to handler with channel info if available
            if hasattr(self._current_handler, 'cc_change_with_channel'):
                self._current_handler.cc_change_with_channel(channel, ccnum, ccval)
            else:
                self._current_handler.cc_change(ccnum, ccval)

        elif evtype == CONST.MIDI_NOTE_ON:
            note = ev[1] & 0x7F
            velocity = ev[2] & 0x7F
            self._current_handler.note_on(note, channel, velocity)

        elif evtype == CONST.MIDI_NOTE_OFF:
            note = ev[1] & 0x7F
            self._current_handler.note_off(note, channel)
            
        elif evtype == CONST.MIDI_PC:
             program = ev[1] & 0x7F
             # Reserve PC 0-5 for Mode Switching if user configures it.
             if program == 0: self._change_handler(self._mixer_handler)
             elif program == 1: self._change_handler(self._device_handler)
             elif program == 2: self._change_handler(self._pattern_handler)

    def refresh(self):
        pass

    def update_mixer_strip(self, chan, symbol, value):
        pass

    def update_mixer_active_chain(self, active_chain):
        pass

    def _change_handler(self, new_handler):
        if new_handler == self._current_handler:
            return
        self._current_handler.set_active(False)
        self._current_handler = new_handler
        self._current_handler.set_active(True)
        logging.info(f"Switched to {new_handler.__class__.__name__}")

    def _on_gui_show_screen(self, screen):
        self._current_screen = screen
        for handler in [self._device_handler, self._mixer_handler, self._pattern_handler]:
            handler.on_screen_change(screen)
        
        # Auto-switch handler based on screen?
        if screen in ["mixer", "zynpad"]:
            self._change_handler(self._mixer_handler)
        elif screen in ["control", "preset", "main_menu", "admin"]:
            self._change_handler(self._device_handler)
        elif screen in ["pattern_editor", "arranger"]:
            self._change_handler(self._pattern_handler)


# --------------------------------------------------------------------------
# Audio mixer and Zynpad handler
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Audio mixer and Zynpad handler
# --------------------------------------------------------------------------
class MixerHandler(ModeHandlerBase):

    # Knobs (Channels 2, 3, 4)
    CHAN_KNOBS_A = 1
    CHAN_KNOBS_B = 2
    CHAN_KNOBS_C = 3
    
    CC_KNOBS_START = 50
    CC_KNOBS_END = 57
    
    # Pads (Channel 11 - 0x0A)
    CHAN_PADS = 10
    NOTE_PAD_START_A = 36
    NOTE_PAD_END_A = 43
    NOTE_PAD_START_B = 44
    NOTE_PAD_END_B = 51

    # Switches (Channel 2)
    CC_SW_1 = 28
    CC_SW_2 = 29
    CC_SW_3 = 30
    CC_SW_4 = 31

    # Transport (Channel 1)
    CHAN_TRANSPORT = 0
    CC_LOOP = 114
    CC_RWD = 115
    CC_FFW = 116
    CC_STOP = 117
    CC_PLAY = 118
    CC_REC = 119

    def __init__(self, state_manager, idev_out):
        super().__init__(state_manager)
        self._idev_out = idev_out
        self._chains_bank = 0

    def note_on(self, note, channel, velocity):
        if channel == self.CHAN_PADS:
            # Bank A Pads (36-43) - Mute toggle 1-8
            if self.NOTE_PAD_START_A <= note <= self.NOTE_PAD_END_A:
                idx = note - self.NOTE_PAD_START_A
                self._update_chain("mute_toggle", idx + self.CC_KNOBS_START, 127)
            # Bank B Pads (44-51) - Solo toggle 1-8?
            elif self.NOTE_PAD_START_B <= note <= self.NOTE_PAD_END_B:
                idx = note - self.NOTE_PAD_START_B
                self._update_chain("solo_toggle", idx + self.CC_KNOBS_START, 127)

    def cc_change_with_channel(self, channel, ccnum, ccval):
        # Transport (Channel 1)
        if channel == self.CHAN_TRANSPORT:
            if ccnum == self.CC_STOP: self._state_manager.send_cuia("STOP_AUDIO_PLAY")
            elif ccnum == self.CC_PLAY: self._state_manager.send_cuia("TOGGLE_AUDIO_PLAY")
            elif ccnum == self.CC_REC: self._state_manager.send_cuia("TOGGLE_AUDIO_RECORD")
            elif ccnum == self.CC_LOOP: self._state_manager.send_cuia("TOGGLE_LOOP")
            elif ccnum == self.CC_FFW: self._state_manager.send_cuia("FORWARD")
            elif ccnum == self.CC_RWD: self._state_manager.send_cuia("BACKWARD")
            return

        # Knobs (Channels 2, 3, 4)
        if self.CC_KNOBS_START <= ccnum <= self.CC_KNOBS_END:
            if channel == self.CHAN_KNOBS_A:
                self._update_volume(ccnum, ccval)
            elif channel == self.CHAN_KNOBS_B:
                self._update_pan(ccnum, ccval)
            elif channel == self.CHAN_KNOBS_C:
                self._update_send(ccnum, ccval)
    
    def cc_change(self, ccnum, ccval):
        pass

    def _update_volume(self, ccnum, ccval):
        return self._update_chain("level", ccnum, ccval, 0, 100)

    def _update_pan(self, ccnum, ccval):
        return self._update_chain("balance", ccnum, ccval, -100, 100)
    
    def _update_send(self, ccnum, ccval):
        # Placeholder
        pass

    def _update_chain(self, type, ccnum, ccval, minv=None, maxv=None):
        index = ccnum - self.CC_KNOBS_START + self._chains_bank * 8
        chain = self._chain_manager.get_chain_by_index(index)
        if chain is None or chain.chain_id == 0:
            return False
        mixer_chan = chain.mixer_chan

        if type == "level":
            value = self._zynmixer.get_level(mixer_chan)
            set_value = self._zynmixer.set_level
        elif type == "balance":
            value = self._zynmixer.get_balance(mixer_chan)
            set_value = self._zynmixer.set_balance
        elif type == "mute_toggle":
            value = not self._zynmixer.get_mute(mixer_chan)
            self._zynmixer.set_mute(mixer_chan, value, True)
            return True
        elif type == "solo_toggle":
            value = not chain.solo
            chain.set_solo(value)
            return True

        if minv is not None and maxv is not None:
             value = minv + (ccval / 127.0) * (maxv - minv)
        
        if 'set_value' in locals():
            set_value(mixer_chan, value)
        return True


# --------------------------------------------------------------------------
# Handle GUI (Device mode)
# --------------------------------------------------------------------------
class DeviceHandler(ModeHandlerBase):
    
    # Pads (Channel 10)
    CHAN_PADS = 10
    NOTE_PAD_UP = 36         # Pad A01
    NOTE_PAD_DOWN = 37       # Pad A02
    NOTE_PAD_LEFT = 38       # Pad A03
    NOTE_PAD_RIGHT = 39      # Pad A04
    NOTE_PAD_BACK = 40       # Pad A05
    NOTE_PAD_SELECT = 41     # Pad A06
    NOTE_PAD_SNAPSHOT = 42   # Pad A07
    NOTE_PAD_LAYER = 43      # Pad A08

    # Knobs (Channel 1, 2, 3) - CC 50-57
    # Bank A -> Knobs 1-8
    
    def __init__(self, state_manager, idev_out):
        super().__init__(state_manager)
        self._idev_out = idev_out
        self._last_cc_values = {}

    def note_on(self, note, channel, velocity):
        if channel != self.CHAN_PADS: return
        
        if note == self.NOTE_PAD_UP: self._state_manager.send_cuia("ARROW_UP")
        elif note == self.NOTE_PAD_DOWN: self._state_manager.send_cuia("ARROW_DOWN")
        elif note == self.NOTE_PAD_LEFT: self._state_manager.send_cuia("ARROW_LEFT")
        elif note == self.NOTE_PAD_RIGHT: self._state_manager.send_cuia("ARROW_RIGHT")
        elif note == self.NOTE_PAD_BACK: self._state_manager.send_cuia("BACK")
        elif note == self.NOTE_PAD_SELECT: self._state_manager.send_cuia("SELECT")
        elif note == self.NOTE_PAD_SNAPSHOT: self._state_manager.send_cuia("SCREEN_ZS3")
        elif note == self.NOTE_PAD_LAYER: self._state_manager.send_cuia("LAYER_TOGGLE")

    def cc_change_with_channel(self, channel, ccnum, ccval):
        # We need channel info for Knobs to distinguish Banks if we map them differently
        # For Device Mode, let's map:
        # Bank A (Ch 2) Knobs 1-4 -> ZynPot 1-4
        # Bank B (Ch 3) Knobs 1-4 -> ZynPot 1-4 (Duplicate?) or ZynPot 5+?
        # Let's map Bank A to Pots 1-4, Bank B to ???
        
        # Typically Device Mode uses 4 knobs for parameters.
        if channel == 1: # Ch 2 (Bank A)
             pot_offset = 0
        else:
             return 

        if 50 <= ccnum <= 53: # Knobs 1-4
            pot_idx = ccnum - 50 + pot_offset
            
            # Absolute to Delta
            last_val = self._last_cc_values.get((channel, ccnum), ccval)
            delta = ccval - last_val
            
            if (channel, ccnum) not in self._last_cc_values:
                delta = 0 # suppress jump on first touch
            
            self._last_cc_values[(channel, ccnum)] = ccval
            
            if delta != 0:
                self._state_manager.send_cuia("ZYNPOT", [pot_idx, delta])



# --------------------------------------------------------------------------
# Handle pattern editor (Pattern mode)
# --------------------------------------------------------------------------
class PatternHandler(ModeHandlerBase):
    
    # Pads (Channel 11 - 0x0A)
    CHAN_PADS = 10
    NOTE_PAD_PLAY = 36 # A01
    NOTE_PAD_STOP = 37 # A02
    NOTE_PAD_REC = 38  # A03
    
    # Transport (Channel 1)
    CHAN_TRANSPORT = 0
    CC_PLAY = 118
    CC_STOP = 117
    CC_REC = 119

    def __init__(self, state_manager, idev_out):
        super().__init__(state_manager)
        self._idev_out = idev_out
        self._knobs_ease = KnobSpeedControl()

    def note_on(self, note, channel, velocity):
        if channel == self.CHAN_PADS:
             if note == self.NOTE_PAD_PLAY: self._state_manager.send_cuia("TOGGLE_PLAY")
             elif note == self.NOTE_PAD_STOP: self._state_manager.send_cuia("STOP")
             elif note == self.NOTE_PAD_REC: self._state_manager.send_cuia("TOGGLE_RECORD")

    def cc_change_with_channel(self, channel, ccnum, ccval):
        if channel == self.CHAN_TRANSPORT:
            if ccnum == self.CC_PLAY: self._state_manager.send_cuia("TOGGLE_PLAY")
            elif ccnum == self.CC_STOP: self._state_manager.send_cuia("STOP")
            elif ccnum == self.CC_REC: self._state_manager.send_cuia("TOGGLE_RECORD")

    def cc_change(self, ccnum, ccval):
        pass

