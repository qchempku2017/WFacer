#U=Integrate all comp analysis into here

import sys
import os
this_file_path = os.path.abspath(__file__)
this_file_dir = os.dirname(this_file_path)
parent_dir = os.dirname(this_file_dir)
sys.path.append(parent_dir)
from utils.specie_utils import *
from utils.enum_utils import *

from monty.json import MSONable

import numpy as np
from functools import reduce
from operators import and_,or_

class Sublattice(MSONable):
    def __init__(self,lattice,sites_in_prim,possible_sps,fractional=True,is_anion=None):
        """
        Cluster expansion sublattice. Species are allowed to be flipped or swapped within
        a sublattice during occupation enum, but not allowed to be flipped or swapped 
        between sublattices.
        lattice:
            a pymatgen.lattice object, definining primitive cell vectors

        sites_in_prim:
            primitive cell coordinates of sites in this sublattice.
            For example, all 16a sites in a cubic spinel primitive cell.

        possible_sps:
            Species that are allowed to occupy this sublattice. Is a list of strings.
            For example, ['Li+','Mn2+','Mn3+'].
            Or can be a dict:
            {'Na+':(0.0,0.1),'K+':(0.0,1.0)}
            In which the tuple constrains the allowed occupation ratio of each specie.
            The left number is a lower-limit, and the right one is an upper-limit.
            Vacancies are denoted as specie string 'Vac', and if there are vacancies,
            they must be explicitly speciefied.
            In new version of CEAuto, all species will be sorted with string ordering,
            instead of pymatgen.specie ordering, including 'Vac's.

        fractional:
            if True, all coordnates of sites are encoded in fractional coordinates.
            if False, all coordnates should be cartesian.
       
        is_anion:
            Whether is sulattice is anion-type or not. By default, will detect automatically
            at initialization.
        """
        self.lattice = lattice
        self.frac_to_cart = lattice.matrix
        self.cart_to_frac = np.linalg.inv(lattice.matrix)
        sites_in_prim = np.array(sites_in_prim)        

        if not fractional:
            self.sites = sites_in_prim@self.cart_to_frac

        self.carts = self.lattice.get_cartesian_coords(self.sites)

        if type(possible_sps)==dict:
            self.species = [k for k,v in sorted(possible_sps.items())]
            self.constraints = [v for k,v in sorted(possible_sps_items())]
        elif type(possible_sps)==list:
            self.species = sorted(possible_sps)
            self.constraints = [(0.0,1.0) for i in range(len(self.species))]
        else:
            raise ValueError("Species not given in desired dict or list format!")

        self.charges = [get_oxi(sp_str) for sp_str in self.species]
        #get_oxi to be implemented in utils.specie_utils       
        self.N_sps = len(self.species)
       
        self.is_anion = is_anion
        should_be_anion = reduce(and_,[(c<=0) for c in self.charges]) and \
                  
        if self.is_anion is not None:
            if self.is_anion!=should_be_anion:
                raise ValueError("Anion site occupied with cation specie!")
        else:
            self.is_anion = should_be_anion

    def enumerate_comps(self,fold=8):
        """
        Enumerates a possible compositions of a sublattice that satisfies self.constraints.
        Inputs:
            fold: use 1/fold as a step in composition space. For example, fold=2 when species
                  are 'Na','K' gives the enumerated list:
                  [{'Na:0.0,'K':1.0},{'Na':0.5,'K':0.5},{'Na':1.0,'K':0.0}]
        Outputs:
            A list containing enumerated compositions.
        """
        if fold<self.N_sps:
            raise ValueError("Number of enumeration folds smaller than number of species.")
        #Implemented in utils.enum_utils
        partitions = enumerate_partitions(n_part=self.N_sps,enum_fold=fold,constrs=self.constraints)
        enum_comps = [{sp:x for x,sp in zip(p,self.species)} for p in partitions]
        return enum_comps

class ExpansionStructure(MSONable)
    def __init__(self,lattice,sublats):
        """
        This class is a prototype used to generate cluster expansion sample structures.
        Also contains a socket to mapping methods that returns the occupation array.
        Inputs:
            lattice: 
                A pymatgen.Lattice object, defining the primitive cell vecs of the cluster expansion.
            sublats:
                Sublattices that makes up the structure. Typically divided into cation and anion, types.
                For a non-charged CE, all sublattices fall into anion type.
                This type division will be crucial in the anion framework matcher.
                A list of ce_elements.Sublattice objects.
        """
        self.lattice = lattice
        self.sublats = sublats
        
    @classmethod
    def from_lat_frac_species(cls,lattice,frac_coords,species,sublat_merge_rule=None,anionic_markings=None)
        """
        This initializes a ExpansionStructure object from a pymatgen.lattice, fractional coordinates
        of sites in a primitive cell, the species on each sites, merging rule of sites into sublattices,
        and a list of boolean variables that suggests whether this site is a anion site or not.

        We highly recommend you to make sure that the structure is properly reduced, so that 
        there is only 1 site for each sublattice.

        Inputs:
            Lattice: a pymatgen.lattice;
            frac_coords: fractional coordinate of sites
            sublat_merge_rule: 
                The rule to merge sites into a sublattice. For example:
                [[0,1,2],[3,4],[5,6]]
                By default, each input site will be considered as a sublattice.
            species:
                species on each site. Is a list of strings.
                For example, ['Li+','Mn2+','Mn3+'].
                Or can be a dict:
                {'Na+':(0.0,0.1),'K+':(0.0,1.0)}
            anionic_markings:
                A list of booleans that specifies whether this site is considered anionic or not.
        """
        if not sublat_merge_rule:
            if len(frac_coords)!=len(species):
                raise ValueError("Some of sublatticed have no occpying species!")            

        if sublat_merge_rule:
            if len(sublat_merge_rule)!=len(species):
                raise ValueError("Some of sublatticed have no occpying species!")            

        if not sublat_merge_rule and anionic_markings:
            if len(frac_coords)!=len(anionic_markings):
                raise ValueError("Anionic markings are not assigned to all sublattices!")

        if sublat_merge_rule and anionic_markings:
            if len(sublat_merge_rule)!=len(anionic_markings):
                raise ValueError("Anionic markings are not assigned to all sublattices!")

        sublat_list = sublat_merge_rule if sublat_merge_rule is not None else \
                      [[i] for i in range(len(species))]

        markings = anionic_markings if anionic_markings else\
                   [None for i in range(len(species))]
        
        frac_coords = np.array(frac_coords)
        sublats = [Sublattice(lattice,frac_coords[sl_ids],sl_species,is_anion=mk) \
                       for sl_ids,sl_species,mk in zip(sublat_list,species,markings)]

