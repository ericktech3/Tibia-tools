# -*- coding: utf-8 -*-
"""
Tibia Tools (Android) - KivyMD app

Tabs: Char / Share XP / Favoritos / Mais
Mais -> telas internas: Bosses (ExevoPan), Boosted, Treino (Exercise), Imbuements, Hunt Analyzer
"""
from __future__ import annotations

import os
import threading
import webbrowser
import traceback
import math
from typing import List, Optional

from kivy.clock import Clock
from kivy.lang import Builder
from kivy.resources import resource_find
from kivy.metrics import dp
from kivy.core.window import Window

from kivymd.app import MDApp
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDFlatButton
from kivymd.uix.list import OneLineIconListItem, IconLeftWidget
from kivymd.uix.menu import MDDropdownMenu

from core.api import fetch_character_tibiadata, fetch_worlds_tibiadata, is_character_online_tibiadata
from core.storage import get_data_dir, safe_read_json, safe_write_json
from core.bosses import fetch_exevopan_bosses
from core.boosted import fetch_boosted
from core.training import TrainingInput, compute_training_plan
from core.hunt import parse_hunt_session_text
from core.imbuements import ImbuementEntry, search_imbuements

KV_FILE = "tibia_tools.kv"
FAV_FILE = "favorites.json"


class MoreItem(OneLineIconListItem):
    icon: str = "chevron-right"
