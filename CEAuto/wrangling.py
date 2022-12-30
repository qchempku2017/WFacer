"""CeDataWrangler.

This file includes a modified version of StructureWrangler, which stores
more information that CE might use.
"""

__author__ = "Fengyu Xie"

import numpy as np
import warnings
from collections import defaultdict

from pymatgen.analysis.structure_matcher import StructureMatcher
from pymatgen.core import Composition

from smol.cofe.wrangling.wrangler import StructureWrangler
from smol.cofe.wrangling.tools import _energies_above_hull


# When using Seko's iterative procedure, it does not make much sense to weight energy.
# We will not include sample weighting scheme here. You can play with the CeDataWangler.add_weights
# if you want.
class CeDataWrangler(StructureWrangler):
    """CeDataWrangler class.

    Interfaces CEAuto generated data, does insertion and deletion,
    but will not generate any data.

    Note: This DataWrangler is not compatible with legacy version of smol.
    """
    def _check_structure_duplicacy(self, entry, sm=None):
        """Whether an entry symmetrically duplicates with existing ones."""
        if sm is None:
            sm = StructureMatcher()
        for entry_old in self.entries:
            if (np.allclose(entry_old.data["correlations"],
                            entry.data["correlations"]) and
                sm.fit(entry_old.data["refined_structure"],
                       entry.data["refined_structure"])):
                # Allows inserting multiple in-equivalent structures
                # with the same correlation functions.
                # Returns the first duplicating entry in self.entries.
                return entry_old
        return None

    @property
    def max_iter_id(self):
        """Maximum index of iteration existing.

        Iteration counted from 0.
        """
        return max(entry.data["properties"]["spec"]["iter_id"] for entry in self.entries)

    def add_entry(
        self,
        entry,
        properties=None,
        weights=None,
        supercell_matrix=None,
        site_mapping=None,
        verbose=True,
        raise_failed=False,
    ):
        """Add a structure and measured property to the DataWrangler.

        The energy and properties need to be extensive (i.e. not normalized per atom
        or unit cell, directly from DFT).

        An attempt to compute the correlation vector is made and if successful the
        structure is succesfully added. Otherwise the structure is ignored.
        Usually failures are caused by the StructureMatcher in the given
        ClusterSubspace failing to map structures to the primitive structure.

        Same as StructureWrangler but refuses to insert symmetrically equivalent
        entries. It also records the iteration number when then entry was added.

        Args:
            entry (ComputedStructureEntry):
                A ComputedStructureEntry with a training structure, energy and
                properties
            properties (dict):
                Dictionary with a key describing the property and the target
                value for the corresponding structure. For example if only a
                single property {'energy': value} but can also add more than
                one, i.e. {'total_energy': value1, 'formation_energy': value2}.
                You are free to make up the keys for each property but make
                sure you are consistent for all structures that you add.
            weights (dict):
                the weight given to the structure when doing the fit. The key
                must match at least one of the given properties.
            supercell_matrix (ndarray): optional
                if the corresponding structure has already been matched to the
                ClusterSubspace prim structure, passing the supercell_matrix
                will use that instead of trying to re-match. If using this,
                the user is responsible for having the correct supercell_matrix.
                Here you are the cause of your own bugs.
            site_mapping (list): optional
                site mapping as obtained by StructureMatcher.get_mapping
                such that the elements of site_mapping represent the indices
                of the matching sites to the prim structure. If you pass this
                option, you are fully responsible that the mappings are correct!
            verbose (bool): optional
                if True, will raise warning regarding  structures that fail in
                StructureMatcher, and structures that have duplicate corr vectors.
            raise_failed (bool): optional
                if True, will raise the thrown error when adding a structure
                that  fails. This can be helpful to keep a list of structures that
                fail for further inspection.
        """
        # Add property "spec" to store iter_id and enum_id to record in which iteration
        # and when the structure was enumerated for calculation. This helps to reference the
        # atomate database. Property "spec" should never be extracted!
        if properties is None:
            properties = {"spec": {"iter_id": 0, "enum_id": 0}}
        elif "spec" not in properties:
            properties["spec"] = {"iter_id": 0, "enum_id": 0}

        processed_entry = self.process_entry(
            entry,
            properties,
            weights,
            supercell_matrix,
            site_mapping,
            verbose,
            raise_failed,
        )
        if processed_entry is not None:
            dupe = self._check_structure_duplicacy(entry,
                                                   sm=self.cluster_subspace._site_matcher)
            # Force dropping duplicacy.
            # TODO: maybe move this to smol in the future as an option.
            if dupe is None:
                self._entries.append(processed_entry)
                if verbose:
                    self._corr_duplicate_warning(self.num_structures - 1)
            else:
                if verbose:
                    warnings.warn("Provided entry duplicates with existing entry:\n"
                                  f"{dupe}. Skipped.")


def get_min_energy_structures_by_composition(wrangler, max_iter_id=None):
    """Get minimum energy and structure at each composition.

    This function provides quick tools to compare minimum DFT energies.
    Remember this is NOT hull!
    Sublattice and oxidation state degrees of freedom in compositions
    are not distinguished in generating hull.

    Args:
        wrangler(CeDataWrangler):
            Datawangler object.
        max_iter_id(int): optional
            Maximum iteration index included in the energy comparison.
            If none given, will read existing maximum iteration number.
    Returns:
        defaultdict:
            element compositions as keys, energy per site and structure
            as values.
    """
    min_e = defaultdict(lambda: (np.inf, None))
    prim_size = len(wrangler.cluster_subspace.structure)
    if max_iter_id is None:
        max_iter_id = wrangler.max_iter_id
    for entry in wrangler.entries:
        if entry.properties["spec"]["iter_id"] <= max_iter_id:
            # Normalize composition and energy to eV per site.
            comp = Composition({k: v / entry.data["size"] / prim_size
                                for k, v
                                in entry.structure.composition
                               .element_composition.items()})
            e = entry.energy / entry.data["size"] / prim_size
            s = entry.structure
            if e < min_e[comp][0]:
                min_e[comp] = (e, s)
    return min_e


def get_hull(wrangler, max_iter_id=None):
    """Get the energies and compositions on the convex hull.

    Sublattice and oxidation state degrees of freedom in compositions
    are not distinguished in generating hull.

    Args:
        wrangler(CeDataWrangler):
            Datawangler object.
        max_iter_id(int): optional
            Maximum iteration index included in the energy comparison.
            If none given, will read existing maximum iteration number.

    Returns:
        dict: element composition and energies in eV/site.
    """
    if max_iter_id is None:
        max_iter_id = wrangler.max_iter_id
    data = [(entry.structure, entry.energy) for entry in wrangler.entries
            if entry.properties["spec"]["iter_id"] <= max_iter_id]
    structures, energies = list(zip(*data))
    e_above_hull = _energies_above_hull(structures, energies,
                                        wrangler.cluster_subspace.structure)

    hull = {}
    prim_size = len(wrangler.cluster_subspace.structure)
    for entry, energy, on_hull in zip(wrangler.entries, energies,
                                      np.isclose(e_above_hull, 0)):
        if on_hull:
            comp = Composition({k: v / entry.data["size"] / prim_size
                                for k, v
                                in entry.structure.composition
                               .element_composition.items()})
            e = energy / entry.data["size"] / prim_size  # eV/site
            hull[comp] = e
    return hull
