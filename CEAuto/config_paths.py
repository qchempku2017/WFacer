"""Specifies paths to ciritical setting files.

You can modify these in paths_setting.json under the running folder."""

__author__ = 'Fengyu Xie'

import os
import json

# Now everything is provided as json.
d = {}
if os.path.isfile('paths.json'):
    with open('paths.json') as fin:
        d = json.load(fin)

PRIM_FILE = d.get('prim_file', 'prim.cif')  # Must be present.
OPTIONS_FILE = d.get('options_file', 'options.json')
HISTORY_FILE = d.get('history_file', 'history.json')
WRAPPER_FILE = d.get('wrapper_file', 'inputs.json')
DECOR_FILE = d.get('decor_file', 'decorators.json')
