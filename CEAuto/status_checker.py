"""Module to check the current iter number and module from dataframes.

This class only appears as an attachment to DataManager.
No save or load.
"""

__author__ = 'Fengyu Xie'

import json
import pandas as pd
import os
from copy import deepcopy

from .config_paths import *
from .utils.frame_utils import load_dataframes


class StatusChecker:
    """
    A class that checks current iteration number and the last completed
    module from the dataframes, and the history document. Readonly, will
    not be saved. 
    Mostly this will serve as an attachment to DataManager, and you may 
    not need to directly initialize this.

    Direct __init__ not recommended.
    """
    #CEAuto modules in their cycle order
    #calc includes calc_reader, calc_writer, calc_manager;
    #gs includes gs_check, gs_solve
    #GS considered as the first module in an iteration(except for
    #iteration 0, the first one).

    modules = ['gs','enum','write','calc','feat','fit']

    def __init__(self,sc_df,comp_df,fact_df,history=[]):
        """
        Args:
            sc_df(DataFrame):
                supercells dataframe
            comp_df(DataFrame):
                compositons dataframe
            fact_df(DataFrame):
                fact dataframe, containing all computation entree.
            history(List[Dict]):
                Historical cluster expansion record.
        """
        self.sc_df = sc_df
        self.comp_df = comp_df        
        self.fact_df = fact_df

        self.history = history

        self._sc_load_path = None
        self._comp_load_path = None
        self._fact_load_path = None
        self._history_load_path = None

    def _get_iter_id_last_module(self):
        """
        Get the current iteration index and the last completed module name
        Returns:
            iter_id, last_module(str|Nonetype)
        """
        if len(self.fact_df)==0:
            return 0,None

        max_iter_id = self.fact_df.iter_id.max()

        filt_ = (self.fact_df.iter_id==max_iter_id)

        last_df = self.fact_df[filt_]
        
        # pd.Series must be converted to list before checking 'in'.
        if 'NC' in last_df.calc_status.tolist():
            last_nc_df = last_df[last_df.calc_status=='NC']
            if 'enum' in last_nc_df.module:
                return max_iter_id, 'enum'
            elif 'gs' in last_nc_df.module:
                return max_iter_id, 'gs'
            else:
                raise ValueError("Module other than enumerator or gs \
                                  solver appeared.")

        if 'CC' in last_df.calc_status.tolist():
            return max_iter_id, 'write'

        if 'CL' in last_df.calc_status.tolist():
            return max_iter_id, 'calc'  

        if (len(self.history) < max_iter_id or
            len(self.history) > max_iter_id + 1):
            raise ValueError("History record broken! \
                             Currently at iteration {}, \
                             but only {} history steps found!"
                             .format(max_iter_id,len(self.history)))

        if len(self.history) == max_iter_id:
            return max_iter_id, 'feat'

        if len(self.history) == max_iter_id + 1:
            return max_iter_id + 1, 'fit'

    @property
    def cur_iter_id(self):
        """
        current iteration id.
        """
        return self._get_iter_id_last_module()[0]

    @property
    def last_completed_module(self):
        """
        last completed module.
        """
        return self._get_iter_id_last_module()[1]

    def before(self,module_name):
        """
        Check whether the specified module HAS NOT been finished 
        in the current iteration.
        Args:
            module_name(str):
                name of the module to check.
        """
        if self.last_completed_module is None:
            return True
        return (StatusChecker.modules.index(self.last_completed_module) < 
                StatusChecker.modules.index(module_name))

    def after(self,module_name):
        """
        Check whether the specified module HAS been finished 
        in the current iteration.
        Args:
            module_name(str):
                name of the module to check.
        """
        return (not self.before(module_name))

    def copy(self):
        """Deepcopy of StatusChecker"""
        sock = StatusChecker(self.sc_df.copy(),
                             self.comp_df.copy(),
                             self.fact_df.copy(),
                             deepcopy(self.history))

        return sock
