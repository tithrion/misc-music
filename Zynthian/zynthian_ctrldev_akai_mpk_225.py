#!/usr/bin/python3
# -*- coding: utf-8 -*-
# ******************************************************************************
# ZYNTHIAN PROJECT: Zynthian Control Device Driver
#
# Zynthian Control Device Driver for "Akai MPK 225 MIDI controller"
#
# Copyright (C) 2015-2025 Fernando Moyano <jofemodo@zynthian.org>
#                         Brian Walton <brian@riban.co.uk>
#                         Steffen Klein <steffen@klein-network.de>
#
# ******************************************************************************
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 2 of
# the License, or any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# For a full copy of the GNU General Public License see the LICENSE.txt file.
#
# ******************************************************************************

import logging
from zyngine.ctrldev.zynthian_ctrldev_base import zynthian_ctrldev_base

# Zynthian specific modules
from zyncoder.zyncore import lib_zyncore

# ------------------------------------------------------------------------------
# Akai MPK 225 MIDI controller
# ------------------------------------------------------------------------------

class zynthian_ctrldev_akai_mpk_225(zynthian_ctrldev_base):

    dev_ids = ["MPK225 IN 1"]
    driver_name = "Akai MPK 225"
    driver_description = "Interface for Akai MPK 225"
    # Keep the input device routed to chains when driver is loaded
    unroute_from_chains = False

    def init(self):
        self.state_manager.add_slow_update_callback(60, self.keep_alive)

    def end(self):
        self.state_manager.remove_slow_update_callback(self.keep_alive)
        super().end()

    def keep_alive(self):
        lib_zyncore.dev_send_note_on(self.idev_out, 0, 0, 0)

# ------------------------------------------------------------------------------

