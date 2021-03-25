__author__ = "Fengyu Xie"

"""
Utility functions to handle encoded occupation arrays.
"""
import numpy as np

from smol.cofe import ClusterSubspace
from smol.moca import CEProcessor

# Utilities to get supercell sublattice sites from primitive sublattice sites.
def get_sc_sllist_from_prim(sl_list_prim,sc_size=1):
    """
    Get supercell sublattice sites list from primitive cell sublattice sites list.
    Args:
        sl_list_prim(List[List[int]]):
             sublattice sites indices in primitive cell
        sc_size(int):
             supercell size. Default to 1.
    Returns:
        List[List[int]]:
             sublattice sites indices in supercell.
    """
    sl_list_sc = []
    for sl_prim in sl_list_prim:
        sl_sc = []
        for sid_prim in sl_prim:
            all_sid_sc = list(range(sid_prim*sc_size,(sid_prim+1)*sc_size))
            sl_sc.extend(all_sid_sc)
        sl_list_sc.append(sl_sc)

    return sl_list_sc

def get_prim_sllist_from_sc(sl_list_sc,sc_size=1):
    """
    Get primitive cell sublattice sites from supercell sublattice sites.
    Args:
        sl_list_sc(List[List[int]]):
            sublattice site indices in supercell
        sc_size(int):
            supercell size. Default to 1.
    Returns:
        List[List[int]]:
            sublattice sites indices in primitive cell.
    """
    sl_list_prim = []
    for sl_sc in sl_list_sc:
        sl_sc = sorted(sl_sc)
        if len(sl_sc)%sc_size!=0:
            raise ValueError("Supercell size does not match supercell sublattice size.")
        sl_prim = []
        for sid_sc in range(0,len(sl_sc),sc_size):
            if sl_sc[sid_sc]%sc_size!=0:
                raise ValueError("Supercell size indices were not generated by pymatgen!")
            sl_prim.append(sl_sc[sid_sc]//sc_size)
        sl_list_prim.append(sl_prim)

    return sl_list_prim

# Utilities for parsing occupation, used in charge-neutral semigrand flip table
def occu_to_species_stat(occupancy,bits,sublat_list_sc):
    """
    Get a statistics table of each specie on sublattices from an encoded 
    occupancy array.
    Args:
        occupancy(np.ndarray like):
            An array representing encoded occupancy, can be list.
        bits(list of lists of Specie):
            A list of species on each sublattice, must correspond to occupancy
            encoding table
        sublat_list_sc(List of lists of ints):
            A list storing sublattice sites in a SUPER cell

    Returns:
        species_stat(2D list of ints/floats)
            Is a statistics of number of species on each sublattice.
            1st dimension: sublattices
            2nd dimension: number of each specie on that specific sublattice.
            Dimensions same as moca.sampler.mcushers.CorrelatedUsher.bits          
    """
    occu = np.array(occupancy)

    species_stat = [[0 for i in range(len(sl_bits))] for sl_bits in bits]

    for s_id,sp_code in enumerate(occu):
        sl_id = None
        for i,sl in enumerate(sublat_list_sc):
            if s_id in sl:
                sl_id = i
                break
        if sl_id is None:
            raise ValueError("Occupancy site {} can not be matched to a sublattice!".format(s_id))   
        species_stat[sl_id][sp_code]+=1

    return species_stat

def occu_to_species_list(occupancy,bits,sublat_list_sc):
    """
    Get table of the indices of sites that are occupied by each specie on sublattices,
    from an encoded occupancy array.
    Inputs:
        occupancy(np.ndarray like):
            An array representing encoded occupancy, can be list.
        bits(list of lists of Specie):
            A list of species on each sublattice, must correspond to occupancy
            encoding table
        sublat_list_sc(List of lists of ints):
            A list storing sublattice sites in a SUPER cell
    Returns:
        species_list(3d list of ints):
            Is a statistics of indices of sites occupied by each specie.
            1st dimension: sublattices
            2nd dimension: species on a sublattice
            3rd dimension: site ids occupied by that specie
    """
    occu = np.array(occupancy)
    
    species_list = [[[] for i in range(len(sl_bits))] for sl_bits in bits]

    for site_id,sp_id in enumerate(occu):
        sl_id = None
        for i,sl in enumerate(sublat_list_sc):
            if site_id in sl:
                sl_id = i
                break
        if sl_id is None:
            raise ValueError("Occupancy site {} can not be matched to a sublattice!".format(s_id))   

        species_list[sl_id][sp_id].append(site_id)

    return species_list

#Wrap up structure_from_occu method from processor module
def structure_from_occu(occu,prim,sc_matrix):
    """
    Decodes structure from encoded occupation array.
    Args:
        occu(1D arraylike):
            encoded occupation string
        prim(pymatgen.Structure):
            primitive cell containing all occupying species information.
            It is your responisibility to ensure that it is exactly the
            one you used to initialize cluster expansion.
        sc_matrix(3*3 arraylike):
            Supercell matrix. It is your responsibility to check size
            matches the length of occu
    Returns:
        Decoded pymatgen.Structure object.
    """
    dummy_cspace = ClusterSubspace.from_cutoffs(prim, cutoffs={2:0.01})
    dummy_coefs = np.zeros(dummy_cspace.num_corr_functions)
    dummy_proc = CEProcessor(dummy_cspace,sc_matrix,dummy_coefs)
    return dummy_proc.structure_from_occupancy(occu)
