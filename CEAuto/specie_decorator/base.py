"""Generic propertie decorator class.

This assign properties to undecorated pymatgen.Element,to make them Species,
with charge and other properties.

Possible decorations includes charge (most commonly used), spin polarization.
If the user wishes to define other properties assignment methods, just derive
a new class Assignment class, and write assignment methods accordingly.
"""

__author__='Fengyu Xie'

import logging
log = logging.getLogger(__name__)

from abc import ABCMeta, abstractmethod
from monty.json import MSONable
from pymatgen.core import Species, DummySpecies, Structure

from ..utils.class_utils import derived_class_factory


def decorate_single_structure(s, decor_keys, decor_values, max_charge=0):
    """Decorates a single, undecorated structure.

    Undecorated structures are composed of pymatgen.Element,
    and we turn them into structures of pymatgen.Species.
    Vacancies not considered.

    Args:
        s(pymatgen.Structure):
            Structure to be decorated.
        decor_keys(list of str):
            Names of properties to be decorated onto the structure.
        decor_values(2D list, second dimension can be None):
            Values of properties to be assigned to each site. Shaped
            as (N_properties, N_sites).
            Charges will be stored in each specie.oxidation_state, while
            other properties will be stoered in specie._properties, if
            allowed by Species class.
            Can't be None.
        max_charge(int):
            Maximum absolute value of charge in a single structure.
            If charge goes over this limit, structure assignment will
            return a failure.
    Returns:
        Pymatgen.Structure: Decorated structure.
    """
    for val in decor_values:
        for v in val:
            assert v is not None
    # No decoration value can be None.
    
    #transpose to N_sites*N_properties
    decors_by_sites = list(zip(*decor_values))
    species_new = []

    for sp, decors_of_site in zip(s.species, decors_by_sites):
        try:
            sp_new = Species(sp.symbol)
        except:
            sp_new = DummySpecies(sp.symbol)
        
        other_props = {}
        for key, val in zip(decor_keys, decors_of_site):
            if key == 'charge':
                sp_new._oxi_state = val
            else:  # Other properties
                if key in Species.supported_properties:
                    other_props[key] = val
                else:
                    log.warning("{} is not a supported pymatgen property."
                                .format(key))
        sp_new._properties = other_props
        species_new.append(sp_new)

    s_decor = Structure(s.lattice, species_new, s.frac_coords)
    if abs(s_decor.charge) <= max_charge:
        return s_decor
    else:
        return None


class BaseDecorator(MSONable, metaclass=ABCMeta):
    """Abstract decorator class.

    Attributes:
        labels_av(Dict{Element: List[int|float]...}):
            A dictionary, specifying the elements, and the labels
            that we should assign to this specific element.
            By default, Vacancy will not appear in structure pool when
            directly read from vasp output, so no need to consider.
            For example:
            OrderedDict({Element.from_string('Li'):[1]})
            when assigning charge +1 to Li in a structure.
            When there are multiple assigned property values possible, 
            the values in the list[int|float] should be sorted by the
            order of their cluster centers in the properties axis.
            For example, If I have Mn2+, Mn3+ and Mn4+ (all on high spin), 
            and we assign charges to Mn atoms by magnetization, then we expect 
            a order of [4,3,2], because this is the order of the magnetic moment
            in these three types of oxidation states.
    """
    # Edit this as you implement new child classes.
    required_props = []

    def __init__(self, labels_table):
        """Initialize.

        Args:
           labels_table(dict{str:list}):
               A table of labels to decorate each site's element.
               keys are element symbol, values are decoration values,
               such as oxidation states.
        """
        self.labels_table = labels_table

    def _get_sites_info_by_element(self, str_pool, properties):
        """Build catalog of sites information."""
        #flatten all structures, and group by elements.
        sites_by_elements = {e: [] for e in self.labels_table.keys()}
        
        for s_id,s in enumerate(str_pool):
            for st_id,st in enumerate(s):
                entry = ([properties[p][s_id][st_id]
                         for p in self.required_props] +
                         [s_id, st_id])
                sites_by_elements[st.specie.symbol].append(entry)

        return sites_by_elements

    @property
    @abstractmethod
    def trained(self):
        """Gives whether this decorator is trained or not.

        If trained, will not be trained again.
        """
        return

    @abstractmethod
    def train(self, str_pool, properties, reset=False):
        """Train a properties assignment model.

        Model or model parameters should be stored in a property of the
        object.

        Args:
            str_pool(List[Structure]):
                Unassigned structures, must contain only pymatgen.Element
            properties(Dict{String: 2D ArrayLike}):
                Numerical properties used to classify sites, and property
                names.
                Each property array has shape N_strs*N_sites.
            reset(Boolean):
                If you want to re-train the decorator model, set this value
                to true. Otherwise we will skip training if self.trained is 
                true.
        """
        return

    @abstractmethod
    def assign(self, str_pool, properties):
        """Give assignment to structures.

        If an assigned structure is not valid,
        for example, in charge assignment, if an assigned structure is not
        charge neutral, then this structure will be returned as None.
        Args:
            str_pool(List[Structure]):
                Unassigned structures, must contain only pymatgen.Element
            properties(3D ArrayLike):
                Numerical properties used to classify sites.
                Shape should be N_different_proerties*N_strs*N_sites
        Returns:
            A dictionary, specifying name of assigned properties and their
            values by structure and by site.
            For example: 
            {'charge':[[1,4,2,...], [...],...]}
            Currently, in pymatgen.Specie's
            other_properties, only 'spin' is allowed. If you want to add more, do
            your own study!
            The de-serialization of property names is given in CEAuto.featurizer.
            featurize.
        """
        return

    @abstractmethod
    def as_dict(self):
        """Serialization method."""
        return

    @classmethod
    @abstractmethod
    def from_dict(cls,d):
        """Deserialization."""
        return


def decorator_factory(decorator_name, *args, **kwargs):
    """Create a species decorator with given name.

    Args:
        decorator_name(str):
            Name of a BaseDecorator subclass.
        *args, **kwargs:
            Arguments used to intialize the class.
    """
    name = decorator_name.capitalize() + 'Decorator'
    return derived_class_factory(name, BaseDecorator, *args, **kwargs)
