"""Monte-carlo to estimate ground states and sample structures."""
import itertools
from abc import ABCMeta, abstractmethod

import numpy as np
from pymatgen.core import Element

from smol.cofe import ClusterExpansion
from smol.cofe.space.domain import Vacancy
from smol.moca import Ensemble, Sampler, CompositionSpace
from smol.utils import derived_class_factory, class_name_from_str

from ..utils.duplicacy import is_duplicate
from ..utils.occu import get_random_occupancy_from_counts

__author__ = "Fengyu Xie"


class McSampleGenerator(metaclass=ABCMeta):
    """Abstract monte-carlo sampler class.

    Allows finding the ground state, and then gradually heats up the ground state
    to generate an unfrozen sample.

    Each Generator should only handle one composition (canonical) or one set of
    chemical potentials (grand-canonical)!
    """
    default_anneal_temp_series = [5000, 3200, 1600, 1000,
                                  800, 600, 400, 200, 100]
    default_heat_temp_series = [500, 1500, 5000]

    def __init__(self, ce, sc_matrix,
                 anneal_temp_series=None,
                 heat_temp_series=None,
                 num_steps_anneal=50000,
                 num_steps_heat=100000,
                 remove_decorations_before_duplicacy=False):
        """Initialize McSampleGenerator.

        Args:
            ce(ClusterExpansion):
                A cluster expansion object to enumerate with.
            sc_matrix(3*3 ArrayLike):
                Supercell matrix to solve on.
            anneal_temp_series(list[float]): optional
                A series of temperatures to use in simulated annealing.
                Must be mono-decreasing.
            heat_temp_series(list[float]): optional
                A series of increasing temperatures to sample on.
                Must be mono-increasing
            num_steps_anneal(int): optional
                Number of MC steps to run per annealing temperature step.
            num_steps_heat(int): optional
                Number of MC steps to run per heat temperature step.
            remove_decorations_before_duplicacy(bool): optional
                Whether to remove all decorations from species (i.e,
                charge and other properties) before comparing duplicacy.
                Default to false.
        """
        self.ce = ce
        self.sc_matrix = np.array(sc_matrix, dtype=int)
        self.sc_size = int(round(abs(np.linalg.det(sc_matrix))))
        self.prim = self.ce.cluster_subspace.structure

        self.anneal_temp_series = (anneal_temp_series
                                   or self.default_anneal_temp_series)
        self.heat_temp_series = (heat_temp_series
                                 or self.default_heat_temp_series)
        self.num_steps_anneal = num_steps_anneal
        self.num_steps_heat = num_steps_heat
        self.remove_decorations = remove_decorations_before_duplicacy

        self._gs_occu = None  # Cleared per-initialization.
        self._ensemble = None
        self._sampler = None

    @property
    @abstractmethod
    def ensemble(self):
        """Get ensemble to run."""
        return

    @property
    def sampler(self):
        """Sampler to run."""
        return

    @property
    def processor(self):
        """Get Processor."""
        return self.ensemble.processor

    @property
    def sublattices(self):
        """Get sublattices in ensemble.

        Note: If you wish to do delicate operations such as sub-lattice
        splitting, please do it on self.ensemble.
        See docs of smol.moca.ensemble.
        """
        return self.ensemble.sublattices

    @abstractmethod
    def _get_init_occu(self):
        return

    def get_ground_state_occupancy(self):
        """Use simulated annealing to solve the ground state occupancy.

        Returns:
            ground state in encoded occupancy array:
                np.ndarray[int]
        """
        if self._gs_occu is None:
            init_occu = self._get_init_occu()

            self.sampler.anneal(self.anneal_temp_series, self.num_steps_anneal,
                                initial_occupancies=
                                np.array([init_occu], dtype=int))

            # Save updates.
            self._gs_occu = (self.sampler.samples
                             .get_minimum_enthalpy_occupancy()
                             .astype(int)
                             .tolist())
            self.sampler.samples.clear()  # Free-up mem.

        return self._gs_occu

    def get_ground_state_structure(self):
        return self.processor\
            .structure_from_occupancy(self.get_ground_state_occupancy())

    def get_unfrozen_sample(self,
                            previous_sampled_structures=None,
                            num_samples=100):
        """Generate a sample of structures by heating the ground state.

        Args:
            previous_sampled_structures(list[Structure]): optional
                Sample structures already calculated in past
                iterations.
            num_samples(int): optional
                Maximum number of samples to draw per unfreezing
                run. Since Structures must be de-duplicated, the actual
                number of structures returned might be fewer than this
                threshold. Default to 100.

        Return:
            list[Structure]:
                New samples structures, not including the ground-state.
        """
        previous_sampled_structures = previous_sampled_structures or []

        thin_by = max(1,
                      len(self.heat_temp_series) * self.num_steps_heat
                      // (num_samples * 10))
        # Thin so we don't have to de-duplicate too many structures.
        # Here we leave out 10 * num_samples to compare.

        gs_occu = self.get_ground_state_occupancy()

        # Will always contain GS at the first position in list.
        rand_occus = []
        init_occu = gs_occu.copy()

        # Sampling temperatures
        for T in self.heat_temp_series:
            self.sampler.samples.clear()
            self.sampler.mckernels[0].temperature = T

            # Equilibrate and sampling.
            self.sampler.run(2 * self.num_steps_heat,
                             initial_occupancies=
                             np.array([init_occu], dtype=int),
                             thin_by=thin_by)
            init_occu = self.sampler.samples.get_occupancies()[-1].astype(int)
            n_samples = self.sampler.samples.num_samples
            # Take the last half as equlibrated, only.
            rand_occus.extend(self.sampler.samples
                              .get_occupancies(discard=n_samples // 2)
                              .astype(int)
                              .tolist())

        # Symmetry deduplication

        rand_strs = [self.processor.structure_from_occupancy(occu)
                     for occu in rand_occus]
        new_strs = []
        for new_id, new_str in enumerate(rand_strs):
            dupe = False
            for old_id, old_str in enumerate(previous_sampled_structures
                                             + new_strs):
                # Must remove decorations to avoid getting fully duplicate inputs.
                if is_duplicate(old_str, new_str,
                                remove_decorations=self.remove_decorations):
                    dupe = True
                    break
            if not dupe:
                new_strs.append(new_str)

            if len(new_strs) == num_samples:
                break

        return new_strs


class CanonicalSampleGenerator(McSampleGenerator):
    """Sample generator in canonical ensemble."""

    def __init__(self, ce, sc_matrix, counts,
                 anneal_temp_series=None,
                 heat_temp_series=None,
                 num_steps_anneal=50000,
                 num_steps_heat=100000):
        """Initialize.

        Args:
            ce(ClusterExpansion):
                A cluster expansion object to enumerate with.
            sc_matrix(3*3 ArrayLike):
                Supercell matrix to solve on.
            counts(1D ArrayLike[int]):
                Composition in the "counts " format, not normalized by
                number of primitive cells per super-cell. Refer to
                smol.moca.Composition space for explanation.
            anneal_temp_series(list[float]): optional
                A series of temperatures to use in simulated annealing.
                Must be mono-decreasing.
            heat_temp_series(list[float]): optional
                A series of increasing temperatures to sample on.
                Must be mono-increasing
            num_steps_anneal(int): optional
                Number of steps to run per simulated annealing temperature.
            num_steps_heat(int): optional
                Number of steps to run per heat temperature.
        """
        super(CanonicalSampleGenerator, self)\
            .__init__(ce, sc_matrix,
                      anneal_temp_series=anneal_temp_series,
                      heat_temp_series=heat_temp_series,
                      num_steps_anneal=num_steps_anneal,
                      num_steps_heat=num_steps_heat)

        self.counts = np.round(counts).astype(int)

    @property
    def ensemble(self):
        """CanonicalEnsemble."""
        if self._ensemble is None:
            self._ensemble = (Ensemble.
                              from_cluster_expansion(self.ce, self.sc_matrix))
        return self._ensemble

    @property
    def sampler(self):
        """A sampler to sample structures."""
        if self._sampler is None:
            # Check if charge balance is needed.
            self._sampler = Sampler.from_ensemble(self.ensemble,
                                                  temperature
                                                  =self.anneal_temp_series[0],
                                                  nwalkers=1)
        return self._sampler

    def _get_init_occu(self):
        """Get an initial occupancy for MC run."""
        return get_random_occupancy_from_counts(self.ensemble, self.counts)


# Grand-canonical generator will not be used very often.
class SemigrandSampleGenerator(McSampleGenerator):
    """Sample generator in canonical ensemble."""

    def __init__(self, ce, sc_matrix,
                 chemical_potentials,
                 anneal_temp_series=None,
                 heat_temp_series=None,
                 num_steps_anneal=50000,
                 num_steps_heat=100000):
        """Initialize.

        Args:
            ce(ClusterExpansion):
                A cluster expansion object to enumerate with.
            sc_matrix(3*3 ArrayLike):
                Supercell matrix to solve on.
            chemical_potentials(dict):
                Chemical potentials of each species. See documentation
                of smol.moca Ensemble.
            anneal_temp_series(list[float]): optional
                A series of temperatures to use in simulated annealing.
                Must be mono-decreasing.
            heat_temp_series(list[float]): optional
                A series of increasing temperatures to sample on.
                Must be mono-increasing
            num_steps_anneal(int): optional
                Number of steps to run per simulated annealing temperature.
            num_steps_heat(int): optional
                Number of steps to run per heat temperature.
        """
        super(SemigrandSampleGenerator, self)\
            .__init__(ce, sc_matrix,
                      anneal_temp_series=anneal_temp_series,
                      heat_temp_series=heat_temp_series,
                      num_steps_anneal=num_steps_anneal,
                      num_steps_heat=num_steps_heat)

        self.chemical_potentials = chemical_potentials

    @property
    def ensemble(self):
        """CanonicalEnsemble."""
        if self._ensemble is None:
            self._ensemble = (Ensemble.
                              from_cluster_expansion(self.ce,
                                                     self.sc_matrix,
                                                     chemical_potentials=
                                                     self.chemical_potentials))
        return self._ensemble

    @property
    def sampler(self):
        """A sampler to sample structures."""
        if self._sampler is None:
            # Check if charge balance is needed.
            bits = [sl.species for sl in self.sublattices]
            charge_decorated = False
            for sp in itertools.chain(*bits):
                if (not isinstance(sp, (Vacancy, Element)) and
                        sp.oxi_state != 0):
                    charge_decorated = True
                    break
            if charge_decorated:
                step_type = "table-flip"
            else:
                step_type = "flip"
            self._sampler = Sampler.from_ensemble(self.ensemble,
                                                  temperature
                                                  =self.anneal_temp_series[0],
                                                  step_type=step_type,
                                                  nwalkers=1)
        return self._sampler

    def _get_init_occu(self):
        """Get an initial occupancy for MC run."""
        bits = [sl.species for sl in self.sublattices]
        sublattice_sizes = np.array([len(sl.sites) for sl in self.sublattices])
        supercell_size = np.gcd.reduce(sublattice_sizes)
        sublattice_sizes = sublattice_sizes / supercell_size
        comp_space = CompositionSpace(bits, sublattice_sizes)
        center_coords = comp_space.get_centroid_composition(supercell_size=
                                                            supercell_size)
        center_counts = comp_space.translate_format(center_coords,
                                                    supercell_size,
                                                    from_format="coordinates",
                                                    to_format="counts")
        return get_random_occupancy_from_counts(self.ensemble, center_counts)


def mcgenerator_factory(mcgenerator_name, *args, **kwargs):
    """Create a MCHandler with given name.

    Args:
        mcgenerator_name(str):
            Name of a McSampleGenerator sub-class.
        *args, **kwargs:
            Arguments used to intialize the class.
    """
    if ("sample-generator" not in mcgenerator_name
            and "SampleGenerator" not in mcgenerator_name):
        mcgenerator_name += "-sample-generator"
    name = class_name_from_str(mcgenerator_name)
    return derived_class_factory(name, McSampleGenerator, *args, **kwargs)
