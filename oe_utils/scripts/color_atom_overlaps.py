#!/usr/bin/env python
"""
Get separate scores for each reference color atom overlap.
"""

__author__ = "Steven Kearnes"
__copyright__ = "Copyright 2014, Stanford University"
__license__ = "3-clause BSD"

import argparse
import collections
from functools import partial
import numpy as np

from oe_utils.chem import MolReader
from oe_utils.scripts import get_map
from oe_utils.shape.overlap import ColorOverlap
from oe_utils.utils import h5_utils


def get_args(input_args=None):
    """
    Get command line arguments.

    Parameters
    ----------
    input_args : list, optional
        Input arguments. If None, defaults to sys.argv[1:].
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('-r', '--ref', required=1,
                        help='Reference molecules.')
    parser.add_argument('-f', '--fit', required=1,
                        help='Fit molecules.')
    parser.add_argument('-o', '--out', required=1,
                        help='Output filename.')
    parser.add_argument('--cluster-id',
                        help='IPython.parallel cluster ID.')
    parser.add_argument('--batch-size', type=int, default=1000,
                        help='Batch size.')
    return parser.parse_args(input_args)


def main(ref_filename, fit_filename, out_filename, cluster_id=None,
         batch_size=1000):
    """
    Get separate scores for each reference color atom overlap.

    Parameters
    ----------
    ref_filename : str
        Reference molecule filename.
    fit_filename : str
        Fit molecule filename.
    out_filename : str
        Output filename.
    cluster_id : str, optional
        IPython.parallel cluster ID.
    batch_size : int, optional (default 1000)
        Batch size.
    """
    color_overlap_kwargs, rocs_kwargs = {}, {}  # TODO: get from command line
    results = []
    ref_color_coords = []
    ref_color_types = []
    ref_color_type_names = []
    ref_reader = MolReader(ref_filename)
    call = get_map(cluster_id)
    ref_size, fit_size = 0, 0
    for ref_mol in ref_reader.get_mols():
        fit_reader = MolReader(fit_filename)  # new generator each time
        f = partial(worker, ref_mol=ref_mol, rocs_kwargs=rocs_kwargs,
                    color_overlap_kwargs=color_overlap_kwargs)
        worker_results = call(f, fit_reader.get_batches(batch_size))
        # store each result as a separate array
        ref_results = []
        worker_color_coords = None
        for ref_result, color_coords in worker_results:
            for fit_result in ref_result:
                ref_results.append(fit_result)
            if worker_color_coords is None:
                worker_color_coords = color_coords
            else:
                assert np.allclose(worker_color_coords, color_coords)
        results.append(ref_results)
        ref_color_coords.append(worker_color_coords)
        ref_size += 1
        fit_size = len(ref_results)
    # ensure that results end up 2D
    data = np.zeros((ref_size, fit_size), dtype=object)
    for i, ref_results in enumerate(results):
        for j, fit_results in enumerate(ref_results):
            data[i, j] = fit_results
    # transpose to get fit mols on first axis
    data = np.asarray(data).transpose((1, 0))
    data = ColorOverlap.group_ref_color_atom_overlaps(data)
    h5_utils.dump(
        {'color_atom_overlaps': data.filled(np.nan),
         'mask': data.mask,
         'ref_color_coords': ref_color_coords,
         'ref_color_types': ref_color_types,
         'ref_color_type_names': ref_color_type_names},
        out_filename)


def worker(fit_mols, ref_mol, rocs_kwargs=None, color_overlap_kwargs=None):
    """
    Worker.

    Parameters
    ----------
    fit_mols : iterable
            Fit molecules.
    ref_mol : OEMol
        Reference molecule.
    rocs_kwargs : dict, optional
        Keyword arguments for ROCS engine.
    color_overlap_kwargs : dict, optional
        Keyword arguments for ColorOverlap engine.
    """
    import numpy as np

    from oe_utils.shape import ROCS
    from oe_utils.shape.overlap import ColorOverlap

    if rocs_kwargs is None:
        rocs_kwargs = {}
    if color_overlap_kwargs is None:
        color_overlap_kwargs = {}
    rocs_engine = ROCS(**rocs_kwargs)
    overlap_engine = ColorOverlap(**color_overlap_kwargs)
    rocs_engine.SetRefMol(ref_mol)
    ref_results = collections.defaultdict(list)
    for fit_mol in fit_mols:
        rocs_result = rocs_engine.get_best_overlay(fit_mol)
        ref_conf, fit_conf = rocs_engine.get_aligned_confs(
            ref_mol, fit_mol, rocs_result)
        overlap_engine.SetRefMol(ref_conf)
        overlap_results = overlap_engine.get_ref_color_atom_overlaps(fit_conf)
        fit_results = np.asarray([overlap.color_overlap
                                 for overlap in overlap_results['overlaps']],
                                 dtype=float)
        ref_results['overlaps'].append(fit_results)
        # Check that reference molecule color atoms are consistent.
        if 'ref_color_coords' not in ref_results:
            ref_results['ref_color_coords'] = overlap_results[
                'ref_color_coords']
            ref_results['ref_color_types'] = overlap_results[
                'ref_color_types']
            ref_results['ref_color_type_names'] = overlap_results[
                'ref_color_type_names']
        else:
            assert np.allclose(ref_results['ref_color_coords'],
                               overlap_results['ref_color_coords'])
            assert np.array_equal(ref_results['ref_color_types'],
                                  overlap_results['ref_color_types'])
            assert np.array_equal(ref_results['ref_color_type_names'],
                                  overlap_results['ref_color_type_names'])
    return ref_results

if __name__ == '__main__':
    args = get_args()
    main(args.ref, args.fit, args.out, args.cluster_id, args.batch_size)
