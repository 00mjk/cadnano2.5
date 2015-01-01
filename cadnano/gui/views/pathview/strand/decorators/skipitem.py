#!/usr/bin/env python
# encoding: utf-8
from cadnano import util
from .abstractdecoratoritem import AbstractDecoratorItem

class SkipItem(AbstractDecoratorItem):
    def __init__(self, parent):
        """The parent should be a VirtualHelixItem."""
        super(SkipItem, self).__init__(parent)

    ### SIGNALS ###

    ### SLOTS ###

    ### METHODS ###

    ### COMMANDS ###
